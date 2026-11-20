"""Read-only notices about later research; never change a memory's adoption status."""

import json
import sqlite3

from sqlalchemy.orm import Session

from work_observer.memory.dependencies import DependencyAudit
from work_observer.storage.models import MemoryRecord


def revision_notices(
    repository,
    memory,
    *,
    at=None,
    project_id=None,
    scoped=False,
    excluded_runs=(),
    job_ids=None,
    public_document_ids=None,
):
    if memory["kind"] not in {"knowledge", "hypothesis", "method"} or not memory.get(
        "source_run_id"
    ):
        return []
    auditor = DependencyAudit(repository, at=at, excluded_runs=excluded_runs)
    original = auditor._read("research_checkpoints", memory["source_run_id"])
    claims = ((original or {}).get("result") or {}).get("claims", [])
    indices = {i for i, claim in enumerate(claims) if claim.get("text") == memory["content"]}
    matched = None
    if not indices and memory.get("previous_id"):
        current, visited = memory, {memory["id"]}
        with Session(repository.engine) as session:
            while current.get("previous_id") and current["previous_id"] not in visited:
                previous = session.get(MemoryRecord, current["previous_id"])
                if (
                    previous is None
                    or previous.root_id != memory["root_id"]
                    or previous.kind != memory["kind"]
                    or previous.source_run_id != memory["source_run_id"]
                    or previous.version >= current["version"]
                    or previous.status == "forgotten"
                    or previous.created_at > auditor.at
                ):
                    break
                visited.add(previous.id)
                indices = {
                    i for i, claim in enumerate(claims) if claim.get("text") == previous.content
                }
                if indices:
                    matched = {"id": previous.id, "version": previous.version}
                    break
                current = {
                    "previous_id": previous.previous_id,
                    "version": previous.version,
                }
    notices = claim_revision_notices(
        repository,
        memory["source_run_id"],
        indices,
        at=at,
        project_id=project_id,
        scoped=scoped,
        excluded_runs=excluded_runs,
        job_ids=job_ids,
        public_document_ids=public_document_ids,
    )
    if matched:
        for notice in notices:
            notice["memory_match"] = matched
            notice["memory_match_note"] = (
                f"此提示涉及第{matched['version']}版记忆采用的原判断。当前表述已经改写，"
                "是否仍受影响须对照当前内容和原文核对；不自动认定已解决或仍有错误。"
            )
    return notices


def claim_revision_notices(
    repository,
    source_run_id,
    claim_indices,
    *,
    at=None,
    project_id=None,
    scoped=False,
    excluded_runs=(),
    job_ids=None,
    public_document_ids=None,
):
    """Map items share the same claim-bound, provisional notices as saved statements."""
    auditor = DependencyAudit(repository, at=at, excluded_runs=excluded_runs)
    original = auditor._read("research_checkpoints", source_run_id)
    claims = ((original or {}).get("result") or {}).get("claims", [])
    indices = {i for i in claim_indices if type(i) is int and 0 <= i < len(claims)}
    if not indices or not auditor.path.is_file():
        return []
    notices, latest, challenged = [], {}, set()
    try:
        with sqlite3.connect(
            auditor.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2
        ) as db:
            # Filter by the exact source before bounding candidates: unrelated new runs
            # cannot hide an older revision of this saved statement.
            candidates = db.execute(
                "SELECT c.id,c.record,r.value FROM research_checkpoints c, "
                "json_each(c.record,'$.result.cognition_revisions') r "
                "WHERE c.namespace=? AND json_extract(r.value,'$.previous_run_id')=? "
                "AND ("
                + " OR ".join(
                    "(json_extract(r.value,'$.previous_claim_index')=? "
                    "AND json_extract(r.value,'$.previous_statement')=?)"
                    for _ in indices
                )
                + ") "
                "AND json_extract(c.record,'$.updated_at')<=? "
                "ORDER BY json_extract(c.record,'$.updated_at') DESC,c.id DESC LIMIT 96",
                (
                    auditor.namespace,
                    source_run_id,
                    *(value for i in sorted(indices) for value in (i, claims[i]["text"])),
                    auditor.at,
                ),
            )
            for identity, encoded, revision_json in candidates:
                record, revision = json.loads(encoded), json.loads(revision_json)
                result = record.get("result") or {}
                revision_project = result.get("project_id") or record.get("input", {}).get(
                    "project_id"
                )
                if (
                    revision.get("decision") not in {"retain", "revise", "withdraw", "unresolved"}
                    or revision.get("previous_claim_index") not in indices
                    or revision.get("previous_statement")
                    != claims[revision["previous_claim_index"]]["text"]
                    or scoped
                    and revision_project
                    and revision_project != project_id
                    or not auditor.run(identity)["eligible"]
                ):
                    continue
                reference_ids = set(revision.get("evidence_ids", []))
                for index in revision.get("new_claim_indices", []):
                    if type(index) is int and 0 <= index < len(result.get("claims", [])):
                        reference_ids.update(result["claims"][index].get("evidence_ids", []))
                sources = [ev for ev in result.get("evidence", []) if ev["id"] in reference_ids]
                scope_limited = (
                    job_ids is not None
                    and any(ev.get("job_id") and ev["job_id"] not in job_ids for ev in sources)
                    or public_document_ids is not None
                    and any(
                        ev.get("public_document_id")
                        and ev["public_document_id"] not in public_document_ids
                        for ev in sources
                    )
                )
                notice = {
                    "run_id": identity,
                    "project_id": revision_project,
                    "decision": revision["decision"],
                    "previous_claim_index": revision["previous_claim_index"],
                    "previous_statement": claims[revision["previous_claim_index"]]["text"],
                    "reason": (
                        "相关后续研究使用了本轮未选的资料；具体修正内容和依据未带入，"
                        "使用旧认识前需补充适用资料并核对。"
                        if scope_limited
                        else revision["reason"]
                    ),
                    "new_statements": [] if scope_limited else revision.get("new_statements", []),
                    "aspects": [] if scope_limited else revision.get("aspects", []),
                    "comparison_notice": (
                        "具体修正及逐项对照未带入当前范围；这不表示原知识已获重新确认。"
                        if scope_limited
                        else revision.get("comparison_notice")
                    ),
                    "evidence_ids": [] if scope_limited else revision.get("evidence_ids", []),
                    **({"scope_limited": True} if scope_limited else {}),
                    "recorded_at": record["updated_at"],
                    "notice": "后续研究提出了不同判断，待核对；未自动改写已保存知识。"
                    "使用前需打开后续研究并重读原文，不能把新旧判断直接当作事实。",
                }
                index = revision["previous_claim_index"]
                latest.setdefault(index, notice)
                if revision["decision"] != "retain":
                    challenged.add(index)
                    notices.append(notice)
                if len(notices) >= 3 and not any(
                    row["decision"] == "retain" and key not in challenged
                    for key, row in latest.items()
                ):
                    break
            for index in challenged:
                if latest[index]["decision"] == "retain":
                    latest[index]["notice"] = (
                        "此判断曾有修订、撤回或疑问，后续研究又提出保留；"
                        "两次意见及原文均须核对，不以记录时间决定真假，未自动修改知识采纳状态。"
                    )
                    notices.append(latest[index])
    except (sqlite3.Error, OSError, ValueError):
        return []
    return sorted(notices, key=lambda row: (row["recorded_at"], row["run_id"]), reverse=True)[:3]
