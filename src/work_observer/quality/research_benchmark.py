"""有界业务研究评测协议：锁题、登记权威输出、一次封卷、盲审和配对。

不执行研究，不复制完整result，不启用方法。人类与独立声明由操作人负责。
"""

import json
import math
import random
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.service import MemoryService
from work_observer.quality.service import DIMENSIONS, digest, freeze, load_corpus
from work_observer.reports.results import audit_result, source_analysis_notes

TABLES = (
    "research_benchmarks",
    "research_benchmark_submissions",
    "research_benchmark_rounds",
    "research_benchmark_reviews",
)
GATES = {
    "minimum_holdout_tasks": 2,
    "maximum_tasks": 20,
    "maximum_claims": 24,
    "minimum_candidate_answer_gain": 1,
    "automatic_activation": False,
}
SCOPE_CONTEXT_NOTICE = (
    "以下公司名称与身份状态仅为冻结资料中的来源标识和核验状态，不是JD逐字业务声明；"
    "不证明岗位的组织隶属、公司整体业务或来源当前仍在招聘。"
)


def _frozen_scope_context(directory, documents, job_ids):
    """Read only whitelisted naming metadata from the verified frozen corpus, never live scope."""
    path = (Path(directory) / "corpus.db").resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
        database.row_factory = sqlite3.Row
        rows = []
        for job_id in sorted(job_ids):
            row = database.execute(
                "SELECT j.id AS job_id,j.title,j.company_name_raw,"
                "COALESCE(c.identity_status,'unknown') AS company_identity_status "
                "FROM jobs j LEFT JOIN companies c ON c.id=j.company_id WHERE j.id=?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise ProbeError("BENCHMARK_FROZEN_SCOPE_METADATA_MISSING")
            rows.append(
                {
                    **dict(row),
                    "snapshot_id": documents[job_id]["snapshot_id"],
                    "layer": "frozen_job_metadata",
                }
            )
    return {"notice": SCOPE_CONTEXT_NOTICE, "jobs": rows}


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern="^[a-zA-Z0-9_-]{1,60}$")
    description: str = Field(min_length=1, max_length=1000)
    required: bool = True


class ResearchTask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern="^[a-zA-Z0-9_-]{1,60}$")
    split: Literal["development", "holdout"]
    question: str = Field(min_length=1, max_length=4000)
    job_ids: list[str] = Field(min_length=1, max_length=20)
    criteria: list[Criterion] = Field(min_length=1, max_length=12)
    max_model_calls: int = Field(default=12, ge=1, le=72)
    max_elapsed_seconds: int = Field(default=300, ge=1, le=1800)
    reused_case_declared: bool = False


class MethodArm(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    output_type: Literal["research"] = "research"
    method_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    method_version: str = Field(min_length=1, max_length=150)
    approach: Literal["standard", "source_first"] | None = None
    strategy_sha256: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    context_sha256: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")


class DimensionRating(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    rating: Literal["pass", "fail", "unknown", "not_applicable"] = "unknown"
    reason: str = Field(min_length=1, max_length=1200)


class ClaimRating(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    index: int = Field(ge=0, le=23)
    support: Literal["supported", "unsupported", "unknown"] = "unknown"
    requirement: Literal["correct", "incorrect", "unknown"] = "unknown"
    reason: str = Field(min_length=1, max_length=1200)


class CriterionRating(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=60)
    rating: Literal["satisfied", "omitted", "unknown", "not_applicable"] = "unknown"
    reason: str = Field(min_length=1, max_length=1200)


class BlindReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    packet_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    reviewer: str = Field(min_length=1, max_length=100)
    reviewer_kind: Literal["human", "agent_assisted"] = "agent_assisted"
    independent_review_declared: bool = False
    blinded_review_declared: bool = False
    dimensions: dict[str, DimensionRating]
    claim_ratings: list[ClaimRating] = Field(max_length=24)
    criterion_ratings: list[CriterionRating] = Field(min_length=1, max_length=12)
    note: str = Field(min_length=1, max_length=2000)


def _normal(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _finite(value):
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def _timestamp(value):
    try:
        stamp = datetime.fromisoformat(value)
        return stamp if stamp.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


class ResearchBenchmarkService:
    def __init__(self, store, repository, *, artifact_root=None):
        self.store, self.repository = store, repository
        repository.bind_research_store(store)
        self.root = (
            Path(artifact_root)
            if artifact_root
            else Path(repository.engine.url.database).parent / "research-benchmarks"
        )
        with store.lock, store.db:
            for table in TABLES:
                store.db.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} (namespace TEXT NOT NULL, "
                    "id TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(namespace,id))"
                )

    def _get(self, table, identity):
        with self.store.lock:
            row = self.store.db.execute(
                f"SELECT record FROM {table} WHERE namespace=? AND id=?",
                (self.store.namespace, identity),
            ).fetchone()
        if not row:
            raise ProbeError("BENCHMARK_RECORD_NOT_FOUND")
        record = json.loads(row[0])
        if record.get("state") == "invalidated":
            raise ProbeError("BENCHMARK_DEPENDENCY_FORGOTTEN")
        return record

    def _save(self, table, record):
        self.store.db.execute(
            f"INSERT INTO {table} VALUES (?,?,?) ON CONFLICT(namespace,id) "
            "DO UPDATE SET record=excluded.record",
            (self.store.namespace, record["id"], json.dumps(record, ensure_ascii=False)),
        )

    def _all(self, table):
        with self.store.lock:
            rows = self.store.db.execute(
                f"SELECT record FROM {table} WHERE namespace=?", (self.store.namespace,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _protocol(self, identity):
        record = self._get(TABLES[0], identity)
        if digest(record["protocol"]) != record["protocol_sha256"]:
            raise ProbeError("BENCHMARK_PROTOCOL_CHANGED")
        corpus = load_corpus(self.root / identity / "corpus")
        if corpus["corpus_sha256"] != record["protocol"]["corpus_sha256"]:
            raise ProbeError("BENCHMARK_CORPUS_CHANGED")
        return record, corpus

    def preregister(
        self,
        title,
        tasks,
        methods,
        *,
        task_author,
        task_author_kind="agent_assisted",
        independent_tasks_declared=False,
        existing_corpus_exposed=True,
        allow_retrospective_development=False,
        external_registration_sha256=None,
        dependency_run_ids=None,
        dependency_project_ids=None,
        dependency_memory_refs=None,
    ):
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 150
            or not isinstance(task_author, str)
            or not task_author.strip()
            or len(task_author) > 100
        ):
            raise ProbeError("BENCHMARK_REGISTRATION_TEXT_REQUIRED")
        if (
            task_author_kind not in {"human", "agent_assisted"}
            or independent_tasks_declared
            and task_author_kind != "human"
        ):
            raise ProbeError("BENCHMARK_TASK_AUTHOR_REQUIRED")
        if any(
            type(value) is not bool
            for value in (
                independent_tasks_declared,
                existing_corpus_exposed,
                allow_retrospective_development,
            )
        ):
            raise ProbeError("BENCHMARK_EXPLICIT_BOOLEAN_DECLARATIONS_REQUIRED")
        if external_registration_sha256 is not None and not re.fullmatch(
            r"[a-f0-9]{64}", external_registration_sha256
        ):
            raise ProbeError("BENCHMARK_INVALID_EXTERNAL_REGISTRATION_DIGEST")
        dependency_run_ids = dependency_run_ids or []
        dependency_project_ids = dependency_project_ids or []
        dependency_memory_refs = dependency_memory_refs or []
        if any(
            not isinstance(values, list)
            or len(values) > 40
            or any(
                not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value)
                for value in values
            )
            for values in (dependency_run_ids, dependency_project_ids)
        ):
            raise ProbeError("BENCHMARK_INVALID_DEPENDENCY_IDS")
        if (
            not isinstance(dependency_memory_refs, list)
            or len(dependency_memory_refs) > 40
            or any(
                not isinstance(ref, dict)
                or set(ref) != {"id", "version"}
                or not isinstance(ref["id"], str)
                or type(ref["version"]) is not int
                for ref in dependency_memory_refs
            )
        ):
            raise ProbeError("BENCHMARK_INVALID_MEMORY_DEPENDENCIES")
        if (
            not isinstance(tasks, list)
            or not 1 <= len(tasks) <= 20
            or not isinstance(methods, dict)
            or set(methods) != {"baseline", "candidate"}
        ):
            raise ProbeError("BENCHMARK_INVALID_PROTOCOL")
        tasks = [ResearchTask.model_validate(row).model_dump() for row in tasks]
        methods = {key: MethodArm.model_validate(row).model_dump() for key, row in methods.items()}
        if len({row["id"] for row in tasks}) != len(tasks) or any(
            len({c["id"] for c in row["criteria"]}) != len(row["criteria"])
            or len(set(row["job_ids"])) != len(row["job_ids"])
            for row in tasks
        ):
            raise ProbeError("BENCHMARK_DUPLICATE_TASK_OR_CRITERION")
        identity = uuid4().hex
        freeze(Path(self.repository.engine.url.database), self.root / identity / "corpus")
        corpus = load_corpus(self.root / identity / "corpus")
        docs = {row["job_id"]: row for row in corpus["documents"]}
        known = {
            fingerprint
            for row in self._all(TABLES[0])
            for fingerprint in row.get("question_scope_fingerprints", [])
        }
        fingerprints = []
        for task in tasks:
            if not set(task["job_ids"]) <= set(docs):
                raise ProbeError("BENCHMARK_FROZEN_DETAIL_SCOPE_REQUIRED")
            if sum(len(docs[job]["text"]) for job in task["job_ids"]) > 100000:
                raise ProbeError("BENCHMARK_REVIEW_SOURCE_CHARACTERS_LIMIT")
            task["sources"] = [
                {
                    key: docs[job].get(key)
                    for key in (
                        "job_id",
                        "snapshot_id",
                        "content_sha256",
                        "document_id",
                        "document_sha256",
                        "text_sha256",
                    )
                }
                for job in sorted(task["job_ids"])
            ]
            task["scope_context"] = _frozen_scope_context(
                self.root / identity / "corpus", docs, task["job_ids"]
            )
            fingerprint = digest(
                {"question": _normal(task["question"]), "sources": task["sources"]}
            )
            task["question_scope_fingerprint"] = fingerprint
            task["reused_case_detected"] = fingerprint in known or fingerprint in fingerprints
            fingerprints.append(fingerprint)
        # 同题分入两区也必须标记复用，不能靠换ID获得独立留出。
        for task in tasks:
            task["reused_case_detected"] |= (
                fingerprints.count(task["question_scope_fingerprint"]) > 1
            )
        protocol = {
            "version": "business-research-benchmark-v1",
            "packet_context_version": 2,
            "id": identity,
            "title": title.strip(),
            "locked_at": now(),
            "task_author": task_author.strip(),
            "task_author_kind": task_author_kind,
            "independent_tasks_declared": independent_tasks_declared,
            "existing_corpus_exposed": existing_corpus_exposed,
            "allow_retrospective_development": allow_retrospective_development,
            "external_registration_sha256": external_registration_sha256,
            "corpus_sha256": corpus["corpus_sha256"],
            "data_kind": "synthetic"
            if all(
                docs[job]["data_kind"] == "synthetic" for task in tasks for job in task["job_ids"]
            )
            else "mixed"
            if any(
                docs[job]["data_kind"] == "synthetic" for task in tasks for job in task["job_ids"]
            )
            else "real_or_user_provided",
            "tasks": tasks,
            "methods": methods,
            "gates": GATES,
        }
        record = {
            "id": identity,
            "state": "locked",
            "created_at": protocol["locked_at"],
            "protocol": protocol,
            "protocol_sha256": digest(protocol),
            "question_scope_fingerprints": fingerprints,
            "source_run_ids": dependency_run_ids,
            "project_ids": dependency_project_ids,
            "memory_refs": dependency_memory_refs,
        }
        with self.store.lock, self.store.db:
            self._save(TABLES[0], record)
        return self.overview(identity)

    def overview(self, identity=None):
        rows = (
            [self._protocol(identity)[0]]
            if identity
            else [row for row in self._all(TABLES[0]) if row.get("state") != "invalidated"]
        )
        items = [
            {
                "id": row["id"],
                "title": row["protocol"]["title"],
                "protocol_sha256": row["protocol_sha256"],
                "locked_at": row["protocol"]["locked_at"],
                "development_tasks": sum(
                    task["split"] == "development" for task in row["protocol"]["tasks"]
                ),
                "holdout_tasks": sum(
                    task["split"] == "holdout" for task in row["protocol"]["tasks"]
                ),
                "existing_corpus_exposed": row["protocol"]["existing_corpus_exposed"],
                "data_kind": row["protocol"]["data_kind"],
                "notice": (
                    "仅为冻结语料内业务评测；人类与独立声明不由程序证明，未执行或启用任何方法。"
                ),
            }
            for row in rows
        ]
        return items[0] if identity else items

    def development_tasks(self, identity):
        record, _ = self._protocol(identity)
        return [row for row in record["protocol"]["tasks"] if row["split"] == "development"]

    def open_phase(self, identity, phase):
        if phase not in {"development", "holdout"}:
            raise ProbeError("BENCHMARK_INVALID_PHASE")
        with self.store.lock, self.store.db:
            record, _ = self._protocol(identity)
            round_id = digest({"benchmark": identity, "phase": phase})[:32]
            if any(row["id"] == round_id for row in self._all(TABLES[2])):
                raise ProbeError("BENCHMARK_PHASE_ALREADY_RESERVED")
            tasks = [task for task in record["protocol"]["tasks"] if task["split"] == phase]
            if not tasks:
                raise ProbeError("BENCHMARK_PHASE_HAS_NO_TASKS")
            slots = [
                {"task_id": task["id"], "arm": arm, "submission_id": uuid4().hex}
                for task in tasks
                for arm in ("baseline", "candidate")
            ]
            round_record = {
                "id": round_id,
                "benchmark_id": identity,
                "phase": phase,
                "state": "collecting",
                "opened_at": now(),
                "slots": slots,
                "packets": [],
                "review_ids": [],
                "source_run_ids": [],
                "project_ids": [],
                "memory_refs": [],
            }
            self._save(TABLES[2], round_record)
        return {
            key: round_record[key] for key in ("id", "benchmark_id", "phase", "state", "opened_at")
        }

    def _round(self, identity, phase):
        return self._get(TABLES[2], digest({"benchmark": identity, "phase": phase})[:32])

    def _output(self, output_type, source_id):
        if output_type != "research":
            raise ProbeError("BENCHMARK_PROFILE_OUTPUT_NOT_SUPPORTED")
        run = self.store.get(source_id)
        if run["state"] == "invalidated":
            raise ProbeError("BENCHMARK_DEPENDENCY_FORGOTTEN")
        context_sha256 = effective_prompt_sha256 = effective_question_sha256 = None
        effective_scope_job_ids = None
        saved = self.store.load_checkpoint(source_id) or {}
        for event in saved.get("history", []):
            if not isinstance(event, dict) or event.get("role") != "user":
                continue
            try:
                content = event.get("content")
                if not isinstance(content, str) or len(content) > 500000:
                    break
                payload = json.loads(content)
                if (
                    isinstance(payload, dict)
                    and {"project_context", "memory_context", "question", "fixed_scope"}
                    <= payload.keys()
                    and isinstance(payload["fixed_scope"], dict)
                    and isinstance(payload["fixed_scope"].get("jobs"), list)
                    and isinstance(payload["memory_context"], list)
                    and (
                        payload["project_context"] is None
                        or isinstance(payload["project_context"], dict)
                    )
                ):
                    context_sha256 = digest(
                        {key: payload[key] for key in ("project_context", "memory_context")}
                        | (
                            {"review_feedback": payload["review_feedback"]}
                            if payload.get("review_feedback")
                            else {}
                        )
                    )
                    effective_prompt_sha256 = digest(payload)
                    effective_question_sha256 = digest(payload["question"])
                    effective_scope_job_ids = sorted(
                        row["id"]
                        for row in payload["fixed_scope"].get("jobs", [])
                        if isinstance(row, dict) and row.get("id")
                    )
            except (ValueError, TypeError):
                pass
            break
        return run.get("result") or {}, {
            "state": run["state"],
            "created_at": run["created_at"],
            "input": run.get("input", {}),
            "project_id": (run.get("result") or {}).get("project_id")
            or run.get("input", {}).get("project_id"),
            "effective_context_sha256": context_sha256,
            "effective_prompt_sha256": effective_prompt_sha256,
            "effective_question_sha256": effective_question_sha256,
            "effective_scope_job_ids": effective_scope_job_ids,
            "context_verifiability": "verified_effective_prompt"
            if context_sha256
            else "reference_only",
        }

    @staticmethod
    def _method(result, metadata, output_type):
        refs = [
            {key: row.get(key) for key in ("id", "version")}
            for row in [*result.get("memory_used", []), *result.get("context_memory_used", [])]
        ]
        actual = {
            "output_type": output_type,
            "method_sha256": result.get("research_method_sha256"),
            "method_version": result.get("research_method_version"),
            "strategy_sha256": (result.get("strategy") or {}).get("config_sha256"),
            "context_sha256": metadata.get("effective_context_sha256"),
            "context_verifiability": metadata["context_verifiability"],
            "context_reference_sha256": digest(
                {
                    "memory_refs": refs,
                    "knowledge_refs": result.get("knowledge_used", []),
                    "continued_from": result.get("continued_from", []),
                    "project_id": metadata.get("project_id"),
                }
            ),
        }
        # 不改旧协议/旧提交的实际方法摘要；新方法显式绑定入口选择。
        if "approach" in result or "approach" in metadata.get("input", {}):
            actual["approach"] = result.get("approach", "standard")
        return actual

    @staticmethod
    def _usage(result):
        rows = result.get("usage") if isinstance(result.get("usage"), list) else []

        def total(key):
            values = [row.get(key) for row in rows if isinstance(row, dict)]
            return sum(values) if values and all(_finite(value) for value in values) else None

        return {
            "model_calls": result.get("model_calls"),
            "elapsed_seconds": result.get("elapsed_seconds"),
            "input_tokens": total("input_tokens"),
            "output_tokens": total("output_tokens"),
            "total_tokens": total("total_tokens"),
            "provider_usage_sha256": digest(rows),
            "cost": None,
        }

    def register(self, identity, task_id, arm, source_id):
        with self.store.lock, self.store.db:
            benchmark, corpus = self._protocol(identity)
            protocol = benchmark["protocol"]
            task = next((row for row in protocol["tasks"] if row["id"] == task_id), None)
            if task is None or arm not in protocol["methods"]:
                raise ProbeError("BENCHMARK_TASK_OR_ARM_UNKNOWN")
            round_record = self._round(identity, task["split"])
            if round_record["state"] != "collecting":
                raise ProbeError("BENCHMARK_PHASE_ALREADY_SEALED")
            slot = next(
                row
                for row in round_record["slots"]
                if row["task_id"] == task_id and row["arm"] == arm
            )
            if any(row["id"] == slot["submission_id"] for row in self._all(TABLES[1])):
                raise ProbeError("BENCHMARK_ATTEMPT_ALREADY_REGISTERED")
            expected = protocol["methods"][arm]
            result, metadata = self._output(expected["output_type"], source_id)
            if metadata["state"] == "running":
                raise ProbeError("BENCHMARK_RUNNING_RESULT_NOT_FINAL")
            actual = self._method(result, metadata, expected["output_type"])
            issues = []
            if metadata["context_verifiability"] != "verified_effective_prompt":
                issues.append("context_unverifiable")
            elif metadata["effective_question_sha256"] != digest(task["question"]) or set(
                metadata["effective_scope_job_ids"] or []
            ) != set(task["job_ids"]):
                issues.append("effective_prompt_question_or_scope_mismatch")
            if (
                expected["output_type"] == "research"
                and result
                and result.get("run_id") != source_id
            ):
                issues.append("authoritative_run_id_mismatch")
            question = result.get("question", metadata["input"].get("question"))
            if question != task["question"]:
                issues.append("question_mismatch")
            actual_jobs = {row["id"] for row in result.get("scope", {}).get("jobs", [])} or set(
                metadata["input"].get("job_ids", [])
            )
            if actual_jobs != set(task["job_ids"]):
                issues.append("scope_mismatch")
            for key, value in expected.items():
                if value is not None and actual.get(key) != value:
                    issues.append("method_contract_mismatch:" + key)
            run_time = _timestamp(metadata["created_at"])
            opened = _timestamp(round_record["opened_at"])
            retrospective = not (run_time and opened and run_time >= opened)
            if retrospective and (
                task["split"] == "holdout" or not protocol["allow_retrospective_development"]
            ):
                issues.append("run_predates_reserved_attempt")
            if task["split"] == "holdout" and (
                task["reused_case_declared"] or task["reused_case_detected"]
            ):
                issues.append("holdout_case_previously_exposed_or_reused")
            if any(
                row.get("source_id") == source_id
                and row.get("output_type") == expected["output_type"]
                for row in self._all(TABLES[1])
            ):
                issues.append("same_authoritative_output_reused")
            source_map = {
                row["job_id"]: row
                for row in corpus["documents"]
                if row["job_id"] in task["job_ids"]
            }
            for evidence in result.get("evidence", []):
                doc = source_map.get(evidence.get("job_id"), {})
                start, end = evidence.get("start"), evidence.get("end")
                if not (
                    doc
                    and type(start) is int
                    and type(end) is int
                    and 0 <= start < end <= len(doc["text"])
                    and doc["text"][start:end] == evidence.get("quote")
                    and evidence.get("id") == f"{doc['snapshot_id']}:{start}:{end}"
                    and all(
                        evidence.get(key) == doc[key]
                        for key in (
                            "snapshot_id",
                            "document_id",
                            "document_sha256",
                            "content_sha256",
                        )
                    )
                ):
                    issues.append("source_outside_frozen_contract")
            claims = result.get("claims", [])
            known = {row.get("id") for row in result.get("evidence", [])}
            if len(claims) > 24 or any(
                not claim.get("evidence_ids") or not set(claim["evidence_ids"]) <= known
                for claim in claims
            ):
                issues.append("invalid_claim_citations")
            if result.get("status") == "completed" and not claims:
                issues.append("completed_without_claims")
            usage = self._usage(result)
            budget_ok = (
                type(usage["model_calls"]) is int
                and 0 <= usage["model_calls"] <= task["max_model_calls"]
                and _finite(usage["elapsed_seconds"])
                and usage["elapsed_seconds"] <= task["max_elapsed_seconds"]
            )
            if not budget_ok:
                issues.append("budget_exceeded_or_usage_unknown")
            audit = audit_result(result, self.repository)
            if any(
                audit.get(key)
                for key in (
                    "stale_memory",
                    "stale_knowledge",
                    "stale_dependencies",
                    "affected_strategy",
                )
            ) or any(
                not row.get("retained_evidence_valid") for row in audit.get("changed_sources", [])
            ):
                issues.append("source_or_dependency_unavailable")
            if result.get("status") != "completed" or metadata["state"] not in {
                "finished",
                "completed",
            }:
                issues.append("execution_not_completed")
            refs = [
                {key: row.get(key) for key in ("id", "version")}
                for row in [
                    *result.get("memory_used", []),
                    *result.get("context_memory_used", []),
                    *metadata.get("memory_versions", []),
                ]
            ]
            submission = {
                "id": slot["submission_id"],
                "benchmark_id": identity,
                "task_id": task_id,
                "arm": arm,
                "split": task["split"],
                "state": "registered",
                "source_id": source_id,
                "output_type": expected["output_type"],
                "result_sha256": digest(result),
                "execution_metadata_sha256": digest(metadata),
                "effective_prompt_sha256": metadata["effective_prompt_sha256"],
                "execution_budget": {
                    key: metadata["input"].get(key) for key in ("max_calls", "timeout")
                },
                "execution_mode": result.get("mode", "unknown"),
                "actual_method": actual,
                "actual_method_sha256": digest(actual),
                "source_scope_sha256": digest(task["sources"]),
                "usage": usage,
                "execution_state": metadata["state"],
                "execution_status": result.get("status", "result_missing"),
                "contract_issues": sorted(set(issues)),
                "retrospective_development": retrospective,
                "registered_at": now(),
                "source_run_ids": [source_id] if expected["output_type"] == "research" else [],
                "project_ids": [metadata["project_id"]] if metadata.get("project_id") else [],
                "memory_refs": refs,
            }
            self._save(TABLES[1], submission)
            benchmark["source_run_ids"] = sorted(
                set(benchmark["source_run_ids"] + submission["source_run_ids"])
            )
            benchmark["project_ids"] = sorted(
                set(benchmark["project_ids"] + submission["project_ids"])
            )
            benchmark["memory_refs"] = list(
                {row["id"]: row for row in benchmark["memory_refs"] + refs}.values()
            )
            self._save(TABLES[0], benchmark)
        return submission

    def seal_phase(self, identity, phase, *, record_missing=False):
        with self.store.lock, self.store.db:
            benchmark, _ = self._protocol(identity)
            round_record = self._round(identity, phase)
            if round_record["state"] != "collecting":
                raise ProbeError("BENCHMARK_PHASE_ALREADY_SEALED")
            submissions = {row["id"]: row for row in self._all(TABLES[1])}
            missing = [
                slot for slot in round_record["slots"] if slot["submission_id"] not in submissions
            ]
            if missing and not record_missing:
                raise ProbeError("BENCHMARK_ALL_ATTEMPTS_REQUIRED")
            for slot in missing:
                row = {
                    "id": slot["submission_id"],
                    "benchmark_id": identity,
                    "task_id": slot["task_id"],
                    "arm": slot["arm"],
                    "split": phase,
                    "state": "not_registered",
                    "source_id": None,
                    "output_type": benchmark["protocol"]["methods"][slot["arm"]]["output_type"],
                    "result_sha256": None,
                    "actual_method": None,
                    "actual_method_sha256": None,
                    "usage": {
                        "model_calls": None,
                        "elapsed_seconds": None,
                        "total_tokens": None,
                        "cost": None,
                    },
                    "execution_state": "missing",
                    "execution_status": "not_run",
                    "contract_issues": ["missing_registration_recorded_at_seal"],
                    "retrospective_development": False,
                    "source_run_ids": [],
                    "project_ids": [],
                    "memory_refs": [],
                }
                self._save(TABLES[1], row)
            packets = [
                {"id": uuid4().hex, "submission_id": slot["submission_id"]}
                for slot in round_record["slots"]
            ]
            random.SystemRandom().shuffle(packets)
            round_record.update(state="reviewing", sealed_at=now(), packets=packets)
            self._save(TABLES[2], round_record)
        return {
            "round_id": round_record["id"],
            "phase": phase,
            "state": "reviewing",
            "packet_ids": [row["id"] for row in packets],
            "notice": (
                "不含arm、run、方法、实际用量或旧评分；写作风格仍可能被识别，"
                "不能由程序保证真正盲法。"
            ),
        }

    def _packet_location(self, identity, packet_id):
        for round_record in self._all(TABLES[2]):
            if (
                round_record.get("benchmark_id") == identity
                and round_record.get("state") != "invalidated"
            ):
                for packet in round_record.get("packets", []):
                    if packet["id"] == packet_id:
                        return round_record, packet
        raise ProbeError("BENCHMARK_BLIND_PACKET_NOT_FOUND")

    def _bound_result(self, submission):
        if submission["source_id"] is None:
            return {}
        try:
            result, metadata = self._output(submission["output_type"], submission["source_id"])
        except ProbeError:
            self.invalidate(
                submission.get("source_run_ids", []),
                submission.get("project_ids", []),
                [row["id"] for row in submission.get("memory_refs", [])],
            )
            raise
        for ref in submission.get("memory_refs", []):
            audit = MemoryService(self.repository).audit(ref["id"], version=ref["version"])
            if any(row["reason"] in {"forgotten", "missing"} for row in audit["issues"]):
                self.invalidate(memory_ids=[ref["id"]])
                raise ProbeError("BENCHMARK_DEPENDENCY_FORGOTTEN")
        if (
            digest(result) != submission["result_sha256"]
            or digest(metadata) != submission["execution_metadata_sha256"]
            or digest(self._method(result, metadata, submission["output_type"]))
            != submission["actual_method_sha256"]
        ):
            raise ProbeError("BENCHMARK_REGISTERED_OUTPUT_CHANGED")
        return result

    def _current_issues(self, result):
        if not result:
            return []
        audit = audit_result(result, self.repository)
        if any(
            audit.get(key)
            for key in (
                "stale_memory",
                "stale_knowledge",
                "stale_dependencies",
                "affected_strategy",
            )
        ) or any(
            not row.get("retained_evidence_valid") for row in audit.get("changed_sources", [])
        ):
            return ["current_source_or_dependency_unavailable"]
        return []

    def blind_packet(self, identity, packet_id):
        benchmark, corpus = self._protocol(identity)
        round_record, packet = self._packet_location(identity, packet_id)
        if round_record["state"] != "reviewing":
            raise ProbeError("BENCHMARK_BLIND_REVIEW_CLOSED")
        submission = self._get(TABLES[1], packet["submission_id"])
        result = self._bound_result(submission)
        task = next(
            row for row in benchmark["protocol"]["tasks"] if row["id"] == submission["task_id"]
        )
        selected = [row for row in corpus["documents"] if row["job_id"] in task["job_ids"]]
        claims = result.get("claims", [])
        if not isinstance(claims, list) or len(claims) > 24:
            claims = []
        evidence = {
            row["id"]: row
            for row in result.get("evidence", [])
            if isinstance(row, dict) and row.get("id")
        }
        formatted = []
        for index, claim in enumerate(claims):
            formatted.append(
                {
                    "index": index,
                    "text": claim.get("text"),
                    "category": claim.get("category"),
                    "basis": claim.get("basis"),
                    "requirement": claim.get("requirement"),
                    "citations": [
                        {
                            key: evidence.get(key_id, {}).get(key)
                            for key in (
                                "id",
                                "job_id",
                                "snapshot_id",
                                "document_id",
                                "document_sha256",
                                "quote",
                                "start",
                                "end",
                            )
                        }
                        for key_id in claim.get("evidence_ids", [])
                    ],
                }
            )
            for field in ("bindings", "sentence_citations"):
                if field in claim:
                    formatted[-1][field] = claim[field]
        value = {
            "packet_id": packet_id,
            "protocol_sha256": benchmark["protocol_sha256"],
            "question": task["question"],
            "completion_criteria": task["criteria"],
            "declared_budget": {
                "max_model_calls": task["max_model_calls"],
                "max_elapsed_seconds": task["max_elapsed_seconds"],
            },
            "claims": formatted,
            "gaps": [str(gap)[:1200] for gap in result.get("gaps", [])[:12]],
            "execution_status": submission["execution_status"],
            "mechanical_issues": sorted(
                set(submission["contract_issues"] + self._current_issues(result))
            ),
            "frozen_sources": [
                {
                    key: row.get(key)
                    for key in (
                        "job_id",
                        "title",
                        "snapshot_id",
                        "document_id",
                        "document_sha256",
                        "text",
                        "data_kind",
                    )
                }
                for row in selected
            ],
            "notice": (
                "只按冻结原文和完成条件核对，不参考旧评分。字段不暴露arm/run/方法身份；"
                "元数据隐藏不保证审核者此前未见过答案。"
            ),
        }
        notes = source_analysis_notes(result)
        if benchmark["protocol"].get("packet_context_version", 1) == 2:
            if "scope_context" not in task:
                raise ProbeError("BENCHMARK_FROZEN_SCOPE_METADATA_MISSING")
            value["scope_context"] = task["scope_context"]
        if notes:
            value["analysis_notes"] = notes
        if result.get("source_findings"):
            from work_observer.research.source_first import review_finding_history, review_findings

            value["source_findings"] = review_findings(result["source_findings"])
            history = review_finding_history(result["source_findings"])
            if history:
                value["source_finding_history"] = history
        value["packet_sha256"] = digest(value)
        return value

    def submit_review(self, identity, packet_id, review):
        data = BlindReview.model_validate(review).model_dump()
        with self.store.lock, self.store.db:
            packet = self.blind_packet(identity, packet_id)
            if data["packet_sha256"] != packet["packet_sha256"]:
                raise ProbeError("BENCHMARK_PACKET_CHANGED")
            if set(data["dimensions"]) != set(DIMENSIONS):
                raise ProbeError("BENCHMARK_SIX_DIMENSIONS_REQUIRED")
            if len(data["claim_ratings"]) != len(packet["claims"]) or {
                row["index"] for row in data["claim_ratings"]
            } != set(range(len(packet["claims"]))):
                raise ProbeError("BENCHMARK_ALL_CLAIMS_REQUIRE_REVIEW")
            if len(data["criterion_ratings"]) != len(packet["completion_criteria"]) or {
                row["id"] for row in data["criterion_ratings"]
            } != {row["id"] for row in packet["completion_criteria"]}:
                raise ProbeError("BENCHMARK_ALL_CRITERIA_REQUIRE_REVIEW")
            round_record, location = self._packet_location(identity, packet_id)
            history = [row for row in self._all(TABLES[3]) if row.get("packet_id") == packet_id]
            actor = self._reviewer_key(data)
            actor_history = [row for row in history if self._reviewer_key(row["review"]) == actor]
            latest = self._latest_reviews(actor_history)
            if latest and latest[0]["review_sha256"] == digest(data):
                return {
                    "id": latest[0]["id"],
                    "state": "recorded",
                    "reviewer_kind": data["reviewer_kind"],
                }
            if not actor_history and len(self._latest_reviews(history)) >= 5:
                raise ProbeError("BENCHMARK_REVIEWER_LIMIT_FIVE")
            if len(history) >= 50:
                raise ProbeError("BENCHMARK_REVIEW_REVISION_LIMIT_FIFTY")
            revision = len(actor_history) + 1
            review_id = digest(
                {"packet": packet_id, "actor": actor, "revision": revision, "review": data}
            )[:32]
            self._save(
                TABLES[3],
                {
                    "id": review_id,
                    "benchmark_id": identity,
                    "round_id": round_record["id"],
                    "packet_id": packet_id,
                    "submission_id": location["submission_id"],
                    "state": "recorded",
                    "created_at": now(),
                    "reviewer_revision": revision,
                    "review_sha256": digest(data),
                    "review": data,
                },
            )
        return {
            "id": review_id,
            "state": "recorded",
            "reviewer_kind": data["reviewer_kind"],
            "notice": "记录审核者声明，不由程序证明身份/独立性或语义正确。",
        }

    @staticmethod
    def _reviewer_key(data):
        # This groups self-declared names, not verified identities.
        name = " ".join(unicodedata.normalize("NFKC", data["reviewer"]).casefold().split())
        return data["reviewer_kind"], name

    @classmethod
    def _latest_reviews(cls, history):
        latest = {}
        for row in sorted(
            history,
            key=lambda row: (row["created_at"], row.get("reviewer_revision", 0), row["id"]),
        ):
            latest[cls._reviewer_key(row["review"])] = row
        return list(latest.values())

    def close_phase(self, identity, phase):
        with self.store.lock, self.store.db:
            self._protocol(identity)
            round_record = self._round(identity, phase)
            if round_record["state"] != "reviewing":
                raise ProbeError("BENCHMARK_ROUND_NOT_REVIEWING")
            reviews = [
                row for row in self._all(TABLES[3]) if row.get("round_id") == round_record["id"]
            ]
            if not {row["id"] for row in round_record["packets"]} <= {
                row["packet_id"] for row in reviews
            }:
                raise ProbeError("BENCHMARK_ALL_BLIND_PACKETS_REQUIRE_REVIEW")
            round_record.update(
                state="closed", closed_at=now(), review_ids=[row["id"] for row in reviews]
            )
            self._save(TABLES[2], round_record)
        return self.paired_report(identity, phase)

    @staticmethod
    def _review_score(review, task):
        data = review["review"]
        dimensions = {key: value["rating"] for key, value in data["dimensions"].items()}
        criteria = {row["id"]: row["rating"] for row in data["criterion_ratings"]}
        claims = data["claim_ratings"]
        return {
            "criterion_ratings": criteria,
            "dimension_ratings": dimensions,
            "claim_ratings": {
                str(row["index"]): {"support": row["support"], "requirement": row["requirement"]}
                for row in claims
            },
            "supported": sum(row["support"] == "supported" for row in claims),
            "unsupported": sum(row["support"] == "unsupported" for row in claims),
            "support_unknown": sum(row["support"] == "unknown" for row in claims),
            "requirement_incorrect": sum(row["requirement"] == "incorrect" for row in claims),
            "requirement_unknown": sum(row["requirement"] == "unknown" for row in claims),
            "omitted_criteria": sum(value == "omitted" for value in criteria.values()),
            "unknown_criteria": sum(value == "unknown" for value in criteria.values()),
            "required_criteria_satisfied": all(
                criteria[row["id"]] == "satisfied" for row in task["criteria"] if row["required"]
            ),
            "unknown_handling": dimensions["unknown_handling"],
            "question_answered": dimensions["question_answered"],
            "all_dimensions_satisfied": all(
                value in {"pass", "not_applicable"} for value in dimensions.values()
            )
            and all(
                dimensions[key] == "pass"
                for key in ("citation_semantics", "unknown_handling", "question_answered")
            ),
        }

    def paired_report(self, identity, phase):
        benchmark, _ = self._protocol(identity)
        protocol = benchmark["protocol"]
        round_record = self._round(identity, phase)
        if round_record["state"] != "closed":
            raise ProbeError("BENCHMARK_UNBLIND_REQUIRES_CLOSED_REVIEWS")
        all_reviews = {row["id"]: row for row in self._all(TABLES[3])}
        reviews = [all_reviews[key] for key in round_record["review_ids"]]
        pairs = []
        candidate_answers = baseline_answers = 0
        all_human = True
        all_contracts = True
        confounds = False
        tasks = [row for row in protocol["tasks"] if row["split"] == phase]
        for task in tasks:
            pair = {
                "task_id": task["id"],
                "question": task["question"],
                "reused_case": task["reused_case_declared"] or task["reused_case_detected"],
                "arms": {},
            }
            for arm in ("baseline", "candidate"):
                slot = next(
                    row
                    for row in round_record["slots"]
                    if row["task_id"] == task["id"] and row["arm"] == arm
                )
                submission = self._get(TABLES[1], slot["submission_id"])
                result = self._bound_result(submission)
                current_issues = self._current_issues(result)
                history = [row for row in reviews if row["submission_id"] == submission["id"]]
                assessments = self._latest_reviews(history)
                human = [
                    row
                    for row in assessments
                    if row["review"]["reviewer_kind"] == "human"
                    and row["review"]["independent_review_declared"]
                    and row["review"]["blinded_review_declared"]
                ]
                scores = [self._review_score(row, task) for row in human or assessments]
                conflict = any(row != scores[0] for row in scores[1:]) if scores else False
                score = scores[0] if scores and not conflict else None
                completed = bool(
                    score
                    and score["question_answered"] == "pass"
                    and score["required_criteria_satisfied"]
                    and score["all_dimensions_satisfied"]
                    and score["unsupported"]
                    == score["support_unknown"]
                    == score["requirement_incorrect"]
                    == score["requirement_unknown"]
                    == 0
                    and submission["execution_status"] == "completed"
                    and not submission["contract_issues"]
                    and not current_issues
                )
                all_human &= bool(human) and not conflict
                all_contracts &= not submission["contract_issues"] and not current_issues
                if arm == "candidate":
                    candidate_answers += completed
                else:
                    baseline_answers += completed
                pair["arms"][arm] = {
                    "source_id": submission["source_id"],
                    "output_type": submission["output_type"],
                    "execution_status": submission["execution_status"],
                    "contract_issues": submission["contract_issues"],
                    "current_integrity_issues": current_issues,
                    "actual_method": submission["actual_method"],
                    "result_sha256": submission["result_sha256"],
                    "usage": submission["usage"],
                    "execution_budget": submission.get("execution_budget"),
                    "execution_mode": submission.get("execution_mode"),
                    "effective_prompt_sha256": submission.get("effective_prompt_sha256"),
                    "retrospective_development": submission["retrospective_development"],
                    "independent_human_reviews": len(human),
                    "agent_assisted_reviews": sum(
                        row["review"]["reviewer_kind"] == "agent_assisted" for row in assessments
                    ),
                    "review_history_count": len(history),
                    "effective_review_count": len(assessments),
                    "review_conflict": conflict,
                    "business_scores": score,
                    "satisfies_task_in_this_review": completed,
                }
            a, b = pair["arms"]["baseline"], pair["arms"]["candidate"]
            for key in ("strategy_sha256", "context_sha256"):
                actual_a = (a["actual_method"] or {}).get(key)
                actual_b = (b["actual_method"] or {}).get(key)
                if actual_a != actual_b and any(
                    protocol["methods"][arm][key] is None for arm in ("baseline", "candidate")
                ):
                    confounds = True
            if any(
                (row["actual_method"] or {}).get("context_verifiability")
                != "verified_effective_prompt"
                for row in (a, b)
            ):
                confounds = True
            pairs.append(pair)
        # Label/version text or a different personal context alone is not a method change.
        method_change = any(
            protocol["methods"]["baseline"][key] != protocol["methods"]["candidate"][key]
            for key in ("method_sha256", "strategy_sha256")
        )
        if any(
            pair["arms"]["baseline"]["result_sha256"] == pair["arms"]["candidate"]["result_sha256"]
            for pair in pairs
        ):
            method_change = False
        reused = any(pair["reused_case"] for pair in pairs)
        independent = (
            protocol["task_author_kind"] == "human"
            and protocol["independent_tasks_declared"]
            and all_human
        )
        if not method_change:
            decision = "no_demonstrated_change"
        elif (
            phase != "holdout"
            or len(tasks) < GATES["minimum_holdout_tasks"]
            or not independent
            or reused
            or confounds
        ):
            decision = "insufficient"
        elif (
            not all_contracts
            or candidate_answers - baseline_answers < GATES["minimum_candidate_answer_gain"]
        ):
            decision = "rejected"
        else:
            decision = "accepted_in_frozen_scope"
        return {
            "benchmark_id": identity,
            "protocol_sha256": benchmark["protocol_sha256"],
            "phase": phase,
            "data_kind": protocol["data_kind"],
            "state": "closed",
            "decision": decision,
            "method_change_locked": method_change,
            "independent_human_review_complete": independent,
            "review_sufficiency": "sufficient" if independent else "insufficient",
            "uncontrolled_context_or_strategy": confounds,
            "strict_single_variable_claim": False,
            "existing_corpus_exposed": protocol["existing_corpus_exposed"],
            "generalization_scope": "same_corpus_task_holdout"
            if protocol["existing_corpus_exposed"]
            else "frozen_corpus_only_not_market_generalization",
            "candidate_tasks_satisfied": candidate_answers,
            "baseline_tasks_satisfied": baseline_answers,
            "pairs": pairs,
            "automatic_activation": False,
            "notice": (
                "人工和独立性为审核者声明；机械绑定不是语义正确率。"
                "开发回顾、复用题或同方法标签不能当新盲验或方法改进。"
            ),
        }

    def invalidate(self, run_ids=(), project_ids=(), memory_ids=()):
        affected = []
        with self.store.lock, self.store.db:
            for record in self._all(TABLES[0]):
                if not (
                    set(record.get("source_run_ids", [])) & set(run_ids)
                    or set(record.get("project_ids", [])) & set(project_ids)
                    or {row["id"] for row in record.get("memory_refs", [])} & set(memory_ids)
                ):
                    continue
                identity = record["id"]
                affected.append(identity)
                minimal = {
                    key: record.get(key)
                    for key in (
                        "id",
                        "source_run_ids",
                        "project_ids",
                        "memory_refs",
                        "question_scope_fingerprints",
                    )
                }
                minimal["state"] = "invalidated"
                self._save(TABLES[0], minimal)
                for table in TABLES[1:]:
                    for child in self._all(table):
                        if child.get("benchmark_id") == identity:
                            self._save(
                                table,
                                {
                                    "id": child["id"],
                                    "benchmark_id": identity,
                                    "state": "invalidated",
                                },
                            )
        return {"invalidated_research_benchmark_ids": affected}
