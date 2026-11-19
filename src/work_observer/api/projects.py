"""项目对话与调查队列入口，调用同一持久业务服务。"""

import asyncio
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from starlette.routing import Route

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.reports.results import audit_result
from work_observer.research.projects import ProjectService, execute_project


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=150)
    goal: str = Field(min_length=1, max_length=4000)
    job_ids: list[str] = Field(min_length=1, max_length=20)
    max_calls: int = Field(default=36, ge=1, le=72)
    max_seconds: int = Field(default=900, ge=1, le=1800)
    max_rounds: int = Field(default=6, ge=1, le=12)
    max_public: int = Field(default=4, ge=0, le=8)
    plan_steps: bool = False
    offline: bool = False
    source_key: str | None = Field(default=None, min_length=1, max_length=200)


class ProjectRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    goal: str = Field(min_length=1, max_length=4000)
    job_ids: list[str] = Field(min_length=1, max_length=20)


class StepInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    question: str = Field(min_length=1, max_length=4000)
    completion: str = Field(
        default="形成带原文引用的回答，并明确未知项", min_length=1, max_length=1000
    )
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

        svc = service()
        project = svc.get(identity)
        project["usage"] = svc.usage(project)
        for step in project["steps"]:
            step["repair"] = repair_preview(svc, project, step, repository())
            if step.get("run_id"):
                run = store().get(step["run_id"])
                result = run.get("result")
                step["result"] = (
                    {**result, "audit": audit_result(result, repository())} if result else None
                )
                if result and result.get("status") == "completed":
                    reviews = QualityReviewService(store(), repository()).list_run(step["run_id"])
                    latest = next((r for r in reviews if not r["stale_result"]), None)
                    step["result"]["business_review"] = (
                        {key: latest.get(key) for key in ("status", "reviewer_kind", "decision")}
                        if latest
                        else {"status": "pending"}
                    )
                step["run_state"] = run["state"]
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
                    key: row[key]
                    for key in ("id", "title", "goal", "state", "revision", "updated_at")
                }
                for row in service().list()
            ]
        )

    async def create(request):
        data = ProjectInput.model_validate(await read_json(request))
        validate_jobs(data.job_ids)
        if data.plan_steps and data.max_rounds < 3:
            raise ProbeError("PROJECT_PLAN_NEEDS_THREE_ROUNDS")
        project = service().create(**data.model_dump(exclude={"plan_steps", "offline"}))
        if data.plan_steps:
            project = plan_project(service(), project, data.offline)
        return response(project, 201)

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
        return response(service().revise(request.path_params["id"], **data.model_dump()))

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
        service().get(identity)
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
        tasks["project:" + identity] = asyncio.create_task(
            execute_project(service(), identity, repository(), settings, model=model, max_steps=3)
        )
        return response({"id": identity, "state": "running", "max_steps": 3}, 202)

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
