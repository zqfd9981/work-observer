"""个人记忆及研究项目共用的可重试遗忘闭包，不删除原始来源。"""

import hashlib
import json
import re
from pathlib import Path

from work_observer.memory.service import MemoryService
from work_observer.reports.inbox import InboxService
from work_observer.reports.results import forget_reports, read_result
from work_observer.storage.locks import exclusive


def forget_personal(repository, store, identity, reports_dir=Path("reports")):
    with exclusive(repository.engine.url.database):
        return _forget(repository, store, identity, Path(reports_dir))


def _forget(repository, store, identity, reports_dir):
    from sqlalchemy.orm import Session

    from work_observer.connectors.mcp_probe import ProbeError

    memory = MemoryService(repository)
    with Session(repository.engine) as session:
        requested = memory._get(session, identity)
        if requested.kind not in {"preference", "correction"}:
            raise ProbeError("MEMORY_FORGET_PERSONAL_ONLY")
    _bind_reports_directory(store, "memory:" + identity, reports_dir)
    forgotten = memory.forget(identity)
    return {
        **forgotten,
        **_cascade(
            repository,
            store,
            reports_dir,
            operation_id="memory:" + identity,
            memory_ids=forgotten["forgotten_memory_ids"],
            profile_ids=forgotten.get("deleted_profile_ids", []),
        ),
    }


def forget_project(repository, store, identity, reports_dir=Path("reports"), *, _resume=False):
    """忘记目标、对话、调查和项目记忆，并清除跨项目的受影响派生链。"""
    from work_observer.research.projects import ProjectService

    with exclusive(repository.engine.url.database):
        projects = ProjectService(store)
        existing = projects.get(identity)
        if not _resume and any(step["state"] == "running" for step in existing.get("steps", [])):
            from work_observer.connectors.mcp_probe import ProbeError

            raise ProbeError("PROJECT_RUNNING")
        if _resume:
            projects.recover()
        _bind_reports_directory(store, "project:" + identity, reports_dir)
        _journal(store, "project:" + identity, project_ids=[identity])
        erased = projects.erase(identity)
        forgotten = MemoryService(repository).forget_project(identity)
        return {
            **erased,
            **forgotten,
            **_cascade(
                repository,
                store,
                Path(reports_dir),
                operation_id="project:" + identity,
                memory_ids=forgotten["forgotten_memory_ids"],
                run_ids=erased["affected_run_ids"],
                project_ids=[identity],
                profile_ids=forgotten.get("deleted_profile_ids", []),
            ),
        }


def _journal(store, operation_id, **updates):
    """只存已发现的依赖ID，先记后擦除，进程中断后重试仍可追完下游。"""
    with store.lock, store.db:
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS privacy_erasures (namespace TEXT NOT NULL, "
            "id TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(namespace,id))"
        )
        row = store.db.execute(
            "SELECT record FROM privacy_erasures WHERE namespace=? AND id=?",
            (store.namespace, operation_id),
        ).fetchone()
        record = json.loads(row[0]) if row else {}
        record.setdefault("id", operation_id)
        record.setdefault("completed", False)
        for key, values in updates.items():
            record[key] = sorted(set(record.get(key, [])) | set(values))
        store.db.execute(
            "INSERT INTO privacy_erasures(namespace,id,record) VALUES(?,?,?) "
            "ON CONFLICT(namespace,id) DO UPDATE SET record=excluded.record",
            (store.namespace, operation_id, json.dumps(record)),
        )
        return record


def _complete(store, operation_id):
    with store.lock, store.db:
        row = store.db.execute(
            "SELECT record FROM privacy_erasures WHERE namespace=? AND id=?",
            (store.namespace, operation_id),
        ).fetchone()
        record = json.loads(row[0])
        record["completed"] = True
        store.db.execute(
            "UPDATE privacy_erasures SET record=? WHERE namespace=? AND id=?",
            (json.dumps(record), store.namespace, operation_id),
        )


def _bind_reports_directory(store, operation_id, reports_dir):
    """目录只留绝对路径指纹；不能把错误目录的missing误判为已完成清除。"""
    from work_observer.connectors.mcp_probe import ProbeError

    signature = hashlib.sha256(str(Path(reports_dir).resolve()).encode("utf-8")).hexdigest()
    with store.lock, store.db:
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS privacy_erasures (namespace TEXT NOT NULL, "
            "id TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(namespace,id))"
        )
        row = store.db.execute(
            "SELECT record FROM privacy_erasures WHERE namespace=? AND id=?",
            (store.namespace, operation_id),
        ).fetchone()
        record = json.loads(row[0]) if row else {"id": operation_id, "completed": False}
        expected = record.get("reports_directory_sha256")
        if expected and expected != signature:
            raise ProbeError("PRIVACY_REPORT_DIRECTORY_MISMATCH")
        record["reports_directory_sha256"] = signature
        store.db.execute(
            "INSERT INTO privacy_erasures(namespace,id,record) VALUES(?,?,?) "
            "ON CONFLICT(namespace,id) DO UPDATE SET record=excluded.record",
            (store.namespace, operation_id, json.dumps(record)),
        )


def pending_erasures(store):
    """只读当前业务命名空间；返回未完成数量，不暴露个人上下文。"""
    with store.lock:
        exists = store.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='privacy_erasures'"
        ).fetchone()
        if not exists:
            return 0
        rows = store.db.execute(
            "SELECT record FROM privacy_erasures WHERE namespace=?", (store.namespace,)
        ).fetchall()
    return sum(json.loads(encoded).get("completed") is not True for (encoded,) in rows)


def resume_erasures(repository, store, reports_dir=Path("reports")):
    """只继续当前命名空间的未完成本地擦除；不调用模型或网络。"""
    with store.lock, store.db:
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS privacy_erasures (namespace TEXT NOT NULL, "
            "id TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(namespace,id))"
        )
        rows = store.db.execute(
            "SELECT id,record FROM privacy_erasures WHERE namespace=?", (store.namespace,)
        ).fetchall()
    resumed = []
    for operation_id, encoded in rows:
        if json.loads(encoded).get("completed") is True:
            continue
        kind, _, identity = operation_id.partition(":")
        if kind == "project":
            forget_project(repository, store, identity, reports_dir, _resume=True)
        elif kind == "memory":
            forget_personal(repository, store, identity, reports_dir)
        else:
            from work_observer.connectors.mcp_probe import ProbeError

            raise ProbeError("INVALID_ERASURE_OPERATION")
        resumed.append(operation_id)
    return {"resumed_erasure_ids": resumed}


def _runs_using_memories(store, identities):
    """在擦除检查点之前收集依赖；不能在删除唯一回链后再寻找派生结果。"""
    identities = set(identities)
    if not identities:
        return set()
    with store.lock:
        rows = store.db.execute(
            "SELECT id,record,checkpoint FROM research_checkpoints WHERE namespace=?",
            (store.namespace,),
        ).fetchall()
    affected = set()
    for identity, encoded, encoded_checkpoint in rows:
        record = json.loads(encoded)
        checkpoint = json.loads(encoded_checkpoint) if encoded_checkpoint else {}
        for result in (record.get("result") or {}, checkpoint.get("result") or {}):
            used = [
                *result.get("memory_used", result.get("memories", [])),
                *result.get("context_memory_used", []),
            ]
            if any(isinstance(item, dict) and item.get("id") in identities for item in used):
                affected.add(identity)
                break
    return affected


def _cascade(
    repository,
    store,
    reports_dir,
    *,
    operation_id,
    memory_ids=(),
    run_ids=(),
    project_ids=(),
    profile_ids=(),
):
    from work_observer.knowledge.service import DomainKnowledgeService
    from work_observer.quality.reviews import QualityReviewService
    from work_observer.research.projects import ProjectService
    from work_observer.workflow.service import WorkflowService

    memory = MemoryService(repository)
    _bind_reports_directory(store, operation_id, reports_dir)
    projects = ProjectService(store)
    workflows = WorkflowService(store, repository)
    journal = _journal(
        store,
        operation_id,
        memory_ids=memory_ids,
        run_ids=run_ids,
        project_ids=project_ids,
        profile_ids=profile_ids,
    )
    identities, affected_runs = set(), set()
    affected_projects = set(journal.get("project_ids", []))
    deleted_profiles = set(journal.get("profile_ids", []))
    report_ids = set(journal.get("report_ids", []))
    relation_ids = set(journal.get("relation_ids", []))
    pending_memories = set(journal.get("memory_ids", []))
    pending_runs = set(journal.get("run_ids", []))
    related = workflows.related_runs(pending_runs, pending_memories, affected_projects)
    pending_runs.update(related["affected_run_ids"])
    affected_projects.update(related["affected_project_ids"])
    _journal(
        store,
        operation_id,
        memory_ids=pending_memories,
        run_ids=pending_runs,
        project_ids=affected_projects,
    )
    # 尚未执行任何模型的关联项目同样可能已有私人目标；不能依赖存在run才擦除。
    for project_id in affected_projects:
        project = projects.get(project_id)
        if any(step["state"] == "running" for step in project.get("steps", [])):
            pending_runs.update(step["run_id"] for step in project["steps"] if step.get("run_id"))
        else:
            pending_runs.update(projects.erase(project_id)["affected_run_ids"])
        forgotten = memory.forget_project(project_id)
        pending_memories.update(forgotten["forgotten_memory_ids"])
        deleted_profiles.update(forgotten.get("deleted_profile_ids", []))
    while pending_memories or pending_runs:
        identities.update(pending_memories)
        pending_runs.update(_runs_using_memories(store, pending_memories))
        pending_memories = set()
        # 执行依赖和项目整轮范围相互扩展；先求闭包，再擦除唯一回链。
        closure = pending_runs - affected_runs
        while closure:
            old = set(closure)
            related = workflows.related_runs(closure | affected_runs, identities, affected_projects)
            closure.update(related["affected_run_ids"])
            affected_projects.update(related["affected_project_ids"])
            closure.update(store.dependent_runs(sorted(closure | affected_runs)))
            for project in projects.list(all_records=True):
                if set(s.get("run_id") for s in project.get("steps", [])) & closure:
                    affected_projects.add(project["id"])
                    closure.update(s["run_id"] for s in project.get("steps", []) if s.get("run_id"))
            _journal(
                store,
                operation_id,
                memory_ids=identities,
                run_ids=closure | affected_runs,
                project_ids=affected_projects,
                report_ids=report_ids,
                profile_ids=deleted_profiles,
                relation_ids=relation_ids,
            )
            closure.update(projects.invalidate(sorted(closure)))
            if closure == old:
                break
        closure -= affected_runs
        for project_id in affected_projects:
            erased = projects.erase(project_id)
            pending_runs.update(set(erased["affected_run_ids"]) - affected_runs - closure)
            forgotten = memory.forget_project(project_id)
            pending_memories.update(set(forgotten["forgotten_memory_ids"]) - identities)
            deleted_profiles.update(forgotten.get("deleted_profile_ids", []))
        if closure:
            # 报告关联也必须在清除运行记录之前持久保存。
            for run_id in closure:
                record = store.get(run_id)
                for source in (record.get("saved") or {}, record.get("result") or {}):
                    report_id = source.get("report_id")
                    if isinstance(report_id, str) and re.fullmatch(r"[a-f0-9]{32}", report_id):
                        report_ids.add(report_id)
            _journal(
                store,
                operation_id,
                memory_ids=identities | pending_memories,
                run_ids=closure | affected_runs,
                project_ids=affected_projects,
                report_ids=report_ids,
                profile_ids=deleted_profiles,
                relation_ids=relation_ids,
            )
            invalidated = store.invalidate_runs(sorted(closure))
            report_ids.update(invalidated["report_ids"])
            affected_runs.update(closure)
            derived = memory.invalidate_research(sorted(closure))
            pending_memories.update(set(derived["affected_memory_ids"]) - identities)
            deleted_profiles.update(derived.get("deleted_profile_ids", []))
            relations = DomainKnowledgeService(repository).invalidate_research(sorted(closure))
            relation_ids.update(relations.get("invalidated_relation_ids", []))
        pending_runs -= affected_runs
        _journal(
            store,
            operation_id,
            memory_ids=identities | pending_memories,
            run_ids=affected_runs,
            project_ids=affected_projects,
            report_ids=report_ids,
            profile_ids=deleted_profiles,
            relation_ids=relation_ids,
        )
    notifications = InboxService(repository).invalidate_research(sorted(affected_runs))
    quality = QualityReviewService(store).invalidate(sorted(affected_runs))
    from work_observer.quality.profile_reviews import ProfileQualityReviewService
    from work_observer.quality.research_benchmark import ResearchBenchmarkService

    profile_quality = ProfileQualityReviewService(store, repository).invalidate(
        run_ids=sorted(affected_runs),
        profile_ids=sorted(deleted_profiles),
        memory_ids=sorted(identities),
    )
    notifications["affected_notification_ids"] = sorted(
        set(
            notifications.get("affected_notification_ids", [])
            + profile_quality.pop("affected_notification_ids", [])
        )
    )
    benchmark_quality = ResearchBenchmarkService(store, repository).invalidate(
        run_ids=sorted(affected_runs),
        project_ids=sorted(affected_projects),
        memory_ids=sorted(identities),
    )
    from work_observer.quality.releases import LocalRetrievalTrialService

    trials = LocalRetrievalTrialService(store, repository).invalidate_research(
        sorted(affected_runs), sorted(identities)
    )
    from work_observer.reports.domain_updates import DomainUpdateService

    updates = DomainUpdateService(store, repository).invalidate(
        sorted(affected_runs), sorted(identities)
    )
    workflow_results = workflows.invalidate(
        sorted(affected_runs), sorted(identities), sorted(affected_projects)
    )
    if reports_dir.exists():
        for path in reports_dir.glob("*.json"):
            if path.is_symlink() or not re.fullmatch(r"[a-f0-9]{32}", path.stem):
                continue
            result = read_result(path.stem, reports_dir)
            used = [
                *result.get("memory_used", result.get("memories", [])),
                *result.get("context_memory_used", []),
            ]
            if (
                identities & {item.get("id") for item in used if isinstance(item, dict)}
                or result.get("run_id") in affected_runs
                or set(result.get("continued_from", [])) & affected_runs
                or set(result.get("feedback_from", [])) & affected_runs
                or result.get("project_id") in affected_projects
            ):
                report_ids.add(path.stem)
    _journal(
        store,
        operation_id,
        memory_ids=identities,
        run_ids=affected_runs,
        project_ids=affected_projects,
        report_ids=report_ids,
        profile_ids=deleted_profiles,
        relation_ids=relation_ids,
    )
    deleted = forget_reports(sorted(report_ids), reports_dir)
    _complete(store, operation_id)
    return {
        "deleted_profile_ids": sorted(deleted_profiles),
        "affected_memory_ids": sorted(identities),
        "affected_run_ids": sorted(affected_runs),
        "affected_project_ids": sorted(affected_projects),
        "report_ids": sorted(report_ids),
        "invalidated_relation_ids": sorted(relation_ids),
        **notifications,
        **quality,
        **profile_quality,
        **benchmark_quality,
        **trials,
        **updates,
        "invalidated_workflow_ids": workflow_results["affected_workflow_ids"],
        **deleted,
    }
