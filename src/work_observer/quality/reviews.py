"""研究结果业务审核；审核记录不是新的研究证据，不自动变更方法。"""

import json
from pathlib import Path

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.quality.service import DIMENSIONS, digest, load_corpus, read_json
from work_observer.reports.inbox import InboxService
from work_observer.reports.results import audit_result, source_analysis_notes


class QualityReviewService:
    def __init__(self, store, repository=None):
        self.store, self.repository = store, repository
        with store.lock, store.db:
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS quality_reviews (namespace TEXT NOT NULL, "
                "id TEXT NOT NULL, run_id TEXT NOT NULL, record TEXT NOT NULL, "
                "PRIMARY KEY(namespace,id))"
            )

    def _result(self, identity):
        run = self.store.get(identity)
        result = run.get("result")
        if run["state"] == "invalidated":
            raise ProbeError("QUALITY_RESEARCH_FORGOTTEN")
        if (
            run["state"] not in {"finished", "completed"}
            or not result
            or result.get("status") != "completed"
        ):
            raise ProbeError("QUALITY_COMPLETED_RESEARCH_REQUIRED")
        return result

    def packet(self, identity):
        result = self._result(identity)
        audit = audit_result(result, self.repository)
        evidence = {item["id"]: item for item in result.get("evidence", [])}
        claims = []
        citation_guard = True
        scoped_jobs = {item["id"] for item in result.get("scope", {}).get("jobs", [])}
        for index, claim in enumerate(result.get("claims", [])):
            cites = []
            for key in claim.get("evidence_ids", []):
                item = evidence.get(key)
                if item is None:
                    citation_guard = False
                    cites.append({"id": key, "quote": "引用缺失", "valid": False})
                else:
                    recognized = bool(item.get("snapshot_id") or item.get("public_document_id"))
                    in_scope = not item.get("job_id") or item["job_id"] in scoped_jobs
                    citation_guard &= recognized and in_scope
                    cites.append(
                        {
                            field: item.get(field)
                            for field in (
                                "id",
                                "quote",
                                "title",
                                "company",
                                "job_id",
                                "snapshot_id",
                                "document_id",
                                "public_document_id",
                                "document_sha256",
                                "start",
                                "end",
                                "observed_at",
                                "source_published_at",
                                "source",
                                "data_kind",
                                "evidence_kind",
                                "url",
                            )
                        }
                    )
                    cites[-1]["valid"] = recognized and in_scope
            citation_guard &= bool(claim.get("evidence_ids"))
            claims.append({"index": index, **claim, "citations": cites})
        approve_allowed = (
            bool(claims)
            and citation_guard
            and not any(
                audit.get(key)
                for key in (
                    "stale_memory",
                    "stale_knowledge",
                    "stale_dependencies",
                    "changed_sources",
                    "affected_strategy",
                )
            )
        )
        packet = {
            "run_id": identity,
            "result_sha256": digest(result),
            "question": result.get("question"),
            "scope": result.get("scope", {}),
            "claims": claims,
            "gaps": result.get("gaps", []),
            "audit": audit,
            "approve_allowed": approve_allowed,
            "citation_guard": bool(citation_guard),
            "dimensions": list(DIMENSIONS),
            "usage": {
                "model_calls": result.get("model_calls"),
                "elapsed_seconds": result.get("elapsed_seconds"),
                "provider_usage": result.get("usage", []),
                "cost": None,
            },
            "reviews": self.list_run(identity, result_sha256=digest(result)),
            "notice": "未审核保持待核对；程序只核对来源与合同，语义由审核者逐条判断。",
        }
        notes = source_analysis_notes(result)
        if notes:
            packet["analysis_notes"] = notes
        if result.get("source_findings"):
            from work_observer.research.source_first import review_finding_history, review_findings

            packet["source_findings"] = review_findings(result["source_findings"])
            history = review_finding_history(result["source_findings"])
            if history:
                packet["source_finding_history"] = history
        return packet

    def list_run(self, identity, *, result_sha256=None):
        result = self._result(identity)
        current = result_sha256 or digest(result)
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT record FROM quality_reviews WHERE namespace=? AND run_id=? "
                "ORDER BY json_extract(record,'$.created_at') DESC,id DESC LIMIT 100",
                (self.store.namespace, identity),
            ).fetchall()
        return [
            {**record, "stale_result": record.get("result_sha256") != current}
            for (encoded,) in rows
            if (record := json.loads(encoded)).get("status") != "invalidated"
        ]

    def submit(self, identity, data):
        packet = self.packet(identity)
        if not data["reviewer"].strip() or not data["note"].strip():
            raise ProbeError("QUALITY_REVIEW_REASON_REQUIRED")
        if data["result_sha256"] != packet["result_sha256"]:
            raise ProbeError("QUALITY_RESULT_CHANGED_REFRESH")
        dimensions = data["dimensions"]
        reviews = data["claim_reviews"]
        if set(dimensions) != set(DIMENSIONS):
            raise ProbeError("QUALITY_ALL_DIMENSIONS_REQUIRED")
        if any(not value["reason"].strip() for value in dimensions.values()):
            raise ProbeError("QUALITY_REVIEW_REASON_REQUIRED")
        if {item["index"] for item in reviews} != set(range(len(packet["claims"]))) or len(
            reviews
        ) != len(packet["claims"]):
            raise ProbeError("QUALITY_ALL_CLAIMS_REQUIRE_SEMANTIC_REVIEW")
        if any(not item["note"].strip() for item in reviews):
            raise ProbeError("QUALITY_CLAIM_REVIEW_REASON_REQUIRED")
        if data["decision"] == "approve" and (
            data["reviewer_kind"] != "human"
            or not packet["approve_allowed"]
            or any(
                value["rating"] not in {"pass", "not_applicable"} for value in dimensions.values()
            )
            or any(
                dimensions[key]["rating"] != "pass"
                for key in ("citation_semantics", "question_answered")
            )
            or any(
                item["support"] != "supported" or item["requirement"] != "correct"
                for item in reviews
            )
        ):
            raise ProbeError("QUALITY_APPROVAL_REQUIRES_HUMAN_SUPPORTED_COMPLETE_REVIEW")
        record = {
            **data,
            "id": digest({"run_id": identity, **data})[:32],
            "run_id": identity,
            "created_at": now(),
            "status": "approved"
            if data["decision"] == "approve"
            else "rejected"
            if data["decision"] == "reject"
            else "pending",
        }
        with self.store.lock, self.store.db:
            # 与遗忘共用同一锁，不能在失效后写回评语或问题。
            current = self._result(identity)
            if digest(current) != packet["result_sha256"]:
                raise ProbeError("QUALITY_RESULT_CHANGED_REFRESH")
            self.store.db.execute(
                "INSERT OR IGNORE INTO quality_reviews(namespace,id,run_id,record) "
                "VALUES (?,?,?,?)",
                (
                    self.store.namespace,
                    record["id"],
                    identity,
                    json.dumps(record, ensure_ascii=False),
                ),
            )
            saved = self.store.db.execute(
                "SELECT record FROM quality_reviews WHERE namespace=? AND id=?",
                (self.store.namespace, record["id"]),
            ).fetchone()
            record = json.loads(saved[0])
            if data["decision"] == "reject":
                InboxService(self.repository).create(
                    "followup",
                    "研究核对后需要补查",
                    data["note"],
                    related_id=identity,
                    dedupe_key="quality-review:" + record["id"],
                )
        return record

    def invalidate(self, run_ids):
        affected = []
        with self.store.lock, self.store.db:
            for run_id in set(run_ids):
                rows = self.store.db.execute(
                    "SELECT id FROM quality_reviews WHERE namespace=? AND run_id=?",
                    (self.store.namespace, run_id),
                ).fetchall()
                for (identity,) in rows:
                    self.store.db.execute(
                        "UPDATE quality_reviews SET record=? WHERE namespace=? AND id=?",
                        (
                            json.dumps({"id": identity, "run_id": run_id, "status": "invalidated"}),
                            self.store.namespace,
                            identity,
                        ),
                    )
                    affected.append(identity)
        return {"invalidated_quality_review_ids": affected}

    def overview(self):
        runs = []
        for run in self.store.list():
            result = run.get("result") or {}
            if run["state"] == "invalidated" or result.get("status") != "completed":
                continue
            reviews = self.list_run(run["id"])
            latest = next((item for item in reviews if not item["stale_result"]), None)
            audit = audit_result(result, self.repository)
            stale = any(
                audit.get(key)
                for key in (
                    "stale_memory",
                    "stale_knowledge",
                    "stale_dependencies",
                    "changed_sources",
                    "affected_strategy",
                )
            )
            runs.append(
                {
                    "id": run["id"],
                    "question": result.get("question"),
                    "created_at": run["created_at"],
                    "claim_count": len(result.get("claims", [])),
                    "review_status": "needs_recheck"
                    if stale
                    else latest["status"]
                    if latest
                    else "pending",
                    "reviewer_kind": latest["reviewer_kind"] if latest else None,
                }
            )
        root = Path(self.repository.engine.url.database).parent
        baselines = []
        for name in ("quality-baseline", "quality-baseline-20261119-v1"):
            directory = root / name
            if not (directory / "manifest.json").is_file():
                continue
            try:
                manifest = load_corpus(directory)
                row = {
                    key: manifest[key]
                    for key in (
                        "scope_total",
                        "detail_total",
                        "missing_detail_total",
                        "corpus_sha256",
                    )
                }
                row["results"] = []
                for phase in ("development", "holdout"):
                    path = directory / (phase + ".paired.json")
                    if path.is_file():
                        paired = read_json(path)
                        row["results"].append(
                            {
                                key: paired.get(key)
                                for key in (
                                    "phase",
                                    "status",
                                    "label_origin",
                                    "label_review_status",
                                    "baseline_mean_recall",
                                    "candidate_mean_recall",
                                    "candidate_mean_precision",
                                    "critical_regressions",
                                    "external_calls",
                                )
                            }
                        )
                baselines.append(row)
            except (ProbeError, OSError, ValueError, KeyError):
                baselines.append({"status": "invalid_or_changed", "results": []})
        return {
            "runs": runs,
            "baselines": baselines,
            "notice": "Agent草案标签与人类审核分开；检索指标不是语义正确率，待审不算通过。",
        }
