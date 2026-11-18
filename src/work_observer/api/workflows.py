"""日常研究流程的薄入口；保存默认不联网，执行时明确选择模型预算。"""

import asyncio

from pydantic import BaseModel, ConfigDict, Field
from starlette.routing import Route

from work_observer.collection.service import error_code
from work_observer.workflow.service import WorkflowService, execute_workflow


class WorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=150)
    goal: str = Field(min_length=1, max_length=4000)
    job_ids: list[str] = Field(min_length=1, max_length=20)
    domain_id: str | None = None
    terms: list[str] = Field(default_factory=list, max_length=10)
    include_personal: bool = False
    max_calls: int = Field(default=72, ge=24, le=72)
    max_seconds: int = Field(default=1800, ge=360, le=1800)


class WorkflowRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow_model: bool = False
    retry_failed: bool = False
    new_cycle: bool = False
    max_calls: int = Field(default=36, ge=0, le=36)
    max_seconds: int = Field(default=900, ge=1, le=900)


class WorkflowScopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    job_ids: list[str] = Field(min_length=1, max_length=20)


def workflow_routes(*, repository, store, settings, model, response, read_json, busy, tasks):
    def service():
        return WorkflowService(store(), repository())

    def detail(identity):
        record = service().get(identity)
        task = tasks.get("workflow:" + identity)
        record["worker_running"] = bool(task and not task.done())
        return record

    async def listing(request):
        return response(service().list())

    async def create(request):
        data = WorkflowInput.model_validate(await read_json(request))
        return response(service().create(**data.model_dump()), 201)

    async def get(request):
        return response(detail(request.path_params["id"]))

    async def refine(request):
        data = WorkflowScopeInput.model_validate(await read_json(request))
        return response(service().refine(request.path_params["id"], **data.model_dump()))

    async def artifact(request):
        from work_observer.connectors.mcp_probe import ProbeError
        from work_observer.reports.domain_updates import DomainUpdateService

        record = service().get(request.path_params["id"])
        kind = request.path_params["kind"]
        if kind not in {"capture", "report"}:
            raise ProbeError("WORKFLOW_ARTIFACT_NOT_FOUND")
        cycle = record["cycles"][-1] if record["cycles"] else {}
        identity = cycle.get(kind + "_id")
        if not identity:
            raise ProbeError("WORKFLOW_ARTIFACT_NOT_READY")
        updates = DomainUpdateService(store(), repository())
        return response(
            updates._get("domain_update_captures", identity)
            if kind == "capture"
            else updates.report(identity)
        )

    async def execute(identity, data):
        try:
            await execute_workflow(service(), identity, settings, model=model, **data.model_dump())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record = service()._get(identity)
            if record["state"] != "invalidated":
                record.update(state="waiting_review", stop_reason=error_code(exc))
                service()._save(record)

    async def run(request):
        identity = request.path_params["id"]
        data = WorkflowRunInput.model_validate(await read_json(request))
        service().get(identity)
        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "已有研究正在进行，请等待或先暂停。"},
                409,
            )
        tasks["workflow:" + identity] = asyncio.create_task(execute(identity, data))
        return response(
            {
                "id": identity,
                "state": "running",
                "allow_model": data.allow_model,
                "budget": {"max_calls": data.max_calls, "max_seconds": data.max_seconds},
            },
            202,
        )

    async def pause(request):
        identity = request.path_params["id"]
        task = tasks.get("workflow:" + identity)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return response(detail(identity))

    return [
        Route("/api/workflows", listing),
        Route("/api/workflows", create, methods=["POST"]),
        Route("/api/workflows/{id}", get),
        Route("/api/workflows/{id}", refine, methods=["PATCH"]),
        Route("/api/workflows/{id}/artifacts/{kind}", artifact),
        Route("/api/workflows/{id}/run", run, methods=["POST"]),
        Route("/api/workflows/{id}/pause", pause, methods=["POST"]),
    ]
