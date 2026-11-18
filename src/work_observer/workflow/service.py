"""资料→必要画像→持久调查→观察面板/差异/收件箱；源事实始终归原业务库。"""

import asyncio
import hashlib
import json
import re
import time
from uuid import uuid4

from sqlalchemy.orm import Session

from work_observer.analysis.profiles import ProfileService
from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.memory.lifecycle import pending_erasures
from work_observer.memory.service import MemoryService
from work_observer.reports.domain_updates import DomainUpdateService
from work_observer.reports.inbox import InboxService
from work_observer.research.projects import ProjectService, completed_steps, execute_project
from work_observer.retrieval.catalog import Catalog
from work_observer.retrieval.enhanced import validated_terms
from work_observer.storage.locks import exclusive
from work_observer.storage.models import MemoryRecord

PROFILE_BUDGET = {"calls": 9, "seconds": 235}
PROJECT_BUDGET = {"calls": 24, "seconds": 360}


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def reserve_project_upgrade(store, project):
    """ProjectService.claim事务内调用：索引验证后补记离线项目的完整模型预留。"""
    exists = store.db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_workflows'"
    ).fetchone()
    key = project.get("source_key") or ""
    match = re.fullmatch(r"workflow:([a-f0-9]{32})", key)
    if not exists:
        if match:
            raise ProbeError("WORKFLOW_PROJECT_UNBOUND")
        return
    bound = []
    for identity, encoded in store.db.execute(
        "SELECT id,record FROM research_workflows WHERE namespace=?", (store.namespace,)
    ):
        record = json.loads(encoded)
        if project["id"] in record.get("invalidation_dependencies", {}).get("project_ids", []):
            raise ProbeError("WORKFLOW_FORGOTTEN_RESTART")
        for cycle in record.get("cycles", []):
            direct = cycle.get("project_id") == project["id"]
            orphan = match and cycle["id"] == match[1] and not cycle.get("project_id")
            if direct or orphan:
                bound.append((identity, record, cycle))
    if not bound:
        if match:
            raise ProbeError("WORKFLOW_PROJECT_UNBOUND")
        return
    if len(bound) != 1:
        raise ProbeError("WORKFLOW_PROJECT_AMBIGUOUS")
    identity, record, cycle = bound[0]
    if record["state"] == "invalidated":
        raise ProbeError("WORKFLOW_FORGOTTEN_RESTART")
    allowed_jobs = cycle.get("job_ids", record["job_ids"])
    if (
        project["goal"] != record["goal"]
        or set(project["job_ids"]) != set(allowed_jobs)
        or project["budget"]["max_calls"] != 24
        or project["budget"]["max_seconds"] != 360
        or project["budget"]["max_public"] != 0
    ):
        raise ProbeError("WORKFLOW_PROJECT_SCOPE_CHANGED")
    old = cycle["project_reservation"]
    if all(old[key] >= PROJECT_BUDGET[key] for key in PROJECT_BUDGET):
        return
    reserved = {
        key: sum(
            item["project_reservation"][key]
            + sum(attempt["reservation"][key] for attempt in item["profile_attempts"])
            for item in record["cycles"]
        )
        for key in PROJECT_BUDGET
    }
    if any(
        reserved[key] - old[key] + PROJECT_BUDGET[key] > record["budget"]["max_" + key]
        for key in PROJECT_BUDGET
    ):
        raise ProbeError("WORKFLOW_LIFETIME_BUDGET_EXHAUSTED")
    cycle["project_reservation"] = dict(PROJECT_BUDGET)
    cycle["project_model_upgrade"] = True
    cycle["project_id"] = project["id"]
    record["project_ids"] = list(dict.fromkeys([*record["project_ids"], project["id"]]))
    revision = record["revision"]
    record.update(
        revision=revision + 1, updated_at=now(), stop_reason="project_model_budget_reserved"
    )
    changed = store.db.execute(
        "UPDATE research_workflows SET revision=?,record=? "
        "WHERE namespace=? AND id=? AND revision=?",
        (
            record["revision"],
            json.dumps(record, ensure_ascii=False),
            store.namespace,
            identity,
            revision,
        ),
    )
    if changed.rowcount != 1:
        raise ProbeError("WORKFLOW_CHANGED_REFRESH")


class WorkflowService:
    def __init__(self, store, repository):
        self.store, self.repository = store, repository
        repository.bind_research_store(store)
        with store.lock, store.db:
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS research_workflows(namespace TEXT NOT NULL, "
                "id TEXT NOT NULL, revision INTEGER NOT NULL, record TEXT NOT NULL, "
                "PRIMARY KEY(namespace,id))"
            )

    def _get(self, identity):
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT record FROM research_workflows WHERE namespace=? AND id=?",
                (self.store.namespace, identity),
            ).fetchone()
        if not row:
            raise ProbeError("WORKFLOW_NOT_FOUND")
        return json.loads(row[0])

    def _save(self, record):
        with self.store.lock, self.store.db:
            revision = record["revision"]
            record.update(revision=revision + 1, updated_at=now())
            changed = self.store.db.execute(
                "UPDATE research_workflows SET revision=?,record=? WHERE namespace=? AND id=? "
                "AND revision=? AND json_extract(record,'$.state') != 'invalidated'",
                (
                    record["revision"],
                    json.dumps(record, ensure_ascii=False),
                    self.store.namespace,
                    record["id"],
                    revision,
                ),
            )
            if changed.rowcount != 1:
                raise ProbeError("WORKFLOW_CHANGED_REFRESH")
        return record

    def list(self):
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT record FROM research_workflows WHERE namespace=? "
                "AND json_extract(record,'$.state') != 'invalidated' "
                "ORDER BY json_extract(record,'$.updated_at') DESC LIMIT 100",
                (self.store.namespace,),
            ).fetchall()
        return [
            {key: item.get(key) for key in ("id", "title", "state", "updated_at", "stop_reason")}
            for (encoded,) in rows
            if (item := json.loads(encoded))
        ]

    def recover(self, identity=None, *, _lock_held=False):
        """仅标记遗留执行，不调用模型；调用方已持研究锁时必须显式声明。"""
        if not _lock_held:
            with exclusive(self.repository.engine.url.database):
                return self.recover(identity, _lock_held=True)
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT record FROM research_workflows WHERE namespace=? "
                + ("AND id=?" if identity else "AND json_extract(record,'$.state')='running'"),
                (self.store.namespace, identity) if identity else (self.store.namespace,),
            ).fetchall()
        recovered = []
        for (encoded,) in rows:
            record = json.loads(encoded)
            if record["state"] == "invalidated":
                continue
            changed = record["state"] == "running"
            for cycle in record["cycles"]:
                for attempt in cycle["profile_attempts"]:
                    if attempt["state"] == "running":
                        attempt["state"] = "interrupted"
                        cycle["profile_tasks"][attempt["job_id"]] = {"state": "interrupted"}
                        changed = True
                if cycle.get("project_id"):
                    projects = ProjectService(self.store)
                    project = projects.get(cycle["project_id"])
                    if project["state"] != "invalidated":
                        for step in project["steps"]:
                            if step["state"] == "running":
                                run = self.store.get(step["run_id"])
                                if run["state"] == "invalidated":
                                    continue
                                if run["state"] == "running":
                                    self.store.save(run["id"], state="interrupted")
                                projects.finish(
                                    project["id"],
                                    step["id"],
                                    state="interrupted",
                                    reason="workflow_explicit_recovery",
                                )
                                changed = True
            if changed:
                record.update(state="interrupted", stop_reason="explicit_or_process_interrupted")
                self._save(record)
                recovered.append(record["id"])
        return {"recovered_workflow_ids": recovered}

    def create(
        self,
        title,
        goal,
        job_ids,
        *,
        domain_id=None,
        terms=None,
        include_personal=False,
        max_calls=72,
        max_seconds=1800,
    ):
        if (
            not isinstance(title, str)
            or not 1 <= len(title.strip()) <= 150
            or not isinstance(goal, str)
            or not 1 <= len(goal.strip()) <= 4000
            or not isinstance(job_ids, list)
            or not 1 <= len(job_ids) <= 20
            or any(not isinstance(item, str) for item in job_ids)
            or type(max_calls) is not int
            or not 24 <= max_calls <= 72
            or type(max_seconds) is not int
            or not 360 <= max_seconds <= 1800
            or type(include_personal) is not bool
        ):
            raise ProbeError("INVALID_WORKFLOW")
        for identity in job_ids:
            self.repository.job(identity)
        if domain_id:
            definition = next(
                (
                    row
                    for row in DomainKnowledgeService(self.repository).list_domains()
                    if row["id"] == domain_id and row["status"] == "active"
                ),
                None,
            )
            if not definition:
                raise ProbeError("WORKFLOW_ACTIVE_DOMAIN_REQUIRED")
        record = {
            "id": uuid4().hex,
            "revision": 1,
            "title": title.strip(),
            "goal": goal.strip(),
            "job_ids": list(dict.fromkeys(job_ids)),
            "domain_id": domain_id,
            "terms": validated_terms(terms) if terms else [],
            "include_personal": include_personal,
            "budget": {
                "max_calls": max_calls,
                "max_seconds": max_seconds,
                "max_candidates": 20,
                "max_cycles": 12,
                "max_public": 0,
            },
            "state": "saved",
            "created_at": now(),
            "updated_at": now(),
            "cycles": [],
            "memory_refs": [],
            "source_run_ids": [],
            "project_ids": [],
            "stop_reason": "saved_no_execution",
            "scope_version": 1,
            "scope_history": [],
        }
        record["estimate"] = self.estimate(record)
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "INSERT INTO research_workflows VALUES(?,?,?,?)",
                (self.store.namespace, record["id"], 1, json.dumps(record, ensure_ascii=False)),
            )
        return record

    def refine(self, identity, *, revision, job_ids):
        """明确缩小未来范围；既有周期、预留与费用记录不重置。"""
        with exclusive(self.repository.engine.url.database):
            record = self._get(identity)
            if record["state"] == "invalidated":
                raise ProbeError("WORKFLOW_FORGOTTEN_RESTART")
            if record["revision"] != revision:
                raise ProbeError("WORKFLOW_CHANGED_REFRESH")
            if (
                not isinstance(job_ids, list)
                or not 1 <= len(job_ids) <= 20
                or any(not isinstance(item, str) for item in job_ids)
                or not set(job_ids) <= set(record["job_ids"])
            ):
                raise ProbeError("WORKFLOW_REFINE_SUBSET_REQUIRED")
            record.setdefault("scope_history", []).append(
                {
                    "version": record.get("scope_version", 1),
                    "job_ids": record["job_ids"],
                    "ended_at": now(),
                }
            )
            record["job_ids"] = list(dict.fromkeys(job_ids))
            record["scope_version"] = record.get("scope_version", 1) + 1
            record.update(state="saved", stop_reason="scope_refined_budget_retained")
            record["estimate"] = self.estimate(record)
            return self._save(record)

    def estimate(self, record):
        from work_observer.memory.dependencies import DependencyAudit

        _, facts, _ = self.fingerprint(record)
        profiles, needed, current = ProfileService(self.repository), [], []
        for fact in facts:
            if fact["integrity"] != "verified":
                continue
            profile = profiles.get(fact["job_id"])
            if (
                profile["status"] == "completed"
                and not profile["stale"]
                and DependencyAudit(self.repository).result(profile["result"])["eligible"]
            ):
                current.append(fact["job_id"])
            else:
                needed.append(fact["job_id"])
        reserved = self.usage(record)["reserved"]
        needed_budget = {
            key: PROJECT_BUDGET[key] + len(needed) * PROFILE_BUDGET[key] for key in PROJECT_BUDGET
        }
        return {
            "candidate_count": len(record["job_ids"]),
            "current_profile_ids": current,
            "profile_job_ids_needed": needed,
            "waiting_material_job_ids": [
                fact["job_id"] for fact in facts if fact["integrity"] != "verified"
            ],
            "worst_new_cycle": needed_budget,
            "remaining_lifetime": {
                key: record["budget"]["max_" + key] - reserved[key] for key in reserved
            },
            "fits_remaining": all(
                reserved[key] + needed_budget[key] <= record["budget"]["max_" + key]
                for key in reserved
            ),
            "note": "仅本地估算；画像每份最多9调用/235秒，研究项目24调用/360秒；未执行不产生调用。",
        }

    def get(self, identity):
        record = self._get(identity)
        if record["state"] == "invalidated":
            raise ProbeError("WORKFLOW_FORGOTTEN_RESTART")
        with Session(self.repository.engine) as session:
            forgotten = [
                ref["id"]
                for ref in record["memory_refs"]
                if (row := session.get(MemoryRecord, ref["id"])) is None
                or row.status == "forgotten"
            ]
        if forgotten:
            self.invalidate([], forgotten, [])
            raise ProbeError("WORKFLOW_FORGOTTEN_RESTART")
        record["usage"] = self.usage(record)
        if record["cycles"] and record["cycles"][-1].get("project_id"):
            project = ProjectService(self.store).get(record["cycles"][-1]["project_id"])
            if project["state"] == "invalidated":
                self.invalidate([], [], [project["id"]])
                raise ProbeError("WORKFLOW_FORGOTTEN_RESTART")
            record["current_project"] = project
        from work_observer.memory.dependencies import DependencyAudit

        record["dependency_issues"] = []
        for run_id in record["source_run_ids"]:
            audit = DependencyAudit(self.repository).run(run_id)
            if not audit["eligible"]:
                record["dependency_issues"].extend(audit["issues"])
        record["stale_dependencies"] = bool(record["dependency_issues"])
        return record

    def usage(self, record):
        reserved = {"calls": 0, "seconds": 0}
        actual = {"calls": 0, "seconds": 0}
        for cycle in record["cycles"]:
            for key in reserved:
                reserved[key] += cycle["project_reservation"][key]
            for attempt in cycle["profile_attempts"]:
                for key in reserved:
                    reserved[key] += attempt["reservation"][key]
                    actual[key] += attempt.get("actual", {}).get(key, 0)
            if cycle.get("project_id"):
                project = ProjectService(self.store).get(cycle["project_id"])
                usage = ProjectService(self.store).usage(project)
                actual["calls"] += usage["calls"]
                actual["seconds"] += usage["seconds"]
        return {
            "reserved": reserved,
            "actual": actual,
            "unknown_actual_attempts": sum(
                "actual" not in attempt
                for cycle in record["cycles"]
                for attempt in cycle["profile_attempts"]
            ),
        }

    def fingerprint(self, record):
        from work_observer.analysis.profiles import ANALYZER_VERSION, PROMPT_VERSION, QUESTION

        profiles, catalog, memory = (
            ProfileService(self.repository),
            Catalog(self.repository),
            MemoryService(self.repository),
        )
        facts, refs = [], {}
        for identity in record["job_ids"]:
            job = self.repository.job(identity)["current"]
            evidence = catalog.evidence(identity, limit=1)
            source = evidence[0] if evidence else None
            facts.append(
                {
                    "job_id": identity,
                    "snapshot_id": source.get("snapshot_id") if source else None,
                    "content_sha256": source.get("content_sha256") if source else None,
                    "integrity": catalog.document(source["document_id"])["integrity"]
                    if source
                    else "missing_detail",
                    "fields": {
                        key: job.get(key)
                        for key in (
                            "title",
                            "company_name_raw",
                            "city",
                            "salary_raw",
                            "education_raw",
                            "experience_raw",
                            "employment_type",
                        )
                    },
                }
            )
            for item in memory.recall(QUESTION + " " + record["goal"], [identity]):
                refs[item["id"]] = {"id": item["id"], "version": item["version"]}
        definition = None
        if record["domain_id"]:
            definition = next(
                (
                    row
                    for row in DomainKnowledgeService(self.repository).list_domains(True)
                    if row["id"] == record["domain_id"]
                ),
                None,
            )
            if not definition or definition["status"] != "active":
                raise ProbeError("WORKFLOW_DOMAIN_CHANGED_REVIEW_REQUIRED")
        memory_refs = sorted(refs.values(), key=lambda item: item["id"])
        return (
            _digest(
                {
                    "facts": facts,
                    "memories": memory_refs,
                    "domain": definition,
                    "method": [ANALYZER_VERSION, PROMPT_VERSION],
                    "strategy": profiles._strategy_context(),
                }
            ),
            facts,
            memory_refs,
        )

    def related_runs(self, run_ids=(), memory_ids=(), project_ids=()):
        affected, runs, projects, captures, reports = [], set(), set(), set(), set()
        ProjectService(self.store)
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT record FROM research_workflows WHERE namespace=?", (self.store.namespace,)
            ).fetchall()
        for (encoded,) in rows:
            record = json.loads(encoded)
            if record["state"] == "invalidated":
                dependencies = record.get("invalidation_dependencies", {})
                if (
                    set(dependencies.get("run_ids", [])) & set(run_ids)
                    or set(dependencies.get("memory_ids", [])) & set(memory_ids)
                    or set(dependencies.get("project_ids", [])) & set(project_ids)
                ):
                    affected.append(record["id"])
                    runs.update(dependencies.get("run_ids", []))
                    projects.update(dependencies.get("project_ids", []))
                    captures.update(dependencies.get("capture_ids", []))
                    reports.update(dependencies.get("report_ids", []))
                continue
            actual_runs = set(record["source_run_ids"])
            actual_projects = set(record["project_ids"])
            for cycle in record["cycles"]:
                actual_runs.update(cycle.get("run_ids", []))
                actual_runs.update(cycle.get("profile_run_ids", []))
                if cycle.get("project_id"):
                    actual_projects.add(cycle["project_id"])
                with self.store.lock:
                    planned = self.store.db.execute(
                        "SELECT id FROM research_projects WHERE namespace=? "
                        "AND (json_extract(record,'$.source_key')=? OR EXISTS(SELECT 1 "
                        "FROM json_each(record,'$.erased_workflow_cycle_ids') WHERE value=?))",
                        (self.store.namespace, "workflow:" + cycle["id"], cycle["id"]),
                    ).fetchall()
                actual_projects.update(row[0] for row in planned)
            for project_id in actual_projects:
                project = ProjectService(self.store).get(project_id)
                actual_runs.update(
                    step["run_id"] for step in project["steps"] if step.get("run_id")
                )
                actual_runs.update(project.get("erased_run_ids", []))
            if not (
                actual_runs & set(run_ids)
                or {ref["id"] for ref in record["memory_refs"]} & set(memory_ids)
                or actual_projects & set(project_ids)
            ):
                continue
            affected.append(record["id"])
            runs.update(actual_runs)
            projects.update(actual_projects)
            for cycle in record["cycles"]:
                captures.add(_digest({"workflow_cycle": cycle["id"], "kind": "capture"})[:32])
                if cycle.get("capture_id"):
                    captures.add(cycle["capture_id"])
                if cycle.get("report_id"):
                    reports.add(cycle["report_id"])
                if cycle.get("project_id"):
                    project = ProjectService(self.store).get(cycle["project_id"])
                    runs.update(step["run_id"] for step in project["steps"] if step.get("run_id"))
        with self.store.lock:
            exists = self.store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='domain_update_reports'"
            ).fetchone()
            if exists:
                for report_id, encoded in self.store.db.execute(
                    "SELECT id,record FROM domain_update_reports WHERE namespace=?",
                    (self.store.namespace,),
                ):
                    report = json.loads(encoded)
                    if report.get("before_id") in captures or report.get("after_id") in captures:
                        reports.add(report_id)
        return {
            "affected_workflow_ids": affected,
            "affected_run_ids": sorted(runs),
            "affected_project_ids": sorted(projects),
            "capture_ids": sorted(captures),
            "report_ids": sorted(reports),
        }

    def invalidate(self, run_ids=(), memory_ids=(), project_ids=()):
        related = self.related_runs(run_ids, memory_ids, project_ids)
        with self.store.lock, self.store.db:
            for identity in related["affected_workflow_ids"]:
                old = self._get(identity)
                dependencies = old.get("invalidation_dependencies") or {
                    "run_ids": related["affected_run_ids"],
                    "memory_ids": [ref["id"] for ref in old["memory_refs"]],
                    "project_ids": related["affected_project_ids"],
                    "capture_ids": related["capture_ids"],
                    "report_ids": related["report_ids"],
                }
                minimal = {
                    "id": identity,
                    "revision": old["revision"] + 1,
                    "state": "invalidated",
                    "title": "关联记忆或项目已忘记",
                    "created_at": old["created_at"],
                    "updated_at": now(),
                    "goal": "[已清除]",
                    "job_ids": [],
                    "cycles": [],
                    "memory_refs": [],
                    "source_run_ids": [],
                    "project_ids": [],
                    "stop_reason": "related_context_forgotten",
                    "invalidation_dependencies": dependencies,
                }
                self.store.db.execute(
                    "UPDATE research_workflows SET revision=?,record=? WHERE namespace=? AND id=?",
                    (minimal["revision"], json.dumps(minimal), self.store.namespace, identity),
                )
            for table, identities in (
                ("domain_update_captures", related["capture_ids"]),
                ("domain_update_reports", related["report_ids"]),
            ):
                exists = self.store.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                if exists:
                    for identity in identities:
                        self.store.db.execute(
                            f"UPDATE {table} SET record=? WHERE namespace=? AND id=?",
                            (
                                json.dumps({"id": identity, "state": "invalidated"}),
                                self.store.namespace,
                                identity,
                            ),
                        )
        InboxService(self.repository).invalidate_research(
            [*related["affected_workflow_ids"], *related["report_ids"]]
        )
        return related


class _WorkflowUpdates(DomainUpdateService):
    def __init__(self, store, repository, cycle, memory_refs):
        super().__init__(store, repository)
        self.cycle, self.refs = cycle, memory_refs

    def _write(self, table, record):
        if table == "domain_update_captures":
            record["id"] = _digest({"workflow_cycle": self.cycle["id"], "kind": "capture"})[:32]
            current = sum(
                task["state"] in {"completed", "current"}
                for task in self.cycle["profile_tasks"].values()
            )
            record["sample"]["profile_result_rows"] = sum(
                job["profile"] is not None for job in record["jobs"]
            )
            record["sample"]["current_profile_outputs"] = current
            record["sample"]["missing_profiles"] = len(record["jobs"]) - current
        record["source_run_ids"] = sorted(
            set(record.get("source_run_ids", []))
            | set(self.cycle.get("run_ids", []))
            | set(self.cycle.get("profile_run_ids", []))
        )
        record["memory_refs"] = list(
            {ref["id"]: ref for ref in [*record.get("memory_refs", []), *self.refs]}.values()
        )
        return super()._write(table, record)


def _plan(service, record, cycle):
    projects = ProjectService(service.store)
    project = projects.create(
        record["title"],
        record["goal"],
        record["job_ids"],
        max_calls=24,
        max_seconds=360,
        max_rounds=12,
        max_public=0,
        source_key="workflow:" + cycle["id"],
    )
    cycle["project_id"] = project["id"]
    record["project_ids"] = list(dict.fromkeys([*record["project_ids"], project["id"]]))
    service._save(record)
    parents = []
    scope_note = ""
    if record["domain_id"]:
        definition = next(
            row
            for row in DomainKnowledgeService(service.repository).list_domains(True)
            if row["id"] == record["domain_id"]
        )
        scope_note = (
            f"领域口径：{definition['name']}第{definition['version']}版；"
            "未分类和人工排除的岗位须单列，不强行归入此领域。"
        )
    for kind, question in (
        ("investigate", record["goal"]),
        ("counterexample", "核对反例、相反职责和仍缺资料：" + record["goal"]),
        ("synthesis", "综合已审核的调查与反例，回答：" + record["goal"]),
    ):
        key = cycle["id"] + ":" + kind
        project = projects.add(
            project["id"],
            (scope_note + question)[:4000],
            revision=project["revision"],
            kind=kind,
            depends_on=parents if kind == "synthesis" else [],
            max_calls=8,
            timeout=120,
            offline=cycle["mode"] == "offline",
            key=key,
        )
        if kind != "synthesis":
            parents.append(next(step["id"] for step in project["steps"] if step.get("key") == key))
    return project


async def execute_workflow(
    service,
    identity,
    settings,
    *,
    model=None,
    allow_model=False,
    retry_failed=False,
    new_cycle=False,
    max_calls=36,
    max_seconds=900,
):
    if (
        type(allow_model) is not bool
        or type(retry_failed) is not bool
        or type(new_cycle) is not bool
        or type(max_calls) is not int
        or not 0 <= max_calls <= 36
        or type(max_seconds) is not int
        or not 1 <= max_seconds <= 900
    ):
        raise ProbeError("INVALID_WORKFLOW_BATCH")
    with exclusive(service.repository.engine.url.database):
        if pending_erasures(service.store):
            raise ProbeError("PRIVACY_ERASURE_PENDING")
        service.recover(identity, _lock_held=True)
        try:
            async with asyncio.timeout(max_seconds):
                return await _execute(
                    service,
                    identity,
                    settings,
                    model=model,
                    allow_model=allow_model,
                    retry_failed=retry_failed,
                    new_cycle=new_cycle,
                    max_calls=max_calls,
                    max_seconds=max_seconds,
                )
        except asyncio.CancelledError:
            record = service._get(identity)
            record.update(state="interrupted", stop_reason="explicit_or_process_interrupted")
            service._save(record)
            raise
        except TimeoutError:
            record = service._get(identity)
            record.update(state="interrupted", stop_reason="workflow_batch_time_limit")
            return service._save(record)


async def _execute(
    service,
    identity,
    settings,
    *,
    model,
    allow_model,
    retry_failed,
    new_cycle,
    max_calls,
    max_seconds,
):
    record = service.get(identity)
    record.pop("usage", None)
    record.pop("current_project", None)
    record.pop("dependency_issues", None)
    record.pop("stale_dependencies", None)
    fingerprint, facts, memory_refs = service.fingerprint(record)
    mode = "model" if allow_model else "offline"
    cycle = record["cycles"][-1] if record["cycles"] else None
    if cycle and cycle["mode"] == "model" and not allow_model and not new_cycle:
        record.update(stop_reason="model_consent_required_to_continue")
        return service._save(record)
    if not cycle or cycle["fingerprint"] != fingerprint or cycle["mode"] != mode or new_cycle:
        if len(record["cycles"]) >= record["budget"]["max_cycles"]:
            raise ProbeError("WORKFLOW_CYCLE_LIMIT")
        usage = service.usage(record)["reserved"]
        record["estimate"] = service.estimate(record)
        if allow_model and not record["estimate"]["fits_remaining"]:
            record.update(
                state="needs_scope_refinement",
                stop_reason="workflow_estimate_exceeds_remaining_budget",
            )
            return service._save(record)
        reservation = PROJECT_BUDGET if allow_model else {"calls": 0, "seconds": 0}
        if any(usage[key] + reservation[key] > record["budget"]["max_" + key] for key in usage):
            record.update(state="waiting_budget", stop_reason="workflow_lifetime_budget_exhausted")
            return service._save(record)
        cycle = {
            "id": uuid4().hex,
            "fingerprint": fingerprint,
            "mode": mode,
            "job_ids": record["job_ids"][:],
            "created_at": now(),
            "state": "ready",
            "project_reservation": dict(reservation),
            "profile_attempts": [],
            "profile_tasks": {},
            "project_id": None,
            "run_ids": [],
            "capture_id": None,
            "report_id": None,
        }
        record["cycles"].append(cycle)
        record["memory_refs"] = list(
            {ref["id"]: ref for ref in [*record["memory_refs"], *memory_refs]}.values()
        )
        record.update(state="ready", stop_reason=None)
        service._save(record)
    started, batch = time.monotonic(), {"calls": 0, "seconds": 0}
    profiles = ProfileService(service.repository)
    for fact in facts:
        job_id, state = fact["job_id"], cycle["profile_tasks"].get(fact["job_id"])
        profile = profiles.get(job_id)
        if fact["integrity"] != "verified":
            cycle["profile_tasks"][job_id] = {
                "state": "waiting_material",
                "reason": fact["integrity"],
            }
            continue
        from work_observer.memory.dependencies import DependencyAudit

        profile_eligible = (
            bool(profile.get("result"))
            and DependencyAudit(service.repository).result(profile["result"])["eligible"]
        )
        if profile["status"] == "completed" and not profile["stale"] and profile_eligible:
            for attempt in cycle["profile_attempts"]:
                if attempt["job_id"] == job_id and attempt["state"] == "running":
                    attempt.update(
                        state="completed", analysis_id=profile["id"], recovered_result=True
                    )
            cycle["profile_tasks"][job_id] = {"state": "current", "analysis_id": profile["id"]}
            continue
        if (
            state
            and state["state"] in {"completed", "current"}
            and (profile["stale"] or not profile_eligible)
        ):
            cycle["profile_tasks"][job_id] = state = {
                "state": "failed",
                "reason": "profile_dependencies_changed_review_required",
            }
        if (
            state
            and state["state"] in {"completed", "evidence_only", "failed", "interrupted"}
            and not retry_failed
        ):
            continue
        for attempt in cycle["profile_attempts"]:
            if attempt["job_id"] == job_id and attempt["state"] == "running":
                attempt["state"] = "interrupted"
                cycle["profile_tasks"][job_id] = {
                    "state": "interrupted",
                    "reason": "profile_checkpoint_not_resumable",
                }
                state = cycle["profile_tasks"][job_id]
        if state and state["state"] == "interrupted" and not retry_failed:
            continue
        reservation = PROFILE_BUDGET if allow_model else {"calls": 0, "seconds": 0}
        used = service.usage(record)["reserved"]
        if any(used[key] + reservation[key] > record["budget"]["max_" + key] for key in used):
            cycle["profile_tasks"][job_id] = {
                "state": "budget_skipped",
                "reason": "workflow_lifetime_budget_exhausted",
            }
            continue
        if (
            batch["calls"] + reservation["calls"] > max_calls
            or batch["seconds"] + reservation["seconds"] > max_seconds
        ):
            cycle["profile_tasks"][job_id] = {"state": "pending", "reason": "workflow_batch_budget"}
            continue
        attempt = {
            "id": uuid4().hex,
            "job_id": job_id,
            "state": "running",
            "reservation": dict(reservation),
            "created_at": now(),
        }
        cycle["profile_attempts"].append(attempt)
        cycle["profile_tasks"][job_id] = {"state": "running"}
        record["state"] = "running"
        service._save(record)
        for key in batch:
            batch[key] += reservation[key]
        try:
            output = await profiles.analyze(
                job_id, settings, model=model, offline=not allow_model, _lock_held=True
            )
            result = output.get("result") or {}
            if result.get("run_id"):
                cycle["profile_run_ids"] = list(
                    dict.fromkeys([*cycle.get("profile_run_ids", []), result["run_id"]])
                )
                record["source_run_ids"] = list(
                    dict.fromkeys([*record["source_run_ids"], result["run_id"]])
                )
            attempt.update(
                state="completed"
                if output["status"] == "completed" and not output["stale"]
                else "evidence_only"
                if not allow_model
                else "failed",
                analysis_id=output["id"],
                actual={
                    "calls": result.get("model_calls", 0),
                    "seconds": result.get("elapsed_seconds", 0),
                },
            )
            cycle["profile_tasks"][job_id] = {
                "state": attempt["state"],
                "analysis_id": output["id"],
            }
        except asyncio.CancelledError:
            attempt["state"] = "interrupted"
            cycle["profile_tasks"][job_id] = {"state": "interrupted"}
            service._save(record)
            raise
        except Exception as exc:
            from work_observer.collection.service import error_code

            attempt.update(state="failed", error_code=error_code(exc))
            cycle["profile_tasks"][job_id] = {"state": "failed", "reason": error_code(exc)}
        service._save(record)
        if service.fingerprint(record)[0] != fingerprint:
            record.update(
                state="waiting_review", stop_reason="workflow_inputs_changed_start_new_cycle"
            )
            return service._save(record)
    if allow_model and any(
        task["state"] in {"pending", "running"} for task in cycle["profile_tasks"].values()
    ):
        record.update(state="ready", stop_reason="workflow_batch_budget_pending_profiles")
        record["last_batch"] = {
            "reserved": batch,
            "max_calls": max_calls,
            "max_seconds": max_seconds,
        }
        return service._save(record)
    if allow_model and any(
        task["state"] in {"failed", "interrupted", "budget_skipped", "waiting_material"}
        for task in cycle["profile_tasks"].values()
    ):
        states = {task["state"] for task in cycle["profile_tasks"].values()}
        record.update(
            state="needs_scope_refinement"
            if "budget_skipped" in states
            else "waiting_review"
            if states & {"failed", "interrupted"}
            else "waiting_material",
            stop_reason="profiles_incomplete_research_not_started",
        )
        return service._save(record)
    project = _plan(service, record, cycle)
    if project["job_ids"] != record["job_ids"] or project["goal"] != record["goal"]:
        raise ProbeError("WORKFLOW_PROJECT_SCOPE_CHANGED")
    cycle["project_id"] = project["id"]
    record["project_ids"] = list(dict.fromkeys([*record["project_ids"], project["id"]]))
    service._save(record)
    if not any(fact["integrity"] not in {"verified", "missing_detail"} for fact in facts):
        for _ in range(3):
            remaining = {
                "calls": max_calls - batch["calls"],
                "seconds": max(
                    0,
                    min(
                        max_seconds - batch["seconds"],
                        int(max_seconds - (time.monotonic() - started)),
                    ),
                ),
                "public": 0,
            }
            record["state"] = "running"
            service._save(record)
            project = await execute_project(
                ProjectService(service.store),
                project["id"],
                service.repository,
                settings,
                model=model,
                max_steps=1,
                _lock_held=True,
                worker_caps=remaining,
            )
            for key in batch:
                batch[key] += project["worker_batch"]["reserved"][key]
            cycle["run_ids"] = [step["run_id"] for step in project["steps"] if step.get("run_id")]
            record["source_run_ids"] = list(
                dict.fromkeys([*record["source_run_ids"], *cycle["run_ids"]])
            )
            service._save(record)
            if service.fingerprint(record)[0] != fingerprint:
                record.update(
                    state="waiting_review", stop_reason="workflow_inputs_changed_start_new_cycle"
                )
                return service._save(record)
            if not project["worker_batch"]["run_ids"]:
                break
    updates = _WorkflowUpdates(service.store, service.repository, cycle, record["memory_refs"])
    capture = updates.capture(
        (record["title"] + " · 当前观察")[:150],
        job_ids=record["job_ids"],
        domain_id=record["domain_id"],
        terms=record["terms"],
        include_personal=record["include_personal"],
    )
    cycle["capture_id"] = capture["id"]
    previous = next(
        (item for item in reversed(record["cycles"][:-1]) if item.get("capture_id")), None
    )
    if previous:
        cycle["report_id"] = updates.compare(previous["capture_id"], capture["id"])["id"]
    states = {step["state"] for step in project["steps"] if step["state"] != "superseded"}
    cycle["state"] = (
        "completed"
        if {step["id"] for step in project["steps"]} <= completed_steps(project)
        else "waiting_review"
        if states & {"waiting_review", "failed"}
        else "waiting_material"
        if "waiting_material" in states
        else "ready"
    )
    record.update(
        state=cycle["state"],
        stop_reason="review_or_material_required"
        if cycle["state"].startswith("waiting")
        else "bounded_batch_finished",
    )
    record["last_batch"] = {
        "reserved": batch,
        "max_calls": max_calls,
        "max_seconds": max_seconds,
        "wall_seconds": round(time.monotonic() - started, 3),
    }
    service._save(record)
    inbox = InboxService(service.repository)
    inbox.create(
        "research",
        record["title"][:120] + " · 流程更新",
        "当前观察已保存；原文变化、样本变化和方法变化分别核对。调查状态："
        + cycle["state"]
        + "。来源暂停未解除；没有可比时间序列时不声称趋势。",
        related_id=record["id"],
        dedupe_key="workflow:" + cycle["id"] + ":" + cycle["state"],
    )
    inbox.create(
        "followup",
        "继续核对本流程缺口",
        ("请核对这个目标下仍缺的资料、反例和研究结论：" + record["goal"])[:4000],
        related_id=record["id"],
        dedupe_key="workflow:" + cycle["id"] + ":followup",
    )
    return service.get(identity)
