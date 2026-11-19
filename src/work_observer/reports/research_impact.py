"""Locate research linked to an observed change; do not infer semantic invalidity."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.knowledge.models import DomainDefinition, WorkRelation
from work_observer.research.projects import ProjectService
from work_observer.storage.models import MemoryRecord


def research_impact(repository, store, before, after, report):
    changed_jobs = {item["job_id"]: "source_content_changed" for item in report["content_changes"]}
    for item in report["metadata_changes"]:
        changed_jobs.setdefault(item["job_id"], "disclosed_fields_changed")
    old_sources = {
        row["job_id"]: row["source"]["snapshot_id"]
        for row in before["jobs"]
        if row.get("source") and row["job_id"] in changed_jobs
    }
    knowledge = set()
    for field, kind in (("definitions", "domain_definition"), ("relations", "work_relation")):
        later = {row["id"]: row for row in after[field]}
        for row in before[field]:
            if row.get("status") == "active" and row != later.get(row["id"]):
                knowledge.add((kind, row["id"]))
    with store.lock:
        rows = store.db.execute(
            "SELECT record FROM research_checkpoints WHERE namespace=?",
            (store.namespace,),
        ).fetchall()
    runs = [json.loads(row[0]) for row in rows]
    runs = [
        row
        for row in runs
        if row.get("state") != "invalidated"
        and (row.get("result") or {}).get("status") == "completed"
        and row.get("created_at", "") <= after["created_at"]
    ]
    direct, affected, reasons = {}, set(), {}
    for run in runs:
        result = run["result"]
        evidence = {
            item["id"]: changed_jobs[item["job_id"]]
            for item in result.get("evidence", [])
            if item.get("job_id") in old_sources
            and item.get("snapshot_id") == old_sources[item["job_id"]]
        }
        claims = [
            {
                "index": i,
                "text": claim["text"],
                "evidence_ids": list(refs),
                "reasons": sorted({evidence[key] for key in refs}),
            }
            for i, claim in enumerate(result.get("claims", []))
            if (refs := [key for key in claim.get("evidence_ids", []) if key in evidence])
        ]
        if claims:
            direct[run["id"]] = claims
            affected.add(run["id"])
            reasons[run["id"]] = {reason for row in claims for reason in row["reasons"]}
    with Session(repository.engine) as session:
        domains = list(session.scalars(select(DomainDefinition)))
        relations = list(session.scalars(select(WorkRelation)))
        memories = list(session.scalars(select(MemoryRecord)))

        def changed_evidence(items):
            return any(
                item.get("job_id") in old_sources
                and item.get("snapshot_id") == old_sources[item["job_id"]]
                for item in items
            )

        knowledge.update(
            ("work_relation", row.id)
            for row in relations
            if changed_evidence([*row.evidence, *row.counterevidence])
        )
        direct_memories = {row.id for row in memories if changed_evidence(row.evidence)}
        # Reuse explicit stored lineage; a link requests review rather than declaring a claim false.
        while True:
            previous = (len(affected), len(knowledge))
            for row in domains:
                if (row.source_context or {}).get("run_id") in affected:
                    knowledge.add(("domain_definition", row.id))
                if ("domain_definition", row.previous_id) in knowledge or any(
                    ("domain_definition", key) in knowledge for key in row.related_ids
                ):
                    knowledge.add(("domain_definition", row.id))
            for row in relations:
                if (
                    row.source_run_id in affected
                    or ("domain_definition", row.domain_id) in knowledge
                ):
                    knowledge.add(("work_relation", row.id))
            memory_ids = direct_memories | {
                row.id for row in memories if row.source_run_id in affected
            }
            for run in runs:
                result = run["result"]
                found = reasons.setdefault(run["id"], set())
                if any(
                    (ref.get("kind"), ref.get("id")) in knowledge
                    for ref in result.get("knowledge_used", [])
                ):
                    found.add("linked_knowledge_changed")
                if any(
                    ref.get("id") in memory_ids
                    for ref in [
                        *result.get("memory_used", []),
                        *result.get("context_memory_used", []),
                    ]
                ):
                    found.add("linked_memory_source_changed")
                if set(result.get("continued_from", [])) & affected:
                    found.add("linked_research_changed")
                if found:
                    affected.add(run["id"])
            if previous == (len(affected), len(knowledge)):
                break
    projects = {
        row["id"]: row
        for row in ProjectService(store).list(all_records=True)
        if row.get("state") == "active"
    }
    output = []
    for run in runs:
        if run["id"] not in affected:
            continue
        project = projects.get(run["result"].get("project_id"))
        step = (
            next((s for s in project["steps"] if s.get("run_id") == run["id"]), None)
            if project
            else None
        )
        output.append(
            {
                "run_id": run["id"],
                "question": run["result"].get("question", ""),
                "created_at": run["created_at"],
                "claims": direct.get(run["id"], []),
                "reasons": sorted(reasons[run["id"]]),
                "project_id": project["id"] if step else None,
                "step_id": step["id"] if step else None,
                "can_followup": bool(step and step["state"] in {"completed", "waiting_review"}),
            }
        )
    output.sort(key=lambda row: (row["created_at"], row["run_id"]), reverse=True)
    return {
        "runs": output[:50],
        "total_runs": len(output),
        "truncated": len(output) > 50,
        "direct_claim_count": sum(len(row["claims"]) for row in output),
        "notice": (
            "按本次面板差异与已保存引用/依赖关联，列出待复核认识；关联不表示旧判断错误，"
            "也不表示行业趋势。仅展示当前仍可读取的研究，不改写历史回答。"
        ),
    }
