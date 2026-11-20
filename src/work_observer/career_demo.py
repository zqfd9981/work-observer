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
        for job in context["fixed_scope"]["jobs"]:
            if not any(ev.get("job_id") == job["id"] for ev in evidence):
                return self.call(history, "read_job", {"job_id": job["id"]})
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
            if row.get("artifact_document")
        )
        if action in {"gaps", "interview", "plan", "pitch"} and career.get("stories"):
            documents.append(career["stories"][-1]["document_id"])
        for document in dict.fromkeys(documents):
            if not any(ev.get("public_document_id") == document for ev in evidence):
                return self.call(
                    history, "read_archived_document", {"document_id": document, "start": 0}
                )
        claims, relations = [], []
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
        args = {"claims": claims[:8], "gaps": ["上线审批由谁负责，哪些失败需要人工接管？"]}
        if action == "map":
            args["work_map"] = {
                "version": "work-map-v3-work-relations",
                "scope_note": "虚构JD的预置关系示例，不代表真实模型研究效果。",
                "work_types": [],
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
            if action in {"answer", "followup"}:
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
            if action == "followup":
                args["gaps"] = ["你说的观察排除了哪些其他原因？下一步最小的对照是什么？"]
            if action == "plan" and context.get("application_background"):
                args["application_plan"] = {
                    "background_memory_id": context["application_background"]["memory_id"],
                    "actions": [
                        {
                            "title": "比较正常响应与超时重试的写入记录",
                            "task_or_ability": "失败处理与验证",
                            "deliverable": "两组输入、输出、请求标识与差异说明",
                            "completion_check": "若正常响应也写入两次，保留反例，不只归因于重试。",
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
        await run("gaps")
        book = career.save_question(
            identity,
            {
                "question": "超时重试足以解释重复写入吗？",
                "why_matters": "避免用工具关键词替代因果检查。",
                "next_evidence": "需要正常与超时两组输入输出，并控制并发。",
                "state": "open",
                "conclusion": "",
                "source_step_id": None,
                "conclusion_step_id": None,
            },
        )
        question = book["questions"][0]
        await run("ask", question_id=question["id"], question=question["question"])
        plan = await run("plan", question_id=question["id"])
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
        reviewed = await run("ask", task_id=task["id"], question=question["question"])
        await run("reflect", task_id=task["id"])
        old = career.add_insight(
            identity,
            {
                "previous_view": "只看到工具说明。",
                "observation": "还没有做对照。",
                "current_view": "重试应该能解释重复写入。",
                "open_question": "正常响应会怎样？",
            },
        )["insights"][-1]
        book = career.add_insight(
            identity,
            {
                "previous_view": old["current_view"],
                "observation": task.get("outcome") or "虚构对照中，正常响应也出现两次写入。",
                "current_view": "原解释不足；还需要控制并发和请求去重，不能仅凭两次输出判断原因。",
                "open_question": "这套检查方法迁移到平台工作还需要什么条件？",
                "task_id": task["id"],
                "source_step_id": reviewed["step_id"],
                "replaces_insight_id": old["id"],
            },
        )
        insight = book["insights"][-1]
        interview = await run("interview")
        answer = await run(
            "answer",
            source_step_id=interview["step_id"],
            answer="虚构回答：我亲自构造输入并记录输出，正常响应也出现两次写入。但并发未控制，所以还不能确定原因，也没有生产效果证据。",
        )
        await run("followup", source_step_id=answer["step_id"])
        career.save_pitch(
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
        return {
            "main": identity,
            "map": mapped["step_id"],
            "question": question["id"],
            "answer": answer["step_id"],
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
                    "此入口使用临时数据，不读取你的服务密钥；可通过导出保留准备包。</p><nav>"
                )
                for title, target in [
                    ("① 看懂工作", f"career/{links['main']}/discussion/{links['map']}"),
                    ("② 验证与认知变化", f"career/{links['main']}/question/{links['question']}"),
                    ("③ 面试与讲述", f"career/{links['main']}/discussion/{links['answer']}"),
                    (
                        "④ 迁移到新岗位",
                        f"career/{links['next_goal']}/question/{links['next_question']}",
                    ),
                ]:
                    notice += f'<a href="#{html.escape(target)}">{html.escape(title)}</a>'
                notice += "</nav></section>"
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
