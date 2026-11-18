"""真实资料质量基线；结构检查与语义审核分离，不自动启用候选。"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.retrieval.enhanced import RetrievalService
from work_observer.tracking.evaluation import validate_aliases

VERSION = "real-research-quality-v1"
DIMENSIONS = (
    "citation_semantics",
    "requirement_classification",
    "profile_coverage",
    "unknown_handling",
    "counterexamples",
    "question_answered",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    """不可静默覆盖冻结文件或既有审核。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def freeze(database, directory):
    """SQLite backup只读取来源；冻结库是含真实资料的本机私有文件。"""
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=False)
    target = root / "corpus.db"
    with readonly(database) as source, sqlite3.connect(target) as copy:
        source.backup(copy)
        if copy.execute("pragma integrity_check").fetchone()[0] != "ok":
            raise ProbeError("QUALITY_CORPUS_INTEGRITY_FAILED")
    with readonly(target) as connection:
        connection.row_factory = sqlite3.Row
        documents = []
        rows = connection.execute(
            "select id,title,description_text,field_document_ids,source_published_at "
            "from jobs order by id"
        ).fetchall()
        for row in rows:
            if not row["description_text"]:
                continue
            source_id = json.loads(row["field_document_ids"] or "{}").get("description_text")
            version = connection.execute(
                "select s.id,s.content_sha256,d.sha256,d.response_origin,d.provenance,"
                "s.payload,d.path "
                "from job_observations o join job_snapshots s on o.snapshot_id=s.id "
                "join source_documents d on o.document_id=d.id "
                "where o.job_id=? and d.id=? and o.kind='detail' "
                "order by o.observed_at desc,o.processed_at desc limit 1",
                (row["id"], source_id),
            ).fetchone()
            if version is None:
                raise ProbeError("QUALITY_SOURCE_VERSION_MISSING")
            if json.loads(version[5]).get("description") != row["description_text"]:
                raise ProbeError("QUALITY_SOURCE_VERSION_TEXT_MISMATCH")
            source_path = Path(version[6])
            source_integrity = (
                source_path.is_file()
                and hashlib.sha256(source_path.read_bytes()).hexdigest() == version[2]
            )
            if not source_integrity:
                raise ProbeError("QUALITY_ORIGINAL_SOURCE_MISSING_OR_CHANGED")
            documents.append(
                {
                    "job_id": row["id"],
                    "title": row["title"],
                    "text": row["description_text"],
                    "text_sha256": hashlib.sha256(row["description_text"].encode()).hexdigest(),
                    "snapshot_id": version[0],
                    "content_sha256": version[1],
                    "document_id": source_id,
                    "document_sha256": version[2],
                    "original_source_integrity": "verified_at_freeze",
                    "response_origin": version[3],
                    "data_kind": json.loads(version[4]).get("data_kind", "unspecified"),
                    "source_published_at": row["source_published_at"],
                }
            )
    manifest = {
        "version": VERSION,
        "created_at": now(),
        "database_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "scope_total": len(rows),
        "detail_total": len(documents),
        "missing_detail_total": len(rows) - len(documents),
        "documents": documents,
        "privacy": "本机私有冻结资料，不提交或公开；旧报告、记忆不是独立证据。",
    }
    manifest["corpus_sha256"] = digest(manifest)
    write_json(root / "manifest.json", manifest)
    return {key: value for key, value in manifest.items() if key != "documents"}


def load_corpus(directory):
    root = Path(directory)
    manifest = read_json(root / "manifest.json")
    identity = manifest.pop("corpus_sha256", None)
    if (
        identity != digest(manifest)
        or hashlib.sha256((root / "corpus.db").read_bytes()).hexdigest()
        != manifest["database_sha256"]
    ):
        raise ProbeError("QUALITY_CORPUS_CHANGED")
    return {**manifest, "corpus_sha256": identity}


def lock_suite(directory, cases, *, label_origin="agent_assisted", reviewer=None):
    """锁定问题和分区；人工标签必须由明确人类审核提供。"""
    corpus = load_corpus(directory)
    if label_origin not in {"human", "agent_assisted"}:
        raise ProbeError("QUALITY_LABEL_ORIGIN_REQUIRED")
    if label_origin == "human" and (not isinstance(reviewer, str) or not reviewer.strip()):
        raise ProbeError("QUALITY_HUMAN_REVIEWER_REQUIRED")
    if not isinstance(cases, list) or not 2 <= len(cases) <= 100:
        raise ProbeError("QUALITY_INVALID_CASES")
    documents = {doc["job_id"]: doc for doc in corpus["documents"]}
    seen, splits = set(), set()
    for case in cases:
        if (
            not isinstance(case, dict)
            or set(case) != {"id", "split", "question", "terms", "relevant", "critical", "notes"}
            or not isinstance(case["id"], str)
            or not case["id"]
            or case["id"] in seen
            or case["split"] not in {"development", "holdout"}
            or not isinstance(case["question"], str)
            or not 1 <= len(case["question"]) <= 1200
            or type(case["critical"]) is not bool
            or not isinstance(case["notes"], str)
            or not isinstance(case["relevant"], list)
        ):
            raise ProbeError("QUALITY_INVALID_CASE")
        # 复用实际检索的词数/长度合同。
        from work_observer.retrieval.enhanced import validated_terms

        validated_terms(case["terms"])
        seen.add(case["id"])
        splits.add(case["split"])
        relevant_ids = set()
        for anchor in case["relevant"]:
            if (
                not isinstance(anchor, dict)
                or set(anchor) != {"job_id", "quote", "reason"}
                or anchor["job_id"] not in documents
                or anchor["job_id"] in relevant_ids
                or not isinstance(anchor["quote"], str)
                or not anchor["quote"]
                or anchor["quote"] not in documents[anchor["job_id"]]["text"]
                or not isinstance(anchor["reason"], str)
                or not anchor["reason"].strip()
            ):
                raise ProbeError("QUALITY_LABEL_ANCHOR_INVALID")
            relevant_ids.add(anchor["job_id"])
    if splits != {"development", "holdout"}:
        raise ProbeError("QUALITY_SEPARATE_HOLDOUT_REQUIRED")
    suite = {
        "version": VERSION,
        "corpus_sha256": corpus["corpus_sha256"],
        "label_origin": label_origin,
        "reviewer": reviewer,
        "review_status": "reviewed" if label_origin == "human" else "pending_human",
        "cases": cases,
        "contract": {
            "recall_at_k": 10,
            "maximum_context_characters": 7000,
            "minimum_holdout_cases": 4,
            "minimum_recall_improvement": 0.1,
            "minimum_candidate_recall": 0.85,
            "minimum_candidate_precision": 0.75,
            "critical_regressions_allowed": 0,
            "activation": "仅产出审核建议，不自动启用；真实应用另需有限范围与回退。",
        },
    }
    suite["suite_sha256"] = digest(suite)
    write_json(Path(directory) / "suite.json", suite)
    return suite


def load_suite(directory):
    corpus = load_corpus(directory)
    suite = read_json(Path(directory) / "suite.json")
    identity = suite.pop("suite_sha256", None)
    if identity != digest(suite) or suite["corpus_sha256"] != corpus["corpus_sha256"]:
        raise ProbeError("QUALITY_SUITE_CHANGED")
    return corpus, {**suite, "suite_sha256": identity}


def paired_evaluation(directory, aliases, *, phase="development", baseline_aliases=None):
    """同一冻结资料/问题上调用实际检索器；分区不混合，无人类标签时不足。"""
    started = time.monotonic()
    if phase not in {"development", "holdout"}:
        raise ProbeError("QUALITY_INVALID_PHASE")
    corpus, suite = load_suite(directory)
    aliases = validate_aliases(aliases)
    baseline_aliases = validate_aliases(baseline_aliases or {})
    candidate_lock = {
        "suite_sha256": suite["suite_sha256"],
        "baseline_config_sha256": digest(baseline_aliases),
        "candidate_config_sha256": digest(aliases),
    }
    lock_path = Path(directory) / ("candidate-" + digest(candidate_lock) + ".json")
    if phase == "development":
        if not lock_path.exists():
            write_json(lock_path, candidate_lock)
    else:
        if not lock_path.exists() or read_json(lock_path) != candidate_lock:
            raise ProbeError("QUALITY_CANDIDATE_MUST_BE_LOCKED_BEFORE_HOLDOUT")
        holdout_path = Path(directory) / "holdout-attempt.json"
        if holdout_path.exists():
            raise ProbeError("QUALITY_HOLDOUT_ALREADY_USED_NEW_INDEPENDENT_SUITE_REQUIRED")
        # 先登记一次独立验收；失败也不可悄悄重试/调参后重用同一验收集。
        write_json(holdout_path, {**candidate_lock, "started_at": now()})
    database = (Path(directory) / "corpus.db").resolve()
    engine = create_engine("sqlite:///" + database.as_uri() + "?mode=ro&uri=true")
    repository = SimpleNamespace(engine=engine)
    base = RetrievalService(repository, alias_groups=baseline_aliases)
    candidate = RetrievalService(repository, alias_groups=aliases)
    documents = {doc["job_id"]: doc for doc in corpus["documents"]}
    cases, guards = [], True
    try:
        for case in suite["cases"]:
            if case["split"] != phase:
                continue
            expected = {item["job_id"] for item in case["relevant"]}
            row = {"case_id": case["id"], "critical": case["critical"]}
            for label, service in (("baseline", base), ("candidate", candidate)):
                result = service.search(case["terms"], limit=suite["contract"]["recall_at_k"])
                hits = {item["job_id"] for item in result["evidence"]}
                valid = result["context_characters"] <= 7000
                for evidence in result["evidence"]:
                    doc = documents.get(evidence["job_id"], {})
                    valid &= (
                        evidence["snapshot_id"] == doc.get("snapshot_id")
                        and evidence["document_id"] == doc.get("document_id")
                        and evidence["document_sha256"] == doc.get("document_sha256")
                        and doc.get("text", "")[evidence["start"] : evidence["end"]]
                        == evidence["quote"]
                    )
                guards &= valid
                row[label] = {
                    "recall": len(hits & expected) / len(expected) if expected else None,
                    "precision": len(hits & expected) / len(hits) if hits else None,
                    "negative_correct": not hits if not expected else None,
                    "retrieved_jobs": sorted(hits),
                    "missing_jobs": sorted(expected - hits),
                    "evidence": result["evidence"],
                    "context_characters": result["context_characters"],
                    "source_and_budget_guard": bool(valid),
                }
            cases.append(row)
    finally:
        engine.dispose()
    regressions = [
        row["case_id"]
        for row in cases
        if row["critical"]
        and (
            (row["baseline"]["recall"] or 0) > (row["candidate"]["recall"] or 0)
            or row["baseline"]["negative_correct"] is True
            and row["candidate"]["negative_correct"] is False
        )
    ]

    def mean(label, metric):
        values = [row[label][metric] for row in cases if row[label][metric] is not None]
        return sum(values) / len(values) if values else None

    baseline_recall, candidate_recall = mean("baseline", "recall"), mean("candidate", "recall")
    precision = mean("candidate", "precision")
    improvement = (
        candidate_recall - baseline_recall
        if candidate_recall is not None and baseline_recall is not None
        else None
    )
    if (
        suite["review_status"] != "reviewed"
        or len(cases) < suite["contract"]["minimum_holdout_cases"]
        or phase != "holdout"
    ):
        status = "insufficient"
    elif (
        not guards
        or regressions
        or improvement is None
        or improvement < suite["contract"]["minimum_recall_improvement"]
        or candidate_recall < suite["contract"]["minimum_candidate_recall"]
        or precision is None
        or precision < suite["contract"]["minimum_candidate_precision"]
    ):
        status = "rejected"
    else:
        status = "accepted_for_human_review"
    report = {
        "version": VERSION,
        "created_at": now(),
        "corpus_sha256": corpus["corpus_sha256"],
        "suite_sha256": suite["suite_sha256"],
        "phase": phase,
        "label_origin": suite["label_origin"],
        "label_review_status": suite["review_status"],
        "baseline_config_sha256": digest(baseline_aliases),
        "candidate_config_sha256": digest(aliases),
        "candidate_aliases": aliases,
        "status": status,
        "baseline_mean_recall": baseline_recall,
        "candidate_mean_recall": candidate_recall,
        "candidate_mean_precision": precision,
        "improvement": improvement,
        "critical_regressions": regressions,
        "source_and_budget_guard": bool(guards),
        "cases": cases,
        "external_calls": 0,
        "retrieval_calls": len(cases) * 2,
        "elapsed_seconds": round(time.monotonic() - started, 4),
        "semantic_quality": "未审核；检索命中和原文锚点存在不能证明语义支持或任务回答。",
        "activation": "未启用任何策略；候选需人工审核及有限实际应用验证。",
    }
    if phase == "holdout":
        # 在调用者导出/渲染前持久保存；导出失败不丢失已消耗的独立验收结果。
        write_json(Path(directory) / "holdout-result.json", report)
    return report


def review_research(directory, case_id, result, judgments, *, reviewer, reviewer_kind="human"):
    """将引用语义和任务完成逐项送审；不让结构绿勾充当业务评分。"""
    corpus, suite = load_suite(directory)
    case = next((item for item in suite["cases"] if item["id"] == case_id), None)
    if case is None:
        raise ProbeError("QUALITY_CASE_NOT_FOUND")
    if reviewer_kind not in {"human", "agent_assisted"} or not reviewer.strip():
        raise ProbeError("QUALITY_REVIEWER_REQUIRED")
    if not isinstance(judgments, dict) or set(judgments) != set(DIMENSIONS):
        raise ProbeError("QUALITY_ALL_DIMENSIONS_REQUIRED")
    for dimension, judgment in judgments.items():
        if (
            not isinstance(judgment, dict)
            or set(judgment) != {"rating", "reason", "claim_indexes"}
            or judgment["rating"] not in {"pass", "fail", "unknown", "not_applicable"}
            or not isinstance(judgment["reason"], str)
            or not judgment["reason"].strip()
            or not isinstance(judgment["claim_indexes"], list)
            or any(
                type(index) is not int or not 0 <= index < len(result.get("claims", []))
                for index in judgment["claim_indexes"]
            )
        ):
            raise ProbeError("QUALITY_INVALID_JUDGMENT")
        if dimension == "citation_semantics" and result.get("claims"):
            if set(judgment["claim_indexes"]) != set(range(len(result["claims"]))):
                raise ProbeError("QUALITY_ALL_CLAIMS_REQUIRE_SEMANTIC_REVIEW")
    source_docs = {doc["snapshot_id"]: doc for doc in corpus["documents"]}
    evidence = {item["id"]: item for item in result.get("evidence", [])}
    claims = result.get("claims", [])

    def valid_evidence(key):
        item = evidence.get(key, {})
        doc = source_docs.get(item.get("snapshot_id"), {})
        start, end = item.get("start"), item.get("end")
        return (
            bool(doc)
            and type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(doc["text"])
            and item.get("job_id") == doc["job_id"]
            and item.get("document_id") == doc["document_id"]
            and item.get("document_sha256") == doc["document_sha256"]
            and item.get("quote") == doc["text"][start:end]
        )

    source_guard = all(
        claim.get("evidence_ids") and all(valid_evidence(key) for key in claim["evidence_ids"])
        for claim in claims
    )
    passed = (
        reviewer_kind == "human"
        and source_guard
        and bool(claims)
        and result.get("status") == "completed"
        and all(value["rating"] in {"pass", "not_applicable"} for value in judgments.values())
    )
    return {
        "version": VERSION,
        "created_at": now(),
        "suite_sha256": suite["suite_sha256"],
        "case_id": case_id,
        "result_sha256": digest(result),
        "reviewer": reviewer,
        "reviewer_kind": reviewer_kind,
        "judgments": judgments,
        "source_scope_guard": source_guard,
        "status": "reviewed_pass" if passed else "needs_attention",
        "usage": {
            "model_calls": result.get("model_calls"),
            "elapsed_seconds": result.get("elapsed_seconds"),
            "provider_usage": result.get("usage", []),
            "cost": None,
        },
        "note": "这是明确审核者提交的判断，程序不独立证明语义；未知费用保持未知。",
    }
