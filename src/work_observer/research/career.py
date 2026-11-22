"""A job seeker's evidence, experiments and interview practice in one research project."""

import json
from copy import deepcopy
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
from work_observer.reports.cognition import work_map_search_parts
from work_observer.reports.results import audit_result
from work_observer.research.applications import PREFIX
from work_observer.research.applications import background as application_background
from work_observer.research.archived_sources import catalog as archive_catalog
from work_observer.research.investigation_memory import (
    interview_origin,
    task_action_indices,
    task_context,
)
from work_observer.research.learning import (
    calculation_records,
    experiment_relation_origin,
    learning_record,
    relation_learning_notes,
    work_relation_record,
)
from work_observer.research.projects import ProjectService, step_continuation
from work_observer.research.resume import resume_items
from work_observer.retrieval.catalog import Catalog
from work_observer.retrieval.unified import UnifiedRetrieval
from work_observer.text_match import match_text

QUESTIONS = {
    "teachback": (
        "围绕用户选定的调查问题或个人认识做一次理解自测，检验用户能否用自己的话解释工作。"
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
        "outcome未填写但comparison_rows已有observed时，逐组对照已记录的条件、输入与观察。"
        "未填写observed的条件仍未观察，不把局部记录推广为全部实验结论。"
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
        "为这个研究目标设计可执行的最小验证；有个人背景时可结合已保存的经历，最多三个动作。"
        "未提供个人背景时，只围绕当前资料中的解释设计一个理解验证，不判断个人适配或能力缺口。"
        "先核对本轮工作资料或岗位原文，再在application_plan给出针对的任务或解释、要区分的问题、"
        "具体产物、可复现的完成检查、需要的资源和未知。每项引用本轮已读原文。"
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


def interview_source(row):
    if row["kind"] in {"interview", "teachback", "followup"}:
        return True
    result = row.get("result") or {}
    return row["kind"] == "ask" and (
        bool(result.get("interview_questions"))
        or len((result.get("career_learning_context") or {}).get("answer_comparison", [])) == 2
    )


def _has_experiment_observations(task):
    return bool(task.get("outcome", "").strip()) or any(
        row.get("observed", "").strip() for row in task.get("comparison_rows", [])
    )


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
        first_question="",
        first_question_job_ids=None,
    ):
        question_jobs = list(first_question_job_ids or [])
        if (len(set(question_jobs)) != len(question_jobs) or not set(question_jobs) <= set(job_ids)
                or question_jobs and not first_question.strip()):
            raise ValueError("请为起始调查选择当前目标中的不同岗位，并写下调查问题。")
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
        material_id = None
        if material_text.strip():
            started = self.add_material(
                project["id"], title=material_title.strip() or "起始工作资料", text=material_text,
                source_name="用户提供的起始工作资料，来源与内容尚需核实。",
            )
            material_id = started["materials"][-1]["id"]
        if resume_text.strip():
            self.set_resume(project["id"], title=resume_title, text=resume_text)
        if first_question.strip():
            started = self.save_question(project["id"], {
                "question": first_question.strip(),
                "material_ids": [material_id] if material_id else [],
                "why_matters": "", "next_evidence": "", "hypothesis_a": "", "hypothesis_b": "",
                "state": "open", "conclusion": "", "source_step_id": None,
                "conclusion_step_id": None, "parent_question_id": None,
                "source_passage": None, "selected_job_ids": question_jobs,
            })
            return self.focus_question(project["id"], started["questions"][-1]["id"])
        return self.get(project["id"])

    def listing(self):
        items = []
        for row in self.projects.list(all_records=True):
            if row["state"] != "active" or not row.get("career"):
                continue
            career = row["career"]
            focus = next((q for q in career.get("questions", [])
                          if q["id"] == career.get("focus_question_id")), None)
            steps = {step["id"]: step for step in row["steps"]}
            latest = next((entry for entry in reversed(career["runs"])
                           if entry["step_id"] in steps), None)
            items.append({
                "id": row["id"],
                "title": row["title"],
                "goal": row["goal"],
                "updated_at": row["updated_at"],
                "job_count": len(row["job_ids"]),
                "story_count": len(career["stories"]),
                "insight_count": len(career.get("insights", [])),
                "open_question_count": sum(
                    q["state"] == "open" for q in career.get("questions", [])
                ),
                "focus_question_id": focus["id"] if focus else None,
                "focus_question": focus["question"] if focus else None,
                "latest_research": {
                    "step_id": latest["step_id"],
                    "kind": latest["kind"],
                    "question": latest.get("user_question")
                    or latest.get("interview_question") or "",
                    "question_id": latest.get("question_id"),
                    "state": steps[latest["step_id"]]["state"],
                    "created_at": latest["created_at"],
                } if latest else None,
                "resume_items": resume_items(row),
                "task_count": len(career["tasks"]),
                "done_count": sum(task["state"] == "done" for task in career["tasks"]),
            })
        return items

    def review(self, *, q="", goal_id=None, state="selected", unknown=False, offset=0):
        from work_observer.research.learning import learning_inquiry_links

        projects = [row for row in self.projects.list(all_records=True)
                    if row["state"] == "active" and row.get("career")]
        goals = [{"id": row["id"], "title": row["title"]} for row in projects]
        terms = [match_text(term) for term in q.split()[:10]]
        notes = []
        for owner in projects:
            if goal_id and owner["id"] != goal_id:
                continue
            career = owner["career"]
            for note in career.get("insights", []):
                selected = note.get("use_for_research", True)
                if state == "selected" and not selected or state == "parked" and selected:
                    continue
                if unknown and not note.get("open_question", "").strip():
                    continue
                links = learning_inquiry_links(career, note)
                text = match_text("\n".join([
                    owner["title"], *(note.get(key, "") for key in (
                        "previous_view", "observation", "current_view", "open_question",
                    )), *(link["question"] for link in links),
                ]))
                if not all(term in text for term in terms):
                    continue
                notes.append({
                    **note, "project_id": owner["id"], "project_title": owner["title"],
                    "inquiry_links": links,
                    "successor_ids": [row["id"] for row in career.get("insights", [])
                                      if row.get("replaces_insight_id") == note["id"]],
                })
        notes.sort(key=lambda row: (
            row.get("updated_at") or row["created_at"], row["project_id"], row["id"],
        ), reverse=True)
        page = notes[offset:offset + 12]
        return {
            "goals": goals, "notes": page, "total_count": len(notes), "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(notes) else None,
        }

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
        self, identity=None, *, q, scope="goal", record_kind="all",
        records_offset=0, sources_offset=0,
    ):
        project = self._project(identity) if identity else None
        if scope == "goal" and project is None:
            raise ValueError("请先选择要检索的目标，或检索全部已保存内容。")
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
            return records[-1]

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
                    ) + "\n" + row.get("comparison_conditions", "")
                    + "\n" + json.dumps(row.get("comparison_rows", []), ensure_ascii=False)
                    + "\n" + json.dumps(
                        experiment_relation_origin(owner, row, self.store), ensure_ascii=False,
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
                    ) + "\n" + (row.get("source_passage") or {}).get("title", "")
                    + "\n" + (row.get("source_passage") or {}).get("quote", "")
                    + "\n" + json.dumps(row.get("source_passages", []), ensure_ascii=False)
                    + "\n" + json.dumps(
                        learning_record(row, owner, self.store).get("source_calculations", {}),
                        ensure_ascii=False,
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
                    + "\n" + "\n".join(
                        origin["note"].get(key, "")
                        for origin in carried.get("learning_notes", [])
                        for key in ("previous_view", "reported_observation", "current_user_view",
                                    "open_question")
                    )
                    + "\n" + passage.get("title", "") + "\n" + passage.get("quote", "")
                    + "\n" + "\n".join(
                        "\n".join(item.get(key, "") for key in (
                            "title", "quote", "user_note", "target_view",
                        ))
                        + "\n" + "\n".join((item.get("conversation_note") or {}).get(key, "")
                                             for key in ("asked_question", "speaker", "context",
                                                         "said_when", "limits"))
                        + "\n" + (
                            (item.get("conversation_note") or {}).get("target_job") or {}
                        ).get("label", "")
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
                map_parts = work_map_search_parts(result.get("work_map") or {}) if (
                    result.get("status") == "completed"
                ) else []
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
                        *[value for part in map_parts for value in part["fields"].values()],
                        json.dumps(calculation_records(result), ensure_ascii=False),
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
                matched = add(
                    owner,
                    "discussion",
                    row,
                    title,
                    text,
                    section,
                    step_id=row["step_id"],
                )
                if matched is not None and result.get("status") == "completed":
                    evidence = {item["id"]: item for item in result.get("evidence", [])}
                    claims = []
                    for index, claim in enumerate(result.get("claims", [])):
                        if not all(term in match_text(claim["text"]) for term in terms):
                            continue
                        claims.append({
                            "index": index,
                            **{key: claim.get(key) for key in (
                                "text", "category", "basis", "requirement",
                            )},
                            "source_titles": list(dict.fromkeys(
                                evidence[key]["title"] for key in claim.get("evidence_ids", [])
                                if key in evidence
                            )),
                        })
                    matched["claim_matches"] = claims[:3]
                    matched["claim_match_count"] = len(claims)
                    map_matches = []
                    for part in map_parts:
                        fields = {key: value for key, value in part["fields"].items()
                                  if any(term in match_text(value) for term in terms)}
                        if not fields:
                            continue
                        full_text = match_text("\n".join(part["fields"].values()))
                        linked = [{"index": index, **result["claims"][index]}
                                  for index in part["claim_indices"]
                                  if 0 <= index < len(result.get("claims", []))]
                        cited = {key for claim in linked for key in claim["evidence_ids"]}
                        map_matches.append({
                            **part, "matched_fields": list(fields),
                            "covers_all_terms": all(term in full_text for term in terms),
                            "claims": linked,
                            "evidence": [value for key, value in evidence.items() if key in cited],
                        })
                    matched["map_matches"] = map_matches
                    matched["map_match_count"] = len(map_matches)

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

    def work_relations(self, *, q="", goal_id=None, node_kind="all", predicate="all",
                       state="all", offset=0):
        """Browse saved report-local relations; keep their original scopes and provenance."""
        owners = [row for row in self.projects.list(all_records=True)
                  if row["state"] == "active" and row.get("career")]
        if goal_id and not any(row["id"] == goal_id for row in owners):
            raise ValueError("请选择已有的调查目标，或查看全部目标。")
        terms = [match_text(term) for term in q.split()[:10]]
        records = []
        for owner in owners:
            if goal_id and owner["id"] != goal_id:
                continue
            steps = {row["id"]: row for row in owner["steps"]}
            for study in owner["career"]["runs"]:
                step = steps.get(study["step_id"], {})
                if not step.get("run_id") or step["state"] == "abandoned":
                    continue
                run = self.store.get(step["run_id"])
                result = run.get("result") or {}
                work_map = result.get("work_map") or {}
                if result.get("status") != "completed" or run["state"] == "invalidated":
                    continue
                current = None
                for index, relation in enumerate(work_map.get("work_relations", [])):
                    if node_kind != "all" and node_kind not in {
                        relation["source_kind"], relation["target_kind"],
                    }:
                        continue
                    if predicate != "all" and predicate != relation["predicate"]:
                        continue
                    text = "\n".join([owner["title"], study.get("user_question") or "",
                                      *[relation[key] for key in (
                                          "source_text", "target_text", "rationale",
                                          "transfer_limit",
                                      )]])
                    if not all(term in match_text(text) for term in terms):
                        continue
                    if current is None:
                        review = next((item for item in QualityReviewService(
                            self.store, self.repository,
                        ).list_run(step["run_id"]) if not item["stale_result"]), None)
                        if review and review["status"] == "rejected":
                            break
                        audit = audit_result(result, self.repository)
                        # Same source/background status used by the goal workspace.
                        current = step["scope_version"] == owner["scope_version"] and not any(
                            audit[key] for key in (
                                "changed_sources", "stale_dependencies", "stale_memory",
                                "stale_knowledge",
                            )
                        )
                    if state != "all" and current != (state == "current"):
                        continue
                    records.append(self._relation_record(owner, study, result, index, current))
        records.sort(key=lambda row: (row["recorded_at"], row["key"]), reverse=True)
        page = records[offset:offset + 12]
        return {
            "goals": [{"id": row["id"], "title": row["title"]} for row in owners],
            "relations": page, "total_count": len(records), "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(records) else None,
            "notice": "已保存研究中的关系解释，不是独立知识或岗位事实。保留每次研究的范围、"
            "判断性质、引用和限制；不同记录不自动合并，新旧顺序不证明对错或行业变化。",
        }

    @staticmethod
    def _relation_record(owner, study, result, index, current):
        row = work_relation_record(owner, study, result, index, current)
        personal_notes = relation_learning_notes(
            owner.get("career", owner).get("insights", []), study["step_id"], index,
        )
        if personal_notes:
            row["personal_notes"] = personal_notes
        tasks = [deepcopy(task) for task in owner.get("career", owner).get("tasks", [])
                 if task.get("source_step_id") == study["step_id"]
                 and task.get("source_relation_index") == index]
        if tasks:
            row["verification_tasks"] = tasks
        return row

    def _comparison_sources(self, origins, include_sources):
        documents, jobs, skipped, references = [], [], [], []
        public = PublicDocumentService(self.repository, self.raw_directory / "public")
        for origin in origins:
            for source in origin["evidence"]:
                reference = {key: source.get(key) for key in (
                    "job_id", "public_document_id", "document_id", "snapshot_id", "title",
                    "evidence_kind", "start", "end", "historical_cutoffs",
                )}
                source["available_for_recheck"] = False
                if include_sources:
                    try:
                        if source.get("public_document_id"):
                            document = public.document(source["public_document_id"])
                            if document["integrity"] != "verified":
                                raise ValueError("原文文件缺失或已变化")
                            documents.append(source["public_document_id"])
                        elif source.get("document_id"):
                            document = Catalog(self.repository).document(source["document_id"])
                            if document["integrity"] != "verified":
                                raise ValueError("旧岗位原文缺失或已变化")
                            version = next((row for row in document["versions"]
                                            if row["snapshot_id"] == source.get("snapshot_id")
                                            and row["kind"] == "detail"), None)
                            if not version or source.get("job_id") not in {None, version["job_id"]}:
                                raise ValueError("这份引用的岗位正文已无法定位")
                            source["job_id"] = reference["job_id"] = version["job_id"]
                            self.repository.job(version["job_id"])
                            jobs.append(version["job_id"])
                            reference["as_of"] = (source.get("historical_cutoffs") or [
                                max(version["observed_at"], version["processed_at"],
                                    key=lambda value: datetime.fromisoformat(value.replace(
                                        "Z", "+00:00",
                                    ))),
                            ])[0]
                        else:
                            raise ValueError("这段引用没有可带入的归档正文定位")
                    except (ProbeError, ValueError) as error:
                        skipped.append({"title": source["title"], "reason": (
                            "原文暂不可读，引用保留供回查。" if isinstance(error, ProbeError)
                            else str(error)
                        )})
                    else:
                        source["available_for_recheck"] = True
                references.append(reference)
        documents, jobs = list(dict.fromkeys(documents)), list(dict.fromkeys(jobs))
        return documents, jobs, skipped, references

    def relation_inquiry(self, *, relations, question, title="", include_sources=True):
        keys = {(row["project_id"], row["step_id"], row["relation_index"]) for row in relations}
        if len(keys) != 2:
            raise ValueError("请选择两条不同的工作关系再建立对照调查。")
        origins, owners = [], {}
        for reference in relations:
            identity = reference["project_id"]
            if identity not in owners:
                owners[identity] = self.get(identity)
            owner = owners[identity]
            study = next((row for row in owner["results"]
                          if row["step_id"] == reference["step_id"]), None)
            result = (study or {}).get("result") or {}
            index = reference["relation_index"]
            if (result.get("status") != "completed" or study["state"] == "abandoned"
                    or result.get("business_review", {}).get("status") == "rejected"
                    or not 0 <= index < len((result.get("work_map") or {}).get(
                        "work_relations", []))):
                raise ValueError("所选关系已无法完整读取，请回到关系库重新选择。")
            snapshot = self._relation_record(owner, study, result, index, study["current"])
            for claim in snapshot["claims"]:
                claim.pop("evidence_ids", None)
            for source in snapshot["evidence"]:
                source.pop("id", None)
            origins.append(snapshot)
        documents, jobs, skipped, references = self._comparison_sources(origins, include_sources)
        if len(jobs) > 6:
            raise ValueError("两条关系涉及超过6个岗位，请选择范围更集中的关系。")
        saved = self.create(title=title or question[:150], goal=question[:1000],
                            background="", constraints="", job_ids=jobs)
        identity = saved["id"]
        with self.store.lock, self.store.db:
            project = self._project(identity)
            project["public_document_ids"] = documents
            self.projects._write(project)
        saved = self.save_question(identity, {
            "question": question, "why_matters": "对照所选工作关系，核对共用点、差异和迁移前提。",
            "next_evidence": "回读两侧原文，寻找反例及能区分解释的观察；来源不可读则保留未知。",
            "state": "open", "conclusion": "", "hypothesis_a": "", "hypothesis_b": "",
            "source_step_id": None, "conclusion_step_id": None, "parent_question_id": None,
            "selected_job_ids": jobs, "material_ids": documents if len(documents) <= 6 else [],
            "carried_understanding": {"work_relations": origins,
                                      "source_references": references,
                                      "skipped_sources": skipped,
                                      "include_sources": include_sources},
        })
        return self.focus_question(identity, saved["questions"][-1]["id"])

    def understanding_inquiry(self, *, notes, question, title="", why_matters="",
                              next_evidence="", include_sources=True):
        if len({(row["project_id"], row["note_id"]) for row in notes}) != 2:
            raise ValueError("请选择两份不同的认识，再建立共同待查的问题。")
        origins, sources, owners = [], [], {}
        for reference in notes:
            identity = reference["project_id"]
            if identity not in owners:
                owners[identity] = self._project(identity)
            owner = owners[identity]
            original = next((row for row in owner["career"].get("insights", [])
                             if row["id"] == reference["note_id"]), None)
            if not original:
                raise ValueError("有一份认识已无法读取，请回到原目标重新选择。")
            memory = learning_record(original, owner, self.store)
            locators = memory["source_locators"]
            if artifact := (memory.get("linked_experiment") or {}).get("artifact_document_id"):
                locators.append({"public_document_id": artifact,
                                 "title": memory["linked_experiment"].get("artifact_title")
                                 or memory["linked_experiment"]["title"],
                                 "evidence_kind": "work_material"})
            usable = [row for row in locators if row.get("evidence_kind") not in {
                "search_answer", "search_excerpt", "list_summary",
            }]
            sources.append({"evidence": usable})
            origins.append({"project_id": identity, "project_title": owner["title"],
                            "project_goal": owner["goal"], "note_id": original["id"],
                            "note": memory})
        documents, jobs, skipped, references = self._comparison_sources(sources, include_sources)
        if len(jobs) > 6:
            raise ValueError("两份认识涉及超过6个岗位，请选择范围更集中的记录。")
        saved = self.create(title=title or question[:150], goal=question[:1000],
                            background="", constraints="", job_ids=jobs)
        identity = saved["id"]
        with self.store.lock, self.store.db:
            project = self._project(identity)
            project["public_document_ids"] = documents
            self.projects._write(project)
        saved = self.save_question(identity, {
            "question": question, "why_matters": why_matters, "next_evidence": next_evidence,
            "state": "open", "conclusion": "", "hypothesis_a": "", "hypothesis_b": "",
            "source_step_id": None, "conclusion_step_id": None, "parent_question_id": None,
            "selected_job_ids": jobs, "material_ids": documents if len(documents) <= 6 else [],
            "carried_understanding": {"learning_notes": origins, "source_references": references,
                                      "skipped_sources": skipped,
                                      "include_sources": include_sources},
        })
        return self.focus_question(identity, saved["questions"][-1]["id"])

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
            "materials": self._material_catalog(
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

    def add_material(self, identity, *, title, text, source_name="", question_id=None):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等本轮研究结束后再补充资料，输入仍保留。")
            question = None
            if question_id:
                question = next((row for row in project["career"].get("questions", [])
                                 if row["id"] == question_id), None)
                if question is None:
                    raise ValueError("未找到这条调查问题，请重新选择资料用途。")
                if len(question.get("material_ids", [])) >= 6:
                    raise ValueError("本调查已有6份重点资料，请先调整选择，或仅保存到目标资料库。")
            documents = list(project.get("public_document_ids") or [])
            document = PublicDocumentService(
                self.repository, self.raw_directory / "public"
            ).archive_text(title, text, source_name)["document"]
            project["public_document_ids"] = [*documents, document["id"]]
            if question is not None:
                question["material_ids"] = [*question.get("material_ids", []), document["id"]]
                question["updated_at"] = now()
            self.projects._write(project)
        return {**self.get(identity), "added_material_id": document["id"]}

    def _material_catalog(self, identities):
        materials = archive_catalog(self.repository, identities, limit=None)
        with Session(self.repository.engine) as session:
            urls = dict(session.execute(select(PublicDocument.id, PublicDocument.url).where(
                PublicDocument.id.in_(identities)
            )).all())
            families = {}
            for document_id, url in session.execute(select(
                PublicDocument.id, PublicDocument.url
            ).where(PublicDocument.url.in_(list(urls.values())))):
                families.setdefault(url, []).append(document_id)
        for material in materials:
            material["related_document_ids"] = families.get(urls.get(material["id"]), [])
        return materials

    def revise_material(self, identity, document_id, *, title, text, source_name="",
                        base_document_id=None):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            documents = list(project.get("public_document_ids") or [])
            if document_id not in documents or document_id in personal_documents(project["career"]):
                raise ValueError("请从本目标的补充工作资料中选择要更新的原文。")
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("请等本轮研究结束后再更新资料，输入仍保留。")
            service = PublicDocumentService(self.repository, self.raw_directory / "public")
            if base_document_id and base_document_id != document_id:
                if service.document(base_document_id)["url"] != (
                    service.document(document_id)["url"]
                ):
                    raise ValueError("请使用这份资料的原文进行补充。")
            try:
                document = service.revise_text(
                    base_document_id or document_id, title, text, source_name
                )["document"]
            except ProbeError as error:
                if error.code == "WORK_MATERIAL_CHANGED_REFRESH":
                    raise ValueError(
                        "这份资料已有更新，请重新打开更新后的原文；当前输入仍保留。"
                    ) from error
                if error.code == "WORK_MATERIAL_REQUIRED":
                    raise ValueError(
                        "归档网页请保留原文；补充说明可以另存为一份工作资料。"
                    ) from error
                raise
            project["public_document_ids"] = list(dict.fromkeys(
                document["id"] if key == document_id else key for key in documents
            ))
            if document["id"] != document_id:
                for question in project["career"].get("questions", []):
                    if document_id in question.get("material_ids", []):
                        question["material_ids"] = list(dict.fromkeys(
                            document["id"] if key == document_id else key
                            for key in question["material_ids"]
                        ))
                        question["updated_at"] = now()
            self.projects._write(project)
        return {**self.get(identity), "updated_material_id": document["id"]}

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
            source_task = next(
                (row for row in project["career"]["tasks"]
                 if row["id"] == data.get("source_task_id")), None
            )
            if data.get("source_task_id") and (
                not source_task or (
                    not _has_experiment_observations(source_task)
                    and not (previous and previous.get("source_task_id") == data["source_task_id"])
                )
            ):
                raise ValueError("请选择本目标中已记录实际观察的练习，再整理经历。")
            retrieval_source = deepcopy(previous.get("retrieval_source")) if (
                previous and previous.get("source_task_id") == data.get("source_task_id")
            ) else None
            if source_task:
                from work_observer.research.retrieval_experiment import (
                    is_retrieval_task,
                    review_context,
                )

                if retrieval_source is None and is_retrieval_task(source_task):
                    retrieval_source = review_context(self.repository, project, source_task)
                    retrieval_source.update(source_project_id=identity,
                                            source_project_title=project["title"])
            text = "\n".join(
                [
                    "用户自述经历，尚未独立核实。",
                    *(["由个人练习整理，不代表企业工作经历或生产效果。",
                       "来源练习：" + ((source_task or {}).get("title") or "本地检索对照记录")]
                      if source_task or retrieval_source else []),
                    *(["来源是本机词面检索对照；标签为当次使用者预期，"
                       "不是独立评测、真实生产效果或个人能力认证。"] if retrieval_source else []),
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
                **({"retrieval_source": retrieval_source} if retrieval_source else {}),
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

    def reuse(self, identity, *, source_project_id, kind, record_id, source_step_id=None):
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
            if source_step_id:
                study = next((row for row in self.get(identity)["results"]
                              if row["step_id"] == source_step_id
                              and (row.get("result") or {}).get("status") == "completed"
                              and row["state"] != "abandoned"), None)
                reads = (study or {}).get("result", {}).get(
                    "career_learning_context", {},
                ).get("read_other_goals", [])
                recalled = next((row for row in reads if row["kind"] == "inquiry"
                                 and row["project_id"] == source_project_id
                                 and row["record_id"] == record_id), None)
                if kind != "question" or not recalled:
                    raise ValueError("请从本轮实际读取过的其他目标调查中选择，再带入当前目标。")
                original = recalled["memory"]
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
                        "source_step_id": source_step_id,
                        "conclusion_step_id": None,
                        **({"hypothesis_a": "", "hypothesis_b": "", "material_ids": [],
                            "selected_job_ids": [], "evidence_passages": []}
                           if source_step_id else {}),
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
                            **({"inquiry": {key: deepcopy(original.get(key)) for key in (
                                "id", "question", "why_matters", "next_evidence", "state",
                                "conclusion", "hypothesis_a", "hypothesis_b", "source_passage",
                                "evidence_passages", "selected_job_ids", "material_ids",
                                "created_at", "updated_at", "origin_learning_note",
                            )}} if kind == "question" and source_step_id else {}),
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
                copied.pop("source_task_id", None)
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
            existing = next((row for row in notes if row["id"] == insight_id), None)
            if passage := data.get("source_passage"):
                old = (existing or {}).get("source_passage") or {}
                keys = ("public_document_id", "document_id", "snapshot_id", "start", "end")
                data = {**data, "source_passage": (
                    old if old and all(old.get(key) == passage.get(key) for key in keys)
                    else self._source_passage({key: value for key, value in passage.items()
                                               if value is not None})
                )}
            if passages := data.get("source_passages"):
                keys = ("public_document_id", "document_id", "snapshot_id", "start", "end")
                old = (existing or {}).get("source_passages", [])
                data = {**data, "source_passages": [
                    next((item for item in old if all(item.get(key) == passage.get(key)
                                                     for key in keys)), None)
                    or self._source_passage({key: value for key, value in passage.items()
                                             if value is not None})
                    for passage in passages
                ]}
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
            claim_index = data.get("source_claim_index")
            relation_index = data.get("source_relation_index")
            task_index = data.get("source_task_index")
            if sum(value is not None for value in (claim_index, relation_index, task_index)) > 1:
                raise ValueError("请只选择一条判断、工作关系或分项解释作为认识起点。")
            if claim_index is not None or relation_index is not None or task_index is not None:
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
                if task_index is not None:
                    if not run or run.get("state") == "invalidated":
                        raise ValueError("原分项解释已不可用，请重新选择来源。")
                    task_context(result, task_index)
                items = (result.get("investigation") or {}).get("tasks", []) if (
                    task_index is not None
                ) else (result.get("work_map") or {}).get("work_relations", []) if (
                    relation_index is not None
                ) else result.get("claims", [])
                chosen_index = task_index if task_index is not None else (
                    relation_index if relation_index is not None else claim_index
                )
                if result.get("status") != "completed" or not 0 <= chosen_index < len(items):
                    raise ValueError("请选择这次完整分析中的一条判断、工作关系或分项解释。")
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

    def capture_passage(
        self, *, passage, goal_id=None, goal_title="", question_id=None, question="",
        include_source=True, relation="unclassified", user_note="", target_view="",
    ):
        """Save a reader selection into a chosen inquiry, without starting research."""
        source = self._source_passage(passage)
        if not question_id and not question.strip():
            raise ValueError("请写下这段原文引出的调查问题。")
        if question_id and not goal_id:
            raise ValueError("请先选择已有问题所在的调查目标。")
        project = self._project(goal_id) if goal_id else None
        if question_id and not any(q["id"] == question_id
                                   for q in project["career"].get("questions", [])):
            raise ValueError("请选择这个目标中的调查问题。")
        public_id, job_id = source.get("public_document_id"), source.get("job_id")
        add_public = include_source and public_id and (
            project is None or public_id not in project.get("public_document_ids", [])
        )
        add_job = include_source and job_id and (
            project is None or job_id not in project["job_ids"]
        )
        if project and (add_public or add_job):
            if any(step["state"] == "running" for step in project["steps"]):
                raise ValueError("这个目标正在研究；可以暂时只保存摘录，或稍后再把原资料加入。")
            if add_job and len(project["job_ids"]) >= 6:
                raise ValueError("这个目标已有6个岗位；可以只保存摘录，或先调整目标岗位。")
        created = project is None
        if created:
            saved = self.create(
                title=goal_title.strip() or question.strip()[:150],
                goal="沿着原文调查，逐步核实工作及适用条件。",
                background="", constraints="", job_ids=[job_id] if add_job else [],
            )
            goal_id = saved["id"]
            project = self._project(goal_id)
        elif add_job:
            project = self.projects.revise(
                goal_id, revision=project["revision"], goal=project["goal"],
                job_ids=[*project["job_ids"], job_id],
            )
        if add_public:
            self.attach_material(goal_id, document_id=public_id)
        if question_id:
            saved = self.save_question_passage(goal_id, question_id, {
                "passage": passage, "relation": relation,
                "user_note": user_note, "target_view": target_view,
            })
        else:
            saved = self.save_question(goal_id, {
                "question": question.strip(), "why_matters": user_note,
                "next_evidence": "", "state": "open", "conclusion": "",
                "hypothesis_a": "", "hypothesis_b": "", "source_passage": passage,
                "source_step_id": None,
                "conclusion_step_id": None, "parent_question_id": None,
                "selected_job_ids": [job_id] if include_source and job_id else [],
                "material_ids": [public_id] if include_source and public_id else [],
            })
            question_id = saved["questions"][-1]["id"]
        if created:
            saved = self.focus_question(goal_id, question_id)
        return {**saved, "captured_question_id": question_id, "created_goal": created}

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
            if data.get("source_insight_id") and not any(
                row["id"] == data["source_insight_id"]
                for row in project["career"].get("insights", [])
            ):
                raise ValueError("请选择当前目标中的认识记录作为问题起点。")
            if "material_ids" in data:
                selected_materials = data["material_ids"]
                retained = set(by_id.get(question_id, {}).get("material_ids", []))
                if (
                    len(selected_materials) > 6
                    or len(selected_materials) != len(set(selected_materials))
                    or not set(selected_materials) <= retained | set(project["public_document_ids"])
                ):
                    raise ValueError("请选择本目标中最多6份不同的重点资料。")
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
            previous = by_id.get(question_id, {})
            gap_index = data.get("source_gap_index", previous.get("source_gap_index"))
            if data.get("source_step_id") != previous.get("source_step_id") and (
                "source_gap_index" not in data
            ):
                gap_index = None
                if "source_gap_index" in previous:
                    data = {**data, "source_gap_index": None}
            if gap_index is not None and (
                gap_index != previous.get("source_gap_index")
                or data.get("source_step_id") != previous.get("source_step_id")
            ):
                source = next((row for row in self.get(identity)["results"]
                               if row["step_id"] == data.get("source_step_id")), None)
                if (not source or source["state"] == "abandoned"
                        or (source.get("result") or {}).get("status") != "completed"
                        or gap_index >= len(source["result"].get("gaps", []))):
                    raise ValueError("请从一份完整研究中的具体未知项建立调查。")
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
            target = None
            if target_id := data.get("target_job_id"):
                if target_id not in project["job_ids"]:
                    raise ValueError("请在当前目标的岗位中选择计划核实对象，或留空。")
                job = self.repository.job(target_id)["current"]
                target = {"id": target_id, "label": " · ".join(
                    value for value in (
                        job.get("title"), job.get("company_name_raw") or job.get("company"),
                    ) if value
                )}
            wording = ("用户记录的原话（系统未独立核实）" if data["wording"] == "quoted"
                       else "用户自己的转述（不是逐字原话）")
            target_line = (
                f"计划核实岗位（用户选择，不代表答复已适用于该岗位）：{target['label']}\n"
                if target else ""
            )
            prefix = (
                "用户提供的沟通或访谈记录，系统未参与或独立核实。"
                "这不是正式招聘原文、组织承诺或用户能力的证明。\n\n"
                f"关联调查问题：{question['question']}\n"
                f"{target_line}"
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
                "conversation_note": {
                    **{key: data[key] for key in (
                        "asked_question", "wording", "speaker", "context", "said_when", "limits",
                    )},
                    "target_job": target, "checklist_key": data.get("checklist_key", ""),
                    "answer_start": len(prefix), "answer_end": end,
                },
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
                                 "relation": data["relation"], "user_note": data["user_note"],
                                 "target_view": data.get("target_view", "")})
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
        inquiry_answer=False,
        offline=False,
        question_index=0,
        task_id=None,
        source_step_id=None,
        claim_review_index=None,
        feedback_gap_index=None,
        practice_task_id=None,
        retrieval_case_name=None,
        experiment_ids=None,
        question="",
        section="requirements",
        hypothesis_a="",
        hypothesis_b="",
        material_id=None,
        material_ids=None,
        allow_public=False,
        story_id=None,
        insight_id=None,
        insight_ids=None,
        counter_insight_id=None,
        question_id=None,
        requirement_key="",
        comparison_step_ids=None,
        passage_ids=None,
        synthesis_question_ids=None,
        selected_job_ids=None,
        inherit_focus=True,
        autonomous=False,
        adaptive=False,
    ):
        if adaptive and kind != "ask":
            raise ValueError("意图理解用于自由提问，其他入口按已选研究方式进行。")
        if kind not in QUESTIONS and kind not in {"answer", "followup", "ask", "challenge"}:
            raise ValueError("请选择一种研究方式。")
        if inquiry_answer and (kind != "answer" or not question_id or any((
            source_step_id, task_id, story_id, insight_id, insight_ids, counter_insight_id,
            comparison_step_ids, synthesis_question_ids, passage_ids, experiment_ids,
        ))):
            raise ValueError("直接回答请只选择一个调查问题；其他练习可另行开始。")
        if claim_review_index is not None and (kind != "ask" or not source_step_id):
            raise ValueError("请先选定一份旧研究和具体判断，再发起这项查证。")
        if feedback_gap_index is not None and (kind != "plan" or not source_step_id):
            raise ValueError("请从一次完整回答的反馈选择待验证的问题，再设计练习。")
        if practice_task_id and kind != "answer":
            raise ValueError("请在重答原题时带入这项练习观察。")
        if retrieval_case_name and kind != "ask":
            raise ValueError("请从已保存评估集的具体样例准备追问。")
        material_focus_supplied = (
            material_id is not None or material_ids is not None or retrieval_case_name is not None
        )
        material_ids = list(material_ids or [])
        if material_ids and (kind not in {"ask", "map", "plan"} or material_id):
            raise ValueError("所选资料可用于提问、工作地图或验证设计，请取消单份重点资料。")
        if len(material_ids) > 6 or len(set(material_ids)) != len(material_ids):
            raise ValueError("每轮请选择最多6份不同的重点资料。")
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if any(
                step["state"] in {"running", "queued", "interrupted"} for step in project["steps"]
            ):
                raise ValueError("已有一轮研究待完成，请先查看或继续原研究。")
            sources = None
            source_job_ids = []
            assessment_job_ids, interview_task_origin = None, None
            retrieval_review, retrieval_job_ids, retrieval_document_ids = None, None, None
            feedback_origin, feedback_documents = None, None
            retrieval_case = None
            answer_pair_documents = None
            comparison_followup_ids = []
            synthesis_sources = []
            if kind == "ask" and source_step_id:
                sources = [
                    row for row in self.get(identity)["results"]
                    if (row.get("result") or {}).get("status") == "completed"
                    and row["state"] != "abandoned"
                    and row["result"].get("business_review", {}).get("status") != "rejected"
                ]
                source = next((row for row in sources if row["step_id"] == source_step_id), None)
                if not source:
                    raise ValueError("请选择一份已完整保存且可继续使用的研究，或直接提问。")
                if claim_review_index is not None and claim_review_index >= len(
                    source["result"].get("claims", []),
                ):
                    raise ValueError("所选研究中没有这条判断，请重新选择。")
                if synthesis_question_ids is None and not any((
                    question_id, task_id, story_id, insight_id, insight_ids,
                    counter_insight_id, comparison_step_ids,
                )):
                    synthesis_sources = source.get("synthesis_sources", [])
                if (inherit_focus and not insight_ids
                        and (not question_id or question_id == source.get("question_id"))):
                    if experiment_ids is None:
                        experiment_ids = list(source.get("experiment_ids") or [])
                    if insight_ids is None:
                        insight_ids = list(source.get("insight_ids") or [])
                    source_job_ids = source.get("selected_job_ids", [])
                    if (retrieval_case_name is None
                            and (not task_id or task_id == source.get("task_id"))):
                        retrieval_case_name = source.get("retrieval_case_name")
                        if retrieval_case_name:
                            material_focus_supplied = True
                    question_ids = {row["id"] for row in project["career"].get("questions", [])}
                    task_ids = {row["id"] for row in project["career"]["tasks"]}
                    story_ids = {row["id"] for row in project["career"]["stories"]}
                    available_insight_ids = {
                        row["id"] for row in project["career"].get("insights", [])
                    }
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
                        if source.get("insight_id") in available_insight_ids else None
                    )
                    counter_insight_id = counter_insight_id or (
                        source.get("counter_insight_id")
                        if source.get("counter_insight_id") in available_insight_ids else None
                    )
                    if not material_focus_supplied and not material_id and not material_ids:
                        material_ids = list(source.get("material_ids") or [])
                        material_id = (
                            source.get("material_id")
                            if not material_ids and source.get("material_id")
                            in project["public_document_ids"] else None
                        )
                    if question_id == source.get("question_id") and not comparison_step_ids:
                        comparison_step_ids = source.get("comparison_step_ids", [])
                    if question_id == source.get("question_id") and passage_ids is None:
                        passage_ids = source.get("passage_ids", [])
            insight_ids = list(insight_ids or [])
            selected_insights = [
                row for key in insight_ids for row in project["career"].get("insights", [])
                if row["id"] == key
            ]
            if insight_ids and (
                kind != "ask" or not 2 <= len(insight_ids) <= 4
                or len(set(insight_ids)) != len(insight_ids)
                or len(selected_insights) != len(insight_ids)
                or any((question_id, task_id, story_id, insight_id, counter_insight_id,
                        comparison_step_ids, synthesis_question_ids))
            ):
                raise ValueError("请选择本目标中的2至4条不同认识一起研究，单项焦点可另行提问。")
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
                if kind != "ask" and not _has_experiment_observations(task):
                    raise ValueError("请先为这项练习记录实际观察，再开始反思。")
                if kind == "reflect" or inherit_focus and kind in {"ask", "plan", "challenge"}:
                    question_id = question_id or task.get("question_id")
            user_question = question.strip() if kind in {"ask", "map"} else ""
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
                if inherit_focus and kind != "teachback":
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
            if insight_id and kind == "teachback" and inherit_focus:
                question_id = question_id or insight.get("question_id")
            understanding_check = kind == "teachback" or inquiry_answer
            if (kind in {"answer", "followup"} and not inquiry_answer
                    or kind == "plan" and source_step_id):
                if sources is None:
                    sources = [row for row in self.get(identity)["results"]
                               if row["current"] and row["result"]["status"] == "completed"]
                previous_assessment = next(
                    (row for row in sources
                     if (interview_source(row) if kind == "answer" else row["kind"] == "answer")
                     and (not source_step_id or row["step_id"] == source_step_id)), None
                )
                if previous_assessment:
                    interview_task_origin = deepcopy(previous_assessment.get("interview_origin"))
                    old_pair = (previous_assessment["result"].get("career_learning_context")
                                or {}).get("answer_comparison", [])
                    if kind in {"answer", "followup"} and len(old_pair) == 2:
                        comparison_followup_ids = [row["step_id"] for row in old_pair]
                        allowed = set(project["public_document_ids"]) | {
                            row.get("answer_document_id") for row in old_pair
                        } | {previous_assessment.get("answer_document_id")}
                        answer_pair_documents = list(dict.fromkeys(
                            key for key in (previous_assessment["result"].get("scope") or {}).get(
                                "archived_public_ids", [],
                            ) if key in allowed
                        ))
                    if inherit_focus and selected_job_ids is None:
                        original_step = next(row for row in project["steps"]
                                             if row["id"] == previous_assessment["step_id"])
                        effective = (previous_assessment["result"].get("investigation") or {}).get(
                            "effective_scope",
                        )
                        assessment_job_ids = list(effective["job_ids"] if effective is not None
                                                  else original_step["job_ids"])
                if previous_assessment and previous_assessment.get("understanding_check"):
                    if question_id and question_id != previous_assessment["question_id"]:
                        raise ValueError("请沿用这组理解自测对应的调查问题，或另开一组自测。")
                    if insight_id and insight_id != previous_assessment.get("insight_id"):
                        raise ValueError("请沿用这组理解自测对应的认识，或另开一组自测。")
                    question_id = previous_assessment["question_id"]
                    insight_id = previous_assessment.get("insight_id")
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
                    "ask", "map", "plan", "reflect", "teachback", "answer", "followup", "challenge"
                }:
                    raise ValueError("请选择已保存的调查问题，再继续提问、设计验证或反思。")
                if inquiry_answer:
                    if question.strip() and question.strip() != saved_question["question"]:
                        raise ValueError("调查问题已修改，请核对当前题目后再提交回答。")
                    material_ids = [key for key in saved_question.get("material_ids", [])
                                    if key in project["public_document_ids"]]
                parent_question = next(
                    (row for row in project["career"].get("questions", [])
                     if row["id"] == saved_question.get("parent_question_id")), None
                )
                if (kind in {"ask", "map", "plan"} and not material_focus_supplied
                    and not material_ids and not material_id):
                    material_ids = list(saved_question.get("material_ids") or [])
                if kind == "challenge":
                    hypothesis_a = hypothesis_a or saved_question.get("hypothesis_a", "")
                    hypothesis_b = hypothesis_b or saved_question.get("hypothesis_b", "")
                    chosen_task = next(
                        (row for row in project["career"]["tasks"] if row["id"] == task_id), {}
                    )
                    if chosen_task.get("question_id") not in {None, question_id}:
                        raise ValueError("请选择这个调查问题关联的实验，或取消实验选择。")
            if kind == "teachback" and (not (question_id or insight_id) or story_id or task_id):
                raise ValueError("请选择一条已保存的认识或调查问题做理解自测，不绑定经历或样本。")
            passage_ids = list(passage_ids or [])
            if passage_ids and (kind != "ask" or not question_id
                                or not 2 <= len(passage_ids) <= 4
                                or len(set(passage_ids)) != len(passage_ids)
                                or not set(passage_ids) <= {
                                    row["id"] for row in saved_question.get("evidence_passages", [])
                                }):
                raise ValueError("请选择同一调查问题中仍保留的2至4段不同摘录。")
            if autonomous and (kind != "ask" or not question_id or offline):
                raise ValueError("请选一个已保存的问题，并取消只整理原文，再开始连续查证。")
            comparison_step_ids = comparison_step_ids or []
            if comparison_step_ids:
                completed = {
                    row["step_id"]: row for row in self.get(identity)["results"]
                    if (row.get("result") or {}).get("status") == "completed"
                    and row["state"] != "abandoned"
                }
                pair = [completed[key] for key in comparison_step_ids if key in completed]
                answer_focus = ("question_id", "task_id", "story_id", "insight_id")
                answer_pair = len(pair) == 2 and all(
                    row["kind"] == "answer" and row.get("interview_question")
                    and row["interview_question"] == pair[0].get("interview_question")
                    and bool(row.get("understanding_check"))
                    == bool(pair[0].get("understanding_check"))
                    and all(row.get(key) == pair[0].get(key) for key in answer_focus)
                    for row in pair
                )
                if answer_pair:
                    requested = dict(zip(
                        answer_focus, (question_id, task_id, story_id, insight_id), strict=True,
                    ))
                    if any((requested[key] or None) != (pair[0].get(key) or None)
                           for key in answer_focus):
                        raise ValueError("请沿用这两次回答对应的认识、调查与经历，再开始对照。")
                    understanding_check = bool(pair[0].get("understanding_check"))
                    if inherit_focus:
                        pair_steps = [next(row for row in project["steps"]
                                           if row["id"] == answer["step_id"]) for answer in pair]
                        if not selected_job_ids:
                            selected_job_ids = None
                            assessment_job_ids = list(dict.fromkeys(
                                key for step in pair_steps for key in step["job_ids"]
                                if key in project["job_ids"]
                            ))
                        answer_ids = {row.get("answer_document_id") for row in pair}
                        allowed = set(project["public_document_ids"]) | answer_ids
                        answer_pair_documents = []
                        for answer, step in zip(pair, pair_steps, strict=True):
                            prior = answer["result"]
                            practice = (prior.get("career_learning_context") or {}).get(
                                "practice_experiment",
                            ) or {}
                            answer_pair_documents.extend([
                                *((prior.get("scope") or {}).get("archived_public_ids",
                                  step["public_document_ids"])),
                                answer.get("answer_document_id"),
                                (practice.get("artifact_document") or {}).get("document_id"),
                            ])
                        answer_pair_documents = list(dict.fromkeys(
                            key for key in [*answer_pair_documents, *material_ids, material_id]
                            if key and key in allowed
                        ))
                candidates = {
                    row["step_id"]: row
                    for row in self.get(identity)["results"]
                    if (answer_pair or (row.get("question_id") == question_id if question_id
                        else (row.get("result") or {}).get("work_map")))
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
                        "请选择同一道题和同一组材料下的两次完整回答、同一调查的两次研究，"
                        "或当前目标下两份完整工作地图。"
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
            experiment_ids = list(experiment_ids or [])
            compared_experiments = []
            if experiment_ids:
                if (kind != "ask" or not 2 <= len(experiment_ids) <= 4
                        or len(set(experiment_ids)) != len(experiment_ids)
                        or any((task_id, story_id, insight_id, insight_ids, counter_insight_id,
                                comparison_step_ids, synthesis_question_ids, passage_ids))):
                    raise ValueError("请单独选择2至4项不同实验进行对照，再编辑本次提问。")
                by_id = {row["id"]: row for row in project["career"]["tasks"]}
                if any(key not in by_id for key in experiment_ids):
                    raise ValueError("所选实验已不在当前目标中，请重新选择。")
                compared_experiments = [by_id[key] for key in experiment_ids]
                if question_id and any(row.get("question_id") != question_id
                                       for row in compared_experiments):
                    raise ValueError(
                        "实验来自不同调查，请作为独立对照提问，或选择同一问题的实验。"
                    )
            answer_document_id, answer_record = None, None
            if material_id and material_id not in (project.get("public_document_ids") or []):
                raise ValueError("这份资料已不在当前目标中，请重新选择或先加入资料。")
            if any(key not in (project.get("public_document_ids") or []) for key in material_ids):
                raise ValueError("重点对读的资料中有已移出的原文，请重新加入或调整资料选择。")
            if kind == "map" and set(material_ids) & personal_documents(project["career"]):
                raise ValueError("工作地图请选择工作说明或调研资料；个人经历和实验可另行查证。")
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
                gaps = previous["result"].get("gaps", [])
                if feedback_gap_index is not None and feedback_gap_index >= len(gaps):
                    raise ValueError("这份反馈中没有所选的未知项，请重新选择。")
                feedback_origin = {
                    "step_id": previous["step_id"], "question": previous["interview_question"],
                    "project_id": identity, "project_title": project["title"],
                    "answer_document_id": previous.get("answer_document_id"),
                    "gap_index": feedback_gap_index,
                    "gap": gaps[feedback_gap_index] if feedback_gap_index is not None else None,
                    "story_id": previous.get("story_id"),
                    "notice": "旧反馈与未知是验证起点，不是已证实的事实；须回读回答和工作原文。",
                }
                question = (
                    QUESTIONS["plan"] + "\n本次只围绕这次模拟面试回答的证据缺口，设计一个最小练习。"
                    "不要把表达不清直接当作能力不会，先区分需要重新表达与确实缺少实际观察。"
                    "完整原题及明确点选的未知见career_evidence.feedback_origin。"
                    "按其step_id用read_research_history回查完整旧反馈，不以截短预览替代末尾限制。"
                    "点选了gap时只针对该项设计一项验证；未点选则从完整反馈中确定一个可检验问题。"
                    "按selected_answer读取用户回答原文，不照抄旧反馈作为事实。"
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
                if material_ids:
                    question += (
                        "本次用户明确选定career_evidence.selected_materials列出的重点资料。"
                        "按各自document_id读取相关原文与限定；可用read_archived_documents批读，"
                        "按需要续读，不靠标题或旧回答代替正文。把各份资料的工作对象、任务、"
                        "交付物和条件放在一起解释，说明共同点、分歧与尚不能连接之处。"
                        "同一资料的不同工作线分别保留，不能把一侧任务接到另一侧交付物上；"
                        "一侧的条件不能覆盖其他资料。未读部分保留未知，不凑齐比较项或选胜者。"
                        "重点选择不表示资料来自独立来源；用户笔记和业务说明保留来源性质，"
                        "涉及岗位个人责任或招聘要求时仍需该岗位原文支持。"
                    )
                if compared_experiments:
                    question += (
                        "本轮用户明确对照career_evidence.selected_experiment_ids对应的完整实验。"
                        "experiments保留它们的预期、设计、条件、用户观察和产物定位。"
                        "分别核对原先预期与实际记录，识别改变了什么、控制了什么以及缺失条件；"
                        "未执行的计划与已记录观察分开，不把done、成功次数或较新记录当作更正确。"
                        "需要核对日志时按本轮范围读取各自原文，未重读就明确尚未核实。"
                        "只在可比较的条件下讨论解释的支持、挑战和未知，不从相关差异推定因果。"
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
            elif kind == "answer" and inquiry_answer:
                if not answer.strip():
                    raise ValueError("请先用自己的话回答这个调查问题，可以明确保留未知。")
                questions, question_index = [saved_question["question"]], 0
                question = "直接回答调查问题：" + questions[0]
                reply = None
                answer_record = {"interview_question": questions[0], "answer": answer}
            elif kind == "answer":
                if not answer.strip():
                    raise ValueError("请先写下你的真实回答。")
                interview = next(
                    (
                        row
                        for row in sources
                        if interview_source(row)
                        and (not source_step_id or row["step_id"] == source_step_id)
                    ),
                    None,
                )
                if not interview:
                    raise ValueError("请先选择当前目标下已生成的面试问题。")
                interview_result = interview["result"]
                interview_task_origin = interview_task_origin or interview_origin(
                    interview_result, interview["step_id"], question_index,
                )
                story_id, task_id = interview.get("story_id"), interview.get("task_id")
                questions = interview_result.get("interview_questions") or [
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
                if kind == "map":
                    if user_question:
                        question += "\n本次最想看清的工作关系：\n" + user_question
                    if material_ids:
                        question += (
                            "\n用户选定的重点原文见career_evidence.selected_materials。逐份读取正文与限定，"
                            "按各自工作线连接任务与交付物，再比较共同点、差异及迁移前提。"
                            "同一资料的不同工作线分别保留，不能把一侧任务接到另一侧交付物上，"
                            "也不能只因工具相同就合并职责。未说明的责任和无法连接之处保留未知。"
                            "用户笔记仍是用户提供的资料，不是独立验证或个人能力证明。"
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
            if comparison_followup_ids:
                question += (
                    "\n本轮继续回答或追问两次解释对照后提出的具体问题；"
                    "selected_answer_comparison保留原来的两次解释、各自观察和未知，"
                    "须先读本轮selected_answer，再按可读原文核对当前回答是否回应了该追问。"
                    "不要重做整套对照，也不因这次回答更肯定就补出未执行的验证或正确性。"
                )
            if practice_task_id:
                practice = next((row for row in project["career"]["tasks"]
                                 if row["id"] == practice_task_id), None)
                origin = (practice or {}).get("feedback_origin") or {}
                original = next((row for row in project["career"]["runs"]
                                 if row["step_id"] == origin.get("step_id")
                                 and row["kind"] == "answer"), None)
                if (not practice or not practice.get("outcome") or not original
                        or origin.get("project_id", identity) != identity):
                    raise ValueError("请先记录这项练习的实际观察，再回到本目标中的原题作答。")
                same_question = (
                    original.get("question_id") == question_id
                    and original["interview_question"] == questions[question_index]
                    and bool(original.get("inquiry_answer")) == bool(inquiry_answer)
                )
                if not inquiry_answer:
                    same_question = same_question and (
                        original.get("source_step_id") == source_step_id
                        and original.get("question_index") == question_index
                    )
                if not same_question:
                    raise ValueError("这项观察承接的是另一道原题，请从练习记录中重答对应问题。")
                feedback_origin = deepcopy(origin)
                question += (
                    "\n本次是带着实际练习观察重答同一原题。"
                    "career_evidence.selected_practice_experiment保留明确选中的完整计划、预期和观察。"
                    "先读取feedback_origin所指的旧反馈、原回答及练习产物，再与本次回答对照："
                    "指出哪个解释因哪项实际观察而改变，哪些条件尚未执行或仍不能判断。"
                    "反馈只是分析，不因重答更长、练习标为done或观点更肯定就认定理解进步；"
                    "用户记录不是独立核验，未执行的对照组不能写成成功。"
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
                    if not task or not _has_experiment_observations(task):
                        raise ValueError("请先为这个工作样本记录实际观察，再围绕它面试。")
                    if not task.get("outcome", "").strip():
                        question += ("所选样本尚未整理整体观察；按comparison_rows逐组提问，"
                                     "未记录observed的条件保留未知，不将局部观察当作全部完成。")
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
            if interview_task_origin:
                question += (
                    "本题承接career_evidence.selected_interview_task中的那一项调查。"
                    "保留原问题、岗位对象、条件与未知，不把其他分项的工作或经验混入。"
                    "当时的解释不是标准答案；先按定位回读本轮可用原文，再反馈或追问。"
                )
            if insight_id and kind in {"ask", "challenge"}:
                question += (
                    "用户明确选中的个人认识在career_evidence.selected_learning_note，"
                    "请回查原文和观察，说明它还能支持什么、哪些需修正、哪些仍未知。"
                    "它可能已经搁置，不因本次讨论而自动恢复；不因记录较新或较旧就判断真假。"
                )
            if insight_id and understanding_check:
                question += (
                    "本次自测明确围绕career_evidence.selected_learning_note的完整认识、原观察、条件与未知。"
                    "这份认识可能有误或已搁置，练习不恢复选用；先回读可用原文，不把个人观点当标准答案。"
                    "出题时用条件变化、反例或证据选择检验推理，不在claims直接泄露题目的答案，"
                    "不要求复述笔记原句；反馈与追问保留同一条认识，并区分概念解释和实际经历。"
                )
            if insight_ids:
                question += (
                    "本轮综合career_evidence.selected_learning_notes中用户明确选定的几条认识。"
                    "逐条保留其问题、适用条件、观察、末尾限定与未知；已搁置的记录只供本次重查。"
                    "围绕共同业务问题、任务、交付物、责任、能力或工具说明它们能怎样连接，"
                    "哪些只是不同维度，哪些在特定条件下冲突，哪些尚不能连接。"
                    "不要投票、强行合并或按新旧决定真伪；用户理解、旧分析和旧摘录都不是新增证据。"
                    "用来源定位回读本轮可用原文，有实验依据时可read_experiments读取完整观察。"
                    "来源已不在当前目标时明确不能重核，不自动带回资料。形成有条件的综合解释，"
                    "指出最值得继续验证的一个缺口，不自动改写、接替或恢复选用这些认识。"
                )
            if counter_insight_id:
                question += (
                    "本次另一条完整认识在career_evidence.selected_counter_learning_note，"
                    "有对应实验时见counter_experiment。与所选认识A或用户改写的解释A对照，"
                    "分别回读两边可用的原文与观察，保留各自末尾条件、未知和当时语境。"
                    "说明看法差异是否来自适用条件、观察或解释，不预设互斥，也不因较新而判定正确。"
                    "两条记录都只是用户理解；无从核实的部分保留未知，不把认识ID当作原文引用。"
                )
            if question_id and kind == "map":
                question += (
                    "本地图关联career_evidence.selected_inquiry中的调查问题，"
                    "以问题定位要解释的工作关系，仍需读取原文。"
                    "关联不会修改用户结论或状态，不能把个人理解当作已验证的事实。"
                )
            elif question_id:
                question += (
                    "本次围绕career_evidence.selected_inquiry中的持续调查问题展开，"
                    "why_matters是用户说明的调查目的、个人背景或取舍，不是岗位事实或能力认证。"
                    "结合它解释工作差异与适用条件；用户在意的条件若未在原文说明，应保留未知。"
                    "结合用户本次提问、关心它的理由和希望补充的证据，回读相关原文。"
                    "origin_discussion包含问题起点的原分析与完整地图，"
                    "保留原关系理由、限定和迁移边界，把待检验解释带入后续验证，不能只按问题标题泛化。"
                    "若含incomplete_origin，本题来自一轮未完成或仅整理原文的研究；"
                    "只借助原问题、状态和资料定位回读原文，不继承未完成草稿或把旧失败当作结论。"
                    "若用户已有结论，它仍是待查证的个人记录，不当作独立事实。"
                    "若含origin_learning_note，这是用户明确关联的问题起点，保留完整个人认识、"
                    "观察、未知及选用状态；已搁置的认识不恢复选用。linked_experiment保留当前"
                    "保存的实验设计、计数与观察，只说明记录内容，不能单凭完成状态证明能力或因果。"
                    "原始产物仍需按本轮目录回读，未在范围内则保留无法重核；不自动改写用户认识。"
                    "若含carried_understanding，它是另一个目标下保存的理解，先核对当前岗位的适用条件；"
                    "其中learning_notes若存在，是用户点选的两份个人认识快照，分别保留原目标、观察、"
                    "未知与搁置状态。共同问题尚未形成结论；逐份核对条件与来源，不将旧认识视为"
                    "当前事实，不按措辞相近判定相同、矛盾或进步，也不恢复原记录的选用状态。"
                    "其中work_relations若存在，是用户选定的两条历史工作关系及完整理由、限定、"
                    "当时范围和引用位置；分别核对两侧，不因同词或同工具就合并工作或推定迁移。"
                    "source_references提供原文定位；JD按historical_cutoffs或as_of使用"
                    "read_historical_job，核对返回的snapshot_id与原定位是否一致。当前JD不能替代旧版本。"
                    "原文未带入、缺失或版本无法重核时保留未知，不把旧引用位置当作本轮已读证据。"
                    "原材料不在本轮范围时，明确无法重核旧结论，不用旧认识替代当前原文。"
                    "carried_understanding若含research_claims，这是从另一目标带来的历史Agent分析，"
                    "保留其原文明示、归纳或推断性质及必备、加分限定；research_gaps是当时的未知。"
                    "work_map是原分析的工作关系，保留关系理由、迁移边界和未知，不当作新证据。"
                    "source_jobs是原研究范围，source_references仅供定位，并未自动带入当前资料。"
                    "结合当前目标重新核对；来源不可读就明确无法重核，不把旧分析当作个人能力或新证据。"
                    "carried_understanding.inquiry若存在，是本轮明确取回的其他目标调查快照，"
                    "含旧问题、A/B解释和摘录标注；它们未自动变成当前假设、结论或可读资料。"
                    "先核对旧场景与当前范围，再按可用原文查证，不用标注关系代替证据。"
                    "明确哪些已经有材料支持、哪些还不能回答，并给出下一步最有价值的查证方向。"
                    "不因为本轮生成回答而宣称问题已解决。"
                    "child_inquiries是明确关联的子调查目录，不依赖标题关键词。若与本次问题有关，"
                    "用read_inquiry按id回查完整解释、限定与待补证据，再读取本轮可用原文，"
                    "说明对子问题和原问题分别能支持什么、还不能说明什么。"
                    "目录中的has_user_conclusion和answered不证明已解决，不恢复parked问题。"
                    "若含followup_to_recheck，这是用户点选带回的直接后续问题及当次答复。"
                    "先对照原问题的当前用户结论与完整限定，再重读该次答复指向的可用原文，"
                    "说明原判断哪些可保留、哪些需要缩窄或修订、哪些仍未知。后续研究的观点"
                    "及用户结论都不是新证据；保留它当时的岗位范围，不能把局部观察外推到整个目标。"
                    "本轮形成复核建议，不自动更新原问题的结论或状态。"
                )
                if passage_ids:
                    question += (
                        "本次明确对照selected_inquiry.selected_passages中的2至4段摘录及其完整标注。"
                        "分别回读对应的同一份归档原文和上下文；摘录、用户的支持或挑战标注及"
                        "target_view都不是本轮独立证据。先核对主体、业务对象、时间与适用条件"
                        "是否相同，再解释是实际冲突、条件不同、补充信息还是仍无法判断。"
                        "同一归档的多段摘录不算多份独立来源，不按标注条数选赢家。"
                        "材料已移出本轮范围或原文不可读时明确无法重核，不自动恢复。"
                        "给出能区分解释的下一项证据，不自动改写原问题、结论或摘录标注。"
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
                        "target_view保留标注当时针对的具体解释原句；为空时未指定解释，"
                        "不能擅自归到解释A或B。若原句与当前解释不同，先说明针对的是旧句或"
                        "另一个判断，不把原标注自动移到新解释上。按每项解释分别核对其依据、"
                        "反例和条件；摘录条数不代表独立来源数量，也不据此投票选出解释。"
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
                    "若包含comparison_rows，逐组区分expected预期与observed实际记录；"
                    "observed为空的组尚无结果，不能用预期补齐。comparison_conditions是用户称保持的条件，"
                    "不保证已控制变量；比较结果时指出缺少的条件、反例和仍不能推出的结论。"
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
                    "若career_evidence.selected_answer_comparison非空，用户在对照两次自述回答与反馈。"
                    "逐次读取其中完整题目、原回答、当时反馈与待核原文；先区分表述变化、"
                    "推理条件变化与仍无依据的部分。较新、较长、语气更确定都不表示理解更正确，"
                    "每侧的practice_experiment_then、feedback_origin_then与input_scope_then"
                    "保留那次回答带入的实际观察、所选未知和资料范围；缺少时不要补造练习。"
                    "对照每组expected与observed，空白仍未执行，不以现在编辑的练习代替当时输入。"
                    "retrieval_review_then只作旧运行线索，须回读本轮可用的原记录与工作原文。"
                    "具体指出哪项观察支持或挑战哪句解释，哪些差异来自输入条件，"
                    "再在gaps提出能区分剩余解释的一道完整追问，允许暂时无法判断。"
                    "自述回答和模型反馈不证明实际经历或能力。不要替用户补造进步或生产结果。"
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
            feedback_task = next((row for row in project["career"]["tasks"]
                                  if row["id"] == (practice_task_id or task_id)), {})
            if feedback_origin is None:
                feedback_origin = deepcopy(feedback_task.get("feedback_origin"))
            if (feedback_origin and inherit_focus
                    and feedback_origin.get("project_id", identity) == identity):
                scope_step_id = (
                    feedback_origin["step_id"] if kind == "plan" and source_step_id
                    else feedback_task.get("source_step_id")
                )
                scope_step = next((row for row in project["steps"]
                                   if row["id"] == scope_step_id), {})
                scope_run = self.store.get(scope_step["run_id"]) if scope_step.get("run_id") else {}
                scope = ((scope_run or {}).get("result") or {}).get("scope") or {}
                if selected_job_ids is None and assessment_job_ids is None:
                    assessment_job_ids = [key for key in scope_step.get("job_ids", [])
                                          if key in project["job_ids"]]
                source_documents = scope.get("archived_public_ids", scope_step.get(
                    "public_document_ids", [],
                ))
                allowed_documents = set(project["public_document_ids"]) | {
                    feedback_origin.get("answer_document_id"),
                }
                feedback_documents = list(dict.fromkeys(key for key in [
                    *source_documents, feedback_origin.get("answer_document_id"),
                    feedback_task.get("artifact_document_id")
                    if feedback_task.get("feedback_origin") else None,
                    *material_ids, material_id, focused_document_id,
                ] if key and key in allowed_documents))
                retrieval_review = deepcopy(scope_step.get("career_retrieval_review"))
            if feedback_origin and not (kind == "plan" and source_step_id):
                if feedback_origin.get("project_id", identity) != identity:
                    question += (
                        "feedback_origin属于复用记录的原目标，保留原题与未知；"
                        "不能按本目标read_research_history读取该旧step_id，也不自动加入旧目标资料。"
                        "本轮依据fixed_scope中的当前岗位和已选练习，检查适用条件；"
                        "无法重核旧反馈时明确未知，不把旧观察当作新岗位的能力证明。"
                    )
                else:
                    question += (
                        "这项练习承接的原题与反馈定位见career_evidence.feedback_origin；"
                        "若有gap，保留这项明确点选的未知，按step_id读取完整旧反馈，再对照实际观察。"
                        "原反馈不是标准答案，不把尚未观察的条件写成完成，也不自动修改用户认识。"
                    )
            if kind in {"reflect", "ask", "challenge", "plan", "interview", "teachback", "pitch",
                        "answer", "followup"} and (
                task_id or retrieval_review is not None
                or inherit_focus and (insight_id or question_id or story_id)
            ):
                from work_observer.research.retrieval_experiment import (
                    is_retrieval_task,
                    review_context,
                )

                retrieval_task_id = task_id
                if not retrieval_task_id and inherit_focus and not story_id:
                    origin_id = insight_id or (
                        saved_question.get("source_insight_id") if question_id else None
                    )
                    origin_note = next((row for row in project["career"].get("insights", [])
                                        if row["id"] == origin_id), {})
                    retrieval_task_id = self._retrieval_note_task_id(identity, origin_note)
                focused_story = next((row for row in project["career"]["stories"]
                                      if row["id"] == story_id), {})
                story_source = focused_story.get("retrieval_source") if inherit_focus else None
                if retrieval_review is not None:
                    local_task = {}
                elif story_source and not task_id:
                    retrieval_review = deepcopy(story_source)
                    if focused_story.get("reused_from"):
                        retrieval_review["source_scope_only"] = True
                        question += (
                            "这份经历沿用自另一目标，retrieval_review只保留旧实验起点。"
                            "本轮目标岗位以fixed_scope为准，读取当前目标JD核对迁移条件；"
                            "旧岗位要求与旧实验结果不能替代新岗位依据，不自动加入其他目标原文。"
                        )
                    local_task = {}
                else:
                    local_task = next((row for row in project["career"]["tasks"]
                                       if row["id"] == retrieval_task_id), {})
                if retrieval_review is None and local_task and is_retrieval_task(local_task):
                    retrieval_review = review_context(self.repository, project, local_task)
                if retrieval_review is not None:
                    if retrieval_review.get("input", {}).get("cases"):
                        question += (
                            "本次是小样本检索评估集，每条样例各有原表达、改写表达和使用者标签。"
                            "逐条核对命中、漏回和额外返回，尤其保留不应命中样例上的额外来源；"
                            "不能只取最前两组或只看累计指标。累计按样例×来源计数，"
                            "同一来源在不同样例可重复计入，不是答案准确率或独立标注结论。"
                            "原文不完整时，未返回不能算负例验证成功；指出最值得继续核对的失败。"
                            "若有previous_suite_comparison，按同名样例回查两次返回与标签："
                            "新增或移除样例没有另一侧结果，标签或范围变化不能冒充查询修复。"
                            "须回读当前与前次产物，不把历史线索当作本轮新执行的结果。"
                        )
                    if retrieval_review.get("artifact_document_id") not in project[
                        "public_document_ids"
                    ]:
                        retrieval_review.update(
                            available=False,
                            unavailable_reason="原运行记录不在当前目标，不能以后来记录替代。",
                        )
                    if retrieval_case_name:
                        from work_observer.research.retrieval_suite import select_case

                        retrieval_case = select_case(retrieval_review, retrieval_case_name)
                        question += (
                            "本轮只围绕selected_retrieval_case这条明确选中的样例追问。"
                            "读取它的两组查询、使用者预期、实际命中与失败定位，再核对原文；"
                            "区分表达不匹配、片段上限、额外来源和标签仍需核实的情况。"
                            "按用户本轮问题给出有引用的有限解释及最有价值的下一项证据，"
                            "不重复整组评估，也不以旧记录证明已经修复或学会。"
                        )
                    if inherit_focus or retrieval_case_name:
                        explicit_scope = selected_job_ids if selected_job_ids is not None else (
                            assessment_job_ids
                        )
                        if explicit_scope is None and retrieval_review.get("source_scope_only"):
                            explicit_scope = project["job_ids"][:]
                        retrieval_job_ids = explicit_scope if explicit_scope is not None else [
                            key for key in retrieval_review["input"]["job_ids"]
                            if key in project["job_ids"]
                        ]
                        selected_job_ids = retrieval_job_ids
                        previous_task = next((
                            row for row in project["career"]["tasks"]
                            if row["id"] == local_task.get("previous_task_id")
                        ), {})
                        answer_source = next((
                            row for row in project["career"]["runs"]
                            if row["step_id"] == local_task.get("source_step_id")
                        ), {})
                        retrieval_document_ids = list(dict.fromkeys(key for key in [
                            *retrieval_review["input"]["document_ids"],
                            retrieval_review.get("artifact_document_id"),
                            (retrieval_review.get("previous_suite_comparison") or {}).get(
                                "artifact_document_id",
                            ),
                            ((retrieval_review.get("note_origin") or {}).get("source_case")
                             or {}).get("artifact_document_id"),
                            previous_task.get("artifact_document_id"),
                            answer_source.get("answer_document_id"),
                            *material_ids, material_id, focused_document_id, answer_document_id,
                            focused_story.get("document_id"),
                        ] if key in project["public_document_ids"]))
                    question += (
                        "本次练习或经历来源另有retrieval_review：available为真且在fixed_scope内时，"
                        "先读取artifact_document_id的运行记录；不可读时说明无法重核，不换用新实验。"
                        "可按各查询diagnostic_read_start直达漏回说明，再回查本轮可用的JD或工作原文。"
                        "若有review_origin，可用read_research_history按step_id取回本次复验承接的"
                        "完整反馈与当时认识；旧句子仅作线索，不能直接充当本轮引用或已证实的解释。"
                        "若有note_origin，保留这次运行时选中的完整个人认识、观察与未知，"
                        "对照新结果说明哪些受支持、哪些受挑战、哪些仍未知；不以现在编辑的笔记替换。"
                        "note_origin.source_case保留原认识针对的具体样例和当时的查询、标签与返回。"
                        "将它与本轮同名样例逐组对照；原样例被移除或改名时，说明无法直接复验，"
                        "不能拿整组累计数字或另一条样例冒充支持，也不因改了标签就说认识通过检验。"
                        "保留两组查询、使用者标签和实际返回；单份复查候选不能补进原列表或抬高指标。"
                        "需要核对当时JD时，可按as_of用read_historical_job回读，不把当前新正文冒充旧输入。"
                        "原文缺失或已移出范围时明确无法核对，不改用工作区其他来源替代，"
                        "也不从局部词面结果推断语义效果、企业要求或个人胜任。"
                    )
            if retrieval_case_name and (not task_id or retrieval_case is None):
                raise ValueError("请选定本目标中已保存的评估集和具体样例，再准备追问。")
            if selected_job_ids is None and assessment_job_ids is not None:
                selected_job_ids = assessment_job_ids
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
            preferred = [*material_ids, material_id, focused_document_id]
            topic = [user_question]
            topic.extend(row["current_view"] + "\n" + row.get("open_question", "")
                         for row in selected_insights)
            preferred.extend((row.get("source_passage") or {}).get("public_document_id")
                             for row in selected_insights)
            preferred.extend(passage.get("public_document_id") for row in selected_insights
                             for passage in row.get("source_passages", []))
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
            preferred.extend(row.get("artifact_document_id") for row in compared_experiments)
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
            if retrieval_document_ids is not None:
                documents = retrieval_document_ids
                omitted = len(set(project["public_document_ids"]) - set(documents))
            if feedback_documents is not None:
                documents = feedback_documents
                omitted = len(set(project["public_document_ids"]) - set(documents))
            if answer_pair_documents is not None:
                documents = answer_pair_documents
                omitted = len(set(project["public_document_ids"]) - set(documents))
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
            if selected_job_ids or assessment_job_ids is not None or retrieval_job_ids is not None:
                project["steps"][-1]["job_ids"] = selected_job_ids[:]
            if retrieval_review is not None:
                project["steps"][-1]["career_retrieval_review"] = retrieval_review
            if retrieval_case is not None:
                project["steps"][-1]["career_retrieval_case"] = retrieval_case
            if feedback_origin:
                project["steps"][-1]["career_feedback_origin"] = feedback_origin
            if practice_task_id:
                project["steps"][-1]["career_practice_task_id"] = practice_task_id
            if retrieval_document_ids is not None:
                project["steps"][-1]["career_source_document_ids"] = retrieval_document_ids[:]
            if feedback_documents is not None:
                project["steps"][-1]["career_source_document_ids"] = feedback_documents[:]
            if answer_pair_documents is not None:
                project["steps"][-1]["career_source_document_ids"] = answer_pair_documents[:]
            project["steps"][-1]["career_omitted_documents"] = omitted
            if adaptive and not offline:
                project["steps"][-1]["career_adaptive"] = True
                project["steps"][-1]["career_adaptive_question"] = user_question
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
                    "material_ids": material_ids if kind in {"ask", "map", "plan"}
                    or inquiry_answer else [],
                    "story_id": story_id if kind in {"pitch", "ask"} | interview_kinds else None,
                    "insight_id": insight_id
                    if kind in {"ask", "challenge"} or understanding_check else None,
                    "insight_ids": insight_ids,
                    "counter_insight_id": counter_insight_id,
                    "question_id": question_id,
                    **({"feedback_origin": feedback_origin} if feedback_origin else {}),
                    **({"practice_task_id": practice_task_id} if practice_task_id else {}),
                    **({"retrieval_case_name": retrieval_case["name"]} if retrieval_case else {}),
                    "comparison_step_ids": comparison_step_ids,
                    "passage_ids": passage_ids,
                    "synthesis_sources": synthesis_sources,
                    "selected_job_ids": selected_job_ids[:],
                    "autonomous_rounds": 3 if autonomous else 0,
                    "materials_only": not bool(project["job_ids"]),
                    "understanding_check": understanding_check,
                    "inquiry_answer": inquiry_answer,
                    "requirement_key": requirement_key if selected_requirement else "",
                    "requirement_text": selected_requirement["text"]
                    if selected_requirement
                    else "",
                    "interview_question": questions[question_index] if kind == "answer" else "",
                    "task_id": task_id if has_task else None,
                    "experiment_ids": experiment_ids,
                    "created_at": now(),
                    **({"interview_origin": interview_task_origin}
                       if interview_task_origin else {}),
                }
            )
            if claim_review_index is not None:
                project["career"]["runs"][-1]["claim_review_index"] = claim_review_index
            if has_task:
                project["steps"][-1]["career_task_id"] = task_id
            if experiment_ids:
                project["steps"][-1]["career_experiment_ids"] = experiment_ids[:]
            if insight_id and (kind in {"ask", "challenge"} or understanding_check):
                project["steps"][-1]["career_insight_id"] = insight_id
            if insight_ids:
                project["steps"][-1]["career_insight_ids"] = insight_ids[:]
            if counter_insight_id:
                project["steps"][-1]["career_counter_insight_id"] = counter_insight_id
            if question_id:
                project["steps"][-1]["career_question_id"] = question_id
            if comparison_step_ids:
                project["steps"][-1]["career_comparison_steps"] = comparison_step_ids
            elif comparison_followup_ids:
                project["steps"][-1]["career_comparison_steps"] = comparison_followup_ids
            if passage_ids:
                project["steps"][-1]["career_passage_ids"] = passage_ids
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
            if kind in {"ask", "map", "plan"} and material_ids:
                project["steps"][-1]["career_material_ids"] = material_ids[:]
            if inquiry_answer:
                project["steps"][-1]["career_inquiry_answer"] = True
                project["steps"][-1]["career_material_ids"] = material_ids[:]
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
                source_task_indices = [n for n in range(len(
                    (result.get("investigation") or {}).get("tasks", []),
                )) if index in task_action_indices(result, n)]
                tasks.append(
                    {
                        "id": uuid4().hex,
                        "source_key": key,
                        "origin": "research",
                        "question_id": source.get("question_id"),
                        "previous_task_id": source.get("task_id"),
                        "source_step_id": step_id,
                        **({"feedback_origin": deepcopy(source["feedback_origin"])}
                           if source.get("feedback_origin") else {}),
                        **({"source_task_index": source_task_indices[0]}
                           if len(source_task_indices) == 1 else {}),
                        **({"target_requirement": step["career_requirement"]}
                           if step.get("career_requirement") else {}),
                        "design_change": "",
                        **action,
                        "comparison_rows": [
                            {**row, "observed": ""} for row in action.get("comparison_rows", [])
                        ],
                        **({"purpose": "understanding_check"}
                           if result["application_plan"].get("purpose") == "understanding_check"
                           else {}),
                        "state": "planned",
                        "outcome": "",
                        "hypothesis": action.get("hypothesis", ""),
                        "artifact": "",
                        "created_at": now(),
                    }
                )
            self.projects._write(project)
        return self.get(identity)

    def _retrieval_record(self, project, task_id):
        from work_observer.research.retrieval_experiment import task_record

        task = next((row for row in project["career"]["tasks"] if row["id"] == task_id), None)
        _, record = task_record(self.repository, project, task)
        return task, record

    def _retrieval_note_task_id(self, identity, note):
        task_id = (note or {}).get("task_id")
        if not task_id and (note or {}).get("source_step_id"):
            source = next((row for row in self.get(identity)["results"]
                           if row["step_id"] == note["source_step_id"]), {})
            recalled = (source.get("result") or {}).get("career_learning_context") or {}
            task_id = (recalled.get("retrieval_review") or {}).get("task_id")
        return task_id

    def retrieval_experiment_record(self, identity, task_id):
        project = self._project(identity)
        task, record = self._retrieval_record(project, task_id)
        return {"input": record["input"], "record_kind": record.get("record_kind"), "previous": {
            "task_id": task_id, "title": task["title"], "as_of": record.get("as_of"),
            "hypothesis": task.get("hypothesis", ""), "sources": record["sources"],
            "comparison_rows": record["comparison_rows"],
            "question_id": task.get("question_id"), "source_step_id": task.get("source_step_id"),
            "review_step_id": task.get("retrieval_review_step_id"),
            "note_origin": task.get("retrieval_note_origin"),
        }}

    def _retrieval_note_origin(self, identity, project, previous, source_insight_id):
        if not source_insight_id:
            return None
        note = next((row for row in project["career"].get("insights", [])
                     if row["id"] == source_insight_id), None)
        note_task = self._retrieval_note_task_id(identity, note)
        if (not previous or not note or note_task != previous["id"]
                and (previous.get("retrieval_note_origin") or {}).get("id") != source_insight_id):
            raise ValueError("请选择这项检索实验或其反馈关联的认识，再带入原查询继续验证。")
        origin = {key: note.get(key) for key in (
            "id", "task_id", "question_id", "previous_view", "observation", "current_view",
            "open_question", "use_for_research",
        )}
        origin["recorded_at"] = note.get("updated_at") or note["created_at"]
        step = next((row for row in project["steps"]
                     if row["id"] == note.get("source_step_id")), {})
        source = (self.store.get(step["run_id"]) if step.get("run_id") else {}) or {}
        context = ((source.get("result") or {}).get("career_learning_context") or {})
        if source.get("state") != "invalidated" and context.get("retrieval_case"):
            review = context.get("retrieval_review") or {}
            origin["source_case"] = {
                **deepcopy(context["retrieval_case"]), "step_id": step["id"],
                "task_id": review.get("task_id"),
                "as_of": review.get("as_of"),
                "artifact_document_id": review.get("artifact_document_id"),
            }
        if "source_case" not in origin:
            linked = next((row for row in project["career"]["tasks"]
                           if row["id"] == note.get("task_id")), {})
            prior = linked.get("retrieval_note_origin") or (
                context.get("retrieval_review") or {}
            ).get("note_origin") or {}
            if (prior.get("id") and note.get("replaces_insight_id") == prior["id"]
                    and prior.get("source_case")):
                origin["source_case"] = deepcopy(prior["source_case"])
        return origin

    def retrieval_experiment(
        self, identity, *, question_id=None, source_step_id=None, hypothesis="",
        previous_task_id=None, review_step_id=None, source_insight_id=None, save=False, **inputs,
    ):
        from work_observer.research.retrieval_experiment import (
            compare_returns,
            comparison_changes,
            record_text,
            run_retrieval_comparison,
        )

        project = self._project(identity)
        previous, previous_record = None, None
        if previous_task_id:
            previous, previous_record = self._retrieval_record(project, previous_task_id)
            if previous_record.get("record_kind") == "retrieval_suite":
                raise ValueError("这是一组评估样例，请在检索评估集入口继续运行。")
            if (source_step_id and source_step_id != previous.get("source_step_id")
                    or question_id and question_id != previous.get("question_id")):
                raise ValueError("请保留上次检索练习的原回答与调查关联，或另开一次独立对照。")
            question_id = previous.get("question_id")
        review_origin = None
        note_origin = self._retrieval_note_origin(identity, project, previous, source_insight_id)
        if review_step_id:
            review = next((row for row in self.get(identity)["results"]
                           if row["step_id"] == review_step_id
                           and (row.get("result") or {}).get("status") == "completed"
                           and row["state"] != "abandoned"), None)
            recalled = ((review or {}).get("result") or {}).get(
                "career_learning_context", {},
            ).get("retrieval_review") or {}
            if (not previous or not recalled.get("available")
                    or recalled.get("task_id") != previous_task_id
                    and previous.get("retrieval_review_step_id") != review_step_id):
                raise ValueError("请从已回查这项检索实验的完整反馈继续，原实验与调查关联仍保留。")
            review_origin = {"step_id": review_step_id, "kind": review["kind"],
                             "question_id": review.get("question_id"),
                             "insight_id": review.get("insight_id"),
                             "answer_document_id": review.get("answer_document_id")}
        if source_step_id and previous is None:
            source = next((row for row in self.get(identity)["results"]
                           if row["step_id"] == source_step_id and row["kind"] == "answer"
                           and (row.get("result") or {}).get("status") == "completed"
                           and row["state"] != "abandoned"), None)
            if source is None:
                raise ValueError("请选择本目标中一次完整回答的反馈作为对照起点。")
            question_id = question_id or source.get("question_id")
            if question_id != source.get("question_id"):
                raise ValueError("请保留原回答对应的调查问题，再运行对照。")
        if question_id and not any(q["id"] == question_id
                                   for q in project["career"].get("questions", [])):
            raise ValueError("请选择本目标中的调查问题，或取消关联。")
        if (set(inputs.get("job_ids", [])) - set(project["job_ids"])
                or set(inputs.get("document_ids", [])) - set(project["public_document_ids"])):
            raise ValueError("本次对照只使用当前目标中明确选中的原文，不能混入其他目标资料。")
        result = run_retrieval_comparison(self.repository, inputs)
        changes = comparison_changes(previous_record, result) if previous_record else []
        if previous:
            result["previous_comparison"] = {
                "task_id": previous["id"], "title": previous["title"],
                "as_of": previous_record.get("as_of"), "changed_conditions": changes,
                "comparison_rows": previous_record["comparison_rows"],
                "return_comparison": compare_returns(previous_record, result),
                "notice": "分别保留两次实际运行；查询、标签、范围、原文或配置改变都可能影响结果，"
                "不能只凭指标变化断言改写更好或已具备岗位能力。",
            }
        if review_origin:
            result["review_origin"] = review_origin
        if note_origin:
            result["note_origin"] = note_origin
        if previous or review_origin or note_origin:
            result["artifact_text"] = record_text(result)
        if not save:
            return {"experiment": result}
        if any(step["state"] == "running" for step in project["steps"]):
            raise ValueError("研究期间可以预览本地检索，结束后再保存记录。")
        change_note = ("本次改变：" + "、".join(changes) if changes
                       else "沿用输入重新运行，结果仍需核对。") if previous else ""
        saved = self.add_experiment(identity, {
            "title": "本地检索对照：查询表达与主题", "question_id": question_id,
            "task_or_ability": "比较查询改写与主题限定如何影响原文召回，核对漏回与额外来源。",
            "deliverable": "两组查询、使用者预期标签、实际返回片段和原文定位。",
            "completion_check": "固定资料、别名与top-k，逐条核对预期标签、命中、漏回与额外返回。",
            "hypothesis": hypothesis, "previous_task_id": previous_task_id,
            "design_change": change_note,
            **({"source_step_id": source_step_id} if source_step_id and not previous else {}),
            "purpose": "understanding_check",
            "local_experiment": "retrieval",
            **({"retrieval_review_step_id": review_step_id} if review_origin else {}),
            **({"retrieval_note_origin": note_origin} if note_origin else {}),
        })
        task_id = saved["tasks"][-1]["id"]
        saved = self.update_task(
            identity, task_id, state="done", outcome=result["outcome"], artifact="",
            artifact_title="本地检索对照 · 查询、预期与实际原文",
            artifact_text=result["artifact_text"], comparison_conditions=result["conditions"],
            comparison_rows=result["comparison_rows"], design_change=change_note,
        )
        return {"experiment": result, "career": saved, "task_id": task_id}

    def retrieval_suite(self, identity, *, question_id=None, source_step_id=None,
                        previous_task_id=None, source_insight_id=None, hypothesis="",
                        save=False, **inputs):
        from work_observer.research.retrieval_experiment import record_text
        from work_observer.research.retrieval_suite import compare_suites, run_retrieval_suite

        project = self._project(identity)
        previous, record = None, None
        if previous_task_id:
            previous, record = self._retrieval_record(project, previous_task_id)
            if record.get("record_kind") != "retrieval_suite":
                raise ValueError("请从已保存的检索评估集继续，单条对照可另行加入样例。")
            if (question_id and question_id != previous.get("question_id")
                    or source_step_id and source_step_id != previous.get("source_step_id")):
                raise ValueError("继续评估时请保留原调查和回答关联。")
            question_id = previous.get("question_id")
            source_step_id = previous.get("source_step_id")
        elif source_step_id:
            source = next((row for row in self.get(identity)["results"]
                           if row["step_id"] == source_step_id and row["kind"] == "answer"
                           and (row.get("result") or {}).get("status") == "completed"
                           and row["state"] != "abandoned"), None)
            if not source or question_id and question_id != source.get("question_id"):
                raise ValueError("请选择本目标中一次完整回答作为评估起点，保留其调查关联。")
            question_id = source.get("question_id")
        note_origin = self._retrieval_note_origin(identity, project, previous, source_insight_id)
        if question_id and not any(row["id"] == question_id
                                   for row in project["career"].get("questions", [])):
            raise ValueError("请选择当前目标中的调查问题，或取消关联。")
        if (set(inputs.get("job_ids", [])) - set(project["job_ids"])
                or set(inputs.get("document_ids", [])) - set(project["public_document_ids"])):
            raise ValueError("评估集只使用本目标中选定的原文，不混入其他目标资料。")
        if save and any(step["state"] == "running" for step in project["steps"]):
            raise ValueError("研究期间可以预览评估，结束后再保存记录。")
        result = run_retrieval_suite(self.repository, inputs)
        result["hypothesis"] = hypothesis
        if note_origin:
            result["note_origin"] = note_origin
        change_note = ""
        if previous:
            comparison = compare_suites(record, result)
            comparison.update(
                task_id=previous_task_id, title=previous["title"], project_id=identity,
                artifact_document_id=previous.get("artifact_document_id"),
            )
            result["previous_comparison"] = comparison
            changes = comparison["shared_changed_conditions"][:]
            changes.extend(row["name"] + "：" + (
                "、".join(row["changed_conditions"]) if row["state"] == "matched"
                else "新增样例" if row["state"] == "added" else "移除样例"
            ) for row in comparison["cases"]
                if row["state"] != "matched" or row["changed_conditions"])
            change_note = "本次记录中的变化：" + "；".join(changes) if changes else (
                "同名样例沿用查询、标签及共同条件重新运行，结果仍须核对。"
            )
        result["artifact_text"] = record_text(result)
        if not save:
            return {"experiment": result}
        saved = self.add_experiment(identity, {
            "title": "本地检索评估集 · " + str(len(result["cases"])) + "条样例",
            "question_id": question_id, "hypothesis": hypothesis,
            "task_or_ability": "建设小样本词面检索评估集，逐条检查预期、漏回和额外返回。",
            "deliverable": "固定原文、每条样例的两组查询与标签、实际返回和失败定位。",
            "completion_check": "逐条回读失败样例的原文；不以累计指标替代样例核对。",
            "previous_task_id": previous_task_id, "purpose": "understanding_check",
            "local_experiment": "retrieval_suite",
            **({"retrieval_note_origin": note_origin} if note_origin else {}),
            "design_change": change_note,
            **({"retrieval_suite_comparison": result["previous_comparison"]} if previous else {}),
            **({"source_step_id": source_step_id}
               if source_step_id and not previous_task_id else {}),
        })
        task_id = saved["tasks"][-1]["id"]
        saved = self.update_task(
            identity, task_id, state="done", outcome=result["outcome"], artifact="",
            artifact_title="本地检索评估集 · 输入、标签、返回与失败样例",
            artifact_text=result["artifact_text"], comparison_conditions=result["conditions"],
            comparison_rows=result["comparison_rows"],
            design_change=change_note,
        )
        return {"experiment": result, "career": saved, "task_id": task_id}

    def retry_experiment(self, identity, *, cases, question_id=None, hypothesis="", save=False):
        from work_observer.research.retry_experiment import run_retry_experiment

        project = self._project(identity)
        if question_id and not any(q["id"] == question_id
                                   for q in project["career"].get("questions", [])):
            raise ValueError("请选择这个目标中想验证的调查问题。")
        result = run_retry_experiment(cases)
        if not save:
            return {"experiment": result}
        if any(step["state"] == "running" for step in project["steps"]):
            raise ValueError("这轮研究结束后可以保存运行记录；仍可先运行并查看本地结果。")
        saved = self.add_experiment(identity, {
            "title": "本地顺序模拟：重试与去重", "question_id": question_id,
            "task_or_ability": "用具体输入区分请求编号、业务编号与动作的去重边界。",
            "deliverable": "本机内存计算的完整输入与逐条执行、跳过记录。",
            "completion_check": "逐条对照输入位置和四种规则，另行核实真实业务及运行条件。",
            "hypothesis": hypothesis, "previous_task_id": None, "design_change": "",
        })
        task_id = saved["tasks"][-1]["id"]
        saved = self.update_task(
            identity, task_id, state="done", outcome=result["outcome"], artifact="",
            artifact_title="本地重试与去重 · 本机运行记录",
            artifact_text=result["artifact_text"], comparison_conditions=result["conditions"],
            comparison_rows=result["comparison_rows"],
        )
        return {"experiment": result, "career": saved, "task_id": task_id}

    def cohort_experiment(self, identity, *, groups, metric, conditions, data_kind,
                          question_id=None, hypothesis="", save=False):
        from work_observer.research.cohort_experiment import run_cohort_experiment

        project = self._project(identity)
        if question_id and not any(q["id"] == question_id
                                   for q in project["career"].get("questions", [])):
            raise ValueError("请选择这个目标中想验证的调查问题。")
        result = run_cohort_experiment(groups=groups, metric=metric, conditions=conditions,
                                       data_kind=data_kind)
        if not save:
            return {"experiment": result}
        if any(step["state"] == "running" for step in project["steps"]):
            raise ValueError("本轮研究结束后可保存指标记录；仍可先在本地计算。")
        saved = self.add_experiment(identity, {
            "title": "本地指标对照：总体与分群", "question_id": question_id,
            "task_or_ability": "区分总体比率、分群比率与人群构成变化。",
            "deliverable": "完整计数、分群与总体比率，以及固定A分群占比后的重算结果。",
            "completion_check": "核对分母、指标口径与人群占比，不把比率对照当作因果验证。",
            "hypothesis": hypothesis, "previous_task_id": None, "design_change": "",
        })
        task_id = saved["tasks"][-1]["id"]
        saved = self.update_task(
            identity, task_id, state="done", outcome=result["outcome"], artifact="",
            artifact_title="本地分群指标对照 · 完整输入与本机计算结果",
            artifact_text=result["artifact_text"], comparison_conditions=conditions,
            comparison_rows=result["comparison_rows"],
        )
        return {"experiment": result, "career": saved, "task_id": task_id}

    def threshold_experiment(self, identity, *, cases, thresholds, signal, conditions, data_kind,
                             false_positive_cost, false_negative_cost, review_cost,
                             question_id=None, hypothesis="", save=False):
        from work_observer.research.threshold_experiment import run_threshold_experiment

        project = self._project(identity)
        if question_id and not any(q["id"] == question_id
                                   for q in project["career"].get("questions", [])):
            raise ValueError("请选择这个目标中想验证的调查问题。")
        result = run_threshold_experiment(
            cases=cases, thresholds=thresholds, signal=signal, conditions=conditions,
            data_kind=data_kind, false_positive_cost=false_positive_cost,
            false_negative_cost=false_negative_cost, review_cost=review_cost, hypothesis=hypothesis,
        )
        if not save:
            return {"experiment": result}
        if any(step["state"] == "running" for step in project["steps"]):
            raise ValueError("本轮研究结束后可保存计算记录；仍可先在本地计算。")
        saved = self.add_experiment(identity, {
            "title": "本地筛选对照：误报、漏报与处理代价", "question_id": question_id,
            "task_or_ability": "比较正确率、筛选工作量与给定错误代价的取舍。",
            "deliverable": "完整案例、参照标签、阈值、代价设置和逐阈值错误定位。",
            "completion_check": "同一批案例逐项核对，不把样本内计算当作真实业务验证。",
            "hypothesis": hypothesis, "previous_task_id": None, "design_change": "",
        })
        task_id = saved["tasks"][-1]["id"]
        saved = self.update_task(
            identity, task_id, state="done", outcome=result["outcome"], artifact="",
            artifact_title="筛选阈值与代价 · 完整输入与本机计算结果",
            artifact_text=result["artifact_text"], comparison_conditions=conditions,
            comparison_rows=result["comparison_rows"],
        )
        return {"experiment": result, "career": saved, "task_id": task_id}

    def add_experiment(self, identity, data):
        with self.store.lock, self.store.db:
            project = self._project(identity)
            if key := data.get("requirement_key"):
                if data.get("source_step_id") or data.get("previous_task_id"):
                    raise ValueError("请从当前岗位要求设计新练习，或保留原实验的设计来源。")
                requirement = next((row for row in self.get(identity)["requirements"]
                                    if row["key"] == key), None)
                if not requirement:
                    raise ValueError("这项岗位分析已不在当前列表，请重新选择要准备的工作。")
                data = {**data, "target_requirement": {
                    **{field: requirement[field] for field in (
                        "key", "text", "category", "requirement", "evidence", "basis",
                    )},
                    **requirement["proof"],
                    "notice": "用户从岗位分析中选定的练习方向；"
                    "计划、关联材料与完成记录不代表胜任。",
                }}
            if data.get("source_experiment_id") and not data.get("source_step_id"):
                raise ValueError("请从本轮已读取的旧实验中选择设计，再准备复验。")
            relation_index = data.get("source_relation_index")
            task_index = data.get("source_task_index")
            if sum(value is not None for value in (
                relation_index, data.get("source_claim_index"), task_index,
            )) > 1:
                raise ValueError("请只选择一条判断、工作关系或分项解释准备验证。")
            if (data.get("source_claim_index") is not None
                    or relation_index is not None or task_index is not None) and (
                not data.get("source_step_id") or data.get("source_experiment_id")
            ):
                raise ValueError("请从一份研究中的具体判断准备验证。")
            if source_id := data.get("source_step_id"):
                source = next((row for row in self.get(identity)["results"]
                               if row["step_id"] == source_id
                               and (row.get("result") or {}).get("status") == "completed"
                               and row["state"] != "abandoned"), None)
                if not source or data.get("previous_task_id"):
                    raise ValueError("请选择当前目标中的一份完整研究，或从已有实验继续验证。")
                if template_id := data.get("source_experiment_id"):
                    templates = source["result"].get("career_learning_context", {}).get(
                        "read_other_goals", [],
                    )
                    if not any(row["kind"] == "experiment" and row["record_id"] == template_id
                               for row in templates):
                        raise ValueError("这次研究没有读取所选旧实验，请重新选择已取回的设计。")
                    if not data.get("design_change", "").strip():
                        raise ValueError(
                            "请说明本次场景、对象或条件与旧设计的异同，再保存复验计划。"
                        )
                    data = {**data, "purpose": "understanding_check"}
                elif task_index is not None:
                    task_context(source["result"], task_index)
                    data = {**data, "purpose": "understanding_check"}
                elif relation_index is not None:
                    relations = (source["result"].get("work_map") or {}).get("work_relations", [])
                    if relation_index >= len(relations):
                        raise ValueError("所选研究中没有这条工作关系，请重新选择。")
                    data = {**data, "purpose": "understanding_check"}
                elif data.get("source_claim_index") is not None:
                    if data["source_claim_index"] >= len(source["result"].get("claims", [])):
                        raise ValueError("所选研究中没有这条判断，请重新选择。")
                    data = {**data, "purpose": "understanding_check"}
                elif source["kind"] != "answer":
                    raise ValueError("请从一次完整回答或本轮取回的旧实验设计准备验证。")
                if data.get("question_id") != source.get("question_id"):
                    raise ValueError("请保留原研究对应的调查问题，再保存验证计划。")
                if source.get("understanding_check"):
                    data = {**data, "purpose": "understanding_check"}
            if data.get("question_id") and not any(
                row["id"] == data["question_id"] for row in project["career"].get("questions", [])
            ):
                raise ValueError("未找到这项练习要检验的调查问题，请重新选择。")
            tasks = project["career"]["tasks"]
            if previous_id := data.get("previous_task_id"):
                previous = next((row for row in tasks if row["id"] == previous_id), None)
                if not previous or not _has_experiment_observations(previous):
                    raise ValueError("请先记录上次实验的实际观察，再设计后续验证。")
                data = {
                    **data,
                    "question_id": data.get("question_id") or previous.get("question_id"),
                    **({"source_step_id": previous.get("source_step_id"),
                        "target_requirement": previous["target_requirement"]}
                       if previous.get("target_requirement") else {}),
                    **({"source_step_id": previous.get("source_step_id"),
                        "purpose": "understanding_check",
                        "source_experiment_id": previous.get("source_experiment_id"),
                        "source_claim_index": previous.get("source_claim_index"),
                        "source_task_index": previous.get("source_task_index"),
                        "source_relation_index": previous.get("source_relation_index")}
                       if previous.get("purpose") == "understanding_check" else {}),
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
        comparison_conditions=None,
        comparison_rows=None,
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
        with self.store.lock, self.store.db:
            project = self._project(identity)
            task = next((row for row in project["career"]["tasks"] if row["id"] == task_id), None)
            if not task:
                raise ValueError("未找到这项练习。")
            rows = task.get("comparison_rows", []) if comparison_rows is None else comparison_rows
            if state == "done" and not outcome.strip():
                observed = sum(bool(row.get("observed", "").strip()) for row in rows)
                if not observed:
                    raise ValueError("请先记录实际做了什么或观察到什么，再标记为已记录结果。")
                outcome = f"用户记录了 {observed} 组实际观察，详情见条件对照；尚未独立执行或验证。"
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
            if comparison_conditions is not None:
                task["comparison_conditions"] = comparison_conditions.strip()
            if comparison_rows is not None:
                task["comparison_rows"] = comparison_rows
            self.projects._write(project)
        return self.get(identity)
