"""A job seeker's evidence, experiments and interview practice in one research project."""

import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.connectors.public_models import PublicDocument
from work_observer.memory.service import MemoryService, _tokens
from work_observer.quality.reviews import QualityReviewService
from work_observer.reports.results import audit_result
from work_observer.research.applications import PREFIX
from work_observer.research.applications import background as application_background
from work_observer.research.archived_sources import catalog as archive_catalog
from work_observer.research.projects import ProjectService, step_continuation
from work_observer.retrieval.catalog import Catalog
from work_observer.retrieval.unified import UnifiedRetrieval
from work_observer.text_match import match_text

QUESTIONS = {
    "teachback": (
        "围绕career_evidence.selected_inquiry做一次理解自测，检验用户能否用自己的话解释工作。"
        "先读取相关工作资料，参考原问题、地图关系、个人认识中的待验证解释与限定。"
        "在gaps给出最多三道完整问题，每道使用问号：先解释为什么，再改变一个条件或提供反例，"
        "最后追问哪些证据能支持或挑战解释。问题应可根据当前资料作有限判断，缺信息可以回答未知。"
        "这是概念理解练习，不是个人经历核实；不要求虚构做过的项目，不替用户作答。"
        "claims只列有原文依据的背景，requirement使用unspecified，不打掌握分或宣称学会。"
        "不生成行动计划，不安排额外调查；等待用户回答再反馈。"
    ),
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
        "hypothesis写这次准备检验的解释及条件，completion_check写具体输入输出与可能推翻预期的结果；"
        "这些是待验证的实验设计，不是已经成立的结论。"
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

MATERIAL_QUESTIONS = {
    "role": (
        "帮助用户理解已保存工作资料描述的业务问题、实际任务、交付物、工具和责任边界。"
        "先读取归档正文，用最多8条有引用的判断串起工作如何产生结果。"
        "当前没有目标JD，不能把产品功能、技术规范或用户笔记改成某个岗位的必备/加分条件，"
        "requirement使用unspecified；未说明的职责与交付物保留未知。"
        "保留来源性质，不把用户粘贴的材料当作独立核实；不评价个人是否胜任，不生成行动计划。"
    ),
    "map": (
        "把已保存工作资料画成可探索的工作地图。先读取归档正文，解释业务问题、任务与交付物，"
        "再连接有依据的能力、工具与责任关系，最多8条判断、4条工作关系。"
        "当前没有目标JD；工作联系是资料描述或待验证解释，不是招聘资格，requirement使用unspecified。"
        "关系写清理由和迁移限制，不能把工具功能推成个人职责；没有依据就保留未知。"
        "材料是用户提供的记录，来源与实际执行尚需核实；不评价个人胜任，不生成行动计划。"
    ),
}


def personal_documents(career):
    return {
        career.get("resume_document_id"),
        *(row["document_id"] for row in career["stories"]),
        *(row.get("artifact_document_id") for row in career["tasks"]),
    } - {None}


def relevant_documents(repository, identities, query):
    tokens = _tokens(query)
    positions = {key: index for index, key in enumerate(identities)}
    ranked = []
    with Session(repository.engine) as session:
        for identity, title, publisher, text in session.execute(
            select(PublicDocument.id, PublicDocument.title, PublicDocument.publisher,
                   PublicDocument.text).where(PublicDocument.id.in_(identities))
        ):
            score = len(tokens & _tokens("\n".join((title, publisher, text))))
            if score:
                ranked.append((score, positions[identity], identity))
    return [identity for _, _, identity in sorted(ranked, reverse=True)]


def research_documents(project, kind, preferred=(), *, repository=None, query=""):
    career = project["career"]
    library = list(dict.fromkeys(project.get("public_document_ids") or []))
    if kind in {"role", "map"}:
        personal = personal_documents(career)
        available = [key for key in library if key not in personal]
        preferred = []
    else:
        available = library
        preferred = [*preferred, career.get("resume_document_id")]
        preferred.extend(row["document_id"] for row in career["stories"][-3:])
        preferred.extend(row.get("artifact_document_id") for row in [
            item for item in career["tasks"] if item.get("outcome")
        ][-3:])
    related = relevant_documents(repository, available, query) if (
        repository is not None and len(available) > 20 and query.strip()
    ) else []
    selected = list(dict.fromkeys(
        [key for key in preferred if key in available] + related + list(reversed(available))
    ))[:20]
    return selected, len(library) - len(selected)


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
        material_title="起始工作资料",
        material_text="",
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
        if material_text.strip():
            self.add_material(
                project["id"], title=material_title.strip() or "起始工作资料", text=material_text,
                source_name="用户提供的起始工作资料，来源与内容尚需核实。",
            )
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
                "focus_question": next(
                    (q["question"] for q in row["career"].get("questions", [])
                     if q["id"] == row["career"].get("focus_question_id")), None
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
            notes = memory.list()
            profile = application_background(notes, identity)
            profile_id = (profile or {}).get("memory_id") or next(
                (row["id"] for row in notes
                 if row["id"] == project["career"].get("background_memory_id")
                 and row["status"] == "active"), None
            )
            content = PREFIX + json.dumps(
                {"background": background, "goal": goal, "constraints": constraints},
                ensure_ascii=False,
            )
            note = (
                memory.revise(profile_id, content)
                if profile_id
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

    def search(
        self, identity, *, q, scope="goal", record_kind="all", records_offset=0, sources_offset=0
    ):
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
            offset=sources_offset,
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
            if record_kind != "all" and record_kind != kind:
                return
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
                passage = row.get("source_passage") or {}
                add(
                    owner,
                    "question",
                    row,
                    row["question"],
                    "\n".join(
                        row.get(key, "") for key in (
                            "why_matters", "next_evidence", "conclusion",
                            "hypothesis_a", "hypothesis_b",
                        )
                    )
                    + "\n"
                    + "\n".join(
                        carried.get(key, "")
                        for key in ("understanding", "observation", "previous_view")
                    )
                    + "\n" + passage.get("title", "") + "\n" + passage.get("quote", "")
                    + "\n" + "\n".join(
                        "\n".join(item.get(key, "") for key in ("title", "quote", "user_note"))
                        for item in row.get("evidence_passages", [])
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
        records.sort(
            key=lambda row: (row["recorded_at"] or "", row["project_id"], row["kind"], row["id"]),
            reverse=True,
        )
        selected_records = records[records_offset : records_offset + 24]
        next_records = records_offset + len(selected_records)
        return {
            "query": q,
            "scope": scope,
            "originals": originals,
            "record_kind": record_kind,
            "records": selected_records,
            "record_count": len(records),
            "records_offset": records_offset,
            "next_records_offset": next_records if next_records < len(records) else None,
            "records_truncated": next_records < len(records),
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
                    "document_ids": list(step.get("public_document_ids") or []),
                    "omitted_documents": step.get("career_omitted_documents", 0),
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
            "focus_question_id": career.get("focus_question_id"),
            "document_ids": project.get("public_document_ids", []),
            "materials": archive_catalog(
                self.repository,
                [
                    key
                    for key in (project.get("public_document_ids") or [])
                    if key not in personal_documents(career)
                ], limit=None,
            ),
            "discovered_materials": archive_catalog(
                self.repository,
                [
                    key
                    for key in career.get("researched_document_ids", [])
                    if key not in (project.get("public_document_ids") or [])
                ], limit=None,
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

    def observe_job(self, identity, job_id, data, archive):
        from pydantic import ValidationError

        from work_observer.connectors.manual import ManualJD, import_jd
        from work_observer.storage.models import Job

        with self.store.lock:
            project = self._project(identity)
            if job_id not in project["job_ids"]:
                raise ValueError("请从当前目标中选择要继续观察的岗位。")
            with Session(self.repository.engine) as session:
                job = session.get(Job, job_id)
                if not job or job.source != "manual":
                    raise ValueError("这里只补充人工维护岗位的新原文，平台原文请保留原有来源。")
                try:
                    jd = ManualJD(
                        title=job.title, company=job.company_name_raw,
                        external_id=job.source_job_id,
                        **{key: value for key, value in data.items() if value},
                    )
                except ValidationError as error:
                    message = error.errors()[0]["msg"].removeprefix("Value error, ")
                    raise ValueError(message) from error
            import_jd(self.repository, archive, jd)
        return self.get(identity)

    def add_material(self, identity, *, title, text, source_name=""):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等本轮研究结束后再补充资料，输入仍保留。")
            documents = list(project.get("public_document_ids") or [])
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
                "discussion": "runs",
            }[kind]
            original = next(
                (row for row in source["career"].get(collection, [])
                 if row.get("id", row.get("step_id")) == record_id),
                None,
            )
            if not original:
                raise ValueError("原目标中已找不到这份记录，请重新选择。")
            understanding = kind in {"insight", "question", "discussion"}
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
                if kind == "discussion":
                    step = next(row for row in source["steps"] if row["id"] == record_id)
                    run = self.store.get(step["run_id"]) if step.get("run_id") else {}
                    result = run.get("result") or {}
                    if run.get("state") == "invalidated" or result.get("status") != "completed":
                        raise ValueError(
                            "请选择仍保留完整答复的研究；未完成或已清除的内容不能带入。"
                        )
                    review = next((item for item in QualityReviewService(
                        self.store, self.repository,
                    ).list_run(step["run_id"]) if not item["stale_result"]), None)
                    cited = {ref_id for claim in result.get("claims", [])
                             for ref_id in claim.get("evidence_ids", [])}
                    references = {}
                    for item in result.get("evidence", []):
                        if item["id"] in cited:
                            reference = {key: item.get(key) for key in (
                                "job_id", "public_document_id", "document_id", "snapshot_id",
                                "title", "evidence_kind",
                            )}
                            key = tuple(reference[name] for name in (
                                "job_id", "public_document_id", "document_id", "snapshot_id",
                            ))
                            references[key] = reference
                    records.append({
                        "id": uuid4().hex,
                        "question": original.get("user_question") or
                        "这份旧研究在当前目标中还成立吗？请核对原文、适用条件和仍未知的部分。",
                        "why_matters": "从已保存的研究线索出发，重新核对它对当前目标的适用性。",
                        "next_evidence": "回读当前目标可用的相关原文；旧资料未选入时保留无法重核。",
                        "state": "open", "conclusion": "", "source_step_id": None,
                        "conclusion_step_id": None, "selected_job_ids": [], "origin": "user",
                        "reused_from": provenance, "created_at": now(),
                        "carried_understanding": {
                            "research_claims": [{key: claim.get(key) for key in (
                                "text", "category", "basis", "requirement",
                            )} for claim in result.get("claims", [])],
                            "research_gaps": result.get("gaps", []),
                            "work_map": result.get("work_map"),
                            "source_references": list(references.values()),
                            "source_jobs": [
                                {key: job.get(key) for key in ("id", "title", "company")}
                                for job in result.get("scope", {}).get("jobs", [])
                            ],
                            "source_cutoff": result.get("created_at"),
                            "research_review_status": review["status"] if review else "unreviewed",
                            "recorded_at": original["created_at"],
                            "notice": "历史Agent分析，不是当前岗位事实或独立证据。"
                            "旧引用只供定位；需按本轮已选范围回读原文，不能直接使用旧引用编号。",
                        },
                    })
                    self.projects._write(project)
                    return self.get(identity)
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
            if data.get("question_id") and not any(
                row["id"] == data["question_id"] for row in project["career"].get("questions", [])
            ):
                raise ValueError("请选择当前目标中的调查问题，或取消关联。")
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

    def focus_question(self, identity, question_id):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if question_id and not any(
                row["id"] == question_id for row in project["career"].get("questions", [])
            ):
                raise ValueError("请选择当前目标中的调查问题，或暂不固定研究焦点。")
            project["career"]["focus_question_id"] = question_id
            self.projects._write(project)
        return self.get(identity)

    def _source_passage(self, reference):
        public_id, document_id = reference.get("public_document_id"), reference.get("document_id")
        if bool(public_id) == bool(document_id):
            raise ValueError("请选择一份已保存的正文，再选取原文段落。")
        try:
            if public_id:
                if reference.get("snapshot_id"):
                    raise ValueError("请按所选资料的原文位置创建问题。")
                documents = PublicDocumentService(self.repository, self.raw_directory / "public")
                source = documents.document(public_id)
                text, title = source["text"], source["title"]
                metadata = {"evidence_kind": source["evidence_kind"]}
            else:
                source = Catalog(self.repository).document(document_id)
                version = next((row for row in source["versions"]
                                if row["snapshot_id"] == reference.get("snapshot_id")), None)
                if not version or version["kind"] != "detail":
                    raise ValueError("请选择这份岗位的完整正文，不使用列表摘要创建原文问题。")
                text, title = version["payload"].get("description", ""), version["payload"]["title"]
                metadata = {"job_id": version["job_id"], "evidence_kind": "job_description"}
        except ProbeError as error:
            raise ValueError("未找到这份原文，请重新打开已保存的资料。") from error
        if source["integrity"] != "verified":
            raise ValueError("这份原文已无法读取，请先重新核对来源。")
        start, end = reference["start"], reference["end"]
        if not 0 <= start < end <= len(text) or end - start > 2000:
            raise ValueError("请从正文中选取1至2000字的连续段落，保留关键条件。")
        return {**reference, **metadata, "title": title, "quote": text[start:end],
                "recorded_at": now()}

    def save_question(self, identity, data, question_id=None):
        if data["state"] == "answered" and not data["conclusion"].strip():
            raise ValueError("请先写下目前弄清了什么、依据和仍有的限制，再标记为已记结论。")
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if data.get("source_passage"):
                data = {**data, "source_passage": self._source_passage(data["source_passage"])}
            questions = project["career"].setdefault("questions", [])
            by_id = {row["id"]: row for row in questions}
            parent_id = data.get("parent_question_id")
            if parent_id and parent_id not in by_id:
                raise ValueError("请选择当前目标中的原调查问题。")
            visited = {question_id} if question_id else set()
            ancestor = parent_id
            while ancestor:
                if ancestor in visited:
                    raise ValueError("后续问题不能再成为原问题的起点。")
                visited.add(ancestor)
                ancestor = by_id.get(ancestor, {}).get("parent_question_id")
            runs = {row["step_id"]: row for row in project["career"]["runs"]}
            for key in ("source_step_id", "conclusion_step_id"):
                if data.get(key) and data[key] not in runs:
                    raise ValueError("未找到所选讨论，请重新选择或取消关联。")
            if not question_id and "selected_job_ids" not in data:
                source = by_id.get(parent_id) or runs.get(data.get("source_step_id"), {})
                if "selected_job_ids" in source:
                    data = {**data, "selected_job_ids": source["selected_job_ids"][:]}
            selected = data.get("selected_job_ids", [])
            if len(selected) != len(set(selected)) or not set(selected) <= set(project["job_ids"]):
                raise ValueError("请选择当前工作区中的岗位，或取消对特定岗位的限定。")
            if question_id:
                question = next((row for row in questions if row["id"] == question_id), None)
                if not question:
                    raise ValueError("未找到这条调查问题，请刷新清单。")
                question.update(**data, updated_at=now())
            else:
                questions.append({"id": uuid4().hex, **data, "origin": "user", "created_at": now()})
            self.projects._write(project)
        return self.get(identity)

    def record_conversation(self, identity, question_id, data):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            question = next((row for row in project["career"].get("questions", [])
                             if row["id"] == question_id), None)
            if not question:
                raise ValueError("请选择当前目标中的调查问题，再记录沟通回复。")
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等本轮研究结束后再保存沟通回复，输入仍保留。")
            wording = ("用户记录的原话（系统未独立核实）" if data["wording"] == "quoted"
                       else "用户自己的转述（不是逐字原话）")
            prefix = (
                "用户提供的沟通或访谈记录，系统未参与或独立核实。"
                "这不是正式招聘原文、组织承诺或用户能力的证明。\n\n"
                f"关联调查问题：{question['question']}\n"
                f"沟通对象（用户填写）：{data['speaker'] or '未说明'}\n"
                f"沟通场景：{data['context'] or '未说明'}\n"
                f"发生时间（用户填写，未核实）：{data['said_when'] or '未说明'}\n"
                f"我询问的问题：{data['asked_question']}\n"
                f"记录方式：{wording}\n\n我记录的答复：\n"
            )
            answer = data["answer"]
            text = prefix + answer + (
                "\n\n保留条件、未说清或需要再次确认之处：\n"
                + (data["limits"] or "未填写；不能据此认为没有限制或已经全部确认。")
            )
            document = PublicDocumentService(
                self.repository, self.raw_directory / "public"
            ).archive_text(
                "沟通记录 · " + question["question"][:120], text,
                "用户提供的沟通记录，" + wording + "，不等于招聘原文或独立验证。",
            )["document"]
            project["public_document_ids"] = [
                *project.get("public_document_ids", []), document["id"]
            ]
            end = len(prefix) + len(answer)
            passage = self._source_passage({
                "public_document_id": document["id"],
                "start": max(len(prefix), end - 2000), "end": end,
            })
            question.setdefault("evidence_passages", []).append({
                "id": uuid4().hex, **passage, "relation": "unclassified",
                "user_note": "用户提供的沟通记录，" + wording + "。"
                + ("答复较长，这里仅定位末尾2000字；" if len(answer) > 2000 else "")
                + "完整记录含提问、场景与保留条件，后续需回读全文，不能把回复直接当成岗位事实。",
            })
            question["updated_at"] = now()
            self.projects._write(project)
        return self.get(identity)

    def save_question_passage(self, identity, question_id, data, passage_id=None):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            question = next((row for row in project["career"].get("questions", [])
                             if row["id"] == question_id), None)
            if not question:
                raise ValueError("请选择当前目标中的调查问题，再收集这段原文。")
            passages = question.setdefault("evidence_passages", [])
            if passage_id:
                passage = next((row for row in passages if row["id"] == passage_id), None)
                if not passage:
                    raise ValueError("未找到这段收集的原文，请刷新调查问题。")
                passage.update(**data, updated_at=now())
            else:
                passages.append({"id": uuid4().hex, **self._source_passage(data["passage"]),
                                 "relation": data["relation"], "user_note": data["user_note"]})
            question["updated_at"] = now()
            self.projects._write(project)
        return self.get(identity)

    def remove_question_passage(self, identity, question_id, passage_id):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            question = next((row for row in project["career"].get("questions", [])
                             if row["id"] == question_id), None)
            if not question or not any(row["id"] == passage_id
                                       for row in question.get("evidence_passages", [])):
                raise ValueError("未找到这个问题收集的原文段落，请刷新后重试。")
            question["evidence_passages"] = [row for row in question["evidence_passages"]
                                             if row["id"] != passage_id]
            question["updated_at"] = now()
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
            if data.get("question_id") and not any(
                row["id"] == data["question_id"] for row in career.get("questions", [])
            ):
                raise ValueError("未找到这张讲述卡关联的调查问题，请选择当前目标中的问题。")
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
        counter_insight_id=None,
        question_id=None,
        requirement_key="",
        comparison_step_ids=None,
        synthesis_question_ids=None,
        selected_job_ids=None,
        inherit_focus=True,
        autonomous=False,
    ):
        if kind not in QUESTIONS and kind not in {"answer", "followup", "ask", "challenge"}:
            raise ValueError("请选择一种研究方式。")
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if any(
                step["state"] in {"running", "queued", "interrupted"} for step in project["steps"]
            ):
                raise ValueError("已有一轮研究待完成，请先查看或继续原研究。")
            sources = None
            source_job_ids = []
            synthesis_sources = []
            if kind == "ask" and source_step_id:
                sources = [
                    row for row in self.get(identity)["results"]
                    if row["current"] and row["result"]["status"] == "completed"
                ]
                source = next((row for row in sources if row["step_id"] == source_step_id), None)
                if not source:
                    raise ValueError("这份分析已不是当前目标下的结果，请重新选择或直接提问。")
                if synthesis_question_ids is None and not any((
                    question_id, task_id, story_id, insight_id,
                    counter_insight_id, comparison_step_ids,
                )):
                    synthesis_sources = source.get("synthesis_sources", [])
                if inherit_focus and (not question_id or question_id == source.get("question_id")):
                    source_job_ids = source.get("selected_job_ids", [])
                    question_ids = {row["id"] for row in project["career"].get("questions", [])}
                    task_ids = {row["id"] for row in project["career"]["tasks"]}
                    story_ids = {row["id"] for row in project["career"]["stories"]}
                    insight_ids = {row["id"] for row in project["career"].get("insights", [])}
                    question_id = question_id or (
                        source.get("question_id")
                        if source.get("question_id") in question_ids else None
                    )
                    task_id = task_id or (
                        source.get("task_id") if source.get("task_id") in task_ids else None
                    )
                    story_id = story_id or (
                        source.get("story_id") if source.get("story_id") in story_ids else None
                    )
                    insight_id = insight_id or (
                        source.get("insight_id")
                        if source.get("insight_id") in insight_ids else None
                    )
                    counter_insight_id = counter_insight_id or (
                        source.get("counter_insight_id")
                        if source.get("counter_insight_id") in insight_ids else None
                    )
                    material_id = material_id or (
                        source.get("material_id")
                        if source.get("material_id") in project["public_document_ids"] else None
                    )
                    if question_id == source.get("question_id") and not comparison_step_ids:
                        comparison_step_ids = source.get("comparison_step_ids", [])
            if synthesis_question_ids is not None:
                identities = list(dict.fromkeys(synthesis_question_ids))
                questions_by_id = {row["id"]: row for row in project["career"].get("questions", [])}
                if not 2 <= len(identities) <= 4 or any(
                    key not in questions_by_id for key in identities
                ):
                    raise ValueError("请选择当前目标中的2至4个不同调查问题。")
                completed = [row for row in self.get(identity)["results"]
                             if row["result"] and row["result"]["status"] == "completed"
                             and row["state"] != "abandoned"]
                synthesis_sources = [{
                    "question_id": key,
                    "step_id": next((row["step_id"] for row in completed
                                     if row.get("question_id") == key), None),
                } for key in identities]
            if synthesis_sources and (kind != "ask" or any((
                question_id, task_id, story_id, insight_id, counter_insight_id, comparison_step_ids,
            ))):
                raise ValueError("综合调查请直接围绕所选问题提问，其他单项焦点可另行研究。")
            if kind in {"reflect", "challenge", "ask", "plan"} and task_id:
                task = next(
                    (row for row in project["career"]["tasks"] if row["id"] == task_id), None
                )
                if not task:
                    raise ValueError("未找到这项实验，请重新选择。")
                if kind != "ask" and not task["outcome"].strip():
                    raise ValueError("请先为这项练习记录实际观察，再开始反思。")
                if kind == "reflect" or inherit_focus and kind in {"ask", "plan", "challenge"}:
                    question_id = question_id or task.get("question_id")
            user_question = question.strip() if kind == "ask" else ""
            selected_requirement = None
            continued_requirement = None
            if kind == "evidence" or kind == "plan" and requirement_key:
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
                if kind == "evidence" and any(
                    not row["available"] for row in selected_requirement["proof"]["records"]
                ):
                    raise ValueError("有一份材料已移出目标，请先调整这项要求的证据。")
                if selected_job_ids is None:
                    source_job_ids = list(dict.fromkeys(
                        row["job_id"] for row in selected_requirement["evidence"]
                        if row.get("job_id") in project["job_ids"]
                    ))
            if task_id and kind in {"reflect", "challenge", "ask", "plan"}:
                continued_requirement = task.get("target_requirement")
                if continued_requirement and selected_job_ids is None:
                    source_job_ids = list(dict.fromkeys(
                        row["job_id"] for row in continued_requirement["evidence"]
                        if row.get("job_id") in project["job_ids"]
                    ))
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
                if inherit_focus:
                    observed_task = next(
                        (
                            row for row in project["career"]["tasks"]
                            if row["id"] == insight.get("task_id")
                            and (kind == "ask" or row.get("outcome"))
                        ),
                        None,
                    )
                    task_id = task_id or (observed_task["id"] if observed_task else None)
                    if kind in {"ask", "challenge"}:
                        question_id = question_id or insight.get("question_id") or (
                            observed_task.get("question_id") if observed_task else None
                        )
            understanding_check = kind == "teachback"
            if kind in {"answer", "followup"} or kind == "plan" and source_step_id:
                if sources is None:
                    sources = [row for row in self.get(identity)["results"]
                               if row["current"] and row["result"]["status"] == "completed"]
                previous_assessment = next(
                    (row for row in sources
                     if row["kind"] in ({"interview", "teachback", "followup"}
                                        if kind == "answer" else {"answer"})
                     and (not source_step_id or row["step_id"] == source_step_id)), None
                )
                if previous_assessment and previous_assessment.get("understanding_check"):
                    if question_id and question_id != previous_assessment["question_id"]:
                        raise ValueError("请沿用这组理解自测对应的调查问题，或另开一组自测。")
                    question_id = previous_assessment["question_id"]
                    understanding_check = True
            if question_id:
                saved_question = next(
                    (
                        row
                        for row in project["career"].get("questions", [])
                        if row["id"] == question_id
                    ),
                    None,
                )
                if not saved_question or kind not in {
                    "ask", "plan", "reflect", "teachback", "answer", "followup", "challenge"
                }:
                    raise ValueError("请选择已保存的调查问题，再继续提问、设计验证或反思。")
                parent_question = next(
                    (row for row in project["career"].get("questions", [])
                     if row["id"] == saved_question.get("parent_question_id")), None
                )
                if kind == "challenge":
                    hypothesis_a = hypothesis_a or saved_question.get("hypothesis_a", "")
                    hypothesis_b = hypothesis_b or saved_question.get("hypothesis_b", "")
                    chosen_task = next(
                        (row for row in project["career"]["tasks"] if row["id"] == task_id), {}
                    )
                    if chosen_task.get("question_id") not in {None, question_id}:
                        raise ValueError("请选择这个调查问题关联的实验，或取消实验选择。")
            if kind == "teachback" and (not question_id or story_id or task_id):
                raise ValueError("请选择一个已保存的调查问题做理解自测，不绑定个人经历或工作样本。")
            if autonomous and (kind != "ask" or not question_id or offline):
                raise ValueError("请选一个已保存的问题，并取消只整理原文，再开始连续查证。")
            comparison_step_ids = comparison_step_ids or []
            if comparison_step_ids:
                candidates = {
                    row["step_id"]: row
                    for row in self.get(identity)["results"]
                    if (row.get("question_id") == question_id if question_id
                        else (row.get("result") or {}).get("work_map"))
                    and row.get("result")
                    and row["result"]["status"] == "completed"
                    and row["state"] != "abandoned"
                }
                if (
                    kind != "ask"
                    or len(set(comparison_step_ids)) != 2
                    or not all(step_id in candidates for step_id in comparison_step_ids)
                ):
                    raise ValueError(
                        "请选择同一调查问题下的两次完整回答，或当前目标下两份完整工作地图。"
                    )
            counter_note = next((row for row in project["career"].get("insights", [])
                                 if row["id"] == counter_insight_id), None)
            if counter_insight_id and (
                kind not in {"ask", "challenge"} or not counter_note
                or counter_insight_id == insight_id
            ):
                raise ValueError("请选择当前目标中的另一条认识进行对照，或取消这项选择。")
            if kind == "pitch" or kind == "ask" and story_id:
                story = next(
                    (row for row in project["career"]["stories"] if row["id"] == story_id), None
                )
                if not story:
                    raise ValueError("请选择当前目标中已保存的经历，再继续研究。")
                if story["document_id"] not in (project.get("public_document_ids") or []):
                    raise ValueError("这份经历原文已移出研究资料，请先重新加入原文。")
            answer_document_id, answer_record = None, None
            if material_id and material_id not in (project.get("public_document_ids") or []):
                raise ValueError("这份资料已不在当前目标中，请重新选择或先加入资料。")
            if sources is None and (
                kind in {"answer", "followup", "ask"} or (kind == "plan" and source_step_id)
            ):
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
                    + "\n先读取本轮相关工作原文（有目标岗位时包括JD）；若选定了实验，"
                    "优先读取career_evidence中所选实验的"
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
                    continued_requirement = (
                        previous_step.get("career_requirement") or continued_requirement
                    )
                    answer_document_id = previous.get("answer_document_id")
                    answer_record = previous if previous.get("answer") else None
                    previous_text = (
                        "\n本轮接着career_evidence.continued_discussion中明确选定的完整讨论。"
                        "保留当时判断的性质、限定、未知与地图关系；先按本轮可用原文重核。"
                        "当时的实验建议不是已发生的结果。原讨论若已不可用，说明无法重核旧答复，"
                        "仍可依据当前资料回答本次问题，不补造旧内容。"
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
                if synthesis_sources:
                    question += (
                        "本轮综合career_evidence.synthesis_inquiries中明确选定的多个调查。"
                        "把业务问题、任务、交付物和能力关系连起来，比较它们在哪些条件下相互支持、"
                        "冲突或尚不能连接；不要逐条改写成互不相关的摘要。"
                        "每个inquiry的结论和learning_notes是个人理解，discussion是旧分析，"
                        "experiments的hypothesis是预期，outcome才是用户报告的观察。"
                        "保留原来的岗位范围、必备或加分性质、推断性质和末尾限定。"
                        "回读本轮可用原文与实验产物，用本轮读取所得引用支撑综合判断；"
                        "原资料不在当前范围时说明无法重核，不能靠多份旧回答互相证明。"
                        "明确共同盲区和最有价值的下一项查证，不自动修改问题结论或状态。"
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
                        if row["kind"] in {"interview", "teachback", "followup"}
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
                question = (MATERIAL_QUESTIONS.get(kind) if not project["job_ids"] else None) or (
                    QUESTIONS[kind]
                )
                reply = None
            if understanding_check and kind == "answer":
                question = (
                    "理解自测题：" + questions[question_index] + "\n"
                    "请先读取career_evidence.selected_answer的用户回答全文与相关工作资料。"
                    "对照所选题目，反馈解释的推理、适用条件、反例和不确定性：哪里有依据，"
                    "哪里过度概括或混淆概念；用最多三条简短判断指出具体回答与依据。"
                    "这是用户的概念解释，不证明做过某项目或具备生产经验；不编造经历或指标，"
                    "不打掌握分，不替用户补成正确答案。gaps保留最值得追问或实际验证的部分。"
                    "反馈需引用回答原话及相关原文，属于分析解释，不生成行动计划。"
                )
            elif understanding_check and kind == "followup":
                question = (
                    "围绕这份理解自测回答继续追问。原题：" + previous["interview_question"] + "\n"
                    "先读取career_evidence.selected_answer中的用户回答全文与工作资料，"
                    "针对上一轮暴露的推理或边界问题，在gaps给出最多两道完整追问，每道使用问号。"
                    "优先改变一个条件、提出反例，或让用户解释怎样检验；允许明确未知。"
                    "不要重出通用经历面试题，不替用户作答，不把概念解释写成实际工作经历。"
                    "claims仅列有引用的依据，保持用户未运行、未参与和不确定的限定。"
                )
            elif understanding_check and kind == "plan":
                question = QUESTIONS["plan"] + (
                    "本次只针对理解自测中暴露的一个解释设计最小验证。先读取selected_answer全文，"
                    "结合selected_inquiry与工作资料，说明什么观察可以支持或挑战原解释。"
                    "用户的解释不是已执行的实验或个人履历；保留未运行和未知的边界，不补造结果。"
                )
            focused_document_id = None
            interview_kinds = {"interview", "teachback", "answer", "followup"}
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
            if counter_insight_id:
                question += (
                    "本次另一条完整认识在career_evidence.selected_counter_learning_note，"
                    "有对应实验时见counter_experiment。与所选认识A或用户改写的解释A对照，"
                    "分别回读两边可用的原文与观察，保留各自末尾条件、未知和当时语境。"
                    "说明看法差异是否来自适用条件、观察或解释，不预设互斥，也不因较新而判定正确。"
                    "两条记录都只是用户理解；无从核实的部分保留未知，不把认识ID当作原文引用。"
                )
            if question_id:
                question += (
                    "本次围绕career_evidence.selected_inquiry中的持续调查问题展开，"
                    "结合用户本次提问、关心它的理由和希望补充的证据，回读相关原文。"
                    "origin_discussion包含问题起点的原分析与完整地图，"
                    "保留原关系理由、限定和迁移边界，把待检验解释带入后续验证，不能只按问题标题泛化。"
                    "若用户已有结论，它仍是待查证的个人记录，不当作独立事实。"
                    "若含carried_understanding，它是另一个目标下保存的理解，先核对当前岗位的适用条件；"
                    "原材料不在本轮范围时，明确无法重核旧结论，不用旧认识替代当前原文。"
                    "carried_understanding若含research_claims，这是从另一目标带来的历史Agent分析，"
                    "保留其原文明示、归纳或推断性质及必备、加分限定；research_gaps是当时的未知。"
                    "work_map是原分析的工作关系，保留关系理由、迁移边界和未知，不当作新证据。"
                    "source_jobs是原研究范围，source_references仅供定位，并未自动带入当前资料。"
                    "结合当前目标重新核对；来源不可读就明确无法重核，不把旧分析当作个人能力或新证据。"
                    "明确哪些已经有材料支持、哪些还不能回答，并给出下一步最有价值的查证方向。"
                    "不因为本轮生成回答而宣称问题已解决。"
                    "若含followup_to_recheck，这是用户点选带回的直接后续问题及当次答复。"
                    "先对照原问题的当前用户结论与完整限定，再重读该次答复指向的可用原文，"
                    "说明原判断哪些可保留、哪些需要缩窄或修订、哪些仍未知。后续研究的观点"
                    "及用户结论都不是新证据；保留它当时的岗位范围，不能把局部观察外推到整个目标。"
                    "本轮形成复核建议，不自动更新原问题的结论或状态。"
                )
                if saved_question.get("source_passage"):
                    question += (
                        "selected_inquiry.source_passage是问题起点的原文摘录与位置，"
                        "先从本轮目录读取对应原文及前后条件，不能把摘录当作已经核对全文。"
                        "若原资料不在本轮可读范围，明确无法重核，不自动恢复资料、不用旧摘录冒充新引用。"
                    )
                if parent_question:
                    question += (
                        "selected_inquiry.parent_inquiry是本问题直接承接的原调查，保留原问题、"
                        "用户结论与末尾限定、竞争解释和待补证据，帮助说明为什么拆出当前问题。"
                        "本轮回答当前后续问题，勿重复整套原调查；原结论只是用户记录，"
                        "不能直接作为事实或新证据。按本轮目录回读相关原文；原资料已移出或不在"
                        "当前岗位范围时，明确无法重核，不扩大范围。后续答案不自动改写原问题结论。"
                    )
                if saved_question.get("evidence_passages"):
                    question += (
                        "selected_inquiry.evidence_passages是用户为同一问题收集的原文线索，"
                        "relation与user_note只是用户标注，不是已确定的支持、冲突或因果关系。"
                        "回读本轮可用的各份原文，核对表面分歧是否来自适用条件或语境；"
                        "允许多种解释同时成立、都不成立或资料不足。未能重核的摘录保留未知，"
                        "不能把保存的摘录当作本轮新读证据或引用ID，也不自动改写用户结论。"
                        "若原文标为用户提供的沟通、访谈或转述，须区分对方据记录如何回答与已证实事实；"
                        "保留提问、场景、记录方式和未确认条件，不能将其升级为正式招聘要求、"
                        "组织承诺、独立验证或用户已有能力。与JD不一致时先列分歧和待核实问题。"
                    )
                if saved_question.get("hypothesis_a") or saved_question.get("hypothesis_b"):
                    question += (
                        "selected_inquiry.hypothesis_a与hypothesis_b是用户保留的待验证解释，"
                        "不是已证实事实。结合当前原文、反例与实验观察，说明能区分什么、仍不能区分什么；"
                        "允许同时成立、都不成立或材料不足，不因存在两个解释就强行二选一。"
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
                    "如果还没有实际观察，只讨论已保存的实验设计，明确尚未执行或结果未知，"
                    "不能补造执行结果。"
                )
            if kind == "ask" and story_id:
                question += (
                    "本次选中的具体经历在career_evidence.selected_story，先按document_id读取全文。"
                    "保留个人行动、实际结果及末尾限制，不能把其他项目混入这份经历，"
                    "也不能用岗位JD证明用户做过什么。经历依然是用户自述，不是独立核验。"
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
            if kind == "plan" and selected_requirement:
                question += (
                    "本次只围绕career_evidence.selected_requirement中的这一项工作或要求，"
                    "设计一个最小工作样本实验；不要扩成整个岗位学习清单。"
                    "先回读对应JD，再回读本轮可用的所选经历或作品正文，区分已观察、计划与未知。"
                    "用户记录的missing和relevance是待核对的个人判断，不能当作能力诊断。"
                    "保留必备、加分或未说明性质，不把加分条件说成求职门槛。"
                    "结合明确背景与投入限制，写具体输入、产物、完成检查和可能推翻预期的结果；"
                    "缺少个人背景时，说明设计依赖的前提，不编造用户已有能力。"
                    "application_plan最多一个动作，练习不等于已经胜任或达到企业验收标准。"
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
                    "用户本次明确对照的两次研究在career_evidence.selected_inquiry.earlier_discussions，"
                    "未绑定调查问题的两份工作地图则在career_evidence.selected_map_comparison。"
                    "按所选顺序比较两次提问、判断和来源。说明哪些差异可能来自问题或材料变化，"
                    "若包含work_map，比较业务问题、任务、交付物、关系理由、迁移限制与未知，"
                    "区分招聘资料发生变化、研究解释变化和无法确定的变化，不从两份地图概括行业趋势。"
                    "保留claim_details_to_recheck中的必备、加分与未说明强度，以及明示、归纳和推断区别。"
                    "哪些还不能解释；句子不同不等于矛盾，引用更多也不自动意味着更可靠。"
                    "旧研究和旧引用只是回查线索，请读取本轮可用原文再作判断；"
                    "若原资料不在本轮范围，保留未知，不把较新的一次当作正确答案。"
                )
            if not project["job_ids"]:
                question += (
                    "当前未选目标JD，只研究本轮可读资料与用户记录。模板中的岗位对照尚无招聘依据，"
                    "不能从业务/技术说明补造具体招聘资格或个人职责，也不能推定用户经历与能力。"
                    "可以解释工作、讨论待检验的迁移或设计学习实验；没有个人背景时保留未知并询问必要信息。"
                )
            if selected_job_ids is None:
                selected_job_ids = (
                    saved_question.get("selected_job_ids", source_job_ids) if question_id
                    else source_job_ids
                )
            if (len(selected_job_ids) != len(set(selected_job_ids))
                    or not set(selected_job_ids) <= set(project["job_ids"])):
                raise ValueError("所选对照岗位不在当前工作区中，请重新选择或取消岗位限定。")
            if selected_job_ids:
                question += (
                    "本轮只研究用户明确选中的岗位，范围以fixed_scope为准。"
                    "逐侧引用各自原文，区别工作差异、要求性质与尚未说明；"
                    "不能把工作区中未选入本轮的其他岗位当作这次对照的依据。"
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
            preferred = [material_id, focused_document_id]
            topic = [user_question]
            if synthesis_sources:
                from work_observer.research.inquiry_synthesis import synthesis_inquiries

                for item in synthesis_inquiries(project, self.store, synthesis_sources):
                    inquiry = item["inquiry"]
                    topic.extend((inquiry["question"], inquiry.get("conclusion", "")))
                    passages = [inquiry.get("source_passage") or {},
                                *inquiry.get("evidence_passages", [])]
                    preferred.extend(passage.get("public_document_id") for passage in passages)
                    preferred.extend(reference.get("public_document_id")
                                     for reference in (item["discussion"] or {}).get(
                                         "source_references_to_reread", []))
                    preferred.extend(task["artifact_document"]["document_id"]
                                     for task in item["experiments"] if task["artifact_document"])
                    preferred.extend(reference.get("public_document_id")
                                     for note in item["learning_notes"]
                                     for reference in note.get("source_locators", []))
                    carried = inquiry.get("carried_understanding") or {}
                    preferred.extend(reference.get("public_document_id")
                                     for reference in carried.get("source_references", []))
            for row in project["career"]["stories"]:
                if row["id"] == story_id:
                    preferred.append(row["document_id"])
                    topic.append(row["title"])
            chosen_task = next(
                (row for row in project["career"]["tasks"] if row["id"] == task_id), {}
            )
            preferred.extend(row.get("artifact_document_id") for row in project["career"]["tasks"]
                             if row["id"] in {task_id, chosen_task.get("previous_task_id")})
            topic.extend((chosen_task.get("title"), chosen_task.get("task_or_ability")))
            if question_id:
                for inquiry in [saved_question, *([parent_question] if parent_question else [])]:
                    topic.append(inquiry["question"])
                    passage = inquiry.get("source_passage") or {}
                    if passage.get("public_document_id") in project["public_document_ids"]:
                        preferred.append(passage["public_document_id"])
                    topic.append(passage.get("quote", ""))
                    for collected in reversed(inquiry.get("evidence_passages", [])):
                        if collected.get("public_document_id") in project["public_document_ids"]:
                            preferred.append(collected["public_document_id"])
                        topic.extend((collected.get("quote", ""), collected.get("user_note", "")))
                    carried = inquiry.get("carried_understanding") or {}
                    preferred.extend(ref["public_document_id"]
                                     for ref in carried.get("source_references", [])
                                     if ref.get("public_document_id")
                                     in project["public_document_ids"])
                preferred.extend(row.get("artifact_document_id") for row in [
                    item for item in project["career"]["tasks"]
                    if item.get("question_id") == question_id
                ][-3:])
            requirement = selected_requirement or continued_requirement or {}
            preferred.extend(row.get("document_id")
                             for row in requirement.get("proof", requirement).get("records", []))
            topic.append(requirement.get("text"))
            related_steps = {source_step_id, *comparison_step_ids}
            if question_id:
                from work_observer.research.learning import learning_inquiry_links

                related_steps.add(saved_question.get("source_step_id"))
                for note in project["career"].get("insights", []):
                    links = learning_inquiry_links(project["career"], note)
                    if note.get("use_for_research", True) and any(
                        link["question_id"] == question_id for link in links
                    ):
                        related_steps.add(note.get("source_step_id"))
                        related_steps.update(link.get("source_step_id") for link in links)
                        linked_task = next((item for item in project["career"]["tasks"]
                                            if item["id"] == note.get("task_id")), {})
                        preferred.append(linked_task.get("artifact_document_id"))
                if parent_question:
                    related_steps.update(parent_question.get(key) for key in (
                        "source_step_id", "conclusion_step_id",
                    ))
            if insight_id:
                chosen_note = next(row for row in project["career"]["insights"]
                                   if row["id"] == insight_id)
                related_steps.add(chosen_note.get("source_step_id"))
                topic.extend((chosen_note["current_view"], chosen_note.get("open_question")))
            if counter_note:
                related_steps.add(counter_note.get("source_step_id"))
                topic.extend((counter_note["current_view"], counter_note.get("open_question")))
                preferred.extend(row.get("artifact_document_id")
                                 for row in project["career"]["tasks"]
                                 if row["id"] == counter_note.get("task_id"))
            if answer_record:
                topic.append(answer_record.get("interview_question"))
            topic.extend(row.get("user_question") or row.get("interview_question")
                         for row in project["career"]["runs"] if row["step_id"] in related_steps)
            for previous_step in project["steps"]:
                if previous_step["id"] in related_steps and previous_step.get("run_id"):
                    previous_run = self.store.get(previous_step["run_id"])
                    if previous_run.get("state") == "invalidated":
                        continue
                    previous_result = previous_run.get("result") or {}
                    preferred.extend(row.get("public_document_id")
                                     for row in previous_result.get("evidence", []))
            documents, omitted = research_documents(
                project, kind, preferred, repository=self.repository,
                query="\n".join(value for value in topic if value) or project["goal"],
            )
            if not project["job_ids"] and not documents:
                raise ValueError("请先导入一份可用于本次研究的工作资料，或选择目标岗位JD。")
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
            project["steps"][-1]["public_document_ids"] = documents
            if selected_job_ids:
                project["steps"][-1]["job_ids"] = selected_job_ids[:]
            project["steps"][-1]["career_omitted_documents"] = omitted
            if answer_record and not answer_document_id:
                answer_label = "理解自测回答" if understanding_check else "模拟面试回答"
                document = PublicDocumentService(
                    self.repository, self.raw_directory / "public"
                ).archive_text(
                    answer_label + " · " + project["title"],
                    "用户" + answer_label + "，未经独立核实，不是招聘原文或能力认证。\n"
                    + ("理解自测问题：" if understanding_check else "面试问题：")
                    + answer_record["interview_question"]
                    + "\n用户回答：\n"
                    + answer_record["answer"],
                    ("用户的理解自测回答，仅作为原话依据；不独立证明经历或实际能力。"
                     if understanding_check else
                     "用户的模拟面试回答，仅作为原话依据；经历及效果未经独立核实。"),
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
                    selected = documents[:19]
                    step["public_document_ids"] = [*selected, answer_document_id]
                    step["career_omitted_documents"] += len(documents) - len(selected)
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
                    "story_id": story_id if kind in {"pitch", "ask"} | interview_kinds else None,
                    "insight_id": insight_id if kind in {"ask", "challenge"} else None,
                    "counter_insight_id": counter_insight_id,
                    "question_id": question_id,
                    "comparison_step_ids": comparison_step_ids,
                    "synthesis_sources": synthesis_sources,
                    "selected_job_ids": selected_job_ids[:],
                    "autonomous_rounds": 3 if autonomous else 0,
                    "materials_only": not bool(project["job_ids"]),
                    "understanding_check": understanding_check,
                    "requirement_key": requirement_key if selected_requirement else "",
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
            if counter_insight_id:
                project["steps"][-1]["career_counter_insight_id"] = counter_insight_id
            if question_id:
                project["steps"][-1]["career_question_id"] = question_id
            if comparison_step_ids:
                project["steps"][-1]["career_comparison_steps"] = comparison_step_ids
            if synthesis_sources:
                project["steps"][-1]["career_synthesis"] = synthesis_sources
            if autonomous:
                project["steps"][-1]["career_auto_rounds"] = 3
            if understanding_check:
                project["steps"][-1]["career_understanding_check"] = True
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
            if story_id and kind in {"pitch", "ask"} | interview_kinds:
                project["steps"][-1]["career_story_id"] = story_id
            self.projects._write(project)
            return {"project_id": identity, "step_id": project["steps"][-1]["id"]}

    def advance_inquiry(self, identity, step, result):
        """Continue one chosen question, using the existing research steps and budgets."""
        remaining = step.get("career_auto_rounds", 0)
        proposals = result.get("investigation_proposals", [])

        def stop(reason):
            with self.store.lock, self.store.db:
                current = self._project(identity)
                entry = next(row for row in current["career"]["runs"]
                             if row["step_id"] == step["id"])
                entry["autonomous_stop"] = reason
                self.projects._write(current)

        if remaining <= 1 or not proposals:
            return stop("已到本批三轮上限，保留当前判断与未知。" if remaining <= 1
                        else "本轮未提出可继续的补查，保留判断与仍需补充的材料或行动。")
        project = self._project(identity)
        source = next(row for row in project["career"]["runs"] if row["step_id"] == step["id"])
        proposal = proposals[0]
        if proposal["question"].strip() == source["user_question"].strip():
            return stop("后续问题与本轮相同，本批停止，避免重复查证。")
        try:
            prepared = self.prepare(
                identity, "ask", question=proposal["question"], question_id=source["question_id"],
                source_step_id=step["id"], section=source.get("section") or "requirements",
                selected_job_ids=source.get("selected_job_ids", []),
                allow_public=step["allow_public"],
            )
        except ValueError as exc:
            return stop(str(exc))
        with self.store.lock, self.store.db:
            project = self._project(identity)
            following = next(row for row in project["steps"] if row["id"] == prepared["step_id"])
            following.update(
                career_auto_rounds=remaining - 1, origin="agent", kind=proposal["kind"],
                completion=proposal["completion"], evidence_needed=proposal["evidence_needed"],
            )
            entry = next(row for row in project["career"]["runs"]
                         if row["step_id"] == following["id"])
            entry.update(autonomous_rounds=remaining - 1, investigation_reason=proposal)
            self.projects._write(project)
        return following["id"]

    def import_tasks(self, identity, step_id, action_indices=None):
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
            actions = (result.get("application_plan") or {}).get("actions", [])
            selected = set(range(len(actions)) if action_indices is None else action_indices)
            if not selected or any(index < 0 or index >= len(actions) for index in selected):
                raise ValueError("请选择这份研究中的工作样本建议。")
            for index, action in enumerate(actions):
                if index not in selected:
                    continue
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
                        **({"source_step_id": step_id,
                            "target_requirement": step["career_requirement"]}
                           if step.get("career_requirement") else {}),
                        "design_change": "",
                        **action,
                        "state": "planned",
                        "outcome": "",
                        "hypothesis": action.get("hypothesis", ""),
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
                    **({"source_step_id": previous.get("source_step_id"),
                        "target_requirement": previous["target_requirement"]}
                       if previous.get("target_requirement") else {}),
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
        hypothesis=None,
        artifact_title="工作样本材料",
        artifact_text="",
        design_change="",
        title=None,
        task_or_ability=None,
        deliverable=None,
        completion_check=None,
    ):
        plan = {
            key: value.strip()
            for key, value in {
                "title": title, "task_or_ability": task_or_ability,
                "deliverable": deliverable, "completion_check": completion_check,
            }.items()
            if value is not None
        }
        if any(not value for value in plan.values()):
            raise ValueError("请填写实验名称、要验证的工作、交付物和检查方法。")
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
                **plan,
                state=state,
                outcome=outcome,
                artifact=artifact,
                hypothesis=task.get("hypothesis", "") if hypothesis is None else hypothesis,
                design_change=design_change,
                updated_at=now(),
            )
            self.projects._write(project)
        return self.get(identity)
