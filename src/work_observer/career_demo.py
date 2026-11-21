"""A disposable, explicitly scripted product walkthrough, with no provider connection."""

import asyncio
import html
import json
import re
from pathlib import Path

from starlette.responses import JSONResponse

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.research.career import CareerService
from work_observer.research.projects import execute_project
from work_observer.research.store import ResearchStore
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository

JOBS = [
    (
        "应用",
        [
            ("task", "负责客服知识库接入、业务接口和检索失败样例验证", "unspecified"),
            ("deliverable", "交付可运行原型、失败案例与运行说明", "unspecified"),
            ("ability", "必须掌握Python接口开发与测试", "required"),
            ("ability", "商科背景加分", "preferred"),
        ],
    ),
    (
        "平台",
        [
            ("task", "负责工具调用、任务编排、超时重试和运行追踪", "unspecified"),
            ("deliverable", "交付执行器、故障记录与接入说明", "unspecified"),
            ("ability", "必须掌握Python接口开发与测试", "required"),
        ],
    ),
]


class DemoModel:
    """Finite local tool scripts. These responses are examples, not model evaluation."""

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        project = context.get("project_context") or {}
        career = project.get("career_evidence") or {}
        action = project.get("career_action")
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        evidence = [ev for output in outputs for ev in output.get("evidence", [])]
        unread = [
            job["id"]
            for job in context["fixed_scope"]["jobs"]
            if not any(ev.get("job_id") == job["id"] for ev in evidence)
        ]
        if len(unread) > 1:
            return self.call(
                history,
                "read_jobs",
                {"reads": [{"job_id": identity, "start": 0} for identity in unread[:6]]},
            )
        if unread:
            return self.call(history, "read_job", {"job_id": unread[0]})
        documents = [
            career[key]["document_id"]
            for key in ("selected_story", "selected_answer", "selected_material")
            if career.get(key)
        ]
        documents.extend(
            row["document_id"]
            for row in (career.get("selected_requirement") or {}).get("records", [])
            if row.get("document_id")
        )
        documents.extend(
            row["artifact_document"]["document_id"]
            for row in career.get("experiments", [])
            if row.get("artifact_document") and row["id"] == career.get("selected_experiment_id")
        )
        previous = career.get("previous_experiment")
        if previous and previous.get("artifact_document"):
            documents.append(previous["artifact_document"]["document_id"])
        inquiry = career.get("selected_inquiry") or {}
        allowed = {row["id"] for row in context["fixed_scope"].get("public_document_titles", [])}
        for passage in [inquiry.get("source_passage") or {}, *inquiry.get("evidence_passages", [])]:
            if passage.get("public_document_id") in allowed:
                documents.append(passage["public_document_id"])
        if (
            action in {"gaps", "interview", "plan", "pitch"}
            and not inquiry
            and career.get("stories")
        ):
            documents.append(career["stories"][-1]["document_id"])
        if not context["fixed_scope"]["jobs"] and not documents:
            documents.extend(
                row["id"] for row in context["fixed_scope"].get("public_document_titles", [])[:2]
            )
        for document in dict.fromkeys(documents):
            if not any(ev.get("public_document_id") == document for ev in evidence):
                return self.call(
                    history, "read_archived_document", {"document_id": document, "start": 0}
                )
        claims, relations, work_types = [], [], []
        for ev in evidence:
            if not ev.get("job_id"):
                continue
            group = {}
            for _, entries in JOBS:
                for category, text, strength in entries:
                    if text in ev["quote"] and not any(
                        row["text"] == text and row["evidence_ids"] == [ev["id"]] for row in claims
                    ):
                        group.setdefault(category, len(claims))
                        claims.append(
                            {
                                "category": category,
                                "basis": "direct",
                                "text": text,
                                "requirement": strength,
                                "evidence_ids": [ev["id"]],
                            }
                        )
            if "task" in group and "ability" in group:
                relations.append(
                    {
                        "source_claim_index": group["task"],
                        "target_claim_index": group["ability"],
                        "predicate": "requires",
                        "basis": "inference",
                        "rationale": "预置示例：完成接口与失败处理任务，需要相应开发和检查能力。",
                        "transfer_limit": "工具与任务相关，不表示胜任或拥有生产审批权限。",
                    }
                )
            if "task" in group and "deliverable" in group:
                task, deliverable = (
                    claims[group["task"]]["text"],
                    claims[group["deliverable"]]["text"],
                )
                application = "知识库" in task
                work_types.append(
                    {
                        "name": "虚构示例：业务应用接入"
                        if application
                        else "虚构示例：执行平台开发",
                        "problem": "把知识与接口接入业务，定位失败样例。"
                        if application
                        else ("让工具调用与任务执行可追踪，运行规模尚未说明。"),
                        "tasks": task,
                        "deliverables": deliverable,
                        "claim_indices": list(group.values()),
                        "basis": "inference",
                        "boundary": "这是虚构样本的预置分类；生产权限与独立验收责任仍未知。",
                        "next_check": "核对真实业务目标、验收口径与交接分工。",
                    }
                )
                relations.append(
                    {
                        "source_claim_index": group["task"],
                        "target_claim_index": group["deliverable"],
                        "predicate": "produces",
                        "basis": "inference",
                        "rationale": "预置示例：把JD列出的任务与相应交付物联系起来。",
                        "transfer_limit": "只能解释这份虚构资料，不推断实际验收权或业务收益。",
                    }
                )
        args = {"claims": claims[:8], "gaps": ["上线审批由谁负责，哪些失败需要人工接管？"]}
        if action == "map":
            args["work_map"] = {
                "version": "work-map-v3-work-relations",
                "scope_note": (
                    "虚构JD的预置关系示例，不代表真实模型研究效果。"
                    if context["fixed_scope"]["jobs"]
                    else "工作资料的预置流程示例，未选择JD；"
                    "不能据此补造招聘资格或声称模型已理解新资料。"
                ),
                "work_types": work_types[:4],
                "work_relations": relations[:4],
                "comparisons": [],
                "unknowns": ["生产权限、实际验收标准与运行规模仍未说明。"],
            }
        elif action not in {"role", "map"}:
            refs = [ev["id"] for ev in evidence]
            text = "【预置示例】可用实际记录讨论检查方法；生产情境和效果仍需证据。"
            if action in {"ask", "reflect", "challenge"}:
                text = "【预置示例】原文能帮助定位工作要求，但不能只靠工具词判断失败原因。"
                if any(
                    ev.get("public_document_id")
                    and "正常" in ev["quote"]
                    and ("write=2" in ev["quote"] or "两次写入" in ev["quote"])
                    for ev in evidence
                ):
                    text = (
                        "【预置示例】正常响应也有两次写入，挑战了只归因于重试的解释。"
                        "并发尚未控制，具体原因仍未知。"
                    )
            if action in {"answer", "followup"} and career.get("understanding_check"):
                text = (
                    "【预置示例】概念解释应区分观察、原因与适用条件，"
                    "并说明还需要什么反例；解释不证明亲自完成了生产工作。"
                    "这是固定示范，不是对本次输入的模型评价。"
                )
            elif action in {"answer", "followup"}:
                text = (
                    "【预置示例】可核对亲自行动、实际观察和未验证的边界。"
                    "这是固定提示，不是对本次输入的模型评价。"
                )
            if action == "pitch":
                text = "【预置示例】项目讲述可按场景、亲自行动、观察和限制组织，请核对原始记录。"
            args["claims"] = [
                {
                    "category": "ability",
                    "basis": "inference",
                    "requirement": "unspecified",
                    "text": text,
                    "evidence_ids": refs,
                }
            ]
            args["gaps"] = ["还需控制哪些条件，才能区分并发、重复提交与重试的影响？"]
            if action == "interview":
                args["gaps"] = [
                    "请结合亲自做过的本地样例，说明怎么检查失败、留下了什么运行记录，哪些结果还不能确定？",
                    "业务应用与执行平台使用相似工具时，交付物和责任有什么不同？",
                ]
            if action == "teachback":
                args["gaps"] = [
                    "为什么正常响应也出现重复写入，会挑战只归因于重试的解释？还有哪些原因未排除？",
                    "如果固定请求标识但改变并发条件，怎样设计一次可能推翻原解释的检查？",
                ]
            if action == "followup":
                args["gaps"] = ["你说的观察排除了哪些其他原因？下一步最小的对照是什么？"]
            if action in {"plan", "challenge"} and context.get("application_background"):
                args["application_plan"] = {
                    "background_memory_id": context["application_background"]["memory_id"],
                    "actions": [
                        {
                            "title": "比较正常响应与超时重试的写入记录",
                            "task_or_ability": "失败处理与验证",
                            "deliverable": "两组输入、输出、请求标识与差异说明",
                            "completion_check": "若正常响应也写入两次，保留反例，不只归因于重试。",
                            "hypothesis": "重复写入只会发生在超时重试时；这是准备检验的解释。",
                            "evidence_ids": refs,
                            "assumptions": ["使用本地虚构输入，不接触生产系统。"],
                        }
                    ],
                    "open_questions": ["并发和请求去重仍待控制。"],
                }
        if not args["claims"]:
            args["claims"] = [
                {
                    "category": "task",
                    "basis": "inference",
                    "requirement": "unspecified",
                    "text": "【预置示例】新资料需要真实模型分析；此入口只演示使用流程。",
                    "evidence_ids": [evidence[0]["id"]],
                }
            ]
        return self.call(history, "finish_research", args)

    @staticmethod
    def call(history, name, arguments):
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": str(len(history)),
        }
        return [call], call


async def populate(settings, model):
    upgrade(settings.database_path)
    repo = Repository(settings.database_path)
    store = ResearchStore(
        settings.database_path.parent / "checkpoints.db",
        namespace=str(settings.database_path.resolve()),
    )
    repo.bind_research_store(store)
    try:
        archive = RawArchive(settings.raw_directory)
        jobs = [
            import_jd(
                repo,
                archive,
                ManualJD(
                    title=f"虚构示例 · Agent{name}工程师",
                    company="虚构示例团队",
                    data_kind="synthetic",
                    external_id="walkthrough-" + name,
                    description="虚构JD，仅作功能演示。"
                    + "。".join(text for _, text, _ in entries)
                    + "。与业务同事协作验收，生产上线审批职责未说明。",
                ),
            )["job_id"]
            for name, entries in JOBS
        ]
        career = CareerService(store, repo, settings.raw_directory)
        book = career.create(
            title="示例：从业务应用看懂执行平台",
            goal="比较两类工作的交付与责任，用本地练习核对个人理解。",
            background="虚构人物小林：做过本地Python接口练习，没有生产上线与效果数据。",
            constraints="只使用虚构资料和本地样例。",
            job_ids=jobs,
            resume_title="虚构简历",
            resume_text="虚构人物小林。构造过超时样例与运行日志，未控制并发，没有生产效果数据。",
        )
        identity = book["id"]
        book = career.add_story(
            identity,
            {
                "title": "虚构项目：客服接口失败样例",
                "situation": "在本地比较正常与超时响应。",
                "action": "亲自构造超时输入，记录请求标识与写入次数。",
                "result": "形成两组本地运行记录。",
                "limits": "未控制并发、未在生产运行，没有业务效果数据。",
                "requirement_key": "",
            },
        )
        story = book["stories"][0]

        async def run(kind, **extra):
            prepared = career.prepare(identity, kind=kind, **extra)
            await execute_project(
                career.projects,
                identity,
                repo,
                settings,
                model=model,
                max_steps=1,
                preferred_step_id=prepared["step_id"],
            )
            result = career.get(identity)["results"][0]
            if not result["result"] or result["result"]["status"] != "completed":
                raise RuntimeError("Demo script did not complete: " + kind)
            return result

        await run("role")
        mapped = await run("map")
        work_text = "虚构操作说明：超时后可重试，需记录输入、请求标识与写入次数；重复原因未说明。"
        book = career.add_material(identity, title="虚构操作说明", text=work_text)
        work_document = book["materials"][-1]["id"]
        question_values = {
            "question": "超时重试足以解释重复写入吗？",
            "why_matters": "避免用工具关键词替代因果检查。",
            "next_evidence": "需要正常与超时两组输入输出，并控制并发。",
            "hypothesis_a": "重复写入只会发生在超时重试时；仍需核实。",
            "hypothesis_b": "正常响应下的重复提交或并发也可能有关，具体原因未知。",
            "state": "open",
            "conclusion": "",
            "source_step_id": None,
            "conclusion_step_id": None,
        }
        book = career.save_question(
            identity,
            {
                **question_values,
                "source_passage": {
                    "public_document_id": work_document,
                    "start": 0,
                    "end": len(work_text),
                },
            },
        )
        question = book["questions"][0]
        career.focus_question(identity, question["id"])
        old = career.add_insight(
            identity,
            {
                "question_id": question["id"],
                "previous_view": "只看到工具说明。",
                "observation": "还没有做对照。",
                "current_view": "重试应该能解释重复写入。",
                "open_question": "正常响应会怎样？",
            },
        )["insights"][-1]
        initial = await run("ask", question_id=question["id"], question=question["question"])
        counter_text = "虚构排查说明：正常响应也应检查重复提交；并发相关原因仍需受控观察。"
        book = career.add_material(identity, title="虚构排查说明", text=counter_text)
        counter_document = book["materials"][-1]["id"]
        career.save_question_passage(
            identity,
            question["id"],
            {
                "passage": {
                    "public_document_id": counter_document,
                    "start": 0,
                    "end": len(counter_text),
                },
                "relation": "challenges",
                "user_note": "可能挑战只归因于重试的解释；这仍是排查建议，不是实验结果。",
            },
        )
        plan = await run("challenge", question_id=question["id"])
        book = career.import_tasks(identity, plan["step_id"])
        task = book["tasks"][0]
        book = career.update_task(
            identity,
            task["id"],
            state="done",
            hypothesis="重复写入只会发生在超时重试时。",
            outcome="虚构观察：正常响应也有两次写入。并发条件未控制，原因仍不能确定。",
            artifact="虚构示例中的本地记录",
            artifact_title="虚构运行记录",
            artifact_text="情境A：正常响应，write=2；情境B：超时重试，write=2。并发条件未控制，本记录未独立执行。",
        )
        task = book["tasks"][0]
        reviewed = await run("reflect", task_id=task["id"])
        book = career.add_insight(
            identity,
            {
                "previous_view": old["current_view"],
                "question_id": question["id"],
                "observation": task.get("outcome") or "虚构对照中，正常响应也出现两次写入。",
                "current_view": "原解释不足；还需要控制并发和请求去重，不能仅凭两次输出判断原因。",
                "open_question": "这套检查方法迁移到平台工作还需要什么条件？",
                "task_id": task["id"],
                "source_step_id": reviewed["step_id"],
                "replaces_insight_id": old["id"],
            },
        )
        insight = book["insights"][-1]
        career.save_question(
            identity,
            {
                **question_values,
                "conclusion": insight["current_view"],
                "conclusion_step_id": reviewed["step_id"],
            },
            question["id"],
        )
        await run(
            "ask",
            question_id=question["id"],
            task_id=task["id"],
            source_step_id=initial["step_id"],
            question="带着新观察与修正后的认识，重新检查原解释还有哪些未解决部分？",
        )
        interview = await run("teachback", question_id=question["id"])
        answer = await run(
            "answer",
            source_step_id=interview["step_id"],
            answer=(
                "虚构回答（理解自测）：正常响应也重复写入，只能挑战把重试当作唯一原因的解释。"
                "还需要固定请求标识、控制并发；没有排除其他原因，也不证明生产有效。"
            ),
        )
        await run("followup", source_step_id=answer["step_id"])
        book = career.save_pitch(
            identity,
            {
                "title": "虚构项目讲述：行动、观察与限制",
                "text": (
                    "我在本地构造正常与超时两组输入，记录请求标识和写入次数。"
                    "正常响应也出现重复写入，原先只归因于重试的解释不足。"
                    "并发未控制，尚不能确定原因；我没有生产上线或业务收益数据。"
                ),
                "story_id": story["id"],
                "source_step_id": None,
            },
        )
        pitch = book["pitches"][-1]
        next_goal = career.create(
            title="示例：带着旧认识转向平台岗位",
            goal="核对旧理解在新岗位中的适用条件。",
            background="同一虚构人物，只有本地练习经历。",
            constraints="只用虚构资料。",
            job_ids=jobs[1:],
        )
        copied = career.reuse(
            next_goal["id"], source_project_id=identity, kind="insight", record_id=insight["id"]
        )
        career.focus_question(next_goal["id"], copied["questions"][0]["id"])
        return {
            "main": identity,
            "map": mapped["step_id"],
            "question": question["id"],
            "answer": answer["step_id"],
            "teachback": interview["step_id"],
            "insight": insight["id"],
            "pitch": pitch["id"],
            "next_goal": next_goal["id"],
            "next_question": copied["questions"][0]["id"],
        }
    finally:
        store.close()
        repo.close()


class DemoSurface:
    def __init__(self, app, links):
        self.app, self.links = app, links

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        if method not in {"GET", "HEAD"} and not (
            path.startswith("/api/career")
            or path in {"/api/import", "/api/imports/documents/extract"}
            or re.fullmatch(r"/api/projects/[a-f0-9]{32}/(?:run|pause)", path)
        ):
            return await JSONResponse(
                {"message": "此入口只演示本地求职流程，联网、模型配置与采集操作未启用。"},
                status_code=403,
            )(scope, receive, send)
        if path != "/":
            return await self.app(scope, receive, send)

        async def tagged(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (key, value)
                    for key, value in message["headers"]
                    if key.lower() != b"content-length"
                ]
            elif message["type"] == "http.response.body":
                links = self.links
                notice = (
                    '<section class="career-demo-banner"><strong>虚构资料 · 预置脚本演示</strong>'
                    "<p>资料、经历和回答均为虚构示例，不代表真实模型研究效果。"
                    "此入口使用临时数据，不读取你的服务密钥；可通过导出保留准备包。</p>"
                    '<details class="career-demo-jump"><summary>三分钟导览 · 跳到某一步</summary>'
                    '<nav aria-label="演示步骤">'
                )
                for index, (title, target, question, note) in enumerate([
                    (
                        "① 看懂工作", f"career/{links['main']}/discussion/{links['map']}",
                        "同样写Agent，实际在交付什么？",
                        "对照应用接入与执行平台的任务、交付物和原文。留意Python必备、商科背景加分，"
                        "共用工具并不等于承担相同工作。",
                    ),
                    (
                        "② 原文、反例与实验", f"career/{links['main']}/journey/{links['question']}",
                        "一条解释怎样被反例挑战？",
                        "沿时间线看最初猜想、补充原文、最小实验和观察记录。正常响应也出现两次写入，"
                        "只归因于重试的解释不足；并发仍未控制。",
                    ),
                    (
                        "③ 检查自己的理解", f"career/{links['main']}/discussion/{links['answer']}",
                        "会复述，还是能解释条件与边界？",
                        "打开自测回答与对应反馈，区分挑战一种解释和已经找到原因。"
                        "再看追问如何改变条件；概念解释不证明做过生产项目。",
                    ),
                    (
                        "④ 认识修正后回看研究",
                        f"career/{links['main']}/understanding/{links['insight']}",
                        "认识改变后，哪些旧研究需要回看？",
                        "对照原先的理解与反例后的修正，回看带入过相关认识的研究。"
                        "历史答复仍然保留，较新不自动代表更正确。",
                    ),
                    (
                        "⑤ 讲清行动与边界", f"career/{links['main']}/pitch/{links['pitch']}",
                        "怎样把探索讲成有依据的项目经历？",
                        "讲清亲自做的对照、观察和仍未验证的部分。保留并发未控制、没有生产上线和"
                        "没有业务收益数据的边界，不把推断写成成果。",
                    ),
                    (
                        "⑥ 迁移到新岗位",
                        f"career/{links['next_goal']}/question/{links['next_question']}",
                        "旧经验可以直接迁移到新岗位吗？",
                        "把同一条认识带到平台岗位，原结论只是待验证起点。"
                        "重新核对任务、交付物与运行责任，不自动当作岗位事实或个人胜任证明。",
                    ),
                ]):
                    notice += (
                        f'<a href="#{html.escape(target)}" data-demo-step="{index}" '
                        f'data-demo-question="{html.escape(question, quote=True)}" '
                        f'data-demo-note="{html.escape(note, quote=True)}">{html.escape(title)}</a>'
                    )
                notice += (
                    '</nav></details></section><aside class="career-demo-tourbar" '
                    'data-demo-tourbar aria-label="演示导览">'
                    '<details class="career-demo-points" open><summary data-demo-guide-label '
                    'aria-live="polite">三分钟导览 · 看要点</summary>'
                    '<div class="career-demo-point-content">'
                    '<p class="form-note" data-demo-position>'
                    '六步看一条调查怎样推进</p><h3 data-demo-question>从工作差异到认识修正</h3>'
                    '<p data-demo-note>点击开始，依次看工作、反例、自测、修正、项目表达和迁移。'
                    '导航只打开已有记录，不开始新的研究。</p></div></details>'
                    '<div class="result-actions"><button type="button" class="secondary small" '
                    'data-demo-direction="-1" disabled>上一步</button>'
                    '<button type="button" class="primary small" data-demo-direction="1">'
                    '开始导览 ↗</button></div></aside>'
                )
                body = message.get("body", b"").replace(
                    b'<meta name="wo-token"',
                    b'<meta name="wo-demo" content="true"><meta name="wo-token"',
                )
                marker = b'<main id="main" tabindex="-1">'
                message["body"] = body.replace(marker, marker + notice.encode())
            await send(message)

        await self.app(scope, receive, tagged)


def create_demo_app(directory: Path):
    settings = Settings(
        database_path=directory / "app.db",
        raw_directory=directory / "raw",
        mcp_config=directory / "no-connectors.toml",
    )
    model = DemoModel()
    links = asyncio.run(populate(settings, model))
    return DemoSurface(create_app(settings, model=model, reports_dir=directory / "reports"), links)
