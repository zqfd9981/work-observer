"""A job seeker's evidence, experiments and interview practice in one research project."""

import json
from uuid import uuid4

from work_observer.collection.contracts import now
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.memory.service import MemoryService
from work_observer.quality.reviews import QualityReviewService
from work_observer.reports.results import audit_result
from work_observer.research.applications import PREFIX
from work_observer.research.applications import background as application_background
from work_observer.research.projects import ProjectService

QUESTIONS = {
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
            current = (
                available
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
                    requirements.append(
                        {
                            "key": f"{step['run_id']}:{index}",
                            **claim,
                            "evidence": [evidence[key] for key in claim["evidence_ids"]],
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
            "requirements": requirements,
            "results": results,
            "usage": self.projects.usage(project),
            "budget": project["budget"],
            "running": any(step["state"] == "running" for step in project["steps"]),
        }

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
            if insight_id:
                note = next((row for row in notes if row["id"] == insight_id), None)
                if not note:
                    raise ValueError("未找到这份认识记录。")
                note.update(**data, updated_at=now())
            else:
                notes.append({"id": uuid4().hex, **data, "origin": "user", "created_at": now()})
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
    ):
        if kind not in QUESTIONS and kind not in {"answer", "followup", "ask"}:
            raise ValueError("请选择一种研究方式。")
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if not project["job_ids"]:
                raise ValueError("请先在研究工作台为这个目标选择岗位原文。")
            if any(
                step["state"] in {"running", "queued", "interrupted"} for step in project["steps"]
            ):
                raise ValueError("已有一轮研究待完成，请先查看或继续原研究。")
            if kind == "reflect" and task_id:
                task = next(
                    (row for row in project["career"]["tasks"] if row["id"] == task_id), None
                )
                if not task or not task["outcome"].strip():
                    raise ValueError("请先为这项练习记录实际观察，再开始反思。")
            user_question = question.strip() if kind == "ask" else ""
            if kind in {"answer", "followup", "ask"}:
                sources = [
                    row
                    for row in self.get(identity)["results"]
                    if row["current"] and row["result"]["status"] == "completed"
                ]
            if kind == "ask":
                if not user_question:
                    raise ValueError("请先写下你想弄清楚的问题。")
                previous = next((row for row in sources if row["step_id"] == source_step_id), None)
                if source_step_id and not previous:
                    raise ValueError("这份分析已不是当前目标下的结果，请重新选择或直接提问。")
                previous_text = ""
                if previous:
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
                    "claims只列有引用的岗位依据，不生成行动计划，不安排额外调查。"
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
                    "不编造经历或替用户补出成功指标，不给虚假分数。最多三条具体反馈，不安排额外调查。"
                )
                reply = interview["step_id"]
                source_step_id = interview["step_id"]
            else:
                question = QUESTIONS[kind]
                reply = None
            project = self.projects.add(
                identity,
                question,
                revision=project["revision"],
                max_calls=6,
                timeout=150,
                offline=offline,
                allow_public=False,
                coverage_mode="question",
                approach="work_map" if kind == "map" else "standard",
                reply_to_step_id=reply,
                completion="给出对应原文、个人自述和待验证方向，帮助用户理解工作并准备真实证据。",
            )
            project["career"]["runs"].append(
                {
                    "kind": kind,
                    "step_id": project["steps"][-1]["id"],
                    "answer": answer,
                    "question_index": question_index if kind == "answer" else None,
                    "source_step_id": source_step_id
                    if kind in {"answer", "followup", "ask"}
                    else None,
                    "user_question": user_question,
                    "section": section if kind == "ask" else None,
                    "interview_question": questions[question_index] if kind == "answer" else "",
                    "task_id": task_id if kind == "reflect" else None,
                    "created_at": now(),
                }
            )
            if kind == "reflect" and task_id:
                project["steps"][-1]["career_task_id"] = task_id
            project["steps"][-1]["career_action"] = kind
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
            for index, action in enumerate(
                (result.get("application_plan") or {}).get("actions", [])
            ):
                key = f"{step['run_id']}:{index}"
                if any(row["source_key"] == key for row in tasks):
                    continue
                if len(tasks) >= 24:
                    raise ValueError("这个目标已保存24项练习，请先集中完成已有练习。")
                tasks.append(
                    {
                        "id": uuid4().hex,
                        "source_key": key,
                        "origin": "research",
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
            tasks = project["career"]["tasks"]
            if len(tasks) >= 24:
                raise ValueError("这个目标已保存24项练习，请先集中完成已有练习。")
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
                updated_at=now(),
            )
            self.projects._write(project)
        return self.get(identity)
