"""Read-only notices about later research; never change a memory's adoption status."""

import json
import sqlite3

from work_observer.memory.dependencies import DependencyAudit


def revision_notices(
    repository, memory, *, at=None, project_id=None, scoped=False, excluded_runs=()
):
    if memory["kind"] not in {"knowledge", "hypothesis", "method"} or not memory.get(
        "source_run_id"
    ):
        return []
    auditor = DependencyAudit(repository, at=at, excluded_runs=excluded_runs)
    original = auditor._read("research_checkpoints", memory["source_run_id"])
    claims = ((original or {}).get("result") or {}).get("claims", [])
    indices = {i for i, claim in enumerate(claims) if claim.get("text") == memory["content"]}
    if not indices or not auditor.path.is_file():
        return []
    notices = []
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
                "AND json_extract(r.value,'$.previous_statement')=? "
                "AND json_extract(c.record,'$.updated_at')<=? "
                "ORDER BY json_extract(c.record,'$.updated_at') DESC,c.id DESC LIMIT 96",
                (auditor.namespace, memory["source_run_id"], memory["content"], auditor.at),
            )
            for identity, encoded, revision_json in candidates:
                record, revision = json.loads(encoded), json.loads(revision_json)
                result = record.get("result") or {}
                revision_project = result.get("project_id") or record.get("input", {}).get(
                    "project_id"
                )
                if (
                    revision.get("decision") not in {"revise", "withdraw", "unresolved"}
                    or revision.get("previous_claim_index") not in indices
                    or scoped
                    and revision_project
                    and revision_project != project_id
                    or not auditor.run(identity)["eligible"]
                ):
                    continue
                notices.append(
                    {
                        "run_id": identity,
                        "project_id": revision_project,
                        "decision": revision["decision"],
                        "reason": revision["reason"],
                        "new_statements": revision.get("new_statements", []),
                        "evidence_ids": revision.get("evidence_ids", []),
                        "recorded_at": record["updated_at"],
                        "notice": "后续研究提出了不同判断，待核对；未自动改写已保存知识。"
                        "使用前需打开后续研究并重读原文，不能把新旧判断直接当作事实。",
                    }
                )
                if len(notices) == 3:
                    break
    except (sqlite3.Error, OSError, ValueError):
        return []
    return notices
