"""A job seeker's evidence, experiments and interview practice in one research project."""

import json
from datetime import datetime
from uuid import uuid4

from work_observer.collection.contracts import now
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.memory.service import MemoryService
from work_observer.quality.reviews import QualityReviewService
from work_observer.reports.results import audit_result
from work_observer.research.applications import PREFIX
from work_observer.research.applications import background as application_background
from work_observer.research.archived_sources import catalog as archive_catalog
from work_observer.research.projects import ProjectService, step_continuation
from work_observer.retrieval.unified import UnifiedRetrieval
from work_observer.text_match import match_text

QUESTIONS = {
    "evidence": (
        "逐项核对用户针对一项岗位要求选中的证据，不做笼统匹配打分。"
        "本次要求和材料在career_evidence.selected_requirement，先回读该要求引用的JD原文，"
        "再读取所选records中每份document_id对应的经历、作品或补充材料正文。"
        "planned练习只是计划，done也只代表用户记录过观察；无产物的练习不能假装已读过产物。"
        "区分招聘要求、自述经历、个人练习观察和你的迁移推断；保留必备、加分和未说明性质。"
        "具体说明哪些个人行动或产物与此要求有关，迁移依赖什么前提，哪些缺口仍未知。"
        "不能仅用JD证明用户做过什么，不因有材料就认定胜任，也不把未提供材料说成不会。"
        "用户填写的relevance和missing是个人判断，须对照原文检验。"
        "claims最多四条，给出相应原文引用；必要时通过application_plan只建议一个最小补证据练习。"
        "结尾在gaps中列仍需补充的信息与最值得核实的问题，不编造能力、指标或企业验收标准。"
    ),
    "pitch": (
        "为用户整理一份基于证据的项目面试讲述草稿。只围绕career_evidence.selected_story，"
        "先读取其document_id对应的用户经历原文，再结合目标JD理解讲述重点。"
        "在claims中按场景、亲自行动、关键取舍、实际结果、限制的顺序，写最多五条简短的"
        "第一人称讲述素材，总计尽量控制在500字以内，每条引用用户经历或作品原文。"
        "JD只支持岗位相关性，不能用JD证明用户做过什么；个人陈述不能冒充独立核验。"
        "计划没有完成就保留未完成，不补造指标、业务收益、上线经验、决定权或参与范围。"
        "不得把其他经历混成同一个项目。表达重组可为归纳，迁移判断应明确是推断，"
        "任职资格强度不适用于个人稿件，使用unspecified。gaps列需要补充的事实和容易被追问的"
        "地方，不编标准答案，不生成行动计划，不安排额外调查。"
    ),
    "map": (
        "把岗位工作画成可探索的工作地图，帮助求职者解释这份工作如何产生结果。"
        "先读取所选JD，只解释有原文支撑的工作线，最多8条判断、4条工作关系。"
        "保留任务、交付物、能力、工具和责任的区别；可连接任务产出什么、完成任务需要什么，"
        "不能因处于同一份JD就任意连线。不强求凑齐六类，原文缺失的交付物和责任保持未知。"
        "关系解释为什么相关、对求职准备意味着什么以及迁移边界；两份JD时只比较有两侧依据的内容。"
        "不评价用户是否胜任，不生成行动计划，不安排后续调查。"
    ),
    "reflect": (
        "结合project_context.career_evidence中用户记录的工作样本实际观察，反思下一步。"
        "先说明练习原先要检验什么、用户实际观察到什么，再判断哪些解释得到支持、哪些被挑战、"
        "若附有作品或运行记录，先用artifact_document中的document_id读取归档正文，"
        "对照记录讨论，不能把用户的总结当作已经运行过的独立评测。"
        "哪些还无法判断。任务状态done只表示用户记录结果，不代表成功或具备岗位能力。"
        "实际观察是用户自述，不能当作招聘原文或独立评测；区分没有证据与证实不会。"
        "回查相关岗位原文，最多建议一个最小的后续验证，可通过application_plan给出。"
        "若记录不足，明确需要补什么观察，不编造结果，不安排额外调查。"
    ),
    "role": (
        "帮助求职者看清所选岗位到底在做什么。只从岗位JD提取最多8条关键任务、交付物、"
        "能力与责任判断，分别保留必备、加分和未说明性质及原文引用。不要把公司平台能力当作个人权限。"
        "同一判断只说明一个具体工作要求，便于逐条对照个人经历。最后指出最值得向面试官核实的问题。"
        "本轮先理解岗位，不评价用户是否胜任，不生成行动计划，不安排后续调查。"
    ),
    "gaps": (
        "依据所选岗位原文、已保存的个人背景和用户项目经历，分析下一步值得验证什么。"
        "区分招聘原文要求、用户自述、研究推断；没有经历证据应说尚未证明，不能判定用户不会。"
        "指出自述经历可迁移的具体任务、迁移前提、缺少的产物或验证，以及需要询问用户的问题。"
        "不要给虚假的匹配百分比，不把关键词重合等同于胜任。优先讨论影响目标的三项问题。"
        "如给application_plan，最多三项具体补证据动作，不安排额外调查。"
    ),
    "plan": (
        "为这个求职目标设计最多三个可执行的工作样本实验，使用已保存的个人背景与经历。"
        "先核对目标岗位原文，再在application_plan给出针对的任务或能力、要解决的业务问题、"
        "可展示产物、可复现的完成检查、需要的资源和未知。每项引用对应岗位依据。"
        "尊重用户投入限制，不编造完成时间；避免只有看教程、学工具的建议。"
        "建议的验收是练习设计，不冒充企业要求；不安排额外调查。"
    ),
    "interview": (
        "围绕目标岗位原文和用户项目经历，设计一次证据驱动的模拟面试。"
        "在gaps中写最多三道完整的面试问题，每道都使用问号，分别检查任务理解、真实参与边界、失败案例与取舍。"
        "每道说明为何与岗位有关、回答时应提供什么过程或产物证据。"
        "claims只列有引用的岗位依据，不能把问题写成已经成立的岗位事实。"
        "若没有足够经历，先指出要补充的真实信息，不编造用户的项目、指标或标准答案。"
        "不要在用户回答前替其回答，不生成行动计划，不安排额外调查。"
    ),
}


def personal_documents(career):
    return {
        career.get("resume_document_id"),
        *(row["document_id"] for row in career["stories"]),
        *(row.get("artifact_document_id") for row in career["tasks"]),
    } - {None}


class CareerService:
    def __init__(self, store, repository, raw_directory):
        self.projects = ProjectService(store)
        self.store = store
        self.repository = repository
        self.raw_directory = raw_directory

    def _project(self, identity):
        project = self.projects.get(identity)
        if project["state"] != "active" or not project.get("career"):
            raise ValueError("这个求职目标已不可用，请重新选择。")
        return project

    def create(
        self,
        *,
        title,
        goal,
        background,
        constraints,
        job_ids,
        resume_title="个人简历",
        resume_text="",
    ):
        for identity in job_ids:
            self.repository.job(identity)
        project = self.projects.create(
            title,
            goal,
            job_ids,
            public_document_ids=[],
            max_calls=72,
            max_seconds=1800,
            max_rounds=12,
            max_public=0,
        )
        note = MemoryService(self.repository).create(
            "preference",
            PREFIX
            + json.dumps(
                {
                    "background": background,
                    "goal": goal,
                    "constraints": constraints,
                },
                ensure_ascii=False,
            ),
            scope="project",
            project_id=project["id"],
            subject="个人应用背景",
            origin="user",
        )
        with self.store.lock, self.store.db:
            project["career"] = {
                "background_memory_id": note["id"],
                "stories": [],
                "tasks": [],
                "runs": [],
            }
            self.projects._write(project)
        if resume_text.strip():
            return self.set_resume(project["id"], title=resume_title, text=resume_text)
        return self.get(project["id"])

    def listing(self):
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "goal": row["goal"],
                "updated_at": row["updated_at"],
                "job_count": len(row["job_ids"]),
                "story_count": len(row["career"]["stories"]),
                "insight_count": len(row["career"].get("insights", [])),
                "open_question_count": sum(
                    q["state"] == "open" for q in row["career"].get("questions", [])
                ),
                "task_count": len(row["career"]["tasks"]),
                "done_count": sum(task["state"] == "done" for task in row["career"]["tasks"]),
            }
            for row in self.projects.list(all_records=True)
            if row["state"] == "active" and row.get("career")
        ]

    def update_goal(self, identity, *, title, goal, background, constraints, job_ids):
        for job_id in job_ids:
            self.repository.job(job_id)
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等本轮研究结束后再调整目标，当前输入仍保留。")
            memory = MemoryService(self.repository)
            profile = application_background(memory.list(), identity)
            content = PREFIX + json.dumps(
                {"background": background, "goal": goal, "constraints": constraints},
                ensure_ascii=False,
            )
            note = (
                memory.revise(profile["memory_id"], content)
                if profile
                else memory.create(
                    "preference",
                    content,
                    scope="project",
                    project_id=identity,
                    subject="个人应用背景",
                    origin="user",
                )
            )
            if project["goal"] != goal or set(project["job_ids"]) != set(job_ids):
                project = self.projects.revise(
                    identity, revision=project["revision"], goal=goal, job_ids=job_ids
                )
            if project["title"] != title:
                project = self.projects.rename(identity, revision=project["revision"], title=title)
            project["career"]["background_memory_id"] = note["id"]
            self.projects._write(project)
        return self.get(identity)

    def search(self, identity, *, q, scope="goal"):
        project = self._project(identity)
        terms = q.split()[:10]
        originals = UnifiedRetrieval(self.repository).search(
            terms,
            job_ids=project["job_ids"] if scope == "goal" else None,
            public_document_ids=list(
                dict.fromkeys(
                    [
                        *(project.get("public_document_ids") or []),
                        *[
                            row["answer_document_id"]
                            for row in project["career"]["runs"]
                            if row.get("answer_document_id")
                        ],
                        *project["career"].get("researched_document_ids", []),
                    ]
                )
            )
            if scope == "goal"
            else None,
            project_id=identity if scope == "goal" else None,
            include_knowledge=False,
            limit=12,
        )
        projects = (
            [project]
            if scope == "goal"
            else [
                row
                for row in self.projects.list(all_records=True)
                if row["state"] == "active" and row.get("career")
            ]
        )
        terms = [match_text(term) for term in terms]
        records = []

        def add(owner, kind, row, title, text, section, *, step_id=None):
            folded = match_text(title + "\n" + text)
            if not all(term in folded for term in terms):
                return
            position = min(
                (match_text(text).find(term) for term in terms if term in match_text(text)),
                default=0,
            )
            start = max(0, position - 50)
            records.append(
                {
                    "id": row.get("id") or row["step_id"],
                    "kind": kind,
                    "title": title,
                    "excerpt": text[start : start + 280],
                    "project_id": owner["id"],
                    "project_title": owner["title"],
                    "section": section,
                    "step_id": step_id,
                    "use_for_research": row.get("use_for_research", True)
                    if kind == "insight"
                    else None,
                    "recorded_at": row.get("updated_at") or row.get("created_at"),
                }
            )

        for owner in projects:
            career = owner["career"]
            for row in career["stories"]:
                add(
                    owner,
                    "story",
                    row,
                    row["title"],
                    "\n".join(
                        row.get(key, "") for key in ("situation", "action", "result", "limits")
                    ),
                    "stories",
                )
            for row in career["tasks"]:
                add(
                    owner,
                    "task",
                    row,
                    row["title"],
                    "\n".join(
                        row.get(key, "")
                        for key in (
                            "task_or_ability",
                            "deliverable",
                            "completion_check",
                            "hypothesis",
                            "outcome",
                            "design_change",
                        )
                    ),
                    "experiments",
                )
            for row in career.get("insights", []):
                add(
                    owner,
                    "insight",
                    row,
                    row["current_view"],
                    "\n".join(
                        row.get(key, "")
                        for key in ("previous_view", "observation", "current_view", "open_question")
                    ),
                    "experiments",
                    step_id=row.get("source_step_id"),
                )
            for row in career.get("pitches", []):
                add(
                    owner,
                    "pitch",
                    row,
                    row["title"],
                    row["text"],
                    "interview",
                    step_id=row.get("source_step_id"),
                )
            for row in career.get("questions", []):
                carried = row.get("carried_understanding") or {}
                add(
                    owner,
                    "question",
                    row,
                    row["question"],
                    "\n".join(
                        row.get(key, "") for key in ("why_matters", "next_evidence", "conclusion")
                    )
                    + "\n"
                    + "\n".join(
                        carried.get(key, "")
                        for key in ("understanding", "observation", "previous_view")
                    ),
                    "requirements",
                    step_id=row.get("conclusion_step_id") or row.get("source_step_id"),
                )
            for row in career["runs"]:
                step = next((item for item in owner["steps"] if item["id"] == row["step_id"]), None)
                run = self.store.get(step["run_id"]) if step and step.get("run_id") else None
                if not run or run["state"] == "invalidated":
                    continue
                result = run.get("result") or {}
                section = row.get("section") or {
                    "role": "requirements",
                    "map": "requirements",
                    "evidence": "requirements",
                    "gaps": "stories",
                    "plan": "experiments",
                    "reflect": "experiments",
                }.get(row["kind"], "interview")
                text = "\n".join(
                    [
                        row.get("interview_question", ""),
                        row.get("answer", ""),
                        *[claim["text"] for claim in result.get("claims", [])],
                        *result.get("gaps", []),
                    ]
                )
                title = (
                    row.get("user_question")
                    or row.get("interview_question")
                    or {
                        "role": "看清岗位",
                        "map": "探索工作地图",
                        "evidence": "逐项核对证据：" + row.get("requirement_text", ""),
                        "gaps": "对照经历与差距",
                        "plan": "工作样本建议",
                        "reflect": "练习反思",
                        "interview": "模拟面试问题",
                        "followup": "针对回答的追问",
                        "answer": "面试回答与反馈",
                    }.get(row["kind"], "研究讨论")
                )
                add(
                    owner,
                    "discussion",
                    row,
                    title,
                    text,
                    section,
                    step_id=row["step_id"],
                )
        records.sort(key=lambda row: row["recorded_at"] or "", reverse=True)
        return {
            "query": q,
            "scope": scope,
            "originals": originals,
            "records": records[:24],
            "record_count": len(records),
            "records_truncated": len(records) > 24,
        }

    def get(self, identity):
        project = self._project(identity)
        career = project["career"]
        notes = MemoryService(self.repository).list()
        profile = application_background(notes, identity)
        requirements, results = [], []
        role_selected = False
        for entry in reversed(career["runs"]):
            step = next((row for row in project["steps"] if row["id"] == entry["step_id"]), None)
            if not step:
                continue
            run = self.store.get(step["run_id"]) if step.get("run_id") else None
            result = (run or {}).get("result")
            available = bool(result and run["state"] != "invalidated")
            audit = audit_result(result, self.repository) if available else None
            checkpoint = (
                self.store.load_checkpoint(step["run_id"])
                if (run and step["state"] in {"running", "interrupted", "failed"})
                else None
            )
            progress = (checkpoint or {}).get("result") or result or {}
            continuation = (
                step_continuation(project, step, run, checkpoint, audit or {}) if run else None
            )
            current = (
                available
                and step["state"] != "abandoned"
                and step["scope_version"] == project["scope_version"]
                and not (
                    audit["changed_sources"]
                    or audit["stale_dependencies"]
                    or audit["stale_memory"]
                    or audit["stale_knowledge"]
                )
            )
            review = (
                next(
                    (
                        row
                        for row in QualityReviewService(self.store, self.repository).list_run(
                            step["run_id"]
                        )
                        if not row["stale_result"]
                    ),
                    None,
                )
                if available and result["status"] == "completed"
                else None
            )
            if review and review["status"] == "rejected":
                current = False
            results.append(
                {
                    **entry,
                    "state": step["state"],
                    "current": bool(current),
                    "scope_current": step["scope_version"] == project["scope_version"],
                    "allow_public": bool(step["allow_public"]),
                    "offline": bool(step["offline"]),
                    "continuation": continuation,
                    "progress": {
                        "calls": progress.get("model_calls", 0),
                        "read_fragments": len(
                            (checkpoint or {}).get("evidence") or progress.get("evidence", [])
                        ),
                        "last_tool": (progress.get("trace") or [{}])[-1].get("tool"),
                    },
                    "run_id": step.get("run_id"),
                    "result": {
                        **result,
                        "audit": audit,
                        "business_review": review or {"status": "pending"},
                    }
                    if available
                    else None,
                }
            )
            if (
                entry["kind"] in {"role", "map"}
                and current
                and result["status"] == "completed"
                and not role_selected
            ):
                role_selected = True
                evidence = {row["id"]: row for row in result["evidence"]}
                for index, claim in enumerate(result["claims"]):
                    if not all(key in evidence for key in claim["evidence_ids"]):
                        continue
                    if not any(
                        evidence[key].get("job_id") in project["job_ids"]
                        for key in claim["evidence_ids"]
                    ):
                        continue
                    requirements.append(
                        {
                            "key": f"{step['run_id']}:{index}",
                            **claim,
                            "evidence": [evidence[key] for key in claim["evidence_ids"]],
                            "proof": self.requirement_proof(project, f"{step['run_id']}:{index}"),
                        }
                    )
        return {
            "id": identity,
            "title": project["title"],
            "goal": project["goal"],
            "profile": profile,
            "resume": {"document_id": career["resume_document_id"], "title": career["resume_title"]}
            if career.get("resume_document_id")
            else None,
            "jobs": [self.repository.job(key) for key in project["job_ids"]],
            "stories": career["stories"],
            "tasks": career["tasks"],
            "insights": career.get("insights", []),
            "pitches": career.get("pitches", []),
            "questions": career.get("questions", []),
            "document_ids": project.get("public_document_ids", []),
            "materials": archive_catalog(
                self.repository,
                [
                    key
                    for key in (project.get("public_document_ids") or [])
                    if key not in personal_documents(career)
                ],
            ),
            "discovered_materials": archive_catalog(
                self.repository,
                [
                    key
                    for key in career.get("researched_document_ids", [])
                    if key not in (project.get("public_document_ids") or [])
                ],
            ),
            "requirements": requirements,
            "results": results,
            "usage": self.projects.usage(project),
            "budget": project["budget"],
            "running": any(step["state"] == "running" for step in project["steps"]),
        }

    def requirement_proof(self, project, key):
        career = project["career"]
        saved = next(
            (
                row
                for row in career.get("requirement_evidence", [])
                if row["requirement_key"] == key
            ),
            None,
        )
        references = (
            saved["records"]
            if saved
            else [
                {"kind": "story", "id": row["id"]}
                for row in career["stories"]
                if row.get("requirement_key") == key
            ][:3]
        )
        records = []
        for ref in references:
            kind, identity = ref["kind"], ref["id"]
            if kind == "material":
                source = (
                    next(iter(archive_catalog(self.repository, [identity])), None)
                    if identity in (project.get("public_document_ids") or [])
                    else None
                )
                row = {"title": source["title"], "document_id": identity} if source else None
            else:
                row = next(
                    (
                        dict(item)
                        for item in career["stories" if kind == "story" else "tasks"]
                        if item["id"] == identity
                    ),
                    None,
                )
                if row and kind == "task":
                    row["document_id"] = row.get("artifact_document_id")
            records.append(
                {
                    **(row or {"title": "已移出当前目标的记录"}),
                    "kind": kind,
                    "id": identity,
                    "available": bool(row),
                }
            )
        return {
            "records": records,
            "relevance": saved.get("relevance", "") if saved else "",
            "missing": saved.get("missing", "") if saved else "",
        }

    def save_requirement_evidence(self, identity, data):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if not any(
                row["key"] == data["requirement_key"] for row in self.get(identity)["requirements"]
            ):
                raise ValueError("请从当前岗位分析中重新选择一项要求。")
            career = project["career"]
            links = career.setdefault("requirement_evidence", [])
            references = list({(ref["kind"], ref["id"]): ref for ref in data["records"]}.values())
            for ref in references:
                available = (
                    ref["id"] in (project.get("public_document_ids") or [])
                    if ref["kind"] == "material"
                    else any(
                        row["id"] == ref["id"]
                        for row in career["stories" if ref["kind"] == "story" else "tasks"]
                    )
                )
                if not available:
                    raise ValueError("所选材料已不在当前目标中，请重新选择。")
            saved = {**data, "records": references, "updated_at": now()}
            previous = next(
                (row for row in links if row["requirement_key"] == data["requirement_key"]), None
            )
            if previous:
                links[links.index(previous)] = saved
            else:
                links.append(saved)
            self.projects._write(project)
        return self.get(identity)

    def end_step(self, identity, step_id):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            step = next((row for row in project["steps"] if row["id"] == step_id), None)
            if not step:
                return self.get(identity)
            if step["state"] not in {"queued", "interrupted", "failed"}:
                raise ValueError("这轮已经运行或结束，请先暂停正在进行的研究。")
            if any(
                row["id"] != step_id
                and (step_id in row.get("depends_on", []) or row.get("reply_to_step_id") == step_id)
                for row in project["steps"]
            ):
                raise ValueError("还有后续研究依赖这一轮，请先在完整研究记录中调整。")
            if not step.get("run_id"):
                project["steps"].remove(step)
                project["turns"] = [row for row in project["turns"] if row["id"] != step_id]
                project["career"]["runs"] = [
                    row for row in project["career"]["runs"] if row["step_id"] != step_id
                ]
            else:
                ended_at = now()
                run = self.store.get(step["run_id"])
                checkpoint = self.store.load_checkpoint(step["run_id"]) or {}
                result = {**checkpoint.get("result", {}), **(run.get("result") or {})}
                if result:
                    result["model_calls"] = max(
                        result.get("model_calls", 0),
                        checkpoint.get("result", {}).get("model_calls", 0),
                    )
                    elapsed = max(result.get("elapsed_seconds", 0), checkpoint.get("elapsed", 0))
                    if checkpoint.get("pending_since"):
                        elapsed += min(
                            55,
                            max(
                                0,
                                (
                                    datetime.fromisoformat(ended_at)
                                    - datetime.fromisoformat(checkpoint["pending_since"])
                                ).total_seconds(),
                            ),
                        )
                    result.update(
                        status="incomplete",
                        stop_reason="user_ended",
                        elapsed_seconds=round(elapsed, 3),
                    )
                    self.store.save(run["id"], state="finished", result=result)
                else:
                    self.store.save(run["id"], state="finished")
                step.update(state="abandoned", stop_reason="user_ended", finished_at=ended_at)
            self.projects._write(project)
        return self.get(identity)

    def set_resume(self, identity, *, title, text):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等本轮研究结束后再更新简历，输入仍保留。")
            previous = project["career"].get("resume_document_id")
            if not previous and len(project.get("public_document_ids") or []) >= 20:
                raise ValueError("本研究已选满20份资料，请先在研究工作台调整。")
            document = PublicDocumentService(
                self.repository, self.raw_directory / "public"
            ).archive_text(
                title,
                "用户提供的简历文字，经历及效果尚未独立核实。\n" + text,
                "用户导入的简历文字，可能由文件提取；图片与版式不作为研究证据，不是企业招聘要求。",
            )["document"]
            project["career"].update(resume_document_id=document["id"], resume_title=title)
            project["public_document_ids"] = [
                key for key in (project.get("public_document_ids") or []) if key != previous
            ] + [document["id"]]
            self.projects._write(project)
        return self.get(identity)

    def add_material(self, identity, *, title, text, source_name=""):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等本轮研究结束后再补充资料，输入仍保留。")
            documents = list(project.get("public_document_ids") or [])
            if len(documents) >= 20:
                raise ValueError("当前目标已有20份材料，请先移除暂时不需要的资料。")
            document = PublicDocumentService(
                self.repository, self.raw_directory / "public"
            ).archive_text(title, text, source_name)["document"]
            project["public_document_ids"] = [*documents, document["id"]]
            self.projects._write(project)
        return self.get(identity)

    def attach_material(self, identity, *, document_id):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等本轮研究结束后再加入材料。")
            documents = list(project.get("public_document_ids") or [])
            if document_id not in documents:
                if len(documents) >= 20:
                    raise ValueError("当前目标已有20份材料，请先移除暂时不需要的资料。")
                document = PublicDocumentService(
                    self.repository, self.raw_directory / "public"
                ).document(document_id)
                if document["integrity"] != "verified":
                    raise ValueError("这份归档资料暂时无法完整读取，请先检查原文。")
                project["public_document_ids"] = [*documents, document_id]
                self.projects._write(project)
        return self.get(identity)

    def remove_material(self, identity, document_id):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if document_id in personal_documents(project["career"]):
                raise ValueError("这是简历、经历或作品材料，请在相应记录中调整。")
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等本轮研究结束后再调整资料。")
            project["public_document_ids"] = [
                key for key in (project.get("public_document_ids") or []) if key != document_id
            ]
            self.projects._write(project)
        return self.get(identity)

    def add_story(self, identity, data, story_id=None):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            stories = project["career"]["stories"]
            previous = next((row for row in stories if row["id"] == story_id), None)
            if story_id and previous is None:
                raise ValueError("这份经历已经不在当前目标中，请刷新列表。")
            if not previous and len(stories) >= 12:
                raise ValueError("每个目标最多保存12份经历，请精简后再补充。")
            if not previous and len(project.get("public_document_ids") or []) >= 20:
                raise ValueError("本研究已选满20份资料，请先在研究工作台调整。")
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等当前研究结束后再补充经历，输入仍保留。")
            text = "\n".join(
                [
                    "用户自述经历，尚未独立核实。",
                    "项目/工作：" + data["title"],
                    "目标和场景：" + data["situation"],
                    "我亲自负责：" + data["action"],
                    "结果与证据：" + data["result"],
                    "限制和未参与部分：" + data["limits"],
                ]
            )
            document = PublicDocumentService(
                self.repository, self.raw_directory / "public"
            ).archive_text(
                data["title"],
                text,
                "用户自述项目经历；不是企业招聘要求或独立核验结果",
            )["document"]
            saved = {
                "id": story_id or uuid4().hex,
                **data,
                "document_id": document["id"],
                "created_at": previous["created_at"] if previous else now(),
                "updated_at": now(),
                **(
                    {"reused_from": previous["reused_from"]}
                    if previous and previous.get("reused_from")
                    else {}
                ),
            }
            if previous:
                stories[stories.index(previous)] = saved
            else:
                stories.append(saved)
            project["public_document_ids"] = [
                *(
                    key
                    for key in (project.get("public_document_ids") or [])
                    if not previous or key != previous["document_id"]
                ),
                document["id"],
            ]
            self.projects._write(project)
        return self.get(identity)

    def remove_story(self, identity, story_id):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等当前研究结束后再移出经历。")
            story = next(
                (row for row in project["career"]["stories"] if row["id"] == story_id), None
            )
            if not story:
                raise ValueError("这份经历已经不在当前目标中。")
            project["career"]["stories"].remove(story)
            project["public_document_ids"] = [
                key
                for key in (project.get("public_document_ids") or [])
                if key != story["document_id"]
            ]
            self.projects._write(project)
        return self.get(identity)

    def reuse(self, identity, *, source_project_id, kind, record_id):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            source = self._project(source_project_id)
            if identity == source_project_id:
                raise ValueError("这份记录已经在当前目标中。")
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等本轮研究结束后再带入材料。")
            collection = {
                "story": "stories",
                "task": "tasks",
                "insight": "insights",
                "question": "questions",
            }[kind]
            original = next(
                (row for row in source["career"].get(collection, []) if row["id"] == record_id),
                None,
            )
            if not original:
                raise ValueError("原目标中已找不到这份记录，请重新选择。")
            understanding = kind in {"insight", "question"}
            records = project["career"].setdefault("questions" if understanding else collection, [])
            provenance = {
                "project_id": source_project_id,
                "project_title": source["title"],
                "record_id": record_id,
                "kind": kind,
            }
            if any(
                all(
                    (row.get("reused_from") or {}).get(key) == provenance[key]
                    for key in ("project_id", "record_id", "kind")
                )
                for row in records
            ):
                return self.get(identity)
            if understanding:
                carried = original.get("carried_understanding") or {}
                records.append(
                    {
                        "id": uuid4().hex,
                        "question": original["question"]
                        if kind == "question"
                        else original.get("open_question") or "这条旧认识在当前岗位中仍然适用吗？",
                        "why_matters": original.get("why_matters", "")
                        if kind == "question"
                        else "从另一个目标保存的个人理解出发，核对它对当前岗位的适用性。",
                        "next_evidence": original.get("next_evidence", "")
                        if kind == "question"
                        else "",
                        "state": "open",
                        "conclusion": "",
                        "source_step_id": None,
                        "conclusion_step_id": None,
                        "origin": "user",
                        "reused_from": provenance,
                        "created_at": now(),
                        "carried_understanding": {
                            "previous_view": original.get(
                                "previous_view", carried.get("previous_view", "")
                            ),
                            "observation": original.get(
                                "observation", carried.get("observation", "")
                            ),
                            "understanding": original.get("current_view", "")
                            if kind == "insight"
                            else original.get("conclusion") or carried.get("understanding", ""),
                            "open_question": original.get("open_question", "")
                            if kind == "insight"
                            else original["question"],
                            "was_in_use": original.get("use_for_research", True)
                            if kind == "insight"
                            else carried.get("was_in_use"),
                            "record_state": original.get("state"),
                            "recorded_at": original.get("updated_at") or original.get("created_at"),
                            "notice": "来自其他目标的个人理解与观察，仅作待验证起点，"
                            "不是当前岗位事实或独立证据。",
                        },
                    }
                )
                self.projects._write(project)
                return self.get(identity)
            if kind == "story" and len(records) >= 12:
                raise ValueError("当前目标已保存足够多的经历或练习，请先集中整理已有内容。")
            document_id = original.get("document_id" if kind == "story" else "artifact_document_id")
            documents = list(project.get("public_document_ids") or [])
            if document_id and document_id not in documents:
                if len(documents) >= 20:
                    raise ValueError("当前目标已有20份材料，请先在研究工作台调整。")
                document = PublicDocumentService(
                    self.repository, self.raw_directory / "public"
                ).document(document_id)
                if document["integrity"] != "verified":
                    raise ValueError("原作品材料暂时无法完整读取，请先检查原记录。")
                documents.append(document_id)
            copied = {
                **original,
                "id": uuid4().hex,
                "reused_from": provenance,
                "created_at": now(),
                "updated_at": now(),
            }
            if kind == "story":
                copied["requirement_key"] = ""
            else:
                copied.update(origin="reused", source_key="user:" + copied["id"], evidence_ids=[])
                copied["question_id"] = None
                copied["previous_task_id"] = None
            records.append(copied)
            project["public_document_ids"] = documents
            self.projects._write(project)
        return self.get(identity)

    def add_insight(self, identity, data, insight_id=None):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            notes = project["career"].setdefault("insights", [])
            task_id = data.get("task_id")
            if task_id and not any(row["id"] == task_id for row in project["career"]["tasks"]):
                raise ValueError("这项练习已不在当前目标中，请重新选择。")
            if data.get("source_step_id") and not any(
                row["step_id"] == data["source_step_id"] for row in project["career"]["runs"]
            ):
                raise ValueError("未找到这次讨论，请重新选择来源。")
            if (claim_index := data.get("source_claim_index")) is not None:
                source_step = next(
                    (
                        row for row in project["steps"]
                        if row["id"] == data.get("source_step_id")
                    ),
                    None,
                )
                run = (
                    self.store.get(source_step["run_id"])
                    if source_step and source_step.get("run_id")
                    else None
                )
                result = (run or {}).get("result") or {}
                if (
                    result.get("status") != "completed"
                    or not 0 <= claim_index < len(result.get("claims", []))
                ):
                    raise ValueError("请选择这次完整分析中的一条判断，或不关联具体判断。")
            replacement = next(
                (row for row in notes if row["id"] == data.get("replaces_insight_id")), None
            )
            if data.get("replaces_insight_id") and (
                not replacement or replacement["id"] == insight_id
            ):
                raise ValueError("请选一份其他认识记录作为接替对象，或不选择接替。")
            if insight_id:
                note = next((row for row in notes if row["id"] == insight_id), None)
                if not note:
                    raise ValueError("未找到这份认识记录。")
                note.update(**data, updated_at=now())
            else:
                notes.append(
                    {
                        "id": uuid4().hex,
                        **data,
                        "origin": "user",
                        "created_at": now(),
                        "use_for_research": True,
                    }
                )
            if replacement:
                replacement.update(use_for_research=False, updated_at=now())
            self.projects._write(project)
        return self.get(identity)

    def save_question(self, identity, data, question_id=None):
        if data["state"] == "answered" and not data["conclusion"].strip():
            raise ValueError("请先写下目前弄清了什么、依据和仍有的限制，再标记为已记结论。")
        with self.store.lock, self.store.db:
            project = self._project(identity)
            questions = project["career"].setdefault("questions", [])
            runs = {row["step_id"]: row for row in project["career"]["runs"]}
            for key in ("source_step_id", "conclusion_step_id"):
                if data.get(key) and data[key] not in runs:
                    raise ValueError("未找到所选讨论，请重新选择或取消关联。")
            if question_id:
                question = next((row for row in questions if row["id"] == question_id), None)
                if not question:
                    raise ValueError("未找到这条调查问题，请刷新清单。")
                question.update(**data, updated_at=now())
            else:
                questions.append({"id": uuid4().hex, **data, "origin": "user", "created_at": now()})
            self.projects._write(project)
        return self.get(identity)

    def use_insight(self, identity, insight_id, use_for_research):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            note = next(
                (row for row in project["career"].get("insights", []) if row["id"] == insight_id),
                None,
            )
            if not note:
                raise ValueError("未找到这条认识记录，请刷新列表。")
            note.update(use_for_research=use_for_research, updated_at=now())
            self.projects._write(project)
        return self.get(identity)

    def save_pitch(self, identity, data, pitch_id=None):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            career = project["career"]
            if data.get("story_id") and not any(
                row["id"] == data["story_id"] for row in career["stories"]
            ):
                raise ValueError("这份经历已不在当前目标中，可改为不绑定具体经历后保存。")
            if data.get("source_step_id") and not any(
                row["step_id"] == data["source_step_id"] and row["kind"] == "pitch"
                for row in career["runs"]
            ):
                raise ValueError("未找到这份讲述素材的研究记录。")
            pitches = career.setdefault("pitches", [])
            previous = next((row for row in pitches if row["id"] == pitch_id), None)
            if pitch_id and not previous:
                raise ValueError("未找到这张讲述卡，请刷新列表。")
            saved = {
                "id": pitch_id or uuid4().hex,
                **data,
                "origin": "user",
                "created_at": previous["created_at"] if previous else now(),
                "updated_at": now(),
            }
            if previous:
                pitches[pitches.index(previous)] = saved
            else:
                pitches.append(saved)
            self.projects._write(project)
        return self.get(identity)

    def prepare(
        self,
        identity,
        kind,
        answer="",
        offline=False,
        question_index=0,
        task_id=None,
        source_step_id=None,
        question="",
        section="requirements",
        hypothesis_a="",
        hypothesis_b="",
        material_id=None,
        allow_public=False,
        story_id=None,
        insight_id=None,
        question_id=None,
        requirement_key="",
        comparison_step_ids=None,
    ):
        if kind not in QUESTIONS and kind not in {"answer", "followup", "ask", "challenge"}:
            raise ValueError("请选择一种研究方式。")
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if not project["job_ids"]:
                raise ValueError("请先在研究工作台为这个目标选择岗位原文。")
            if any(
                step["state"] in {"running", "queued", "interrupted"} for step in project["steps"]
            ):
                raise ValueError("已有一轮研究待完成，请先查看或继续原研究。")
            if kind in {"reflect", "challenge", "ask", "plan"} and task_id:
                task = next(
                    (row for row in project["career"]["tasks"] if row["id"] == task_id), None
                )
                if not task or not task["outcome"].strip():
                    raise ValueError("请先为这项练习记录实际观察，再开始反思。")
                if kind in {"reflect", "ask", "plan"}:
                    question_id = question_id or task.get("question_id")
            user_question = question.strip() if kind == "ask" else ""
            selected_requirement = None
            continued_requirement = None
            if kind == "evidence":
                selected_requirement = next(
                    (
                        row
                        for row in self.get(identity)["requirements"]
                        if row["key"] == requirement_key
                    ),
                    None,
                )
                if not selected_requirement:
                    raise ValueError("请先选择当前分析中的一项岗位要求。")
                if any(not row["available"] for row in selected_requirement["proof"]["records"]):
                    raise ValueError("有一份材料已移出目标，请先调整这项要求的证据。")
            if question_id:
                saved_question = next(
                    (
                        row
                        for row in project["career"].get("questions", [])
                        if row["id"] == question_id
                    ),
                    None,
                )
                if not saved_question or kind not in {"ask", "plan", "reflect"}:
                    raise ValueError("请选择已保存的调查问题，再继续提问、设计验证或反思。")
            comparison_step_ids = comparison_step_ids or []
            if comparison_step_ids:
                candidates = {
                    row["step_id"]: row
                    for row in self.get(identity)["results"]
                    if row.get("question_id") == question_id
                    and row.get("result")
                    and row["result"]["status"] == "completed"
                    and row["state"] != "abandoned"
                }
                if (
                    kind != "ask"
                    or not question_id
                    or len(set(comparison_step_ids)) != 2
                    or not all(step_id in candidates for step_id in comparison_step_ids)
                ):
                    raise ValueError("请选择同一调查问题下两次已完整形成的回答进行对照。")
            if insight_id:
                insight = next(
                    (
                        row
                        for row in project["career"].get("insights", [])
                        if row["id"] == insight_id
                    ),
                    None,
                )
                if not insight:
                    raise ValueError("未找到要核对的认识，请重新选择。")
                task_id = task_id or insight.get("task_id")
            if kind == "pitch":
                story = next(
                    (row for row in project["career"]["stories"] if row["id"] == story_id), None
                )
                if not story:
                    raise ValueError("请先选择一份已保存的真实经历，再整理讲述素材。")
                if story["document_id"] not in (project.get("public_document_ids") or []):
                    raise ValueError("这份经历原文已移出研究资料，请先重新加入原文。")
            answer_document_id, answer_record = None, None
            if material_id and material_id not in (project.get("public_document_ids") or []):
                raise ValueError("这份资料已不在当前目标中，请重新选择或先加入资料。")
            if kind in {"answer", "followup", "ask"} or (kind == "plan" and source_step_id):
                sources = [
                    row
                    for row in self.get(identity)["results"]
                    if row["current"] and row["result"]["status"] == "completed"
                ]
            if kind == "plan" and source_step_id:
                previous = next(
                    (
                        row
                        for row in sources
                        if row["step_id"] == source_step_id and row["kind"] == "answer"
                    ),
                    None,
                )
                if not previous:
                    raise ValueError("请选择一份当前目标下已完成反馈的回答。")
                task_id = task_id or previous.get("task_id")
                if task_id:
                    task = next(row for row in project["career"]["tasks"] if row["id"] == task_id)
                    question_id = question_id or task.get("question_id")
                answer_document_id = previous.get("answer_document_id")
                answer_record = previous
                feedback = "\n".join(
                    [claim["text"] for claim in previous["result"]["claims"]]
                    + previous["result"].get("gaps", [])
                )[:1000]
                question = (
                    QUESTIONS["plan"] + "\n本次只围绕这次模拟面试回答的证据缺口，设计一个最小练习。"
                    "不要把表达不清直接当作能力不会，先区分需要重新表达与确实缺少实际观察。"
                    "本次面试问题："
                    + previous["interview_question"][:700]
                    + "\n上一轮研究反馈（待结合原文核对）："
                    + feedback
                    + "\n按selected_answer读取用户回答原文，不照抄旧反馈作为事实。"
                    "最多给application_plan中的一个动作，检查方式应有机会发现失败或反例，"
                    "而不是保证一次练习就能胜任岗位。"
                )
                reply = previous["step_id"]
            elif kind == "challenge":
                if not hypothesis_a.strip() or not hypothesis_b.strip():
                    raise ValueError("请分别写下两种想对照的解释。")
                user_question = (
                    "解释 A：" + hypothesis_a.strip() + "\n解释 B：" + hypothesis_b.strip()
                )
                section = "experiments"
                question = (
                    "请对照两种尚未验证的解释，不预设必须有一方正确：\n"
                    + user_question
                    + "\n先读取当前岗位原文；若选定了实验，优先读取career_evidence中所选实验的"
                    "artifact_document归档记录，对照实际观察。"
                    "分别说明每种解释支持什么、受到哪些反例挑战，以及现有资料无法区分什么。"
                    "不要因为表述不同就断定互斥，也允许两者同时成立或都不成立。"
                    "用户日志是用户提供的材料，未由你独立运行，不证明因果或企业招聘要求。"
                    "claims只写有已读原文引用的判断，区分岗位原文、用户记录与分析推断，"
                    "把待判断的问题留在gaps。最后如有必要，通过application_plan提出最多一个"
                    "能区分两种解释的最小验证，写具体产物与检查方式，不编造结果，不安排额外调查。"
                )
                reply = None
            elif kind == "ask":
                if not user_question:
                    raise ValueError("请先写下你想弄清楚的问题。")
                previous = next((row for row in sources if row["step_id"] == source_step_id), None)
                if source_step_id and not previous:
                    raise ValueError("这份分析已不是当前目标下的结果，请重新选择或直接提问。")
                previous_text = ""
                if previous:
                    previous_step = next(
                        row for row in project["steps"] if row["id"] == previous["step_id"]
                    )
                    continued_requirement = previous_step.get("career_requirement")
                    answer_document_id = previous.get("answer_document_id")
                    answer_record = previous if previous.get("answer") else None
                    previous_text = (
                        "\n用户希望接着讨论的旧分析（不是新证据，请重新核对原文）：\n"
                        + "\n".join(
                            ([previous["user_question"]] if previous.get("user_question") else [])
                            + (
                                [
                                    "当时的问题：" + previous["interview_question"],
                                    "当时用户自述的回答：" + previous["answer"],
                                ]
                                if previous.get("answer")
                                else []
                            )
                            + [claim["text"] for claim in previous["result"]["claims"]]
                            + previous["result"].get("gaps", [])
                        )[:1000]
                    )
                    section = previous.get("section") or {
                        "role": "requirements",
                        "map": "requirements",
                        "gaps": "stories",
                        "plan": "experiments",
                        "reflect": "experiments",
                        "interview": "interview",
                        "answer": "interview",
                        "followup": "interview",
                    }.get(previous["kind"], section)
                question = (
                    "用户这次真正想弄清楚的问题：\n"
                    + user_question
                    + previous_text
                    + "\n围绕用户的问题，结合当前岗位原文、个人背景、经历与练习记录给出具体回答。"
                    "区分原文事实、用户自述和你的推断；旧分析不能充当新的原文证据。"
                    "如果问题中的前提不成立，指出前提；缺信息就明确缺什么，不能凭空补全。"
                    "优先解释工作为什么这样做、取舍是什么、对求职者下一步有什么具体影响。"
                    "不泛讲学习路线，不给虚假匹配分，不安排额外调查；确有必要时最多建议一个验证动作。"
                )
                if material_id:
                    question += (
                        "本次用户已选定一份资料，优先按career_evidence.selected_material中的"
                        "document_id读取归档正文，再结合岗位原文回答；不能把标题当证据，"
                        "也不能把业务或技术说明推成所选岗位个人职责。"
                    )
                reply = previous["step_id"] if previous else None
            elif kind == "followup":
                previous = next(
                    (
                        row
                        for row in sources
                        if row["kind"] == "answer" and row["step_id"] == source_step_id
                    ),
                    None,
                )
                if not previous:
                    raise ValueError("请选择一份已完成反馈的回答，再继续追问。")
                answer_document_id = previous.get("answer_document_id")
                answer_record = previous
                story_id, task_id = previous.get("story_id"), previous.get("task_id")
                feedback = "\n".join(
                    [claim["text"] for claim in previous["result"]["claims"]]
                    + previous["result"].get("gaps", [])
                )[:400]
                question = (
                    "根据这份用户回答继续追问，而不是重新安排一套通用面试。\n"
                    "原问题："
                    + previous["interview_question"][:500]
                    + "\n用户自述回答（未经独立核实）："
                    + previous["answer"]
                    + "\n上一轮研究反馈（仍需核对，不是企业事实）："
                    + feedback
                    + "\n结合岗位原文，在gaps中给出最多两道完整的面试追问，每道使用问号。"
                    "追问必须指出这份回答中具体需要澄清的行动、取舍、证据或责任边界；"
                    "说明为什么追问以及应拿什么材料回答。不要替用户回答或编造指标，"
                    "claims只列有引用的岗位依据或回答中的自述依据，不生成行动计划，不安排额外调查。"
                )
                reply = previous["step_id"]
            elif kind == "answer":
                if not answer.strip():
                    raise ValueError("请先写下你的真实回答。")
                interview = next(
                    (
                        row
                        for row in sources
                        if row["kind"] in {"interview", "followup"}
                        and (not source_step_id or row["step_id"] == source_step_id)
                    ),
                    None,
                )
                if not interview:
                    raise ValueError("请先选择当前目标下已生成的面试问题。")
                interview_result = interview["result"]
                story_id, task_id = interview.get("story_id"), interview.get("task_id")
                questions = [
                    text for text in interview_result.get("gaps", []) if "？" in text or "?" in text
                ]
                if interview_result.get("status") != "completed" or not 0 <= question_index < len(
                    questions
                ):
                    raise ValueError("请先选择一份已生成的面试问题。")
                question = (
                    "本次模拟面试问题：" + questions[question_index][:1000] + "\n"
                    "这是用户的自述回答，不是招聘原文或已核验事实：\n"
                    + answer
                    + "\n请对照本次明确选中的面试问题、岗位原文和用户经历反馈：回答覆盖了什么，"
                    "哪些主张还缺证据，下一步最有价值的追问是什么。区分表达问题和能力未知，"
                    "反馈评价属于分析推断，应引用用户回答原文及相关岗位依据；"
                    "不能只拿JD证明用户说过什么或亲自做过什么。"
                    "不编造经历或替用户补出成功指标，不给虚假分数。最多三条具体反馈，不安排额外调查。"
                )
                reply = interview["step_id"]
                source_step_id = interview["step_id"]
                answer_record = {"interview_question": questions[question_index], "answer": answer}
            else:
                question = QUESTIONS[kind]
                reply = None
            focused_document_id = None
            interview_kinds = {"interview", "answer", "followup"}
            if kind in interview_kinds:
                if story_id and task_id:
                    raise ValueError("本轮请选择一份经历或一个工作样本作为面试重点。")
                if story_id:
                    story = next(
                        (row for row in project["career"]["stories"] if row["id"] == story_id),
                        None,
                    )
                    if not story or story["document_id"] not in project["public_document_ids"]:
                        raise ValueError("这份经历已不在当前目标中，请重新选择面试重点。")
                    focused_document_id = story["document_id"]
                    question += (
                        "本次面试明确围绕career_evidence.selected_story对应的这份经历，"
                        "请先读取其document_id对应原文，再结合岗位提问或反馈。"
                        "后续回答和追问保持这个项目的场景、个人行动与限制，不能混入其他经历。"
                    )
                if task_id:
                    task = next(
                        (row for row in project["career"]["tasks"] if row["id"] == task_id), None
                    )
                    if not task or not task["outcome"].strip():
                        raise ValueError("请先为这个工作样本记录实际观察，再围绕它面试。")
                    focused_document_id = task.get("artifact_document_id")
                    if (
                        focused_document_id
                        and focused_document_id not in project["public_document_ids"]
                    ):
                        raise ValueError("这份作品材料已移出目标，请重新选择面试重点。")
                    question += (
                        "本次面试明确围绕career_evidence.selected_experiment_id对应的工作样本，"
                        "对照其完整预期和实际观察提问或反馈，有artifact_document时先读取正文。"
                        "关注失败、取舍、检查方法和迁移限制；后续追问保持同一个样本。"
                        "done仅表示记下结果，不能把失败观察改写成成功或真实业务经验。"
                    )
            if answer_document_id or answer_record:
                question += (
                    "请先按career_evidence.selected_answer.document_id读取本次所讨论的回答全文，"
                    "再作反馈或追问。回答是用户自述，不代表经历已核实或能力已经证明。"
                )
            if insight_id and kind in {"ask", "challenge"}:
                question += (
                    "用户明确选中的个人认识在career_evidence.selected_learning_note，"
                    "请回查原文和观察，说明它还能支持什么、哪些需修正、哪些仍未知。"
                    "它可能已经搁置，不因本次讨论而自动恢复；不因记录较新或较旧就判断真假。"
                )
            if question_id:
                question += (
                    "本次围绕career_evidence.selected_inquiry中的持续调查问题展开，"
                    "结合用户本次提问、关心它的理由和希望补充的证据，回读相关原文。"
                    "若用户已有结论，它仍是待查证的个人记录，不当作独立事实。"
                    "若含carried_understanding，它是另一个目标下保存的理解，先核对当前岗位的适用条件；"
                    "原材料不在本轮范围时，明确无法重核旧结论，不用旧认识替代当前原文。"
                    "明确哪些已经有材料支持、哪些还不能回答，并给出下一步最有价值的查证方向。"
                    "不因为本轮生成回答而宣称问题已解决。"
                )
                if kind == "plan":
                    question += (
                        "本次只为这个调查问题设计一个最小工作样本验证，不扩大成通用学习路线。"
                        "先写要区分的解释，再给出实际产物和可能推翻预期的检查方式。"
                    )
            if kind == "ask" and task_id:
                question += (
                    "用户本次带回的具体练习在career_evidence.selected_experiment_id对应记录，"
                    "对照完整预期、实际观察和附带作品原文回答原问题；不能把done状态当成成功。"
                    "有artifact_document时先读取正文，说明哪些原先解释被支持或挑战、哪些仍未知。"
                )
            if kind == "plan" and task_id:
                question += (
                    "这次只基于selected_experiment_id对应实验的完整实际观察设计一个后续验证。"
                    "有artifact_document时先读取正文，不能把原来的预期当成已发生的结果。"
                    "明确本次改变或控制什么、什么观察能区分仍未解决的解释，"
                    "最多给application_plan中的一个动作，不重复安排已经做过的检查。"
                )
            if kind in {"reflect", "ask", "challenge", "plan"} and task_id:
                question += (
                    "若career_evidence.previous_experiment存在，它是本次实验所接续的上次记录。"
                    "对照两次设计、design_change与实际观察，有两份作品原文时都应读取。"
                    "说明哪些条件改变或未说明，不能仅因后一结果不同就证明因果或能力提升。"
                )
            if continued_requirement:
                question += (
                    "本次沿着一项岗位要求的证据对照继续讨论，原先选定的材料在"
                    "career_evidence.selected_requirement。请按本轮可用目录回查原文，"
                    "用户原先写的相关性和缺口不是独立事实，旧讨论也不是新增证据。"
                    "若资料已不在本轮可读范围，明确指出，不补造或假装已经读取。"
                )
            if comparison_step_ids:
                question += (
                    "用户本次明确对照的两次研究在selected_inquiry.earlier_discussions，"
                    "按所选顺序比较两次提问、判断和来源。说明哪些差异可能来自问题或材料变化，"
                    "保留claim_details_to_recheck中的必备、加分与未说明强度，以及明示、归纳和推断区别。"
                    "哪些还不能解释；句子不同不等于矛盾，引用更多也不自动意味着更可靠。"
                    "旧研究和旧引用只是回查线索，请读取本轮可用原文再作判断；"
                    "若原资料不在本轮范围，保留未知，不把较新的一次当作正确答案。"
                )
            used = self.projects.usage(project)
            allow_public = bool(allow_public and not offline)
            if allow_public:
                public_limit = project["budget"]["max_public"] or 8
                if used["public"] + 4 > public_limit:
                    raise ValueError(
                        "本目标剩余公开补查额度不足一轮，可关闭补查并继续使用已保存原文。"
                    )
                if project["budget"]["max_public"] == 0:
                    project["budget"]["max_public"] = public_limit
                    self.projects._write(project)
            calls_left = project["budget"]["max_calls"] - used["reserved_calls"]
            seconds_left = int(project["budget"]["max_seconds"] - used["reserved_seconds"])
            if not offline and (calls_left < 2 or seconds_left < 1):
                raise ValueError("本目标的模型调用或时间额度已用完，仍可整理资料、记录观察和认识。")
            project = self.projects.add(
                identity,
                question,
                revision=project["revision"],
                max_calls=6 if offline else min(6, calls_left),
                timeout=150 if offline else min(150, seconds_left),
                offline=offline,
                allow_public=allow_public,
                coverage_mode="question",
                approach="work_map" if kind == "map" else "standard",
                reply_to_step_id=reply,
                completion="给出对应原文、个人自述和待验证方向，帮助用户理解工作并准备真实证据。",
            )
            if kind in {"role", "map"}:
                personal = personal_documents(project["career"])
                project["steps"][-1]["public_document_ids"] = [
                    doc_id
                    for doc_id in project["steps"][-1].get("public_document_ids", [])
                    if doc_id not in personal
                ]
            if answer_record and not answer_document_id:
                document = PublicDocumentService(
                    self.repository, self.raw_directory / "public"
                ).archive_text(
                    "模拟面试回答 · " + project["title"],
                    "用户模拟面试回答，未经独立核实，不是招聘原文或能力认证。\n"
                    "面试问题："
                    + answer_record["interview_question"]
                    + "\n用户回答：\n"
                    + answer_record["answer"],
                    "用户的模拟面试回答，仅作为原话依据；经历及效果未经独立核实。",
                )["document"]
                answer_document_id = document["id"]
                if answer_record.get("step_id"):
                    original = next(
                        row
                        for row in project["career"]["runs"]
                        if row["step_id"] == answer_record["step_id"]
                    )
                    original["answer_document_id"] = answer_document_id
            if answer_document_id:
                step = project["steps"][-1]
                documents = list(step.get("public_document_ids") or [])
                if answer_document_id not in documents:
                    preferred = [focused_document_id, project["career"].get("resume_document_id")]
                    preferred.extend(
                        row["document_id"] for row in project["career"]["stories"][-3:]
                    )
                    preferred.extend(
                        row.get("artifact_document_id")
                        for row in [
                            item for item in project["career"]["tasks"] if item.get("outcome")
                        ][-3:]
                    )
                    if material_id:
                        preferred.insert(0, material_id)
                    selected = list(
                        dict.fromkeys([key for key in preferred if key in documents] + documents)
                    )[:19]
                    step["public_document_ids"] = [*selected, answer_document_id]
                    step["career_omitted_documents"] = len(documents) - len(selected)
                step["career_answer_document_id"] = answer_document_id
            has_task = task_id and (
                kind in {"reflect", "challenge", "ask", "plan"} | interview_kinds or insight_id
            )
            project["career"]["runs"].append(
                {
                    "kind": kind,
                    "step_id": project["steps"][-1]["id"],
                    "answer": answer,
                    "answer_document_id": answer_document_id,
                    "question_index": question_index if kind == "answer" else None,
                    "source_step_id": source_step_id
                    if kind in {"answer", "followup", "ask", "plan"}
                    else None,
                    "user_question": user_question,
                    "section": section if kind in {"ask", "challenge"} else None,
                    "hypothesis_a": hypothesis_a.strip() if kind == "challenge" else "",
                    "hypothesis_b": hypothesis_b.strip() if kind == "challenge" else "",
                    "material_id": material_id if kind == "ask" else None,
                    "story_id": story_id if kind in {"pitch"} | interview_kinds else None,
                    "insight_id": insight_id if kind in {"ask", "challenge"} else None,
                    "question_id": question_id,
                    "comparison_step_ids": comparison_step_ids,
                    "requirement_key": requirement_key if kind == "evidence" else "",
                    "requirement_text": selected_requirement["text"]
                    if selected_requirement
                    else "",
                    "interview_question": questions[question_index] if kind == "answer" else "",
                    "task_id": task_id if has_task else None,
                    "created_at": now(),
                }
            )
            if has_task:
                project["steps"][-1]["career_task_id"] = task_id
            if insight_id and kind in {"ask", "challenge"}:
                project["steps"][-1]["career_insight_id"] = insight_id
            if question_id:
                project["steps"][-1]["career_question_id"] = question_id
                if comparison_step_ids:
                    project["steps"][-1]["career_comparison_steps"] = comparison_step_ids
            if selected_requirement:
                project["steps"][-1]["career_requirement"] = {
                    **{
                        key: selected_requirement[key]
                        for key in ("key", "text", "category", "requirement", "evidence")
                    },
                    **selected_requirement["proof"],
                    "notice": "用户选定的材料与判断，关联不代表胜任，须回读原文核对。",
                }
            elif continued_requirement:
                project["steps"][-1]["career_requirement"] = continued_requirement
            project["steps"][-1]["career_action"] = kind
            if kind == "ask" and material_id:
                project["steps"][-1]["career_material_id"] = material_id
            if story_id and kind in {"pitch"} | interview_kinds:
                project["steps"][-1]["career_story_id"] = story_id
            self.projects._write(project)
            return {"project_id": identity, "step_id": project["steps"][-1]["id"]}

    def import_tasks(self, identity, step_id):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            step = next((row for row in project["steps"] if row["id"] == step_id), None)
            if not step or not step.get("run_id"):
                raise ValueError("未找到这份研究建议。")
            if step["scope_version"] != project["scope_version"]:
                raise ValueError("这份建议来自调整前的目标，请先按当前岗位重新研究。")
            run = self.store.get(step["run_id"])
            result = run.get("result") or {}
            if run["state"] == "invalidated" or result.get("status") != "completed":
                raise ValueError("这份建议尚不可用，请查看原研究。")
            reviews = QualityReviewService(self.store, self.repository).list_run(step["run_id"])
            if any(row["status"] == "rejected" and not row["stale_result"] for row in reviews[:1]):
                raise ValueError("这份建议的质量核对未通过，请先查看或修正原研究。")
            audit = audit_result(result, self.repository)
            if (
                audit["changed_sources"]
                or audit["stale_dependencies"]
                or audit["stale_memory"]
                or audit["stale_knowledge"]
            ):
                raise ValueError("建议依据已有变化，请先重新研究。")
            tasks = project["career"]["tasks"]
            source = next(
                (row for row in project["career"]["runs"] if row["step_id"] == step_id), {}
            )
            for index, action in enumerate(
                (result.get("application_plan") or {}).get("actions", [])
            ):
                key = f"{step['run_id']}:{index}"
                if any(row["source_key"] == key for row in tasks):
                    continue
                tasks.append(
                    {
                        "id": uuid4().hex,
                        "source_key": key,
                        "origin": "research",
                        "question_id": source.get("question_id"),
                        "previous_task_id": source.get("task_id"),
                        "design_change": "",
                        **action,
                        "state": "planned",
                        "outcome": "",
                        "hypothesis": "",
                        "artifact": "",
                        "created_at": now(),
                    }
                )
            self.projects._write(project)
        return self.get(identity)

    def add_experiment(self, identity, data):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if data.get("question_id") and not any(
                row["id"] == data["question_id"] for row in project["career"].get("questions", [])
            ):
                raise ValueError("未找到这项练习要检验的调查问题，请重新选择。")
            tasks = project["career"]["tasks"]
            if previous_id := data.get("previous_task_id"):
                previous = next((row for row in tasks if row["id"] == previous_id), None)
                if not previous or not previous.get("outcome", "").strip():
                    raise ValueError("请先记录上次实验的实际观察，再设计后续验证。")
                data = {
                    **data,
                    "question_id": data.get("question_id") or previous.get("question_id"),
                }
            task_id = uuid4().hex
            tasks.append(
                {
                    "id": task_id,
                    "source_key": "user:" + task_id,
                    "origin": "user",
                    **data,
                    "evidence_ids": [],
                    "assumptions": [],
                    "state": "planned",
                    "outcome": "",
                    "artifact": "",
                    "created_at": now(),
                }
            )
            self.projects._write(project)
        return self.get(identity)

    def update_task(
        self,
        identity,
        task_id,
        *,
        state,
        outcome,
        artifact,
        hypothesis="",
        artifact_title="工作样本材料",
        artifact_text="",
        design_change="",
    ):
        if state == "done" and not outcome.strip():
            raise ValueError("请先记录实际做了什么或观察到什么，再标记为已记录结果。")
        with self.store.lock, self.store.db:
            project = self._project(identity)
            task = next((row for row in project["career"]["tasks"] if row["id"] == task_id), None)
            if not task:
                raise ValueError("未找到这项练习。")
            if artifact_text.strip():
                if any(step["state"] == "running" for step in project["steps"]):
                    raise ValueError("请等本轮研究结束后再保存作品材料，输入仍保留。")
                previous = task.get("artifact_document_id")
                if not previous and len(project.get("public_document_ids") or []) >= 20:
                    raise ValueError("这个目标已保存20份资料，请先在研究工作台调整。")
                title = artifact_title.strip() or task["title"] + " · 作品材料"
                document = PublicDocumentService(
                    self.repository, self.raw_directory / "public"
                ).archive_text(
                    title,
                    "用户提供的个人练习产物或运行记录，尚未独立执行或验证。\n" + artifact_text,
                    "用户提供的工作样本材料，不是招聘要求或独立评测结果。",
                )["document"]
                task.update(artifact_document_id=document["id"], artifact_title=title)
                project["public_document_ids"] = [
                    key for key in (project.get("public_document_ids") or []) if key != previous
                ] + [document["id"]]
            task.update(
                state=state,
                outcome=outcome,
                artifact=artifact,
                hypothesis=hypothesis,
                design_change=design_change,
                updated_at=now(),
            )
            self.projects._write(project)
        return self.get(identity)
