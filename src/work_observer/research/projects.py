"""持久研究项目：业务会话与有界调查步骤，独立于模型执行检查点。"""

import hashlib
import json
import re
from uuid import uuid4

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError


def step_reservation(step):
    """一次领取预留整轮最坏开销；恢复也不重新开放原预算。"""
    return {
        "calls": 0 if step["offline"] else step["max_calls"],
        "seconds": 0 if step["offline"] else step["timeout"],
        "public": 4 if step["allow_public"] and not step["offline"] else 0,
    }


def completed_steps(record, rejected=()):
    """审核后的补查可完成原等待事项；旧范围的完成状态不能用于新范围。"""
    current = record["scope_version"]
    completed = {
        s["id"]
        for s in record["steps"]
        if s["state"] == "completed" and s["scope_version"] == current and s["id"] not in rejected
    }
    for _ in range(len(record["steps"])):
        before = len(completed)
        for step in record["steps"]:
            if step["scope_version"] == current and step.get("replacement_step_id") in completed:
                completed.add(step["id"])
        if len(completed) == before:
            break
    return completed


def dependency_steps(record, identities):
    result = set(identities)
    for _ in range(len(record["steps"])):
        before = len(result)
        result.update(
            s["replacement_step_id"]
            for s in record["steps"]
            if s["id"] in result and s.get("replacement_step_id")
        )
        if len(result) == before:
            break
    return result


class ProjectService:
    def __init__(self, store):
        self.store = store
        with store.lock, store.db:
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS research_projects (namespace TEXT NOT NULL, "
                "id TEXT NOT NULL, revision INTEGER NOT NULL, record TEXT NOT NULL, "
                "PRIMARY KEY(namespace,id))"
            )

    def get(self, identity):
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT record FROM research_projects WHERE namespace=? AND id=?",
                (self.store.namespace, identity),
            ).fetchone()
        if not row:
            raise ProbeError("PROJECT_NOT_FOUND")
        return json.loads(row[0])

    def list(self, *, all_records=False):
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT record FROM research_projects WHERE namespace=? "
                "ORDER BY json_extract(record,'$.updated_at') DESC"
                + ("" if all_records else " LIMIT 100"),
                (self.store.namespace,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _write(self, record):
        old = record["revision"]
        record.update(revision=old + 1, updated_at=now())
        changed = self.store.db.execute(
            "UPDATE research_projects SET revision=?,record=? "
            "WHERE namespace=? AND id=? AND revision=?",
            (
                old + 1,
                json.dumps(record, ensure_ascii=False),
                self.store.namespace,
                record["id"],
                old,
            ),
        )
        if changed.rowcount != 1:
            raise ProbeError("PROJECT_CHANGED_REFRESH")
        return record

    def erase(self, identity):
        """先收集所有项目执行，再清空目标、交流、调查和范围历史，供遗忘闭包使用。"""
        with self.store.lock, self.store.db:
            record = self.get(identity)
            if any(step["state"] == "running" for step in record.get("steps", [])):
                raise ProbeError("PROJECT_RUNNING")
            run_ids = set(record.get("erased_run_ids", []))
            cycle_ids = set(record.get("erased_workflow_cycle_ids", []))
            source_key = record.get("source_key")
            if isinstance(source_key, str) and re.fullmatch(r"workflow:[a-f0-9]{32}", source_key):
                cycle_ids.add(source_key.split(":", 1)[1])
            run_ids.update(step["run_id"] for step in record.get("steps", []) if step.get("run_id"))
            rows = self.store.db.execute(
                "SELECT id,record,checkpoint FROM research_checkpoints WHERE namespace=?",
                (self.store.namespace,),
            ).fetchall()
            for run_id, encoded, encoded_checkpoint in rows:
                run = json.loads(encoded)
                checkpoint = json.loads(encoded_checkpoint) if encoded_checkpoint else {}
                if any(
                    isinstance(context, dict) and context.get("project_id") == identity
                    for context in (
                        run.get("input"),
                        run.get("result"),
                        checkpoint.get("result"),
                    )
                ):
                    run_ids.add(run_id)
            if record.get("stop_reason") != "project_forgotten":
                minimal = dict(
                    id=record["id"],
                    revision=record["revision"],
                    title="[已忘记研究项目]",
                    goal="此项目内容已清除，请建立新项目",
                    job_ids=[],
                    state="invalidated",
                    created_at=record["created_at"],
                    updated_at=now(),
                    scope_version=record.get("scope_version", 1),
                    turns=[],
                    steps=[],
                    scope_history=[],
                    budget=dict(max_calls=0, max_seconds=0, max_rounds=0, max_public=0),
                    stop_reason="project_forgotten",
                    erased_run_ids=sorted(run_ids),
                    erased_workflow_cycle_ids=sorted(cycle_ids),
                )
                self._write(minimal)
            return {"erased_project_id": identity, "affected_run_ids": sorted(run_ids)}

    def create(
        self,
        title,
        goal,
        job_ids,
        *,
        max_calls=36,
        max_seconds=900,
        max_rounds=6,
        max_public=4,
        source_key=None,
    ):
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 150
            or not isinstance(goal, str)
            or not goal.strip()
            or len(goal) > 4000
            or not isinstance(job_ids, list)
            or not 1 <= len(set(job_ids)) <= 20
            or any(not isinstance(key, str) for key in job_ids)
        ):
            raise ProbeError("INVALID_PROJECT")
        if not (
            1 <= max_calls <= 72
            and 1 <= max_seconds <= 1800
            and 1 <= max_rounds <= 12
            and 0 <= max_public <= 8
        ):
            raise ProbeError("INVALID_PROJECT_BUDGET")
        stamp = now()
        if source_key is not None and (
            not isinstance(source_key, str) or not source_key.strip() or len(source_key) > 200
        ):
            raise ProbeError("INVALID_PROJECT_SOURCE_KEY")
        signature = hashlib.sha256(
            json.dumps(
                dict(
                    title=title.strip(),
                    goal=goal.strip(),
                    job_ids=sorted(set(job_ids)),
                    max_calls=max_calls,
                    max_seconds=max_seconds,
                    max_rounds=max_rounds,
                    max_public=max_public,
                ),
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        identity = (
            hashlib.sha256((self.store.namespace + ":" + source_key).encode()).hexdigest()[:32]
            if source_key
            else uuid4().hex
        )
        record = dict(
            id=identity,
            source_key=source_key,
            create_signature=signature,
            title=title.strip(),
            goal=goal.strip(),
            job_ids=list(dict.fromkeys(job_ids)),
            revision=1,
            scope_version=1,
            state="active",
            created_at=stamp,
            updated_at=stamp,
            turns=[],
            steps=[],
            scope_history=[],
            budget=dict(
                max_calls=max_calls,
                max_seconds=max_seconds,
                max_rounds=max_rounds,
                max_public=max_public,
            ),
            stop_reason=None,
        )
        with self.store.lock, self.store.db:
            # 恢复到新目录只改变namespace，不改变已有项目及其回链ID。
            # 先找原来源键，避免路径变化后再次创建预算与调查。
            if source_key:
                previous = self.store.db.execute(
                    "SELECT id FROM research_projects WHERE namespace=? "
                    "AND json_extract(record,'$.source_key')=?",
                    (self.store.namespace, source_key),
                ).fetchone()
                if previous:
                    record["id"] = identity = previous[0]
            self.store.db.execute(
                "INSERT OR IGNORE INTO research_projects VALUES (?,?,?,?)",
                (self.store.namespace, record["id"], 1, json.dumps(record, ensure_ascii=False)),
            )
            existing = self.get(identity)
            if existing.get("create_signature") != signature:
                raise ProbeError("PROJECT_SOURCE_KEY_CONFLICT")
            self._editable(existing)
            if existing["goal"] != goal.strip() or set(existing["job_ids"]) != set(job_ids):
                raise ProbeError("PROJECT_SOURCE_KEY_CONFLICT")
        return existing

    def revise(self, identity, *, revision, goal, job_ids):
        with self.store.lock, self.store.db:
            record = self.get(identity)
            self._editable(record, revision)
            if not goal.strip() or len(goal) > 4000 or not 1 <= len(set(job_ids)) <= 20:
                raise ProbeError("INVALID_PROJECT")
            if any(step["state"] == "running" for step in record["steps"]):
                raise ProbeError("PROJECT_RUNNING")
            record["scope_history"].append(
                {
                    "version": record["scope_version"],
                    "goal": record["goal"],
                    "job_ids": record["job_ids"],
                    "ended_at": now(),
                }
            )
            record.update(
                goal=goal.strip(),
                job_ids=list(dict.fromkeys(job_ids)),
                scope_version=record["scope_version"] + 1,
            )
            for step in record["steps"]:
                if step["state"] in {"queued", "interrupted"}:
                    step.update(state="waiting_review", stop_reason="scope_changed_replan")
            return self._write(record)

    def _editable(self, record, revision=None):
        if record["state"] == "invalidated":
            raise ProbeError("PROJECT_FORGOTTEN_RESTART")
        if revision is not None and record["revision"] != revision:
            raise ProbeError("PROJECT_CHANGED_REFRESH")

    def add(
        self,
        identity,
        question,
        *,
        revision,
        kind="investigate",
        depends_on=None,
        completion="形成带原文引用的回答，并明确未知项",
        offline=False,
        allow_public=False,
        max_calls=10,
        timeout=180,
        key=None,
    ):
        if (
            not question.strip()
            or len(question) > 4000
            or not completion.strip()
            or len(completion) > 1000
            or kind not in {"investigate", "counterexample", "synthesis"}
            or not 1 <= max_calls <= 12
            or not 1 <= timeout <= 300
        ):
            raise ProbeError("INVALID_INVESTIGATION_STEP")
        with self.store.lock, self.store.db:
            record = self.get(identity)
            self._editable(record, revision)
            if key:
                existing = next((s for s in record["steps"] if s.get("key") == key), None)
                if existing:
                    return record
            if len(record["steps"]) >= record["budget"]["max_rounds"]:
                raise ProbeError("PROJECT_ROUND_LIMIT")
            parents = list(dict.fromkeys(depends_on or []))
            if any(parent not in {s["id"] for s in record["steps"]} for parent in parents):
                raise ProbeError("INVALID_STEP_DEPENDENCY")
            if any(
                s["id"] in parents and s["scope_version"] != record["scope_version"]
                for s in record["steps"]
            ):
                raise ProbeError("STEP_SCOPE_CHANGED_REPLAN")
            step_id = uuid4().hex
            record["steps"].append(
                dict(
                    id=step_id,
                    key=key,
                    question=question.strip(),
                    kind=kind,
                    completion=completion.strip(),
                    depends_on=parents,
                    state="queued",
                    scope_version=record["scope_version"],
                    job_ids=record["job_ids"][:],
                    offline=offline,
                    allow_public=allow_public,
                    max_calls=max_calls,
                    timeout=timeout,
                    run_id=None,
                    created_at=now(),
                    stop_reason=None,
                )
            )
            record["turns"].append(
                dict(
                    id=step_id,
                    role="user",
                    text=question.strip(),
                    scope_version=record["scope_version"],
                    created_at=now(),
                )
            )
            return self._write(record)

    def refresh_waiting(
        self,
        identity,
        step_id,
        repository,
        *,
        revision,
        note,
        offline=False,
        allow_public=False,
        max_calls=10,
        timeout=180,
    ):
        """显式补充资料/纠正后新轮调查，原轮预算、历史和审核均保留。"""
        from work_observer.research.materials import material_state

        if (
            not isinstance(note, str)
            or not note.strip()
            or len(note) > 1000
            or type(offline) is not bool
            or type(allow_public) is not bool
            or not 1 <= max_calls <= 12
            or not 1 <= timeout <= 300
        ):
            raise ProbeError("INVALID_STEP_REFRESH")
        initial = self.get(identity)
        self._editable(initial)
        original = next((s for s in initial["steps"] if s["id"] == step_id), None)
        if not original:
            raise ProbeError("STEP_NOT_FOUND")
        if original["scope_version"] != initial["scope_version"]:
            raise ProbeError("STEP_SCOPE_CHANGED_REPLAN")
        # 重复点击不制造新调查，旧步骤只回链已有补查。
        if original.get("replacement_step_id"):
            replacement = next(
                s for s in initial["steps"] if s["id"] == original["replacement_step_id"]
            )
            if (
                replacement.get("refresh_note"),
                replacement["offline"],
                replacement["allow_public"],
                replacement["max_calls"],
                replacement["timeout"],
            ) == (note.strip(), offline, allow_public, max_calls, timeout):
                return initial
            raise ProbeError("STEP_ALREADY_REFRESHED")
        self._editable(initial, revision)
        if original["state"] not in {"waiting_material", "waiting_review", "failed"}:
            raise ProbeError("STEP_NOT_WAITING_FOR_MATERIAL")
        material = material_state(
            repository, original["question"], job_ids=original["job_ids"], project_id=identity
        )
        run = self.store.get(original["run_id"]) if original.get("run_id") else {}
        old = (run.get("result") or {}).get("material_signature") or (
            (run.get("progress") or {}).get("materials") or {}
        ).get("signature")
        if old and material["signature"] == old and not (original["offline"] and not offline):
            raise ProbeError("NO_NEW_RESEARCH_MATERIAL")
        if (
            original.get("review_run_id")
            and original["offline"]
            and not offline
            and old == material["signature"]
        ):
            if allow_public:
                raise ProbeError("RESEARCH_FEEDBACK_STANDARD_ONLY")
            return self.repair_reviewed(
                identity,
                step_id,
                repository,
                revision=revision,
                review_id=original["review_id"],
                note=note,
                offline=False,
                max_calls=max_calls,
                timeout=timeout,
            )
        with self.store.lock, self.store.db:
            record = self.get(identity)
            self._editable(record, revision)
            if any(s["state"] == "running" for s in record["steps"]):
                raise ProbeError("PROJECT_RUNNING")
            if len(record["steps"]) >= record["budget"]["max_rounds"]:
                raise ProbeError("PROJECT_ROUND_LIMIT")
            original = next(s for s in record["steps"] if s["id"] == step_id)
            identity_new = uuid4().hex
            step = {
                **original,
                "id": identity_new,
                "key": f"refresh:{step_id}:{material['signature']}",
                "state": "queued",
                "offline": offline,
                "allow_public": allow_public,
                "max_calls": max_calls,
                "timeout": timeout,
                "run_id": None,
                "created_at": now(),
                "stop_reason": None,
                "replaces_step_id": step_id,
                "refresh_note": note.strip(),
                "refresh_material_signature": material["signature"],
                "legacy_material_basis": old is None,
            }
            for key in (
                "started_at",
                "finished_at",
                "review",
                "replacement_step_id",
                "review_run_id",
                "review_id",
                "review_source_step_id",
                "repair_note",
            ):
                step.pop(key, None)
            original["replacement_step_id"] = identity_new
            original["state"] = "superseded"
            record["steps"].append(step)
            record["turns"].append(
                {
                    "id": identity_new,
                    "role": "user",
                    "text": note.strip(),
                    "scope_version": record["scope_version"],
                    "created_at": now(),
                }
            )
            return self._write(record)

    def repair_reviewed(self, identity, step_id, repository, **options):
        from work_observer.research.project_feedback import repair_reviewed

        return repair_reviewed(self, identity, step_id, repository, **options)

    def rejected_steps(self, record):
        from work_observer.quality.reviews import QualityReviewService

        if not self.store.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='quality_reviews'"
        ).fetchone():
            return set()
        rejected = set()
        quality = QualityReviewService(self.store)
        for step in record["steps"]:
            if not step.get("run_id"):
                continue
            run = self.store.get(step["run_id"])
            if (run.get("result") or {}).get("status") != "completed" or run["state"] not in {
                "finished",
                "completed",
            }:
                continue
            latest = next(
                (r for r in quality.list_run(step["run_id"]) if not r["stale_result"]), None
            )
            if latest and latest["status"] == "rejected":
                rejected.add(step["id"])
        return rejected

    def usage(self, record):
        used = dict(calls=0, seconds=0.0, public=0, reserved_calls=0, reserved_seconds=0)
        for step in record["steps"]:
            if not step.get("run_id"):
                continue
            run = self.store.get(step["run_id"])
            result = run.get("result") or {}
            used["calls"] += result.get("model_calls", 0)
            used["seconds"] += result.get("elapsed_seconds", 0)
            used["public"] += result.get("public_searches", 0) + result.get("public_reads", 0)
            # 领取前预留整轮预算；中断不会把额度重新开放给另一步。
            used["reserved_calls"] += step["max_calls"] if not step["offline"] else 0
            used["reserved_seconds"] += step["timeout"] if not step["offline"] else 0
        return used

    def claim(self, identity, *, worker_caps=None, claim_outcome=None):
        if worker_caps is not None and (
            not isinstance(worker_caps, dict)
            or set(worker_caps) != {"calls", "seconds", "public"}
            or type(worker_caps["calls"]) is not int
            or not 0 <= worker_caps["calls"] <= 36
            or type(worker_caps["seconds"]) is not int
            or not 0 <= worker_caps["seconds"] <= 900
            or type(worker_caps["public"]) is not int
            or not 0 <= worker_caps["public"] <= 4
        ):
            raise ProbeError("INVALID_WORKER_BUDGET")
        with self.store.lock, self.store.db:
            record = self.get(identity)
            self._editable(record)
            if any(s["state"] == "running" for s in record["steps"]):
                raise ProbeError("PROJECT_RUNNING")
            completed = completed_steps(record, self.rejected_steps(record))
            ready = [
                s
                for s in record["steps"]
                if s["state"] in {"queued", "interrupted"} and set(s["depends_on"]) <= completed
            ]
            if not ready:
                if claim_outcome is not None:
                    claim_outcome["stop_reason"] = "no_ready_steps"
                return None
            step = next(
                (
                    item
                    for item in ready
                    if worker_caps is None
                    or all(
                        value <= worker_caps[key] for key, value in step_reservation(item).items()
                    )
                ),
                None,
            )
            if step is None:
                if claim_outcome is not None:
                    claim_outcome["stop_reason"] = "worker_budget_exhausted"
                return None
            reservation = step_reservation(step)
            used, budget = self.usage(record), record["budget"]
            if not step["run_id"]:
                calls = 0 if step["offline"] else step["max_calls"]
                seconds = 0 if step["offline"] else step["timeout"]
                if (
                    used["reserved_calls"] + calls > budget["max_calls"]
                    or used["reserved_seconds"] + seconds > budget["max_seconds"]
                    or used["public"] + reservation["public"] > budget["max_public"]
                ):
                    record["stop_reason"] = "project_budget_exhausted"
                    self._write(record)
                    if claim_outcome is not None:
                        claim_outcome["stop_reason"] = "project_budget_exhausted"
                    return None
                if not step["offline"]:
                    from work_observer.workflow.service import reserve_project_upgrade

                    reserve_project_upgrade(self.store, record)
                run = dict(
                    id=uuid4().hex,
                    state="running",
                    created_at=now(),
                    updated_at=now(),
                    input=dict(
                        question=step["question"],
                        job_ids=step["job_ids"],
                        offline=step["offline"],
                        max_calls=step["max_calls"],
                        timeout=step["timeout"],
                        allow_public=step["allow_public"],
                        project_id=identity,
                    ),
                    result=None,
                    saved=None,
                )
                if step.get("review_run_id"):
                    run["input"].update(
                        review_run_id=step["review_run_id"], review_id=step["review_id"]
                    )
                self.store.db.execute(
                    "INSERT INTO research_checkpoints(namespace,id,record) VALUES (?,?,?)",
                    (self.store.namespace, run["id"], json.dumps(run, ensure_ascii=False)),
                )
                step["run_id"] = run["id"]
            else:
                if not step["offline"]:
                    from work_observer.workflow.service import reserve_project_upgrade

                    reserve_project_upgrade(self.store, record)
                run = self.store.get(step["run_id"])
                run.update(state="running", updated_at=now())
                self.store.db.execute(
                    "UPDATE research_checkpoints SET record=? WHERE namespace=? AND id=?",
                    (json.dumps(run, ensure_ascii=False), self.store.namespace, run["id"]),
                )
            step.update(state="running", started_at=now())
            self._write(record)
            return dict(step)

    def finish(self, identity, step_id, *, state, reason=None):
        if state not in {
            "waiting_review",
            "waiting_material",
            "completed",
            "failed",
            "interrupted",
        }:
            raise ProbeError("INVALID_STEP_STATE")
        with self.store.lock, self.store.db:
            record = self.get(identity)
            self._editable(record)
            step = next((s for s in record["steps"] if s["id"] == step_id), None)
            if not step:
                raise ProbeError("STEP_NOT_FOUND")
            if step["state"] != "running":
                raise ProbeError("STEP_NOT_RUNNING")
            step.update(state=state, stop_reason=reason, finished_at=now())
            return self._write(record)

    def review(self, identity, step_id, *, revision, action, note, repository=None):
        if action not in {"accept", "wait", "retry"} or not note.strip() or len(note) > 1000:
            raise ProbeError("INVALID_STEP_REVIEW")
        with self.store.lock, self.store.db:
            record = self.get(identity)
            self._editable(record, revision)
            step = next((s for s in record["steps"] if s["id"] == step_id), None)
            if not step or step["state"] not in {"waiting_review", "waiting_material", "failed"}:
                raise ProbeError("STEP_NOT_REVIEWABLE")
            if step["scope_version"] != record["scope_version"]:
                raise ProbeError("STEP_SCOPE_CHANGED_REPLAN")
            run = self.store.get(step["run_id"]) if step.get("run_id") else {}
            result = run.get("result") or {}
            if action == "accept" and repository is not None:
                if step["id"] in self.rejected_steps(record):
                    raise ProbeError("STEP_QUALITY_REJECTION_REPAIR_REQUIRED")
                from work_observer.reports.results import audit_result

                audit = audit_result(result, repository)
                if any(
                    audit.get(key)
                    for key in (
                        "stale_memory",
                        "stale_knowledge",
                        "stale_dependencies",
                        "changed_sources",
                        "affected_strategy",
                    )
                ):
                    raise ProbeError("STEP_RESULT_STALE_REFRESH")
            if action == "accept" and (
                result.get("status") != "completed" or not result.get("claims")
            ):
                raise ProbeError("STEP_EVIDENCE_REQUIRED")
            if action == "retry" and (
                not step.get("run_id") or not self.store.load_checkpoint(step["run_id"])
            ):
                raise ProbeError("STEP_NEW_ROUND_REQUIRED")
            step.update(
                state={"accept": "completed", "wait": "waiting_material", "retry": "interrupted"}[
                    action
                ],
                review={"note": note.strip(), "at": now(), "action": action},
            )
            return self._write(record)

    def recover(self):
        """进程重启只标中断；不会自行继续调用模型。"""
        for record in self.list(all_records=True):
            with self.store.lock, self.store.db:
                if record["state"] == "invalidated":
                    continue
                changed = False
                for step in record["steps"]:
                    if step["state"] == "running":
                        step.update(state="interrupted", stop_reason="process_interrupted")
                        changed = True
                if changed:
                    self._write(record)

    def invalidate(self, run_ids):
        affected = []
        for record in self.list(all_records=True):
            if record["state"] == "invalidated":
                continue
            if not set(run_ids) & {s.get("run_id") for s in record["steps"]}:
                continue
            with self.store.lock, self.store.db:
                affected.extend(s["run_id"] for s in record["steps"] if s.get("run_id"))
                record.update(
                    state="invalidated",
                    title="相关记忆已忘记",
                    goal="请建立新项目",
                    turns=[],
                    steps=[],
                    scope_history=[],
                    stop_reason="memory_forgotten",
                )
                self._write(record)
        return sorted(set(affected))

    def context(self, identity, step, repository):
        """选择有界、仍有效的既往结论；引用仅是线索，当前轮必须重读原文。"""
        from work_observer.memory.dependencies import DependencyAudit
        from work_observer.memory.service import _tokens
        from work_observer.reports.results import audit_result

        record = self.get(identity)
        self._editable(record)
        allowed = set(step["job_ids"])
        dependencies = dependency_steps(record, step["depends_on"])
        rejected = self.rejected_steps(record)
        excluded = {s["run_id"] for s in record["steps"] if s["id"] in rejected}
        if step.get("review_run_id"):
            excluded.add(step["review_run_id"])
        auditor = DependencyAudit(repository, excluded_runs=excluded)
        candidates = []
        for previous in record["steps"]:
            if previous["id"] == step["id"] or previous["state"] not in {
                "completed",
                "waiting_review",
            }:
                continue
            if previous["scope_version"] != step["scope_version"]:
                continue
            run = self.store.get(previous["run_id"])
            result = run.get("result") or {}
            if excluded and not auditor.run(previous["run_id"])["eligible"]:
                continue
            audit = audit_result(result, repository)
            if (
                audit["stale_memory"]
                or audit.get("stale_knowledge")
                or audit.get("stale_dependencies")
                or audit["changed_sources"]
                or audit["affected_strategy"]
            ):
                continue
            if not {j["id"] for j in result.get("scope", {}).get("jobs", [])} <= allowed:
                continue
            score = len(_tokens(step["question"]) & _tokens(previous["question"]))
            if previous["id"] not in dependencies and not score:
                continue
            candidates.append((previous["id"] in dependencies, score, previous, result))
        candidates.sort(key=lambda value: value[:2], reverse=True)
        context = dict(
            project_id=identity,
            goal=record["goal"],
            scope_version=step["scope_version"],
            completion=step["completion"],
            investigation_kind=step["kind"],
            previous_findings=[],
            memory_dependencies=[],
            knowledge_dependencies=[],
            refresh_note=step.get("refresh_note"),
            selection_note=(
                "仅选择同范围、仍有效的相关研究；omitted_claims是未放入上下文的判断数，"
                "未展示不能当作不存在。"
            ),
        )
        for _, _, previous, result in candidates[:3]:
            query_tokens = _tokens(step["question"])
            ranked = sorted(
                enumerate(result.get("claims", [])),
                key=lambda pair: (
                    -len(query_tokens & _tokens(pair[1]["text"])),
                    pair[1].get("requirement") not in {"required", "preferred"},
                    pair[0],
                ),
            )
            item = dict(
                run_id=previous["run_id"],
                question=previous["question"][:1000],
                review_state=previous["state"],
                research_method_version=result.get("research_method_version", "legacy_unspecified"),
                requirement_policy=result.get(
                    "requirement_policy", "旧结果未记录统一口径，需要重新核对"
                ),
                derived_claims=[],
                gaps=[gap[:300] for gap in result.get("gaps", [])[-3:]],
                total_claims=len(ranked),
                omitted_claims=len(ranked),
            )
            dependencies = [*result.get("memory_used", []), *result.get("context_memory_used", [])]
            saved_dependencies = context["memory_dependencies"][:]
            saved_knowledge = context["knowledge_dependencies"][:]
            context["knowledge_dependencies"] = list(
                {
                    (ref["kind"], ref["id"]): ref
                    for ref in [*saved_knowledge, *result.get("knowledge_used", [])]
                }.values()
            )
            context["memory_dependencies"] = list(
                {
                    m["id"]: {key: m.get(key) for key in ("id", "version", "kind")}
                    for m in [*saved_dependencies, *dependencies]
                }.values()
            )
            context["previous_findings"].append(item)
            if len(json.dumps(context, ensure_ascii=False)) > 14000:
                context["previous_findings"].pop()
                context["memory_dependencies"] = saved_dependencies
                context["knowledge_dependencies"] = saved_knowledge
                continue
            for index, claim in ranked:
                selected = {**claim, "previous_claim_index": index}
                item["derived_claims"].append(selected)
                if len(json.dumps(context, ensure_ascii=False)) > 14000:
                    item["derived_claims"].pop()
                    continue
                item["omitted_claims"] -= 1
            item["derived_claims"].sort(key=lambda claim: claim["previous_claim_index"])
        return context


async def execute_project(
    service,
    identity,
    repository,
    settings,
    *,
    model=None,
    max_steps=3,
    _lock_held=False,
    worker_caps=None,
):
    """领取前持有跨进程研究锁，防止活跃执行被其他入口恢复或重复领取。"""
    from work_observer.storage.locks import exclusive

    if _lock_held:
        return await _execute_project_locked(
            service,
            identity,
            repository,
            settings,
            model=model,
            max_steps=max_steps,
            worker_caps=worker_caps,
        )
    with exclusive(repository.engine.url.database):
        return await _execute_project_locked(
            service,
            identity,
            repository,
            settings,
            model=model,
            max_steps=max_steps,
            worker_caps=worker_caps,
        )


async def _execute_project_locked(
    service, identity, repository, settings, *, model=None, max_steps=3, worker_caps=None
):
    """串行领取并释放步骤；等待资料或人审不占用worker，无子任务自等待。"""
    import asyncio

    from work_observer.collection.service import error_code
    from work_observer.research.agent import research

    if not 1 <= max_steps <= 6:
        raise ProbeError("INVALID_WORKER_BATCH")
    remaining = dict(worker_caps) if worker_caps is not None else None
    reserved = {"calls": 0, "seconds": 0, "public": 0}
    worker_run_ids, worker_stop_reason = [], "step_limit"
    for _ in range(max_steps):
        outcome = {}
        step = service.claim(identity, worker_caps=remaining, claim_outcome=outcome)
        if step is None:
            worker_stop_reason = outcome.get("stop_reason", "no_ready_steps")
            break
        reservation = step_reservation(step)
        for key in reserved:
            reserved[key] += reservation[key]
            if remaining is not None:
                remaining[key] -= reservation[key]
        worker_run_ids.append(step["run_id"])
        run_id = step["run_id"]
        try:
            resume = bool(service.store.load_checkpoint(run_id))
            context = service.context(identity, step, repository)
            result = await research(
                repository,
                step["question"],
                settings,
                job_ids=step["job_ids"],
                offline=step["offline"],
                max_calls=step["max_calls"],
                timeout=step["timeout"],
                allow_public=step["allow_public"],
                model=model,
                project_id=identity,
                conversation_context=context,
                checkpoint=(service.store, run_id),
                resume=resume,
                _lock_held=True,
                **(
                    {key: step[key] for key in ("review_run_id", "review_id")}
                    if step.get("review_run_id")
                    else {}
                ),
            )
            service.store.save(run_id, state="finished", result=result)
            status = result.get("status")
            next_state = (
                "waiting_review"
                if status == "completed"
                else "waiting_material"
                if status in {"evidence_only", "insufficient_evidence"}
                else "failed"
            )
            service.finish(identity, step["id"], state=next_state, reason=result.get("stop_reason"))
            if status == "completed":
                for index, proposal in enumerate(result.get("investigation_proposals", [])[:2]):
                    current = service.get(identity)
                    planned_calls = sum(
                        s["max_calls"] for s in current["steps"] if not s["offline"]
                    )
                    planned_seconds = sum(
                        s["timeout"] for s in current["steps"] if not s["offline"]
                    )
                    calls = min(8, current["budget"]["max_calls"] - planned_calls)
                    seconds = min(120, current["budget"]["max_seconds"] - planned_seconds)
                    if (
                        len(current["steps"]) >= current["budget"]["max_rounds"]
                        or calls < 3
                        or seconds < 30
                    ):
                        break
                    if any(s["question"] == proposal["question"] for s in current["steps"]):
                        continue
                    service.add(
                        identity,
                        proposal["question"],
                        revision=current["revision"],
                        kind=proposal["kind"],
                        max_calls=calls,
                        timeout=seconds,
                        completion=(
                            proposal["completion"] + "；所需证据：" + proposal["evidence_needed"]
                        )[:1000],
                        key=f"{run_id}:proposal:{index}",
                    )
        except asyncio.CancelledError:
            service.store.save(run_id, state="interrupted")
            service.finish(
                identity, step["id"], state="interrupted", reason="user_or_process_interrupted"
            )
            raise
        except Exception as exc:
            code = error_code(exc)
            service.store.save(run_id, state="failed", error_code=code)
            service.finish(identity, step["id"], state="failed", reason=code)
    result = service.get(identity)
    if worker_caps is not None:
        result["worker_batch"] = {
            "reserved": reserved,
            "run_ids": worker_run_ids,
            "stop_reason": worker_stop_reason,
        }
    return result
