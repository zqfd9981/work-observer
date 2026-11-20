"""项目对话与调查队列入口，调用同一持久业务服务。"""

import asyncio
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.routing import Route

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.reports.results import audit_result
from work_observer.research.projects import ProjectService, completed_steps, execute_project


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=150)
    goal: str = Field(min_length=1, max_length=4000)
    job_ids: list[str] = Field(
        min_length=0, max_length=20, description="空列表仅使用已归档资料（网页与粘贴原文）"
    )
    public_document_ids: list[str] | None = Field(
        default=None,
        max_length=20,
        description="限定归档原文ID；null使用全部可用归档，空列表不使用归档",
    )
    max_calls: int = Field(default=36, ge=1, le=72)
    max_seconds: int = Field(default=900, ge=1, le=1800)
    max_rounds: int = Field(default=6, ge=1, le=12)
    max_public: int = Field(default=4, ge=0, le=8)
    plan_steps: bool = False
    offline: bool = False
    source_key: str | None = Field(default=None, min_length=1, max_length=200)


class ProjectRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_document_ids: list[str] | None = Field(
        default=None,
        max_length=20,
        description="限定归档原文ID；null使用全部可用归档，空列表不使用归档",
    )
    revision: int = Field(ge=1)
    goal: str = Field(min_length=1, max_length=4000)
    job_ids: list[str] = Field(
        min_length=0, max_length=20, description="空列表仅使用已归档资料（网页与粘贴原文）"
    )


class ProjectTitle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=150)


class StepInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    question: str = Field(min_length=1, max_length=4000)
    completion: str = Field(
        default="形成带原文引用的回答，并明确未知项", min_length=1, max_length=1000
    )
    evidence_needed: str | None = Field(default=None, min_length=1, max_length=600)
    kind: str = Field(default="investigate", pattern="^(investigate|counterexample|synthesis)$")
    depends_on: list[str] = Field(default_factory=list, max_length=6)
    reply_to_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    offline: bool = False
    allow_public: bool = False
    max_calls: int = Field(default=10, ge=1, le=12)
    timeout: int = Field(default=180, ge=1, le=300)
    key: str | None = Field(default=None, max_length=100)
    approach: Literal["standard", "work_map"] = "standard"
    coverage_mode: Literal["all", "question"] = "all"


class StepReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    action: str = Field(pattern="^(accept|wait|retry)$")
    note: str = Field(min_length=1, max_length=1000)


class ProjectRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class StepRefresh(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=1000)
    offline: bool = True
    allow_public: bool = False
    max_calls: int = Field(default=10, ge=1, le=12)
    timeout: int = Field(default=180, ge=1, le=300)


class StepRepair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    review_id: str = Field(pattern="^[a-f0-9]{32}$")
    note: str = Field(min_length=1, max_length=1000)
    offline: bool = True
    max_calls: int = Field(default=8, ge=1, le=12)
    timeout: int = Field(default=180, ge=1, le=300)


def plan_project(service, project, offline=False):
    """固定业务步骤确保有反例和汇总；不把模型文字计划冒充已完成调查。"""
    parents = []
    for kind, question, completion in [
        (
            "investigate",
            project["goal"],
            "回答目标中的具体问题，关键判断有当前范围原文支持；列明未知",
        ),
        (
            "counterexample",
            "围绕这个目标主动查找反例、相反职责与资料缺口：" + project["goal"],
            "展示支持和不支持的原文，区分没有读到与不存在；无法判断时等待资料",
        ),
        (
            "synthesis",
            "综合已审核的调查和反例，修订解释并回答：" + project["goal"],
            "同时讨论支持、反例、适用范围和仍缺资料，不把样本扩展为市场结论",
        ),
    ]:
        project = service.add(
            project["id"],
            question[:4000],
            revision=project["revision"],
            kind=kind,
            completion=completion,
            offline=offline,
            depends_on=parents if kind == "synthesis" else [],
            key=f"{project['id']}:initial:{kind}",
        )
        if kind != "synthesis":
            parents.append(
                next(
                    step["id"]
                    for step in project["steps"]
                    if step.get("key") == f"{project['id']}:initial:{kind}"
                )
            )
    return project


def project_routes(
    *,
    repository,
    store,
    settings,
    model,
    response,
    read_json,
    busy,
    tasks,
    reports_dir=Path("reports"),
):
    def service():
        return ProjectService(store())

    def validate_jobs(job_ids):
        for job_id in job_ids:
            repository().job(job_id)

    def detail(identity):
        from work_observer.quality.reviews import QualityReviewService
        from work_observer.research.project_feedback import repair_preview
        from work_observer.research.projects import step_continuation

        svc = service()
        project = svc.get(identity)
        project["usage"] = svc.usage(project)
        from work_observer.connectors.public_models import PublicDocument
        from work_observer.storage.models import Job

        with Session(repository().engine) as session:
            project["scope_materials"] = {
                "jobs": [
                    {"id": key, "title": title, "company": company, "has_detail": has_detail}
                    for key, title, company, has_detail in session.execute(
                        select(
                            Job.id,
                            Job.title,
                            Job.company_name_raw,
                            Job.description_text.is_not(None) & (Job.description_text != ""),
                        ).where(Job.id.in_(project["job_ids"]))
                    )
                ],
                "documents": [
                    {"id": key, "title": title, "publisher": publisher, "observed_at": observed_at}
                    for key, title, publisher, observed_at in session.execute(
                        select(
                            PublicDocument.id,
                            PublicDocument.title,
                            PublicDocument.publisher,
                            PublicDocument.observed_at,
                        ).where(PublicDocument.id.in_(project.get("public_document_ids") or []))
                    )
                ],
            }
        for step in project["steps"]:
            step["repair"] = repair_preview(svc, project, step, repository())
            if step.get("run_id"):
                run = store().get(step["run_id"])
                result = run.get("result")
                checkpoint = (
                    store().load_checkpoint(step["run_id"])
                    if step["state"] in {"failed", "interrupted"}
                    or (result or {}).get("status") in {"incomplete", "failed"}
                    else None
                )
                if result and run["state"] != "invalidated":
                    from work_observer.research.answer_feedback import with_submission_feedback

                    result = with_submission_feedback(
                        result,
                        checkpoint if result.get("status") in {"incomplete", "failed"} else None,
                    )
                step["result"] = (
                    {**result, "audit": audit_result(result, repository())} if result else None
                )
                if result and (report_id := (run.get("saved") or {}).get("report_id")):
                    step["result"]["report_id"] = report_id
                if result and result.get("status") == "completed":
                    reviews = QualityReviewService(store(), repository()).list_run(step["run_id"])
                    latest = next((r for r in reviews if not r["stale_result"]), None)
                    step["result"]["business_review"] = (
                        {key: latest.get(key) for key in ("status", "reviewer_kind", "decision")}
                        if latest
                        else {"status": "pending"}
                    )
                step["run_state"] = run["state"]
                if continuation := step_continuation(
                    project,
                    step,
                    run,
                    checkpoint,
                    (step.get("result") or {}).get("audit", {}),
                ):
                    step["continuation"] = continuation
        from work_observer.research.projects import upstream_revision_notices

        findings = []
        for step in project["steps"]:
            result = step.get("result") or {}
            audit = result.get("audit") or {}
            if (
                result.get("status") == "completed"
                and step.get("run_state") != "invalidated"
                and step["scope_version"] == project["scope_version"]
                and result.get("business_review", {}).get("status") != "rejected"
                and result.get("audit") is not None
                and not any(
                    audit.get(key)
                    for key in (
                        "stale_memory",
                        "stale_knowledge",
                        "stale_dependencies",
                        "changed_sources",
                        "affected_strategy",
                    )
                )
            ):
                findings.append((step, result))
        upstream_notices = upstream_revision_notices(findings)
        for step in project["steps"]:
            if notice := upstream_notices.get(step.get("run_id")):
                step["result"]["upstream_revision_notices"] = notice
        completed = completed_steps(project, svc.rejected_steps(project))
        project["ready_step_ids"] = [
            step["id"]
            for step in project["steps"]
            if step["state"] in {"queued", "interrupted"} and set(step["depends_on"]) <= completed
        ]
        project["worker_running"] = bool(
            tasks.get("project:" + identity) and not tasks["project:" + identity].done()
        )
        task = tasks.get("project:" + identity)
        if task and task.done() and not task.cancelled():
            from work_observer.collection.service import error_code

            exc = task.exception()
            project["worker_error"] = error_code(exc) if exc else None
        return project

    async def listing(request):
        return response(
            [
                {
                    **{
                        key: row[key]
                        for key in ("id", "title", "goal", "state", "revision", "updated_at")
                    },
                    "step_count": len(row["steps"]),
                    "job_count": len(row["job_ids"]),
                    "document_count": len(row["public_document_ids"])
                    if row.get("public_document_ids") is not None
                    else None,
                    "last_question": row["steps"][-1]["question"] if row["steps"] else None,
                    "last_state": row["steps"][-1]["state"] if row["steps"] else None,
                    "worker_running": bool(
                        tasks.get("project:" + row["id"])
                        and not tasks["project:" + row["id"]].done()
                    ),
                }
                for row in service().list()
            ]
        )

    async def create(request):
        data = ProjectInput.model_validate(await read_json(request))
        validate_jobs(data.job_ids)
        from work_observer.research.document_scope import validate

        validate(repository(), data.public_document_ids)
        if data.plan_steps and data.max_rounds < 3:
            raise ProbeError("PROJECT_PLAN_NEEDS_THREE_ROUNDS")
        project = service().create(**data.model_dump(exclude={"plan_steps", "offline"}))
        if data.plan_steps:
            project = plan_project(service(), project, data.offline)
        return response(project, 201)

    async def rename(request):
        data = ProjectTitle.model_validate(await read_json(request))
        return response(service().rename(request.path_params["id"], **data.model_dump()))

    async def get(request):
        return response(detail(request.path_params["id"]))

    async def erase(request):
        if busy():
            return response(
                {
                    "error_code": "RESEARCH_BUSY",
                    "message": "请先暂停或等待当前研究，再忘记项目及派生结果。",
                },
                409,
            )
        from work_observer.memory.lifecycle import forget_project

        return response(
            forget_project(
                repository(), store(), request.path_params["id"], reports_dir=reports_dir
            )
        )

    async def revise(request):
        data = ProjectRevision.model_validate(await read_json(request))
        validate_jobs(data.job_ids)
        from work_observer.research.document_scope import validate

        validate(repository(), data.public_document_ids)
        return response(
            service().revise(request.path_params["id"], **data.model_dump(exclude_unset=True))
        )

    async def add(request):
        data = StepInput.model_validate(await read_json(request))
        return response(service().add(request.path_params["id"], **data.model_dump()), 201)

    async def review(request):
        data = StepReview.model_validate(await read_json(request))
        return response(
            service().review(
                request.path_params["id"],
                request.path_params["step_id"],
                repository=repository(),
                **data.model_dump(),
            )
        )

    async def refresh_step(request):
        data = StepRefresh.model_validate(await read_json(request))
        if busy():
            return response(
                {
                    "error_code": "RESEARCH_BUSY",
                    "message": "请先等待或暂停调查，再更新资料后的步骤。",
                },
                409,
            )
        return response(
            service().refresh_waiting(
                request.path_params["id"],
                request.path_params["step_id"],
                repository(),
                **data.model_dump(),
            ),
            201,
        )

    async def run(request):
        identity = request.path_params["id"]
        data = ProjectRunInput.model_validate(
            await read_json(request) if await request.body() else {}
        )
        project = service().get(identity)
        if data.step_id:
            completed = completed_steps(project, service().rejected_steps(project))
            if data.step_id not in {
                step["id"]
                for step in project["steps"]
                if step["state"] in {"queued", "interrupted"}
                and set(step["depends_on"]) <= completed
            }:
                raise ProbeError("STEP_NOT_READY")
        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "已有任务正在进行，请等待或先暂停。"},
                409,
            )
        from work_observer.storage.locks import exclusive

        try:
            with exclusive(repository().engine.url.database):
                pass  # 真正领取仍由执行器持有整批锁；这里提供即时跨入口忙提示。
        except ProbeError as exc:
            if exc.code != "RESEARCH_BUSY":
                raise
            return response(
                {
                    "error_code": "RESEARCH_BUSY",
                    "message": "另一个窗口或命令正在调查，请等待它完成。",
                },
                409,
            )
        max_steps = 1 if project.get("career") else 3
        tasks["project:" + identity] = asyncio.create_task(
            execute_project(
                service(),
                identity,
                repository(),
                settings,
                model=model,
                max_steps=max_steps,
                preferred_step_id=data.step_id,
            )
        )
        return response({"id": identity, "state": "running", "max_steps": max_steps}, 202)

    async def repair_step(request):
        data = StepRepair.model_validate(await read_json(request))
        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "请先等待或暂停调查，再保存补查。"}, 409
            )
        return response(
            service().repair_reviewed(
                request.path_params["id"],
                request.path_params["step_id"],
                repository(),
                **data.model_dump(),
            ),
            201,
        )

    async def pause(request):
        identity = request.path_params["id"]
        service().get(identity)
        task = tasks.get("project:" + identity)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return response(detail(identity))

    return [
        Route("/api/projects", listing),
        Route("/api/projects", create, methods=["POST"]),
        Route("/api/projects/{id}/title", rename, methods=["POST"]),
        Route("/api/projects/{id}", get),
        Route("/api/projects/{id}", erase, methods=["DELETE"]),
        Route("/api/projects/{id}", revise, methods=["PATCH"]),
        Route("/api/projects/{id}/steps", add, methods=["POST"]),
        Route("/api/projects/{id}/steps/{step_id}/review", review, methods=["POST"]),
        Route("/api/projects/{id}/steps/{step_id}/refresh", refresh_step, methods=["POST"]),
        Route("/api/projects/{id}/steps/{step_id}/repair", repair_step, methods=["POST"]),
        Route("/api/projects/{id}/run", run, methods=["POST"]),
        Route("/api/projects/{id}/pause", pause, methods=["POST"]),
    ]
