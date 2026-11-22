"""持久研究项目：业务会话与有界调查步骤，独立于模型执行检查点。"""

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime
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


def upstream_revision_notices(findings):
    """Flag older descendants of a changed claim without declaring them false."""
    by_run = {step["run_id"]: (index, result) for index, (step, result) in enumerate(findings)}
    corrections = []
    for index, (step, result) in enumerate(findings):
        for revision in result.get("cognition_revisions", []):
            original = by_run.get(revision["previous_run_id"])
            claim_index = revision["previous_claim_index"]
            if (
                revision["decision"] not in {"retain", "revise", "withdraw", "unresolved"}
                or not original
                or original[0] >= index
                or type(claim_index) is not int
                or not 0 <= claim_index < len(original[1].get("claims", []))
                or revision["previous_statement"] != original[1]["claims"][claim_index]["text"]
            ):
                continue
            corrections.append((index, step["run_id"], revision))
    notices = {}
    for index, (step, result) in enumerate(findings):
        ancestors, pending = set(), list(result.get("continued_from", []))
        while pending:
            parent = pending.pop()
            if parent in ancestors or parent not in by_run or by_run[parent][0] >= index:
                continue
            ancestors.add(parent)
            pending.extend(by_run[parent][1].get("continued_from", []))
        history, latest, challenged = [], {}, set()
        for correction_index, run_id, revision in corrections:
            if correction_index <= index or revision["previous_run_id"] not in ancestors:
                continue
            key = (revision["previous_run_id"], revision["previous_claim_index"])
            if revision["decision"] != "retain":
                challenged.add(key)
            if key in challenged:
                entry = (run_id, revision)
                history.append(entry)
                latest[key] = entry
        # Repeated retentions must not crowd out the challenge they rechecked.
        selected = [
            entry
            for entry in history
            if entry[1]["decision"] != "retain"
            or latest[(entry[1]["previous_run_id"], entry[1]["previous_claim_index"])] is entry
        ]
        affected = [
            {
                "run_id": run_id,
                "previous_run_id": revision["previous_run_id"],
                "previous_claim_index": revision["previous_claim_index"],
                "decision": revision["decision"],
                "reason": revision["reason"],
                "aspects": revision.get("aspects", []),
                "comparison_notice": revision.get("comparison_notice"),
            }
            for run_id, revision in selected
        ]
        if affected:
            notices[step["run_id"]] = {
                "items": affected[-3:],
                "omitted": len(history) - len(affected[-3:]),
                "notice": "本轮曾沿用的旧研究后来有修订、撤回或疑问。依赖只记录到研究轮次，"
                "不能据此断定本轮每条判断错误；继续使用前须核对修正及本轮原文。"
                "后续意见未自动改写本轮回答或已采纳知识。"
                + (
                    "也保留后续重新保留原判断的意见，须与早期疑问和原文一并核对，不以记录时间决定真假。"
                    if any(revision["decision"] == "retain" for _, revision in selected)
                    else ""
                ),
            }
    return notices


def step_continuation(project, step, run, checkpoint, audit, *, at=None):
    """Describe an existing checkpoint's remaining limits, without changing them."""
    if step["state"] not in {"failed", "interrupted"}:
        return None
    info = {"available": False, "remaining_calls": 0, "remaining_seconds": 0}
    if run["state"] == "invalidated" or project["state"] != "active":
        return {**info, "reason": "unavailable"}
    if (run.get("result") or {}).get("status") == "completed":
        return {**info, "reason": "answer_completed"}
    if step["scope_version"] != project["scope_version"]:
        return {**info, "reason": "scope_changed"}
    if not checkpoint:
        return {**info, "reason": "no_checkpoint"}
    used = max(
        (checkpoint.get("result") or {}).get("model_calls", 0),
        (run.get("result") or {}).get("model_calls", 0),
    )
    elapsed = checkpoint.get("elapsed", 0)
    if checkpoint.get("pending_since"):
        elapsed += min(
            55,
            max(
                0,
                (
                    datetime.fromisoformat(at or now())
                    - datetime.fromisoformat(checkpoint["pending_since"])
                ).total_seconds(),
            ),
        )
    info.update(
        remaining_calls=max(0, checkpoint["max_calls"] - used),
        remaining_seconds=max(0, int(checkpoint["timeout"] - elapsed)),
    )
    reason = (
        "calls_exhausted"
        if not info["remaining_calls"]
        else "time_exhausted"
        if not info["remaining_seconds"]
        else None
    )
    if not reason and any(
        audit.get(key)
        for key in (
            "stale_memory",
            "stale_knowledge",
            "stale_dependencies",
            "changed_sources",
            "affected_strategy",
        )
    ):
        reason = "material_changed"
    return {**info, "reason": reason, "available": reason is None}


def _map_context(context, item, result, *, focus=None):
    """Extend selected reasoning; a comparison and any missing relations fit as one unit."""
    from work_observer.reports.cognition import checked_map

    if not result.get("work_map"):
        return
    value = checked_map(result)
    keys = ("work_types", "ability_relations", "work_relations", "comparisons", "unknowns")
    selected = {row["previous_claim_index"] for row in item["derived_claims"]}
    output = item.get("work_map") or {
        "version": value["version"],
        "scope_note": value["scope_note"],
        "note": (
            "这是原研究的分析结构，不是独立证据或已确认事实。previous_index是原地图下标，"
            "claim_indices仍指原判断下标，relation_indices仍指原关系下标；不可按展示位置重编号。"
            "先结合判断的followup_decisions核实后续修正，再读本轮原文。未展示不表示不存在。"
        ),
        "omitted": {key: len(value.get(key, [])) for key in keys},
        **{key: [] for key in keys},
    }
    omitted = item.pop("work_map_omitted", None)
    item["work_map"] = output
    if len(json.dumps(context, ensure_ascii=False)) > 14000:
        item.pop("work_map")
        if omitted is not None:
            item["work_map_omitted"] = omitted
        return
    targets = (
        [focus]
        if focus
        else [(key, index) for key in keys for index in range(len(value.get(key, [])))]
    )
    for key, index in targets:
        row = value[key][index]
        unit = (
            [("work_relations", i) for i in row["relation_indices"]] + [(key, index)]
            if key == "comparisons"
            else [(key, index)]
        )
        if any(
            kind != "unknowns" and not set(value[kind][i]["claim_indices"]) <= selected
            for kind, i in unit
        ):
            continue
        added = []
        for kind, i in unit:
            if any(existing["previous_index"] == i for existing in output[kind]):
                continue
            row = value[kind][i]
            bound = (
                {"previous_index": i, "text": row}
                if kind == "unknowns"
                else {
                    **row,
                    "previous_index": i,
                }
            )
            if kind == "work_relations" and row.get("source_claim_index") is not None:
                # Canonical node text/category already live in the selected claims.
                for field in ("source_text", "target_text", "source_kind", "target_kind"):
                    bound.pop(field)
            output[kind].append(bound)
            output["omitted"][kind] -= 1
            added.append(kind)
        if len(json.dumps(context, ensure_ascii=False)) > 14000:
            for kind in reversed(added):
                output[kind].pop()
                output["omitted"][kind] += 1
    for key in keys:
        output[key].sort(key=lambda row: row["previous_index"])
    return focus is None or any(row["previous_index"] == focus[1] for row in output[focus[0]])


def _prior_claim_context(context, item, result, ranked, followups, query):
    """Pack relevant reasoning and all its claims before filling remaining context space."""
    from work_observer.research.relevance import ranked_map_rows

    prepared = {}
    for index, claim in ranked:
        selected = {**claim, "previous_claim_index": index}
        if decisions := followups.get((item["run_id"], index)):
            selected["followup_decisions"] = decisions[-3:]
            selected["reuse_status"] = "has_provisional_followup"
        prepared[index] = selected
    for key, index, indices in ranked_map_rows(result, query):
        saved = deepcopy(item)
        present = {row["previous_claim_index"] for row in item["derived_claims"]}
        item["derived_claims"].extend(
            prepared[i] for i in dict.fromkeys(indices) if i not in present
        )
        item["omitted_claims"] = len(prepared) - len(item["derived_claims"])
        if not _map_context(context, item, result, focus=(key, index)):
            item.clear()
            item.update(saved)
    for index, _ in ranked:
        if any(row["previous_claim_index"] == index for row in item["derived_claims"]):
            continue
        item["derived_claims"].append(prepared[index])
        if len(json.dumps(context, ensure_ascii=False)) > 14000:
            item["derived_claims"].pop()
            continue
        item["omitted_claims"] -= 1
    item["derived_claims"].sort(key=lambda claim: claim["previous_claim_index"])
    _map_context(context, item, result)


def historical_document_scope(repository, identities, selected):
    """An explicit reply may compare a retained version of the same selected source."""
    if selected is None or identities <= set(selected):
        return True
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from work_observer.connectors.public_models import PublicDocument

    with Session(repository.engine) as session:
        documents = dict(
            session.execute(
                select(PublicDocument.id, PublicDocument.url).where(
                    PublicDocument.id.in_(identities | set(selected))
                )
            ).all()
        )
    selected_urls = {documents[key] for key in selected if key in documents}
    return all(key in documents and documents[key] in selected_urls for key in identities)


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
        public_document_ids=None,
    ):
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 150
            or not isinstance(goal, str)
            or not goal.strip()
            or len(goal) > 4000
            or not isinstance(job_ids, list)
            or len(set(job_ids)) > 20
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
        from work_observer.research.document_scope import normalize

        public_document_ids = normalize(public_document_ids)
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
                    **(
                        {"public_document_ids": public_document_ids}
                        if public_document_ids is not None
                        else {}
                    ),
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
            **(
                {"public_document_ids": public_document_ids}
                if public_document_ids is not None
                else {}
            ),
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
            update = re.fullmatch(
                r"domain-update:([a-f0-9]{32})(?::(?:common-cohort|both-panels))?",
                source_key or "",
            )
            if update:
                exists = self.store.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='domain_update_reports'"
                ).fetchone()
                source = (
                    self.store.db.execute(
                        "SELECT record FROM domain_update_reports WHERE namespace=? AND id=?",
                        (self.store.namespace, update[1]),
                    ).fetchone()
                    if exists
                    else None
                )
                if not source:
                    raise ProbeError("UPDATE_RECORD_NOT_FOUND")
                if json.loads(source[0]).get("state") == "invalidated":
                    raise ProbeError("UPDATE_MEMORY_FORGOTTEN")
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

    def rename(self, identity, *, revision, title):
        if not isinstance(title, str) or not title.strip() or len(title) > 150:
            raise ProbeError("INVALID_PROJECT")
        with self.store.lock, self.store.db:
            record = self.get(identity)
            self._editable(record, revision)
            if record["title"] == title.strip():
                return record
            record["title"] = title.strip()
            return self._write(record)

    def revise(self, identity, *, revision, goal, job_ids, public_document_ids=...):
        from work_observer.research.document_scope import normalize

        if public_document_ids is not ...:
            public_document_ids = normalize(public_document_ids)
        with self.store.lock, self.store.db:
            record = self.get(identity)
            self._editable(record, revision)
            if not goal.strip() or len(goal) > 4000 or len(set(job_ids)) > 20:
                raise ProbeError("INVALID_PROJECT")
            if any(step["state"] == "running" for step in record["steps"]):
                raise ProbeError("PROJECT_RUNNING")
            record["scope_history"].append(
                {
                    "version": record["scope_version"],
                    "goal": record["goal"],
                    "job_ids": record["job_ids"],
                    "public_document_ids": record.get("public_document_ids"),
                    "ended_at": now(),
                }
            )
            if public_document_ids is not ...:
                record["public_document_ids"] = public_document_ids
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
        approach="standard",
        coverage_mode="all",
        reply_to_step_id=None,
        origin="user",
        evidence_needed=None,
    ):
        if (
            not question.strip()
            or len(question) > 4000
            or not completion.strip()
            or len(completion) > 1000
            or kind not in {"investigate", "counterexample", "synthesis"}
            or not 1 <= max_calls <= 12
            or not 1 <= timeout <= 300
            or approach not in {"standard", "work_map"}
            or coverage_mode not in {"all", "question"}
            or origin not in {"user", "agent"}
            or evidence_needed is not None
            and (
                not isinstance(evidence_needed, str)
                or not evidence_needed.strip()
                or len(evidence_needed) > 600
            )
        ):
            raise ProbeError("INVALID_INVESTIGATION_STEP")
        with self.store.lock, self.store.db:
            record = self.get(identity)
            self._editable(record, revision)
            if key:
                existing = next((s for s in record["steps"] if s.get("key") == key), None)
                if existing:
                    return record
            if not record.get("career") and len(record["steps"]) >= record["budget"]["max_rounds"]:
                raise ProbeError("PROJECT_ROUND_LIMIT")
            if reply_to_step_id is not None:
                reply = next((s for s in record["steps"] if s["id"] == reply_to_step_id), None)
                if reply is None:
                    raise ProbeError("INVALID_STEP_REPLY")
                if reply["state"] in {"queued", "running", "interrupted"}:
                    raise ProbeError("STEP_REPLY_NOT_READY")
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
                    origin=origin,
                    kind=kind,
                    completion=completion.strip(),
                    **({"evidence_needed": evidence_needed.strip()} if evidence_needed else {}),
                    depends_on=parents,
                    state="queued",
                    scope_version=record["scope_version"],
                    job_ids=record["job_ids"][:],
                    **(
                        {"public_document_ids": record["public_document_ids"]}
                        if record.get("public_document_ids") is not None
                        else {}
                    ),
                    offline=offline,
                    allow_public=allow_public,
                    max_calls=max_calls,
                    timeout=timeout,
                    approach=approach,
                    coverage_mode=coverage_mode,
                    reply_to_step_id=reply_to_step_id,
                    run_id=None,
                    created_at=now(),
                    stop_reason=None,
                )
            )
            record["turns"].append(
                dict(
                    id=step_id,
                    role="assistant" if origin == "agent" else "user",
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
            repository,
            original["question"],
            job_ids=original["job_ids"],
            project_id=identity,
            public_document_ids=original.get("public_document_ids"),
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
                "origin": "user",
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
                (
                    r
                    for r in quality.list_run(step["run_id"])
                    if not r["stale_result"] and r.get("decision") in {"approve", "reject"}
                ),
                None,
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
            # Finished coaching releases unused headroom; resumable work keeps its reservation.
            settled = (
                record.get("career")
                and run["state"] == "finished"
                and (
                    result.get("status") in {"completed", "evidence_only", "insufficient_evidence"}
                    or step["state"] == "abandoned"
                )
            )
            if not step["offline"]:
                used["reserved_calls"] += (
                    result.get("model_calls", 0) if settled else step["max_calls"]
                )
                used["reserved_seconds"] += (
                    result.get("elapsed_seconds", 0) if settled else step["timeout"]
                )
        return used

    def claim(self, identity, *, worker_caps=None, claim_outcome=None, preferred_step_id=None):
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
            if preferred_step_id is not None:
                ready = [step for step in ready if step["id"] == preferred_step_id]
                if not ready:
                    raise ProbeError("STEP_NOT_READY")
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
                        **(
                            {"public_document_ids": step["public_document_ids"]}
                            if step.get("public_document_ids") is not None
                            else {}
                        ),
                        offline=step["offline"],
                        max_calls=step["max_calls"],
                        timeout=step["timeout"],
                        allow_public=step["allow_public"],
                        project_id=identity,
                        approach=step.get("approach", "standard"),
                        coverage_mode=step.get("coverage_mode", "all"),
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
        from work_observer.research.relevance import finding_score, ranked_claims

        record = self.get(identity)
        self._editable(record)
        query_tokens = _tokens(step["question"])
        allowed = set(step["job_ids"])
        dependencies = dependency_steps(record, step["depends_on"])
        reply_id = step.get("reply_to_step_id")
        reply_run = next((s.get("run_id") for s in record["steps"] if s["id"] == reply_id), None)
        rejected = self.rejected_steps(record)
        excluded = {s["run_id"] for s in record["steps"] if s["id"] in rejected}
        if step.get("review_run_id"):
            excluded.add(step["review_run_id"])
        auditor = DependencyAudit(repository, excluded_runs=excluded)
        candidates, eligible, audits, past_followups = [], [], {}, []
        historical_reply = None
        for previous in record["steps"]:
            if (
                not previous.get("run_id")
                or previous["id"] == step["id"]
                or previous["state"]
                not in {
                    "completed",
                    "waiting_review",
                }
            ):
                continue
            is_reply = previous["id"] == reply_id
            run = self.store.get(previous["run_id"])
            result = run.get("result") or {}
            corrects_reply = reply_run and any(
                row["previous_run_id"] == reply_run for row in result.get("cognition_revisions", [])
            )
            scope_changed = previous["scope_version"] != step["scope_version"]
            if scope_changed and not (is_reply or corrects_reply):
                continue
            rejected_reply = (
                is_reply and previous["id"] in rejected and not step.get("review_run_id")
            )
            if previous["run_id"] in excluded and not rejected_reply:
                continue
            if excluded and any(
                issue["reason"] != "source_changed" for issue in auditor.result(result)["issues"]
            ):
                continue
            audit = audit_result(result, repository)
            audits[previous["run_id"]] = audit
            evidence_ids = {ev["id"] for ev in result.get("evidence", [])}
            if (
                is_reply
                and (
                    rejected_reply
                    or scope_changed
                    or audit["changed_sources"]
                    or any(
                        issue["reason"] == "source_changed" and issue["id"] in evidence_ids
                        for issue in audit.get("dependency_issues", [])
                    )
                )
                and all(
                    change["reason"] == "job_current_version_changed"
                    and change["retained_evidence_valid"]
                    for change in audit["changed_sources"]
                )
                and not audit["stale_memory"]
                and not audit.get("stale_knowledge")
                and not audit["affected_strategy"]
                and all(
                    issue["reason"] == "source_changed"
                    for issue in audit.get("dependency_issues", [])
                )
                and {j["id"] for j in result.get("scope", {}).get("jobs", [])} <= allowed
                and historical_document_scope(
                    repository,
                    {
                        ev["public_document_id"]
                        for ev in result.get("evidence", [])
                        if ev.get("public_document_id")
                    },
                    step.get("public_document_ids"),
                )
            ):
                historical_reply = previous, result
            if (
                previous["id"] in rejected
                or audit["stale_memory"]
                or audit.get("stale_knowledge")
                or audit.get("stale_dependencies")
                or audit["changed_sources"]
                or audit["affected_strategy"]
            ):
                continue
            if not {j["id"] for j in result.get("scope", {}).get("jobs", [])} <= allowed:
                continue
            selected_documents = step.get("public_document_ids")
            if selected_documents is not None and not {
                ev["public_document_id"]
                for ev in result.get("evidence", [])
                if ev.get("public_document_id")
            } <= set(selected_documents):
                continue
            if scope_changed:
                if corrects_reply:
                    past_followups.append((previous, result))
                continue
            eligible.append((previous, result))
            score = finding_score(query_tokens, previous["question"], result)
            if not is_reply and previous["id"] not in dependencies and not score:
                continue
            candidates.append(
                (2 if is_reply else int(previous["id"] in dependencies), score, previous, result)
            )
        selected_runs = {previous["run_id"] for _, _, previous, _ in candidates}
        if historical_reply:
            selected_runs.add(historical_reply[0]["run_id"])
        related = [
            (previous, result)
            for previous, result in eligible
            if any(
                row["previous_run_id"] in selected_runs
                for row in result.get("cognition_revisions", [])
            )
        ][-2:]
        for order, (previous, result) in enumerate(related):
            candidates = [row for row in candidates if row[2]["id"] != previous["id"]]
            candidates.append((3, order, previous, result))
        candidates.sort(key=lambda value: value[:2], reverse=True)
        followups = {}
        step_order = {row["id"]: index for index, row in enumerate(record["steps"])}
        followup_sources = sorted(
            [*eligible, *past_followups], key=lambda pair: step_order[pair[0]["id"]]
        )
        eligible_runs = {previous["run_id"] for previous, _ in followup_sources}
        if historical_reply:
            eligible_runs.add(historical_reply[0]["run_id"])
        for previous, result in followup_sources:
            for revision in result.get("cognition_revisions", []):
                if revision["previous_run_id"] not in eligible_runs:
                    continue
                key = (revision["previous_run_id"], revision["previous_claim_index"])
                followups.setdefault(key, []).append(
                    {
                        "run_id": previous["run_id"],
                        "decision": revision["decision"],
                        "new_claim_indices": revision["new_claim_indices"],
                        "reason": revision["reason"],
                        "aspects": revision.get("aspects", []),
                        "comparison_notice": revision.get("comparison_notice"),
                        "review_state": previous["state"],
                        "source_scope_version": previous["scope_version"],
                        "historical_scope": previous["scope_version"] != step["scope_version"],
                    }
                )
        context = dict(
            project_id=identity,
            goal=record["goal"],
            scope_version=step["scope_version"],
            completion=step["completion"],
            **({"evidence_needed": step["evidence_needed"]} if step.get("evidence_needed") else {}),
            investigation_kind=step["kind"],
            investigation_origin=step.get("origin", "unspecified"),
            previous_findings=[],
            excluded_prior_findings=[
                {"run_id": s["run_id"], "reason": "quality_rejected"}
                for s in record["steps"]
                if s["id"] in rejected and s.get("run_id")
            ][:10],
            context_version="project-context-v2",
            memory_dependencies=[],
            knowledge_dependencies=[],
            refresh_note=step.get("refresh_note"),
            selection_note=(
                "按旧问题、原判断及地图关系/边界定位同范围、仍有效的相关研究；"
                "优先带入本题相关关系/比较及其完整原判断，其他内容按剩余额度选择。"
                "文字相关不证明结论成立。omitted_claims是未放入上下文的判断数，"
                "work_map_omitted表示整份地图未带入时各类省略数；未展示不能当作不存在。"
                "origin为agent的问题由Agent提出，不是用户新增偏好或知识采纳。"
                "范围变化的明确追问只带旧判断作重读对照，不作为当前有效前提。"
            ),
        )
        if reply_id:
            reply = next(s for s in record["steps"] if s["id"] == reply_id)
            context["reply_to"] = {
                "step_id": reply_id,
                "run_id": reply.get("run_id"),
                "question": reply["question"][:1000],
                "question_origin": reply.get("origin", "unspecified"),
                "review_state": reply["state"],
                "source_scope_version": reply["scope_version"],
                "findings_included": False,
            }
            context["context_version"] = "project-context-v3-replies"
            context["selection_note"] += (
                "reply_to明确本次追问对象，不表示认可旧回答；findings_included=false时，"
                "旧结论因未完成、被拒绝、来源/范围变化或上下文限制未复用，须从现有原文重新调查。"
            )
        if historical_reply:
            previous, result = historical_reply
            historical = dict(
                run_id=previous["run_id"],
                question=previous["question"][:1000],
                question_origin=previous.get("origin", "unspecified"),
                review_state=previous["state"],
                reason=(
                    "project_scope_changed"
                    if previous["scope_version"] != step["scope_version"]
                    else "source_version_changed"
                ),
                source_scope_version=previous["scope_version"],
                current_scope_version=step["scope_version"],
                derived_claims=[],
                total_claims=len(result.get("claims", [])),
                omitted_claims=len(result.get("claims", [])),
                read_evidence_ids=[e["id"] for e in result.get("evidence", [])],
                note=(
                    "仅供明确追问对照的旧判断，原文版本已变化，不是当前事实或新证据。"
                    "必须读取本轮原文后才可用revisions说明保留、修订、撤回或未知；"
                    "不能由新旧认识不同推定外部工作实际变化。"
                ),
            )
            if historical["reason"] == "project_scope_changed":
                historical["note"] = (
                    "旧判断所在的资料范围或研究目标已调整，只供本次明确追问定位，"
                    "不能代表新范围的结论或当前事实；也不能直接外推到新加入的资料。"
                    "须重读本轮来源，核对旧判断及其followup_decisions后说明保留、修订或未知；"
                    "范围调整不等于外部工作发生变化。"
                )
            if previous["id"] in rejected:
                from work_observer.quality.reviews import QualityReviewService

                review = next(
                    row
                    for row in QualityReviewService(self.store).list_run(previous["run_id"])
                    if not row["stale_result"] and row.get("decision") == "reject"
                )
                historical["reason"] = "quality_rejected"
                historical["review_diagnostic"] = {
                    key: review[key] for key in ("id", "status", "reviewer_kind")
                }
                historical["review_diagnostic"].update(
                    note=review["note"][:1200],
                    note_truncated=len(review["note"]) > 1200,
                )
                historical["note"] = (
                    "旧判断已被核对拒绝，仅供本次明确追问定位，不能作为当前事实或已接受结论。"
                    "核对意见是待核实诊断，不是新的来源证据；须读取本轮原文后再说明修订。"
                    "仅重读原文时trigger用recheck；依据此拒绝诊断修正可用review，"
                    "不表示已绑定专门复核补查或人审通过。"
                )
            context["historical_reply"] = historical
            ranked = ranked_claims(result, query_tokens)
            for index, claim in ranked:
                selected = {**claim, "previous_claim_index": index}
                if decisions := followups.get((previous["run_id"], index)):
                    selected["followup_decisions"] = decisions[-3:]
                historical["derived_claims"].append(selected)
                if len(json.dumps(context, ensure_ascii=False)) > 6000:
                    historical["derived_claims"].pop()
                    continue
                historical["omitted_claims"] -= 1
            if historical["derived_claims"]:
                context["reply_to"]["historical_findings_included"] = True
                context["memory_dependencies"] = [
                    {key: ref.get(key) for key in ("id", "version", "kind")}
                    for ref in [
                        *result.get("memory_used", []),
                        *result.get("context_memory_used", []),
                    ]
                ]
                context["knowledge_dependencies"] = result.get("knowledge_used", [])[:]
                if len(json.dumps(context, ensure_ascii=False)) > 14000:
                    context.pop("historical_reply")
                    context["reply_to"]["historical_findings_included"] = False
                    context["memory_dependencies"] = []
                    context["knowledge_dependencies"] = []
            else:
                context.pop("historical_reply")
        upstream_notices = upstream_revision_notices(eligible)
        for _, _, previous, result in candidates[:3]:
            ranked = ranked_claims(result, query_tokens)
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
                read_evidence_ids=[e["id"] for e in result.get("evidence", [])],
                coverage_mode=result.get("coverage_mode", "all"),
            )
            if notice := upstream_notices.get(previous["run_id"]):
                item["upstream_revision_notices"] = notice
            if historical_sources := audits[previous["run_id"]].get("historical_sources"):
                item["historical_source_note"] = (
                    "这轮判断采用明确截止时已入库的历史正文，可用于时点对照；"
                    "不是当前岗位事实，不能因仍可回查就当成最新要求。"
                )
                item["historical_source_cutoffs"] = sorted(
                    {cutoff for evidence in historical_sources for cutoff in evidence["cutoffs"]}
                )
            if result.get("work_map"):
                item["work_map_omitted"] = {
                    key: len(result["work_map"].get(key, []))
                    for key in (
                        "work_types",
                        "ability_relations",
                        "work_relations",
                        "comparisons",
                        "unknowns",
                    )
                }
            if previous["id"] == reply_id and result.get("application_plan"):
                item["application_plan"] = result["application_plan"]
                item["application_plan_note"] = (
                    "这是原研究的建议，不是已执行事实或能力证明；实际回报须读本轮归档原文。"
                )
                if (
                    len(json.dumps(context, ensure_ascii=False))
                    + len(json.dumps(item, ensure_ascii=False))
                    > 14000
                ):
                    item.pop("application_plan")
                    item["application_plan_note"] = "原建议超出本轮上下文限额，未带入，不能补造。"
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
            _prior_claim_context(context, item, result, ranked, followups, query_tokens)
            if previous["id"] == reply_id:
                context["reply_to"]["findings_included"] = True
                if result.get("application_plan"):
                    context["reply_to"]["application_plan_included"] = "application_plan" in item
        if career := record.get("career"):
            if step.get("career_action"):
                context["career_action"] = step["career_action"]
                # Coaching starts from current sources and the user's own records.
                # It does not require a formal revision of earlier research sentences.
                context["previous_findings"] = []
                context["memory_dependencies"] = []
                context["knowledge_dependencies"] = []
                context.pop("historical_reply", None)
                if context.get("reply_to"):
                    context["reply_to"]["findings_included"] = False
                context["selection_note"] = (
                    "本轮从当前岗位原文及用户自述重新分析，旧研究句子不作为既定事实，"
                    "不要求生成逐句修订记录。经历、实验预期与实际观察见career_evidence；"
                    "如需面试反馈，本轮问题已明确包含用户回答的那道面试问题。"
                )
            stories = career.get("stories", [])
            observations = [row for row in career.get("tasks", []) if row.get("outcome")]
            if selected_task := step.get("career_task_id"):
                observations = [row for row in career["tasks"] if row["id"] == selected_task]
            selected_story = next(
                (row for row in stories if row["id"] == step.get("career_story_id")), None
            )
            if selected_story:
                stories = [selected_story]
            compared_steps = set(step.get("career_comparison_steps", []))
            comparing_answers = bool(compared_steps) and all(
                entry["kind"] == "answer" for entry in career["runs"]
                if entry["step_id"] in compared_steps
            )
            if (
                step.get("career_action") in {"interview", "answer", "followup"}
                or comparing_answers
            ):
                if selected_story:
                    observations = []
                elif selected_task:
                    stories = []
            notes = career.get("insights", [])
            from work_observer.research.learning import (
                experiment_answer_origin,
                experiment_claim_origin,
                experiment_template_origin,
                learning_record,
                recall_learning_notes,
            )

            active_notes, learning_recall = recall_learning_notes(career, step, record["goal"])
            selected_note = next(
                (row for row in notes if row["id"] == step.get("career_insight_id")), None
            )
            counter_note = next(
                (row for row in notes if row["id"] == step.get("career_counter_insight_id")), None
            )

            def experiment_record(row, full=False):
                return {
                    "id": row["id"],
                    "title": row["title"],
                    "task_or_ability": row["task_or_ability"],
                    "planned_deliverable": row["deliverable"],
                    "proposed_check": row["completion_check"],
                    "origin": row.get("origin", "research"),
                    "purpose": row.get("purpose"),
                    "reused_from_goal": (row.get("reused_from") or {}).get("project_title"),
                    "state": row["state"],
                    "reported_observation": row["outcome"] if full else row["outcome"][:500],
                    "prior_expectation": row.get("hypothesis", "")
                    if full
                    else row.get("hypothesis", "")[:400],
                    "previous_task_id": row.get("previous_task_id"),
                    "source_step_id": row.get("source_step_id"),
                    "answer_to_verify": experiment_answer_origin(career, row) if full else None,
                    "claim_to_verify": experiment_claim_origin(record, row, self.store)
                    if full else None,
                    "template_origin": experiment_template_origin(record, row, self.store)
                    if full else None,
                    "design_change": row.get("design_change", ""),
                    "comparison_conditions": row.get("comparison_conditions", "") if full else "",
                    "comparison_rows": deepcopy(row.get("comparison_rows", [])) if full else [],
                    "comparison_row_count": len(row.get("comparison_rows", [])),
                    "artifact": row["artifact"][:200],
                    "artifact_document": {
                        "document_id": row["artifact_document_id"],
                        "title": row["artifact_title"],
                        "notice": "用户提供的练习产物或运行记录，"
                        "未独立执行验证；可读取归档全文。",
                    }
                    if row.get("artifact_document_id")
                    else None,
                }

            selected_experiment = next(
                (row for row in career["tasks"] if row["id"] == selected_task), None
            )
            previous_experiment = next(
                (
                    row
                    for row in career["tasks"]
                    if row["id"] == (selected_experiment or {}).get("previous_task_id")
                ),
                None,
            )

            def learning_note(row):
                return learning_record(row, record, self.store)

            selected_inquiry = next(
                (
                    dict(row)
                    for row in career.get("questions", [])
                    if row["id"] == step.get("career_question_id")
                ),
                None,
            )
            if selected_inquiry:
                selected_ids = step.get("career_passage_ids", [])
                if selected_ids:
                    passages = {row["id"]: row for row in
                                selected_inquiry.get("evidence_passages", [])}
                    selected = [deepcopy(passages[key]) for key in selected_ids if key in passages]
                    selected_inquiry.update(
                        selected_passage_ids=selected_ids[:], selected_passages=selected,
                        missing_selected_passage_ids=[key for key in selected_ids
                                                      if key not in passages],
                        other_evidence_passage_count=len(passages) - len(selected),
                        evidence_passages=selected,
                    )
                origin_note = next(
                    (row for row in career.get("insights", [])
                     if row["id"] == selected_inquiry.get("source_insight_id")), None
                )
                if origin_note:
                    selected_inquiry["origin_learning_note"] = learning_note(origin_note)
                parent = next(
                    (row for row in career.get("questions", [])
                     if row["id"] == selected_inquiry.get("parent_question_id")), None
                )
                selected_inquiry["parent_inquiry"] = {
                    key: parent.get(key) for key in (
                        "id", "question", "why_matters", "state", "conclusion", "next_evidence",
                        "hypothesis_a", "hypothesis_b", "source_step_id", "conclusion_step_id",
                        "source_passage", "evidence_passages", "selected_job_ids",
                    )
                } if parent else None
                entry = next((row for row in career.get("runs", [])
                              if row["step_id"] == step["id"]), {})
                followup_entry = next((row for row in career.get("runs", [])
                                       if row["step_id"] == entry.get("source_step_id")), {})
                followup_question = next((row for row in career.get("questions", [])
                                          if row["id"] == followup_entry.get("question_id")
                                          and row.get("parent_question_id")
                                          == selected_inquiry["id"]), None)
                if followup_question:
                    followup_step = next(row for row in record["steps"]
                                         if row["id"] == followup_entry["step_id"])
                    followup_run = (self.store.get(followup_step["run_id"])
                                    if followup_step.get("run_id") else None) or {}
                    followup_result = followup_run.get("result") or {}
                    if (followup_result.get("status") == "completed"
                            and followup_run.get("state") != "invalidated"):
                        selected_inquiry["followup_to_recheck"] = {
                            "question_id": followup_question["id"],
                            "question": followup_question["question"],
                            "user_conclusion": followup_question.get("conclusion", ""),
                            "step_id": followup_step["id"],
                            "asked_then": followup_entry.get("user_question"),
                            "selected_job_ids": followup_entry.get("selected_job_ids", []),
                            "source_cutoff": followup_result.get("created_at"),
                            "claim_details_to_recheck": [
                                {key: claim.get(key) for key in (
                                    "text", "category", "basis", "requirement",
                                )} for claim in followup_result.get("claims", [])
                            ],
                            "unresolved_then": followup_result.get("gaps", []),
                            "source_references_to_reread": [
                                {key: source.get(key) for key in (
                                    "title", "evidence_kind", "job_id", "public_document_id",
                                    "document_id", "snapshot_id", "historical_cutoffs",
                                    "start", "end",
                                )} for source in followup_result.get("evidence", [])
                            ],
                        }
                origin_step = next(
                    (row for row in record["steps"]
                     if row["id"] == selected_inquiry.get("source_step_id")), None
                )
                origin_run = (
                    self.store.get(origin_step["run_id"])
                    if origin_step and origin_step.get("run_id") else None
                )
                origin_result = (origin_run or {}).get("result") or {}
                selected_inquiry["origin_discussion"] = {
                    "step_id": origin_step["id"],
                    "question": origin_step["question"],
                    "source_cutoff": origin_result.get("created_at"),
                    "same_job_scope": origin_step["scope_version"] == record["scope_version"],
                    "work_map": origin_result.get("work_map"),
                    "claim_details_to_recheck": [
                        {key: claim.get(key) for key in (
                            "text", "category", "basis", "requirement",
                        )}
                        for claim in origin_result.get("claims", [])
                    ],
                    "unresolved_then": origin_result.get("gaps", []),
                    "source_references_to_reread": [
                        {key: source.get(key) for key in (
                            "title", "evidence_kind", "job_id", "public_document_id",
                            "document_id", "snapshot_id", "historical_cutoffs", "start", "end",
                        )}
                        for source in origin_result.get("evidence", [])
                    ],
                } if origin_result.get("status") == "completed" and (
                    origin_run["state"] != "invalidated"
                ) else None
                selected_inquiry["origin_notice"] = (
                    "origin_discussion是问题形成时的原分析和完整工作地图，仅供定位，不是新证据。"
                    "若问题提到某一条关系，按原地图中的顺序回查其完整两端、理由与迁移限制。"
                    "设计验证时针对其中尚未验证的解释；先读取本轮可用原文，"
                    "资料不可读时明确保留未知，不把旧解释或旧引用编号当作本轮事实。"
                )
                linked_experiments = [
                    row
                    for row in career.get("tasks", [])
                    if row.get("question_id") == selected_inquiry["id"]
                ]
                selected_inquiry["linked_experiment_count"] = len(linked_experiments)
                selected_inquiry["linked_experiments"] = [
                    {
                        key: row.get(key)
                        for key in (
                            "id",
                            "title",
                            "state",
                            "hypothesis",
                            "deliverable",
                            "completion_check",
                            "outcome",
                            "artifact_document_id",
                            "previous_task_id",
                            "design_change",
                        )
                    }
                    for row in linked_experiments[-3:]
                ]
                selected_inquiry["experiment_notice"] = (
                    "列出最近三项相关练习，先参考已有计划与实际观察，避免重复安排。"
                    "planned只是计划，done只表示用户记录了结果；这些都不是独立评测。"
                    "指定练习的完整观察及作品读取位置另见career_evidence.experiments。"
                )
                earlier = []
                comparison_steps = step.get("career_comparison_steps", [])
                for entry in career["runs"]:
                    if (
                        entry.get("question_id") != selected_inquiry["id"]
                        or entry["step_id"] == step["id"]
                        or (comparison_steps and entry["step_id"] not in comparison_steps)
                    ):
                        continue
                    previous_step = next(
                        (item for item in record["steps"] if item["id"] == entry["step_id"]), None
                    )
                    previous_run = (
                        self.store.get(previous_step["run_id"])
                        if previous_step and previous_step.get("run_id")
                        else None
                    )
                    result = (previous_run or {}).get("result") or {}
                    if (
                        result.get("status") != "completed"
                        or previous_run["state"] == "invalidated"
                    ):
                        continue
                    earlier.append(
                        {
                            "step_id": entry["step_id"],
                            "question": entry.get("user_question"),
                            "recorded_at": entry["created_at"],
                            "source_cutoff": result.get("created_at"),
                            "claims_to_recheck": [
                                claim["text"] for claim in result.get("claims", [])
                            ],
                            "claim_details_to_recheck": [
                                {
                                    key: claim.get(key)
                                    for key in ("text", "category", "basis", "requirement")
                                }
                                for claim in result.get("claims", [])
                            ]
                            if comparison_steps
                            else [],
                            "unresolved_then": result.get("gaps", []),
                            "same_job_scope": previous_step["scope_version"]
                            == record["scope_version"],
                            "work_map": result.get("work_map") if comparison_steps else None,
                            "source_references_to_reread": [
                                {
                                    key: source.get(key)
                                    for key in (
                                        "title",
                                        "evidence_kind",
                                        "job_id",
                                        "public_document_id",
                                        "document_id",
                                        "snapshot_id",
                                        "historical_cutoffs",
                                        "start",
                                        "end",
                                    )
                                }
                                for source in result.get("evidence", [])
                            ],
                        }
                    )
                selected_inquiry["earlier_discussions"] = (
                    sorted(earlier, key=lambda item: comparison_steps.index(item["step_id"]))
                    if comparison_steps
                    else earlier[-2:]
                )
                selected_inquiry["comparison_requested"] = bool(comparison_steps)
                selected_inquiry["history_notice"] = (
                    "先前分析只供对照问题如何推进，不是新证据。"
                    "须重读本轮可用原文；指出新材料改变或未能改变哪些判断，不能直接沿用旧结论。"
                    "source_cutoff是当时研究的来源截止，不是网站发布时间。"
                    "回读旧JD可用read_historical_job；原引用有historical_cutoffs时按其时点读取，"
                    "否则使用该讨论的source_cutoff。当前JD使用read_job。两侧原文分别引用，"
                    "不能仅因回答措辞变化就说岗位发生了变化。"
                )

            selected_answers = []
            for step_id in step.get("career_comparison_steps", []):
                entry = next(row for row in career["runs"] if row["step_id"] == step_id)
                if entry["kind"] != "answer":
                    continue
                old_step = next(row for row in record["steps"] if row["id"] == step_id)
                old_result = (self.store.get(old_step["run_id"]) or {}).get("result") or {}
                selected_answers.append({
                    "step_id": step_id,
                    "interview_question": entry.get("interview_question"),
                    "user_answer": entry.get("answer"),
                    "answer_document_id": entry.get("answer_document_id"),
                    "recorded_at": entry["created_at"],
                    "understanding_check": bool(entry.get("understanding_check")),
                    "same_job_scope": old_step["scope_version"] == record["scope_version"],
                    "claim_details_to_recheck": [
                        {key: claim.get(key) for key in (
                            "text", "category", "basis", "requirement",
                        )}
                        for claim in old_result.get("claims", [])
                    ],
                    "unresolved_then": old_result.get("gaps", []),
                    "source_references_to_reread": [
                        {key: source.get(key) for key in (
                            "title", "evidence_kind", "job_id", "public_document_id",
                            "document_id", "snapshot_id", "historical_cutoffs", "start", "end",
                        )}
                        for source in old_result.get("evidence", [])
                    ],
                })
            selected_maps = []
            if not selected_inquiry:
                for step_id in step.get("career_comparison_steps", []):
                    old_step = next(row for row in record["steps"] if row["id"] == step_id)
                    old_result = (self.store.get(old_step["run_id"]) or {}).get("result") or {}
                    entry = next(row for row in career["runs"] if row["step_id"] == step_id)
                    if entry["kind"] == "answer":
                        continue
                    selected_maps.append({
                        "step_id": step_id,
                        "question": entry.get("user_question") or old_step["question"],
                        "recorded_at": entry["created_at"],
                        "same_job_scope": old_step["scope_version"] == record["scope_version"],
                        "work_map": old_result.get("work_map"),
                        "claim_details_to_recheck": [
                            {key: claim.get(key) for key in (
                                "text", "category", "basis", "requirement",
                            )}
                            for claim in old_result.get("claims", [])
                        ],
                        "unresolved_then": old_result.get("gaps", []),
                        "source_references_to_reread": [
                            {key: source.get(key) for key in (
                                "title", "evidence_kind", "job_id", "public_document_id",
                                "start", "end",
                            )}
                            for source in old_result.get("evidence", [])
                        ],
                    })

            context["career_evidence"] = {
                "understanding_check": bool(step.get("career_understanding_check")),
                "autonomous_inquiry": {"rounds_remaining": step["career_auto_rounds"]}
                if step.get("career_auto_rounds") else None,
                "selected_requirement": step.get("career_requirement"),
                "selected_inquiry": selected_inquiry,
                "selected_map_comparison": selected_maps,
                "selected_answer_comparison": selected_answers,
                "selected_learning_note": learning_note(selected_note) if selected_note else None,
                "selected_learning_notes": [learning_note(row)
                                            for key in step.get("career_insight_ids", [])
                                            for row in notes if row["id"] == key],
                "selected_counter_learning_note": learning_note(counter_note)
                if counter_note else None,
                "counter_experiment": next(
                    (experiment_record(row, full=True) for row in career["tasks"]
                     if counter_note and row["id"] == counter_note.get("task_id")), None
                ),
                "learning_recall": learning_recall,
                "learning_tools_notice": "可用search_learning_notes查找其他选用中的认识，再用"
                "read_learning_note读取完整内容。点选认识重查时，也可读取同一接替脉络的旧记录；"
                "搜索预览不是全文，读取不改变选用状态，个人理解不能作为原文证据引用。",
                "learning_selection_notice": "learning_notes最多带入三份选用中的个人认识，"
                "优先同一调查问题、练习或认识接替关系，其次本次问题的字面关键词相关性。"
                "具体提问不以无关的近期笔记补满；未指定讨论重点且无匹配时，才带入近期记录。"
                "字面相关只用于找回线索，不代表语义一致或结论成立；未带入不表示已遗忘或不相关。"
                "selected_learning_note是用户本次明确要求重查的完整记录，可能已搁置。"
                "selected_counter_learning_note是用户点选的另一条完整认识，需对照各自条件与来源。"
                "重查不等于重新采用，不因新旧顺序判断真伪。",
                "selected_story": {
                    "id": selected_story["id"],
                    "title": selected_story["title"],
                    "document_id": selected_story["document_id"],
                    "source_task_id": selected_story.get("source_task_id"),
                    "notice": "用户选中的经历，需读取原文，不把不同项目混为同一个项目。",
                }
                if selected_story
                else None,
                "presentation_drafts": [
                    {
                        "title": row["title"],
                        "text": row["text"],
                        "story_id": row.get("story_id"),
                        "notice": "用户自己的讲述稿，不是新增事实来源；事实仍需回查经历原文。",
                    }
                    for row in career.get("pitches", [])[-2:]
                ],
                "public_research_policy": (
                    "可按问题需要补查企业官方业务说明和技术资料，优先从所选JD与已有归档出发。"
                    "公开检索只针对业务、企业、产品或技术问题，不把个人简历、联系方式、面试回答"
                    "或个人实验原文写进搜索词；不要搜索个人信息或请求招聘平台。"
                    "搜索摘要只能定位线索；需以网页事实作判断时读取并引用正文。"
                    "公司介绍和产品文档不能单独证明岗位个人职责、权限或任职要求。"
                )
                if step.get("allow_public")
                else None,
                "selected_answer": {
                    "document_id": step["career_answer_document_id"],
                    "notice": "本次讨论的用户回答原文，可引用原话；经历和效果仍未独立核实。",
                }
                if step.get("career_answer_document_id")
                else None,
                "omitted_documents": step.get("career_omitted_documents", 0),
                "document_selection_notice": "omitted_documents是未放入开头优先选择的资料数量，"
                "不表示资料不存在、无关或不可读取。可读范围见fixed_scope.archived_public_ids，"
                "开头目录未列完时可分页查看；正文仍须另行读取。",
                "selected_material": {
                    "document_id": step["career_material_id"],
                    "notice": "用户明确选中的归档资料，需读取正文后回答；标题不是证据。",
                }
                if step.get("career_material_id")
                else None,
                "selected_materials": [
                    {"document_id": key,
                     "notice": "用户选定的重点原文之一；需分别读取条件，再进行对读。"}
                    for key in step.get("career_material_ids", [])
                ],
                "resume": {
                    "document_id": career["resume_document_id"],
                    "title": career["resume_title"],
                    "notice": "用户提供的简历，经历未经独立核实；需要时读取归档全文。",
                }
                if career.get("resume_document_id")
                else None,
                "notice": "以下是用户自述和个人练习记录，不是招聘原文、独立评测或能力认证。"
                "摘要仅供定位；项目经历全文可按document_id读取本轮归档。",
                "selected_experiment_id": step.get("career_task_id"),
                "previous_experiment": experiment_record(previous_experiment, full=True)
                if previous_experiment
                else None,
                "learning_notes": [learning_note(row) for row in active_notes],
                "stories": [
                    {
                        "title": row["title"],
                        "document_id": row["document_id"],
                        "reused_from_goal": (row.get("reused_from") or {}).get("project_title"),
                        "personal_action": row["action"][:400],
                        "reported_result": row["result"][:300],
                        "limits": row["limits"][:200],
                    }
                    for row in stories[-3:]
                ],
                "experiments": [
                    experiment_record(row, full=bool(selected_task)) for row in observations[-3:]
                ],
                "omitted_stories": max(0, len(stories) - 3),
                "omitted_experiments": max(0, len(observations) - 3),
                "experiment_history_notice": (
                    "开头只展示部分实验。可用search_experiments查找本目标较早的设计与观察，"
                    "再read_experiments读取完整记录；前后条件可能不同，记录不是独立验证。"
                ),
            }
            current_entry = next(
                (row for row in career["runs"] if row["step_id"] == step["id"]), {},
            )
            if step.get("career_action") == "ask" and current_entry.get("source_step_id"):
                source_id = current_entry["source_step_id"]
                source_step = next((row for row in record["steps"] if row["id"] == source_id), {})
                source_run = (
                    self.store.get(source_step["run_id"]) if source_step.get("run_id") else {}
                ) or {}
                source_result = source_run.get("result") or {}
                continued = {"step_id": source_id, "unavailable": True}
                if (source_run.get("state") != "invalidated"
                        and source_result.get("status") == "completed"):
                    source_entry = next((row for row in career["runs"]
                                         if row["step_id"] == source_id), {})
                    plan = deepcopy(source_result.get("application_plan"))
                    cited = {identity for claim in source_result.get("claims", [])
                             for identity in claim.get("evidence_ids", [])}
                    if plan:
                        for action in plan.get("actions", []):
                            cited.update(action.pop("evidence_ids", []))
                    continued = {
                        **{key: source_entry.get(key) for key in (
                            "step_id", "kind", "user_question", "interview_question", "created_at",
                            "question_id", "selected_job_ids", "task_id", "story_id", "insight_id",
                            "hypothesis_a", "hypothesis_b", "synthesis_sources",
                        )},
                        "source_cutoff": source_result.get("created_at"),
                        "scope": source_result.get("scope"),
                        "user_reported_answer": source_entry.get("answer", ""),
                        "claim_details_to_recheck": [
                            {
                                "position": index + 1,
                                **{key: claim.get(key) for key in (
                                    "text", "category", "basis", "requirement",
                                )},
                            }
                            for index, claim in enumerate(source_result.get("claims", []))
                        ],
                        "work_map": source_result.get("work_map"),
                        "application_plan": plan,
                        "unresolved_then": source_result.get("gaps", []),
                        "source_references_to_reread": [
                            {key: source.get(key) for key in (
                                "title", "evidence_kind", "job_id", "public_document_id",
                                "document_id", "snapshot_id", "historical_cutoffs", "start", "end",
                            )}
                            for source in source_result.get("evidence", []) if source["id"] in cited
                        ],
                        "notice": "这是用户指定的那次旧讨论，不能用最新一次替代，也不是新证据。"
                        "scope是当时的资料范围，当前范围以fixed_scope为准。保留判断性质、"
                        "地图迁移限制及未知；个人回答仍为自述，application_plan仍是当时的建议。"
                        "旧引用仅供定位，须从本轮读取获得新引用，不能把旧判断或建议当作已验证结果。",
                    }
                context["career_evidence"]["continued_discussion"] = continued
            if step.get("career_synthesis"):
                from work_observer.research.inquiry_synthesis import synthesis_inquiries

                context["career_evidence"]["synthesis_inquiries"] = synthesis_inquiries(
                    record, self.store, step["career_synthesis"],
                )
            if step.get("career_action") in {"role", "map"}:
                context["career_evidence"] = {
                    "public_research_policy": context["career_evidence"]["public_research_policy"],
                    "selected_material": None,
                    "selected_materials": context["career_evidence"]["selected_materials"],
                    "selected_inquiry": {
                        "id": selected_inquiry["id"], "question": selected_inquiry["question"],
                        "notice": "用户要继续解释的调查问题，只作为研究方向，不代表结论已成立。",
                    } if selected_inquiry else None,
                    "notice": "本轮只理解岗位工作。个人简历、经历、练习和认识不作为岗位要求依据。",
                }
                from work_observer.research.career import personal_documents

                private = personal_documents(career)
            else:
                private = set()
            context["career_evidence"]["source_document_ids"] = [
                key for key in record.get("public_document_ids", []) if key not in private
            ]
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
    preferred_step_id=None,
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
            preferred_step_id=preferred_step_id,
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
            preferred_step_id=preferred_step_id,
        )


async def _execute_project_locked(
    service,
    identity,
    repository,
    settings,
    *,
    model=None,
    max_steps=3,
    worker_caps=None,
    preferred_step_id=None,
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
    for _index in range(max_steps):
        outcome = {}
        step = service.claim(
            identity,
            worker_caps=remaining,
            claim_outcome=outcome,
            preferred_step_id=preferred_step_id,
        )
        if step is None:
            worker_stop_reason = outcome.get("stop_reason", "no_ready_steps")
            break
        preferred_step_id = None
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
            from work_observer.research.learning import LearningNotebook

            notebook = (
                LearningNotebook(
                    lambda: service.get(identity), service.store,
                    step.get("career_insight_id"), step.get("career_counter_insight_id"),
                    selected_note_ids=step.get("career_insight_ids", []),
                    project_lister=lambda: service.list(all_records=True),
                )
                if "learning_recall" in context.get("career_evidence", {}) else None
            )
            result = await research(
                repository,
                step["question"],
                settings,
                job_ids=step["job_ids"],
                public_document_ids=step.get("public_document_ids"),
                offline=step["offline"],
                max_calls=step["max_calls"],
                timeout=step["timeout"],
                allow_public=step["allow_public"],
                allow_proposals=not bool(service.get(identity).get("career")),
                model=model,
                project_id=identity,
                conversation_context=context,
                learning_notebook=notebook,
                checkpoint=(service.store, run_id),
                resume=resume,
                approach=step.get("approach", "standard"),
                coverage_mode=step.get("coverage_mode", "all"),
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
            if step["allow_public"]:
                discovered = [
                    row["public_document_id"]
                    for row in result.get("evidence", [])
                    if row.get("source") == "public_web" and row.get("public_document_id")
                ]
                if discovered:
                    with service.store.lock, service.store.db:
                        current = service.get(identity)
                        if current.get("career"):
                            career = current["career"]
                            career["researched_document_ids"] = list(
                                dict.fromkeys(
                                    career.get("researched_document_ids", []) + discovered
                                )
                            )
                            service._write(current)
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
        else:
            if status == "completed":
                if step.get("career_auto_rounds"):
                    from work_observer.research.career import CareerService

                    preferred_step_id = CareerService(
                        service.store, repository, settings.raw_directory
                    ).advance_inquiry(identity, step, result)
                    if preferred_step_id is None:
                        break
                    continue
                from work_observer.research.investigations import arrange_proposals

                arrange_proposals(service, identity, step, result)
        if step.get("career_auto_rounds"):
            break
    result = service.get(identity)
    if worker_caps is not None:
        result["worker_batch"] = {
            "reserved": reserved,
            "run_ids": worker_run_ids,
            "stop_reason": worker_stop_reason,
        }
    return result
