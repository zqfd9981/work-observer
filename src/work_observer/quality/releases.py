"""真实冻结评测后的有限本地检索试用；不改变全局检索或任何来源权限。"""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.service import MemoryService
from work_observer.quality.service import digest, load_suite, read_json, retrieval_method_digest
from work_observer.retrieval.catalog import Catalog
from work_observer.retrieval.enhanced import RetrievalService, validated_terms
from work_observer.tracking.evaluation import StrategyService, validate_aliases

EVALUATION_CONTRACT = {
    "recall_at_k": 10,
    "maximum_context_characters": 7000,
    "minimum_holdout_cases": 4,
    "minimum_recall_improvement": 0.1,
    "minimum_candidate_recall": 0.85,
    "minimum_candidate_precision": 0.75,
    "critical_regressions_allowed": 0,
}


def _query_key(terms):
    return digest(sorted(term.casefold() for term in validated_terms(terms)))


def _text(value, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ProbeError("TRIAL_REVIEW_TEXT_REQUIRED")
    return value.strip()


class LocalRetrievalTrialService:
    def __init__(self, store, repository, *, artifact_root=None):
        self.store, self.repository = store, repository
        repository.bind_research_store(store)
        self.artifact_root = (
            Path(artifact_root)
            if artifact_root
            else Path(repository.engine.url.database).parent / "quality-trials"
        )
        with store.lock, store.db:
            for table in ("retrieval_trials", "retrieval_trial_events"):
                store.db.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} (namespace TEXT NOT NULL, "
                    "id TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(namespace,id))"
                )

    def _directory(self, bundle_id):
        if bundle_id == "legacy-real-v1":
            directory = (
                Path(self.repository.engine.url.database).parent / "quality-baseline-20261119-v1"
            )
        elif isinstance(bundle_id, str) and re.fullmatch(r"[a-f0-9]{32}", bundle_id):
            directory = self.artifact_root / bundle_id
        else:
            raise ProbeError("TRIAL_INVALID_BUNDLE_ID")
        if directory.is_symlink() or not directory.is_dir():
            raise ProbeError("TRIAL_BUNDLE_NOT_FOUND")
        return directory

    def _bundle(self, bundle_id):
        directory = self._directory(bundle_id)
        if any(path.is_symlink() for path in directory.iterdir()):
            raise ProbeError("TRIAL_SYMLINK_ARTIFACT_DENIED")
        for name in (
            "corpus.db",
            "manifest.json",
            "suite.json",
            "holdout-result.json",
            "holdout.paired.json",
        ):
            path = directory / name
            if path.is_file() and path.stat().st_size > (
                512_000_000 if name.endswith(".db") else 16_000_000
            ):
                raise ProbeError("TRIAL_ARTIFACT_SIZE_LIMIT")
        if not (directory / "suite.json").is_file():
            raise ProbeError("TRIAL_BUNDLE_DRAFT_NOT_EVALUATED")
        corpus, suite = load_suite(directory)
        if any(
            suite.get("contract", {}).get(key) != value
            for key, value in EVALUATION_CONTRACT.items()
        ):
            raise ProbeError("TRIAL_FIXED_EVALUATION_CONTRACT_REQUIRED")
        result_path = directory / "holdout-result.json"
        if not result_path.is_file():
            result_path = directory / "holdout.paired.json"
        if not result_path.is_file():
            raise ProbeError("TRIAL_HOLDOUT_RESULT_REQUIRED")
        report = read_json(result_path)
        candidate = validate_aliases(report.get("candidate_aliases"))
        baseline_path = directory / "baseline-aliases.json"
        baseline = validate_aliases(read_json(baseline_path)) if baseline_path.is_file() else {}
        for config in (baseline, candidate):
            words = {word.casefold() for key, values in config.items() for word in [key, *values]}
            if len(words) > 30:
                raise ProbeError("TRIAL_ALIAS_CONTEXT_BOUND_REQUIRED")
        pins = {
            "corpus_sha256": corpus["corpus_sha256"],
            "suite_sha256": suite["suite_sha256"],
            "baseline_config_sha256": digest(baseline),
            "candidate_config_sha256": digest(candidate),
        }
        lock = {
            key: pins[key]
            for key in ("suite_sha256", "baseline_config_sha256", "candidate_config_sha256")
        }
        if (
            report.get("phase") != "holdout"
            or any(report.get(key) != value for key, value in pins.items())
            or read_json(directory / ("candidate-" + digest(lock) + ".json")) != lock
        ):
            raise ProbeError("TRIAL_FROZEN_DIGEST_MISMATCH")
        attempt = read_json(directory / "holdout-attempt.json")
        if any(attempt.get(key) != value for key, value in lock.items()):
            raise ProbeError("TRIAL_HOLDOUT_ATTEMPT_MISMATCH")
        independent = (
            suite.get("label_origin") == "human"
            and suite.get("review_status") == "reviewed"
            and suite.get("label_independence", {}).get("independent_of_candidate") is True
            and bool(suite.get("label_independence", {}).get("declared_by"))
            and bool(suite.get("created_at"))
            and suite["created_at"] <= attempt.get("started_at", "")
        )
        pins["holdout_result_sha256"] = digest(report)
        pins["holdout_attempt_sha256"] = digest(attempt)
        pins["retrieval_method_sha256"] = retrieval_method_digest()
        return directory, corpus, suite, report, baseline, candidate, pins, independent

    @staticmethod
    def _score(service, case, job_ids=None):
        result = service.search(case["terms"], job_ids=job_ids, limit=10)
        expected = {row["job_id"] for row in case["relevant"]}
        if job_ids is not None:
            expected &= set(job_ids)
        hits = {row["job_id"] for row in result["evidence"]}
        return {
            "recall": len(hits & expected) / len(expected) if expected else None,
            "precision": len(hits & expected) / len(hits) if hits else None,
            "negative_correct": not hits if not expected else None,
            "retrieved_jobs": sorted(hits),
            "context_characters": result["context_characters"],
        }, result

    @staticmethod
    def _verified_evidence(result, documents):
        for item in result["evidence"]:
            doc = documents.get(item["job_id"], {})
            start, end = item.get("start"), item.get("end")
            if not (
                type(start) is int
                and type(end) is int
                and 0 <= start < end <= len(doc.get("text", ""))
                and item["snapshot_id"] == doc.get("snapshot_id")
                and item["id"] == f"{doc.get('snapshot_id')}:{start}:{end}"
                and item["content_sha256"] == doc.get("content_sha256")
                and item["document_id"] == doc.get("document_id")
                and item["document_sha256"] == doc.get("document_sha256")
                and doc.get("text", "")[item["start"] : item["end"]] == item["quote"]
            ):
                return False
        return result["context_characters"] <= 7000

    def _verify_holdout(self, bundle):
        directory, corpus, suite, report, baseline, candidate, pins, independent = bundle
        cases = [row for row in suite["cases"] if row["split"] == "holdout"]
        recorded = {row["case_id"]: row for row in report.get("cases", [])}
        if set(recorded) != {row["id"] for row in cases}:
            return False
        documents = {row["job_id"]: row for row in corpus["documents"]}
        scores = []
        engine = create_engine(
            "sqlite:///" + (directory / "corpus.db").resolve().as_uri() + "?mode=ro&uri=true"
        )
        try:
            for case in cases:
                pair = {}
                for label, aliases in (("baseline", baseline), ("candidate", candidate)):
                    metric, result = self._score(
                        RetrievalService(SimpleNamespace(engine=engine), alias_groups=aliases), case
                    )
                    if not self._verified_evidence(result, documents) or any(
                        recorded[case["id"]][label].get(key) != value
                        for key, value in metric.items()
                    ):
                        return False
                    pair[label] = metric
                scores.append({"critical": case["critical"], **pair})
        finally:
            engine.dispose()
        contract = suite["contract"]

        def mean(label, key):
            values = [row[label][key] for row in scores if row[label][key] is not None]
            return sum(values) / len(values) if values else None

        baseline_recall, candidate_recall = mean("baseline", "recall"), mean("candidate", "recall")
        precision = mean("candidate", "precision")
        improvement = (
            candidate_recall - baseline_recall
            if candidate_recall is not None and baseline_recall is not None
            else None
        )
        regression = any(
            row["critical"]
            and (
                (row["baseline"]["recall"] or 0) > (row["candidate"]["recall"] or 0)
                or row["baseline"]["negative_correct"] is True
                and row["candidate"]["negative_correct"] is False
            )
            for row in scores
        )
        return bool(
            independent
            and report.get("retrieval_method_sha256") == pins["retrieval_method_sha256"]
            and len(cases) >= contract["minimum_holdout_cases"]
            and report.get("status") == "accepted_for_human_review"
            and report.get("source_and_budget_guard") is True
            and not report.get("critical_regressions")
            and not regression
            and candidate_recall is not None
            and candidate_recall >= contract["minimum_candidate_recall"]
            and precision is not None
            and precision >= contract["minimum_candidate_precision"]
            and improvement is not None
            and improvement >= contract["minimum_recall_improvement"]
            and report.get("baseline_mean_recall") == baseline_recall
            and report.get("candidate_mean_recall") == candidate_recall
            and report.get("candidate_mean_precision") == precision
            and report.get("improvement") == improvement
        )

    def _sample(self, job_ids):
        records, _, _ = RetrievalService(self.repository)._records({}, job_ids, None)
        if {row["job_id"] for row in records} != set(job_ids):
            raise ProbeError("TRIAL_SCOPE_JOB_MISSING")
        sample = []
        for item in records:
            row = item["row"]
            if row is None or not item["record"].get("description_text"):
                raise ProbeError("TRIAL_COMPLETE_LOCAL_TEXT_REQUIRED")
            observation, snapshot, document, run, watchset = row
            if Catalog(self.repository).document(document.id)["integrity"] != "verified":
                raise ProbeError("TRIAL_SOURCE_INTEGRITY_FAILED")
            sample.append(
                {
                    "job_id": item["job_id"],
                    "snapshot_id": snapshot.id,
                    "document_id": document.id,
                    "document_sha256": document.sha256,
                    "content_sha256": snapshot.content_sha256,
                    "text_sha256": hashlib.sha256(
                        item["record"]["description_text"].encode()
                    ).hexdigest(),
                    "source_skills": item["record"].get("source_skills"),
                }
            )
        return sorted(sample, key=lambda row: row["job_id"])

    def _get(self, identity):
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT record FROM retrieval_trials WHERE namespace=? AND id=?",
                (self.store.namespace, identity),
            ).fetchone()
        if not row:
            raise ProbeError("TRIAL_NOT_FOUND")
        return json.loads(row[0])

    def _save(self, record, action, details=None):
        record["updated_at"] = now()
        self.store.db.execute(
            "INSERT INTO retrieval_trials VALUES (?,?,?) ON CONFLICT(namespace,id) "
            "DO UPDATE SET record=excluded.record",
            (self.store.namespace, record["id"], json.dumps(record, ensure_ascii=False)),
        )
        event = {
            "id": uuid4().hex,
            "trial_id": record["id"],
            "created_at": now(),
            "action": action,
            "details": details or {},
        }
        self.store.db.execute(
            "INSERT INTO retrieval_trial_events VALUES (?,?,?)",
            (self.store.namespace, event["id"], json.dumps(event, ensure_ascii=False)),
        )

    @staticmethod
    def summary(record, *, detail=False):
        value = {
            key: record.get(key)
            for key in (
                "id",
                "state",
                "bundle_id",
                "created_at",
                "updated_at",
                "job_ids",
                "allowed_queries",
                "uses",
                "max_uses",
                "expires_at",
                "pins",
                "label_origin",
                "independent_human_labels",
                "holdout_verified",
                "shadow",
                "review",
                "stop_reason",
                "data_mode",
            )
        }
        if not detail and value.get("shadow"):
            value["shadow"] = {
                "passed": record["shadow"]["passed"],
                "query_count": len(record["shadow"]["queries"]),
                "external_calls": 0,
            }
        return value

    @staticmethod
    def _application_digest(record):
        return digest(
            {
                key: record.get(key)
                for key in (
                    "pins",
                    "job_ids",
                    "allowed_queries",
                    "sample_sha256",
                    "max_uses",
                    "expires_at",
                    "baseline_aliases",
                    "candidate_aliases",
                )
            }
        )

    def bundles(self):
        names = (
            [
                row.name
                for row in self.artifact_root.iterdir()
                if row.is_dir() and re.fullmatch(r"[a-f0-9]{32}", row.name)
            ]
            if self.artifact_root.is_dir()
            else []
        )
        legacy = Path(self.repository.engine.url.database).parent / "quality-baseline-20261119-v1"
        if legacy.is_dir():
            names.append("legacy-real-v1")
        output = []
        for identity in sorted(names)[:100]:
            try:
                _, corpus, suite, report, _, _, pins, independent = self._bundle(identity)
                output.append(
                    {
                        "id": identity,
                        "pins": pins,
                        "job_ids": [row["job_id"] for row in corpus["documents"]],
                        "development_queries": [
                            row["terms"] for row in suite["cases"] if row["split"] == "development"
                        ],
                        "label_origin": suite["label_origin"],
                        "independent_human_labels": independent,
                        "holdout_status": report["status"],
                        "data_mode": "synthetic"
                        if all(row["data_kind"] == "synthetic" for row in corpus["documents"])
                        else "real_or_user_provided",
                        "notice": "预留验收题和标签不会返回；独立标签声明仍需人类负责核对。",
                    }
                )
            except (ProbeError, OSError, ValueError, KeyError, TypeError):
                output.append({"id": identity, "state": "invalid_bundle"})
        return output

    def list(self):
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT record FROM retrieval_trials WHERE namespace=? "
                "ORDER BY json_extract(record,'$.created_at') DESC LIMIT 100",
                (self.store.namespace,),
            ).fetchall()
        return [self.get(json.loads(row[0])["id"], detail=False) for row in rows]

    def get(self, identity, *, detail=True):
        with self.store.lock, self.store.db:
            record = self._get(identity)
            if record["state"] == "active":
                failure = self._guard(record)
                if failure:
                    self._revert(record, failure)
            return self.summary(record, detail=detail)

    def shadow(
        self, bundle_id, job_ids, allowed_terms, *, max_uses=10, expires_hours=4, source_run_id=None
    ):
        if (
            not isinstance(job_ids, list)
            or not 1 <= len(job_ids) <= 20
            or any(not isinstance(value, str) for value in job_ids)
        ):
            raise ProbeError("TRIAL_SCOPE_LIMIT_20")
        if (
            type(max_uses) is not int
            or not 1 <= max_uses <= 20
            or type(expires_hours) is not int
            or not 1 <= expires_hours <= 24
        ):
            raise ProbeError("TRIAL_FINITE_BUDGET_REQUIRED")
        allowed_terms = validated_terms(allowed_terms)
        bundle = self._bundle(bundle_id)
        _, corpus, suite, report, baseline, candidate, pins, independent = bundle
        if digest(StrategyService(self.repository).active_config()["aliases"]) != digest(baseline):
            raise ProbeError("TRIAL_BASELINE_CHANGED")
        documents = {row["job_id"]: row for row in corpus["documents"]}
        if not set(job_ids) <= set(documents):
            raise ProbeError("TRIAL_SCOPE_OUTSIDE_FROZEN_CORPUS")
        sample = self._sample(job_ids)
        if any(
            row["snapshot_id"] != documents[row["job_id"]]["snapshot_id"]
            or row["document_sha256"] != documents[row["job_id"]]["document_sha256"]
            for row in sample
        ):
            raise ProbeError("TRIAL_CURRENT_SAMPLE_DIFFERS_FROM_FROZEN")
        terms = {term.casefold() for term in allowed_terms}
        cases = [
            row
            for row in suite["cases"]
            if row["split"] == "development" and {term.casefold() for term in row["terms"]} <= terms
        ]
        if (
            not cases
            or len(cases) > 20
            or not terms <= {term.casefold() for row in cases for term in row["terms"]}
        ):
            raise ProbeError("TRIAL_ONLY_VERIFIED_DEVELOPMENT_QUERIES")
        good, positive, results = True, False, []
        for case in cases:
            a, ar = self._score(
                RetrievalService(self.repository, alias_groups=baseline), case, job_ids
            )
            b, br = self._score(
                RetrievalService(self.repository, alias_groups=candidate), case, job_ids
            )
            positive |= b["recall"] is not None
            good &= self._verified_evidence(ar, documents) and self._verified_evidence(
                br, documents
            )
            good &= (
                (b["recall"] is None or b["recall"] >= (a["recall"] or 0))
                and (
                    b["recall"] is None
                    or b["recall"] >= EVALUATION_CONTRACT["minimum_candidate_recall"]
                )
                and (b["precision"] is None or b["precision"] >= 0.75)
                and b["negative_correct"] is not False
            )
            results.append(
                {
                    "query": case["terms"],
                    "baseline": a,
                    "candidate": b,
                    "baseline_evidence": ar["evidence"],
                    "candidate_evidence": br["evidence"],
                }
            )
        holdout = self._verify_holdout(bundle) if independent else False
        source_run_ids, memory_refs = [], []
        if source_run_id:
            source = self.store.get(source_run_id)
            if source["state"] == "invalidated":
                raise ProbeError("TRIAL_SOURCE_RESEARCH_FORGOTTEN")
            if not MemoryService(self.repository).derived_eligibility(
                source_run_id, job_ids=job_ids
            )["eligible"]:
                raise ProbeError("TRIAL_UPSTREAM_DEPENDENCY_INELIGIBLE")
            source_run_ids = [source_run_id]
            result = source.get("result") or {}
            memory_refs = [
                {"id": row["id"], "version": row["version"]}
                for row in [*result.get("memory_used", []), *result.get("context_memory_used", [])]
            ]
        record = {
            "id": uuid4().hex,
            "state": "awaiting_review"
            if independent and holdout and good and positive
            else "insufficient",
            "created_at": now(),
            "bundle_id": bundle_id,
            "pins": pins,
            "job_ids": sorted(set(job_ids)),
            "allowed_queries": list(
                {_query_key(row["terms"]): row["terms"] for row in cases}.values()
            ),
            "sample_sha256": digest(sample),
            "baseline_aliases": baseline,
            "candidate_aliases": candidate,
            "uses": 0,
            "max_uses": max_uses,
            "expires_at": (datetime.now(UTC) + timedelta(hours=expires_hours)).isoformat(),
            "label_origin": suite["label_origin"],
            "independent_human_labels": independent,
            "holdout_verified": holdout,
            "shadow": {"passed": bool(good and positive), "queries": results, "external_calls": 0},
            "review": None,
            "source_run_ids": source_run_ids,
            "memory_refs": memory_refs,
            "data_mode": "synthetic"
            if all(documents[key]["data_kind"] == "synthetic" for key in job_ids)
            else "real_or_user_provided",
            "stop_reason": None
            if independent and holdout and good and positive
            else "independent_human_labels_holdout_or_shadow_insufficient",
        }
        record["application_sha256"] = self._application_digest(record)
        with self.store.lock, self.store.db:
            if source_run_id and self.store.get(source_run_id)["state"] == "invalidated":
                raise ProbeError("TRIAL_SOURCE_RESEARCH_FORGOTTEN")
            self._save(record, "shadow_created")
        return self.summary(record, detail=True)

    def review(
        self,
        identity,
        reviewer,
        decision,
        reason,
        *,
        reviewer_kind="human",
        labels_independent_confirmed=False,
    ):
        reviewer, reason = _text(reviewer, 100), _text(reason)
        if decision not in {"approve", "reject", "pending"} or reviewer_kind not in {
            "human",
            "agent_assisted",
        }:
            raise ProbeError("TRIAL_INVALID_REVIEW")
        with self.store.lock, self.store.db:
            record = self._get(identity)
            if record["state"] in {"rolled_back", "expired", "invalidated"}:
                raise ProbeError("TRIAL_CLOSED_NEW_SHADOW_REQUIRED")
            if decision == "approve" and (
                reviewer_kind != "human" or labels_independent_confirmed is not True
            ):
                raise ProbeError("TRIAL_INDEPENDENT_HUMAN_APPROVAL_REQUIRED")
            if decision == "approve" and not (
                record["independent_human_labels"]
                and record["holdout_verified"]
                and record["shadow"]["passed"]
            ):
                raise ProbeError("TRIAL_REAL_LABELS_OR_EVALUATION_INSUFFICIENT")
            reason_code = self._guard(record)
            if reason_code:
                self._revert(record, reason_code)
                return self.summary(record)
            record["review"] = {
                "reviewer": reviewer,
                "reviewer_kind": reviewer_kind,
                "decision": decision,
                "reason": reason,
                "created_at": now(),
            }
            record["state"] = (
                "active"
                if decision == "approve"
                else "rolled_back"
                if decision == "reject"
                else "awaiting_review"
                if record["independent_human_labels"] and record["holdout_verified"]
                else "insufficient"
            )
            record["stop_reason"] = "human_rejected" if decision == "reject" else None
            if record["state"] == "insufficient":
                record["stop_reason"] = "independent_human_labels_holdout_or_shadow_insufficient"
            self._save(record, "human_review")
            return self.summary(record)

    def _guard(self, record):
        try:
            if datetime.now(UTC) >= datetime.fromisoformat(record["expires_at"]):
                return "expired"
            if self._application_digest(record) != record.get("application_sha256"):
                return "application_contract_changed"
            if record["pins"].get("retrieval_method_sha256") != retrieval_method_digest():
                return "retrieval_method_changed"
            if (
                digest(record["baseline_aliases"]) != record["pins"]["baseline_config_sha256"]
                or digest(record["candidate_aliases"]) != record["pins"]["candidate_config_sha256"]
            ):
                return "candidate_or_baseline_config_changed"
            if self._bundle(record["bundle_id"])[6] != record["pins"]:
                return "frozen_artifacts_changed"
            if digest(StrategyService(self.repository).active_config()["aliases"]) != digest(
                record["baseline_aliases"]
            ):
                return "global_baseline_changed"
            if digest(self._sample(record["job_ids"])) != record["sample_sha256"]:
                return "local_sample_drift"
            for identity in record.get("source_run_ids", []):
                if self.store.get(identity)["state"] == "invalidated":
                    return "upstream_research_forgotten"
                if not MemoryService(self.repository).derived_eligibility(
                    identity, job_ids=record["job_ids"]
                )["eligible"]:
                    return "upstream_dependency_changed"
            for ref in record.get("memory_refs", []):
                if not MemoryService(self.repository).audit(
                    ref["id"], version=ref["version"], job_ids=record["job_ids"]
                )["eligible"]:
                    return "upstream_dependency_changed"
        except (ProbeError, OSError, ValueError, KeyError, TypeError):
            return "artifact_or_source_guard_failed"
        return None

    def _revert(self, record, reason):
        record.update(state="expired" if reason == "expired" else "rolled_back", stop_reason=reason)
        self._save(record, "automatic_rollback", {"reason": reason})

    def _baseline(self, terms, job_ids):
        try:
            self._sample(job_ids)
            result = RetrievalService(self.repository).search(terms, job_ids=job_ids, limit=10)
            if result["evidence"]:
                with Session(self.repository.engine) as session:
                    MemoryService(self.repository)._validate_evidence(session, result["evidence"])
            self._sample(job_ids)
            return result, True
        except (ProbeError, OSError, ValueError, KeyError, TypeError):
            return {
                "terms": terms,
                "matching_jobs": None,
                "evidence": [],
                "context_characters": 0,
                "context_limit": 7000,
                "sample": {"unknown": len(job_ids), "denominator": None},
                "note": "原始归档、范围或引用无法核对，基线也关闭；待核实，不能按零命中解释。",
            }, False

    def search(self, identity, terms, *, request_key, job_ids=None):
        terms = validated_terms(terms)
        request_key = _text(request_key, 100)
        with self.store.lock, self.store.db:
            record = self._get(identity)
            if record["state"] == "invalidated":
                raise ProbeError("TRIAL_SOURCE_RESEARCH_FORGOTTEN")
            failure = self._guard(record)
            if job_ids is not None and set(job_ids) != set(record["job_ids"]):
                failure = "request_scope_drift"
            if _query_key(terms) not in {_query_key(query) for query in record["allowed_queries"]}:
                failure = "unreviewed_query"
            if failure and record["state"] not in {"rolled_back", "expired"}:
                self._revert(record, failure)
            key = digest({"trial": identity, "request_key": request_key})[:32]
            cached = self.store.db.execute(
                "SELECT record FROM retrieval_trial_events WHERE namespace=? AND id=?",
                (self.store.namespace, key),
            ).fetchone()
            if not failure and record["state"] == "active" and cached:
                prior = json.loads(cached[0])
                if prior["request_sha256"] != digest({"terms": terms, "job_ids": job_ids}):
                    raise ProbeError("TRIAL_REQUEST_KEY_CONFLICT")
                return {**prior["result"], "replayed": True}
            if record["state"] == "active" and record["uses"] >= record["max_uses"]:
                self._revert(record, "use_budget_exhausted")
            baseline, baseline_valid = self._baseline(terms, record["job_ids"])
            if not baseline_valid and record["state"] not in {"rolled_back", "expired"}:
                self._revert(record, "baseline_source_unavailable")
            result = {
                "trial_id": identity,
                "mode": "baseline" if baseline_valid else "source_unavailable",
                "trial_state": record["state"],
                "stop_reason": record.get("stop_reason"),
                "retrieval": baseline,
                "uses": record["uses"],
                "max_uses": record["max_uses"],
                "external_calls": 0,
            }
            if record["state"] == "active" and baseline_valid:
                candidate = RetrievalService(
                    self.repository, alias_groups=record["candidate_aliases"]
                ).search(terms, job_ids=record["job_ids"], limit=10)
                baseline_hits = {row["job_id"] for row in baseline["evidence"]}
                candidate_hits = {row["job_id"] for row in candidate["evidence"]}
                try:
                    documents = {
                        row["job_id"]: row
                        for row in self._bundle(record["bundle_id"])[1]["documents"]
                    }
                    valid = self._verified_evidence(candidate, documents)
                    valid &= digest(self._sample(record["job_ids"])) == record["sample_sha256"]
                except (ProbeError, OSError, ValueError, KeyError, TypeError):
                    valid = False
                if not baseline_hits <= candidate_hits or not valid:
                    self._revert(record, "candidate_evidence_or_coverage_guard_failed")
                    result.update(trial_state=record["state"], stop_reason=record["stop_reason"])
                else:
                    record["uses"] += 1
                    result.update(
                        mode="limited_candidate",
                        retrieval=candidate,
                        baseline_comparison={
                            "matching_jobs": baseline["matching_jobs"],
                            "evidence_job_ids": sorted(baseline_hits),
                        },
                        uses=record["uses"],
                    )
                    self._save(record, "limited_search", {"uses": record["uses"]})
            else:
                result["shadow_notice"] = "未采用候选；默认检索与全局配置保持。"
            event = {
                "id": key,
                "trial_id": identity,
                "created_at": now(),
                "action": "query_result",
                "request_sha256": digest({"terms": terms, "job_ids": job_ids}),
                "result": result,
            }
            self.store.db.execute(
                "INSERT OR IGNORE INTO retrieval_trial_events VALUES (?,?,?)",
                (self.store.namespace, key, json.dumps(event, ensure_ascii=False)),
            )
            return result

    def rollback(self, identity, reason):
        reason = _text(reason)
        with self.store.lock, self.store.db:
            record = self._get(identity)
            if record["state"] == "invalidated":
                raise ProbeError("TRIAL_SOURCE_RESEARCH_FORGOTTEN")
            if record["state"] not in {"rolled_back", "expired"}:
                record.update(state="rolled_back", stop_reason="explicit_rollback")
                self._save(record, "explicit_rollback", {"reason": reason})
        return self.summary(record)

    def feedback(self, identity, request_key, rating, note, *, reviewer_kind="human"):
        if rating not in {"pass", "fail", "unknown"} or reviewer_kind not in {
            "human",
            "agent_assisted",
        }:
            raise ProbeError("TRIAL_INVALID_FEEDBACK")
        note = _text(note)
        with self.store.lock, self.store.db:
            record = self._get(identity)
            if record["state"] == "invalidated":
                raise ProbeError("TRIAL_SOURCE_RESEARCH_FORGOTTEN")
            key = digest({"trial": identity, "request_key": _text(request_key, 100)})[:32]
            if not self.store.db.execute(
                "SELECT id FROM retrieval_trial_events WHERE namespace=? AND id=?",
                (self.store.namespace, key),
            ).fetchone():
                raise ProbeError("TRIAL_QUERY_FEEDBACK_TARGET_MISSING")
            self._save(
                record,
                "quality_feedback",
                {
                    "rating": rating,
                    "note": note,
                    "reviewer_kind": reviewer_kind,
                    "request_key": request_key,
                },
            )
            if rating in {"fail", "unknown"} and record["state"] not in {"rolled_back", "expired"}:
                self._revert(
                    record,
                    "quality_feedback_failed" if rating == "fail" else "quality_feedback_uncertain",
                )
        return self.summary(record)

    def events(self, identity):
        self._get(identity)
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT record FROM retrieval_trial_events WHERE namespace=? "
                "AND json_extract(record,'$.trial_id')=? "
                "ORDER BY json_extract(record,'$.created_at') DESC LIMIT 100",
                (self.store.namespace, identity),
            ).fetchall()
        return [
            {key: event.get(key) for key in ("id", "trial_id", "created_at", "action", "details")}
            for (raw,) in rows
            if (event := json.loads(raw)).get("action") != "query_result"
        ]

    def invalidate_research(self, run_ids, memory_ids=()):
        affected = []
        with self.store.lock, self.store.db:
            rows = self.store.db.execute(
                "SELECT id,record FROM retrieval_trials WHERE namespace=?", (self.store.namespace,)
            ).fetchall()
            for identity, raw in rows:
                record = json.loads(raw)
                if not (
                    set(record.get("source_run_ids", [])) & set(run_ids)
                    or {ref["id"] for ref in record.get("memory_refs", [])} & set(memory_ids)
                ):
                    continue
                tombstone = {
                    "id": identity,
                    "state": "invalidated",
                    "source_run_ids": record.get("source_run_ids", []),
                    "memory_refs": record.get("memory_refs", []),
                }
                self.store.db.execute(
                    "UPDATE retrieval_trials SET record=? WHERE namespace=? AND id=?",
                    (json.dumps(tombstone), self.store.namespace, identity),
                )
                self.store.db.execute(
                    "DELETE FROM retrieval_trial_events WHERE namespace=? "
                    "AND json_extract(record,'$.trial_id')=?",
                    (self.store.namespace, identity),
                )
                affected.append(identity)
        return {"invalidated_retrieval_trial_ids": affected}
