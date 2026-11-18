"""完整画像专属审核：绑定JobAnalysis原始result，不把补充审核写回基础研究。"""

import json
import sqlite3
from copy import deepcopy
from pathlib import Path

from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_models import PublicDocument
from work_observer.memory.dependencies import DependencyAudit
from work_observer.quality.service import DIMENSIONS, digest
from work_observer.reports.inbox import InboxService
from work_observer.reports.results import audit_result
from work_observer.storage.locks import exclusive
from work_observer.storage.models import JobAnalysis, JobSnapshot


def _data_kind(result):
    evidence = result.get("evidence", [])
    if not evidence:
        return "unknown"
    synthetic = [item.get("data_kind") == "synthetic" for item in evidence]
    if all(synthetic):
        return "synthetic"
    if any(synthetic):
        return "mixed"
    known = [
        item.get("data_kind") in {"real", "user_provided"}
        or item.get("source") == "public_web"
        or item.get("source") == "boss"
        and item.get("response_origin") in {"website", "cache", "replay"}
        for item in evidence
    ]
    return "real_or_user_provided" if all(known) else "unknown"


def profile_review_state(repository, analysis_id, result):
    """只读当前原始画像hash的人审状态；Agent反馈不能变成人类拒绝或批准。"""
    signature = digest(result)
    empty = {"status": "pending", "artifact_sha256": signature, "reviewer_kind": None}
    path = Path(
        getattr(
            repository,
            "research_store_path",
            Path(repository.engine.url.database).parent / "checkpoints.db",
        )
    )
    namespace = getattr(
        repository, "research_namespace", str(Path(repository.engine.url.database).resolve())
    )
    if not path.is_file():
        return empty
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_quality_reviews'"
            ).fetchone():
                return empty
            row = db.execute(
                "SELECT id,record FROM profile_quality_reviews WHERE namespace=? AND analysis_id=? "
                "AND json_extract(record,'$.artifact_sha256')=? "
                "AND json_extract(record,'$.reviewer_kind')='human' "
                "AND json_extract(record,'$.decision') IN ('approve','reject') "
                "AND json_extract(record,'$.status')!='invalidated' "
                "ORDER BY json_extract(record,'$.created_at') DESC,id DESC LIMIT 1",
                (namespace, analysis_id, signature),
            ).fetchone()
            if row:
                value = json.loads(row[1])
                return {
                    "status": "approved" if value["decision"] == "approve" else "rejected",
                    "artifact_sha256": signature,
                    "reviewer_kind": "human",
                    "review_id": row[0],
                    "created_at": value.get("created_at"),
                }
    except (OSError, sqlite3.Error, ValueError):
        return {**empty, "status": "unavailable"}
    return empty


class ProfileQualityReviewService:
    def __init__(self, store, repository):
        self.store, self.repository = store, repository
        repository.bind_research_store(store)
        with store.lock, store.db:
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS profile_quality_reviews(namespace TEXT NOT NULL, "
                "id TEXT NOT NULL,analysis_id TEXT NOT NULL,record TEXT NOT NULL,"
                "PRIMARY KEY(namespace,id))"
            )

    def _artifact(self, identity):
        with Session(self.repository.engine) as session:
            row = session.get(JobAnalysis, identity)
            if row is None:
                raise ProbeError("PROFILE_QUALITY_ARTIFACT_NOT_FOUND")
            if not isinstance(row.result, dict):
                raise ProbeError("PROFILE_QUALITY_ARTIFACT_UNAVAILABLE")
            return {
                "id": row.id,
                "job_id": row.job_id,
                "snapshot_id": row.snapshot_id,
                "status": row.status,
                "result": deepcopy(row.result),
                "memory_versions": deepcopy(row.memory_versions),
                "created_at": row.created_at,
            }

    def list_reviews(self, identity, *, artifact_sha256=None):
        current = artifact_sha256 or digest(self._artifact(identity)["result"])
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT record FROM profile_quality_reviews WHERE namespace=? AND analysis_id=? "
                "ORDER BY json_extract(record,'$.created_at') DESC,id DESC LIMIT 100",
                (self.store.namespace, identity),
            ).fetchall()
        return [
            {**record, "stale_artifact": record.get("artifact_sha256") != current}
            for (encoded,) in rows
            if (record := json.loads(encoded)).get("status") != "invalidated"
        ]

    def packet(self, identity):
        from work_observer.analysis.profiles import ProfileService

        artifact = self._artifact(identity)
        job = self.repository.job(artifact["job_id"])["current"]
        result = artifact["result"]
        signature = digest(result)
        output = ProfileService(self.repository).get(artifact["job_id"], analysis_id=identity)
        audit = audit_result(result, self.repository)
        run_id = result.get("run_id")
        source = (
            DependencyAudit(self.repository).run(run_id)
            if run_id
            else {
                "eligible": False,
                "issues": [{"kind": "run", "id": None, "reason": "source_run_missing"}],
            }
        )
        pool = {item["id"]: item for item in result.get("evidence", [])}
        scoped = {row["id"] for row in result.get("scope", {}).get("jobs", [])}
        citation_guard = True

        def citations(keys):
            nonlocal citation_guard
            found = []
            if not keys:
                citation_guard = False
            for key in keys:
                item = pool.get(key)
                valid = bool(
                    item
                    and (item.get("snapshot_id") or item.get("public_document_id"))
                    and (not item.get("job_id") or item["job_id"] in scoped)
                )
                citation_guard &= valid
                found.append({**(item or {"id": key, "quote": "引用缺失"}), "valid": valid})
            return found

        claims = [
            {**claim, "index": index, "citations": citations(claim.get("evidence_ids", []))}
            for index, claim in enumerate(result.get("claims", []))
        ]
        support = {
            key
            for claim in result.get("claims", [])
            if claim.get("category") in {"task", "responsibility"}
            for key in claim.get("evidence_ids", [])
        }
        domains = []
        for index, domain in enumerate(result.get("domains", [])):
            cite = citations(domain.get("evidence_ids", []))
            citation_guard &= (
                bool(domain.get("evidence_ids")) and set(domain["evidence_ids"]) <= support
            )
            domains.append({**domain, "index": index, "citations": cite})
        questions = [
            {"index": index, "text": text}
            for index, text in enumerate(result.get("interview_questions", []))
        ]
        texts, seen, characters, truncated = [], set(), 0, False
        with Session(self.repository.engine) as session:
            for item in pool.values():
                key = item.get("snapshot_id") or item.get("public_document_id")
                if not key or key in seen:
                    continue
                seen.add(key)
                row = (
                    session.get(JobSnapshot, key)
                    if item.get("snapshot_id")
                    else session.get(PublicDocument, key)
                )
                text = (
                    (row.payload.get("description", "") if item.get("snapshot_id") else row.text)
                    if row
                    else None
                )
                if text is None:
                    citation_guard = False
                    continue
                if len(texts) >= 20 or characters + len(text) > 600_000:
                    truncated = True
                    continue
                characters += len(text)
                texts.append(
                    {
                        "snapshot_id": item.get("snapshot_id"),
                        "public_document_id": item.get("public_document_id"),
                        "document_id": item.get("document_id"),
                        "title": item.get("title"),
                        "company": item.get("company"),
                        "text": text,
                        "source": item.get("source"),
                        "data_kind": item.get("data_kind", "unknown"),
                        "observed_at": item.get("observed_at"),
                        "source_published_at": item.get("source_published_at"),
                    }
                )
        complete = (
            artifact["status"] == result.get("status") == "completed"
            and bool(claims)
            and bool(questions)
            and isinstance(result.get("domains"), list)
            and not truncated
        )
        stale = bool(
            output["stale"]
            or not source["eligible"]
            or any(
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
        return {
            "analysis_id": identity,
            "artifact_sha256": signature,
            "artifact_status": artifact["status"],
            "data_kind": _data_kind(result),
            "job_id": artifact["job_id"],
            "title": job.get("title"),
            "company": job.get("company_name_raw"),
            "source_run_id": run_id,
            "question": result.get("question"),
            "claims": claims,
            "domains": domains,
            "interview_questions": questions,
            "gaps": result.get("gaps", []),
            "missing_dimensions": result.get("missing_dimensions", []),
            "source_texts": texts,
            "source_texts_truncated": truncated,
            "audit": audit,
            "source_eligibility": source,
            "stale": stale,
            "stale_reasons": output["stale_reasons"],
            "complete_artifact": complete,
            "approve_allowed": complete and citation_guard and not stale,
            "citation_guard": citation_guard,
            "dimensions": list(DIMENSIONS),
            "profile_review": profile_review_state(self.repository, identity, result),
            "reviews": self.list_reviews(identity, artifact_sha256=signature),
            "notice": "逐项核对原始完整画像，包括领域候选和向招聘方核实的问题。"
            "批准不激活知识；拒绝只影响该画像，不拒绝基础研究事实。",
        }

    @staticmethod
    def _complete_items(items, expected, fields, code):
        if (
            not isinstance(items, list)
            or any(
                not isinstance(item, dict) or type(item.get("index")) is not int for item in items
            )
            or len(items) != len(expected)
            or {item.get("index") for item in items} != set(range(len(expected)))
        ):
            raise ProbeError(code)
        if any(
            not isinstance(item.get("note"), str)
            or not item["note"].strip()
            or len(item["note"]) > 1200
            for item in items
        ):
            raise ProbeError("PROFILE_QUALITY_REASON_REQUIRED")
        return all(all(item.get(key) == value for key, value in fields.items()) for item in items)

    def blind_packet(self, identity):
        """动态匿名包不带旧评分、审核者、基础run或analysis ID；不复制保存result。"""
        packet = self.packet(identity)
        sources, aliases = [], {}
        for index, source in enumerate(packet["source_texts"]):
            alias = "S" + str(index + 1)
            aliases[source.get("snapshot_id") or source.get("public_document_id")] = alias
            sources.append(
                {
                    "source": alias,
                    **{
                        key: source.get(key)
                        for key in (
                            "title",
                            "company",
                            "text",
                            "data_kind",
                            "observed_at",
                            "source_published_at",
                        )
                    },
                }
            )

        def anonymous(row):
            return {
                **{
                    key: value
                    for key, value in row.items()
                    if key not in {"evidence_ids", "citations"}
                },
                "citations": [
                    {
                        "source": aliases.get(
                            item.get("snapshot_id") or item.get("public_document_id"), "unavailable"
                        ),
                        "quote": item.get("quote"),
                        "start": item.get("start"),
                        "end": item.get("end"),
                    }
                    for item in row.get("citations", [])
                ],
            }

        return {
            "packet_id": digest(
                {"analysis_id": identity, "artifact_sha256": packet["artifact_sha256"]}
            )[:32],
            "artifact_type": "profile",
            "data_kind": packet["data_kind"],
            "artifact_sha256": packet["artifact_sha256"],
            "question": packet["question"],
            "source_texts": sources,
            "source_texts_truncated": packet["source_texts_truncated"],
            "result": {
                "claims": [anonymous(row) for row in packet["claims"]],
                "domains": [anonymous(row) for row in packet["domains"]],
                "interview_questions": packet["interview_questions"],
                "gaps": packet["gaps"],
                "missing_dimensions": packet["missing_dimensions"],
            },
            "notice": "匿名原文及当前完整画像，不含既有评分；独立辅助复核不能替代人类批准。",
        }

    def submit(self, identity, data):
        with exclusive(self.repository.engine.url.database):
            packet = self.packet(identity)
            if not data.get("reviewer", "").strip() or not data.get("note", "").strip():
                raise ProbeError("PROFILE_QUALITY_REASON_REQUIRED")
            if data.get("reviewer_kind") not in {"human", "agent_assisted"} or data.get(
                "decision"
            ) not in {"approve", "reject", "pending"}:
                raise ProbeError("PROFILE_QUALITY_INVALID_REVIEW")
            if data.get("artifact_sha256") != packet["artifact_sha256"]:
                raise ProbeError("PROFILE_QUALITY_ARTIFACT_CHANGED_REFRESH")
            dimensions = data.get("dimensions", {})
            if set(dimensions) != set(DIMENSIONS) or any(
                not value.get("reason", "").strip() for value in dimensions.values()
            ):
                raise ProbeError("PROFILE_QUALITY_ALL_DIMENSIONS_REQUIRED")
            known = self._complete_items(
                data.get("claim_reviews"),
                packet["claims"],
                {"support": "supported", "requirement": "correct"},
                "PROFILE_QUALITY_ALL_CLAIMS_REQUIRED",
            )
            known &= self._complete_items(
                data.get("domain_reviews"),
                packet["domains"],
                {"support": "supported", "scope": "correct"},
                "PROFILE_QUALITY_ALL_DOMAINS_REQUIRED",
            )
            known &= self._complete_items(
                data.get("question_reviews"),
                packet["interview_questions"],
                {"direction": "correct", "relevance": "correct"},
                "PROFILE_QUALITY_ALL_QUESTIONS_REQUIRED",
            )
            if data["decision"] == "approve" and (
                data["reviewer_kind"] != "human"
                or not packet["approve_allowed"]
                or not known
                or any(
                    value["rating"] not in {"pass", "not_applicable"}
                    for value in dimensions.values()
                )
                or any(
                    dimensions[key]["rating"] != "pass"
                    for key in DIMENSIONS
                    if key != "counterexamples"
                )
            ):
                raise ProbeError("PROFILE_QUALITY_APPROVAL_REQUIRES_COMPLETE_HUMAN_REVIEW")
            artifact = self._artifact(identity)
            refs = {
                item["id"]: {"id": item["id"], "version": item.get("version")}
                for item in [
                    *artifact["memory_versions"],
                    *artifact["result"].get("memory_used", []),
                    *artifact["result"].get("context_memory_used", []),
                ]
            }
            record = {
                **data,
                "id": digest({"analysis_id": identity, **data})[:32],
                "analysis_id": identity,
                "data_kind": packet["data_kind"],
                "source_run_ids": [packet["source_run_id"]] if packet["source_run_id"] else [],
                "memory_refs": list(refs.values()),
                "created_at": now(),
                "status": "approved"
                if data["decision"] == "approve"
                else "rejected"
                if data["decision"] == "reject"
                else "pending",
            }
            with self.store.lock, self.store.db:
                if digest(self._artifact(identity)["result"]) != packet["artifact_sha256"]:
                    raise ProbeError("PROFILE_QUALITY_ARTIFACT_CHANGED_REFRESH")
                self.store.db.execute(
                    "INSERT OR IGNORE INTO profile_quality_reviews"
                    "(namespace,id,analysis_id,record) "
                    "VALUES(?,?,?,?)",
                    (
                        self.store.namespace,
                        record["id"],
                        identity,
                        json.dumps(record, ensure_ascii=False),
                    ),
                )
                row = self.store.db.execute(
                    "SELECT record FROM profile_quality_reviews WHERE namespace=? AND id=?",
                    (self.store.namespace, record["id"]),
                ).fetchone()
                record = json.loads(row[0])
            if data["decision"] == "reject":
                InboxService(self.repository).create(
                    "followup",
                    "完整画像有待核对或重新分析",
                    data["note"],
                    related_id=identity,
                    dedupe_key="profile-quality:" + record["id"],
                )
            return record

    def overview(self):
        from work_observer.analysis.profiles import ProfileService

        profiles = []
        for output in ProfileService(self.repository).list():
            identity = output["id"]
            job = self.repository.job(output["job_id"])["current"]
            artifact = self._artifact(identity)
            state = profile_review_state(self.repository, identity, artifact["result"])
            reviews = self.list_reviews(identity)
            profiles.append(
                {
                    "analysis_id": identity,
                    "job_id": output["job_id"],
                    "title": job.get("title"),
                    "company": job.get("company_name_raw"),
                    "data_kind": _data_kind(artifact["result"]),
                    "status": output["status"],
                    "stale": output["stale"],
                    "created_at": output["created_at"],
                    "claim_count": len(output["result"].get("claims", [])),
                    "domain_count": len(output["result"].get("domains", [])),
                    "question_count": len(output["result"].get("interview_questions", [])),
                    "human_review": state,
                    "latest_feedback": {
                        key: reviews[0].get(key)
                        for key in ("reviewer_kind", "status", "stale_artifact")
                    }
                    if reviews
                    else None,
                }
            )
        return {
            "profiles": profiles,
            "notice": "完整画像单独送审；基础研究的审核不代表领域候选及核实问题已经审核。"
            "Agent反馈不替代人审。",
        }

    def invalidate(self, run_ids=(), profile_ids=(), memory_ids=()):
        affected, analyses = [], set(profile_ids)
        with self.store.lock, self.store.db:
            rows = self.store.db.execute(
                "SELECT id,record FROM profile_quality_reviews WHERE namespace=?",
                (self.store.namespace,),
            ).fetchall()
            for _, encoded in rows:
                record = json.loads(encoded)
                if set(record.get("source_run_ids", [])) & set(run_ids) or {
                    item["id"] for item in record.get("memory_refs", [])
                } & set(memory_ids):
                    analyses.add(record["analysis_id"])
            for identity, encoded in rows:
                record = json.loads(encoded)
                if (
                    record["analysis_id"] not in analyses
                    and not set(record.get("source_run_ids", [])) & set(run_ids)
                    and not {item["id"] for item in record.get("memory_refs", [])} & set(memory_ids)
                ):
                    continue
                analyses.add(record["analysis_id"])
                minimal = {
                    "id": identity,
                    "analysis_id": record["analysis_id"],
                    "status": "invalidated",
                    "source_run_ids": record.get("source_run_ids", []),
                    "memory_refs": record.get("memory_refs", []),
                }
                self.store.db.execute(
                    "UPDATE profile_quality_reviews SET record=? WHERE namespace=? AND id=?",
                    (json.dumps(minimal), self.store.namespace, identity),
                )
                affected.append(identity)
        notifications = InboxService(self.repository).invalidate_research(sorted(analyses))
        return {
            "invalidated_profile_quality_review_ids": sorted(affected),
            "affected_profile_quality_analysis_ids": sorted(analyses),
            **notifications,
        }
