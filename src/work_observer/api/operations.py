"""本地观察配置、可恢复任务与更新收件箱；不提供来源解锁或认证操作。"""

import asyncio

from pydantic import BaseModel, ConfigDict, Field
from starlette.routing import Route

from work_observer.collection.contracts import WatchsetSpec


class WatchsetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    spec: WatchsetSpec


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    watchset_id: str
    hour: int = Field(default=8, ge=0, le=23)
    minute: int = Field(default=30, ge=0, le=59)
    enabled: bool = False
    schedule_id: str | None = None


class CollectionTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    watchset_id: str


class FollowupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)
    source_run_id: str | None = None


def operations_routes(*, repository, settings, response, read_json, busy, operation_lock, tasks):
    def service():
        from work_observer.tasks.service import TaskService

        return TaskService(repository())

    def inbox():
        from work_observer.reports.inbox import InboxService

        return InboxService(repository())

    async def list_watchsets(request):
        return response(
            service().watchsets(
                include_history=request.query_params.get("history") in {"1", "true"}
            )
        )

    async def list_schedules(request):
        return response(service().schedules())

    async def list_tasks(request):
        return response(service().list())

    async def get_task(request):
        return response(service().get(request.path_params["id"]))

    async def list_inbox(request):
        return response(inbox().list(unread=request.query_params.get("unread") in {"1", "true"}))

    async def list_collection_runs(request):
        return response(repository().runs(limit=100))

    async def get_collection_run(request):
        return response(repository().run(request.path_params["id"]))

    async def overview(request):
        current = service()
        return response(
            {
                "watchsets": current.watchsets(),
                "tasks": current.list(),
                "schedules": current.schedules(),
                "inbox": inbox().list(),
            }
        )

    async def watchset(request):
        data = WatchsetInput.model_validate(await read_json(request))
        return response(service().save_watchset(data.name, data.spec), 201)

    async def schedule(request):
        data = ScheduleInput.model_validate(await read_json(request))
        return response(service().save_schedule(**data.model_dump()), 201)

    async def create_task(request):
        data = CollectionTaskInput.model_validate(await read_json(request))
        return response(service().create_collection(data.watchset_id), 201)

    async def run_task(request):
        identity = request.path_params["id"]
        current = service().get(identity)
        if current["state"] != "queued":
            return response(
                {
                    "error_code": "TASK_NOT_QUEUED",
                    "message": "请先显式重试，将任务恢复到等待队列。",
                },
                409,
            )
        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "已有研究或任务正在执行。"}, 409
            )

        async def execute():
            async with operation_lock:
                await service().run(identity, settings)

        tasks[identity] = asyncio.create_task(execute())
        # 业务服务保存失败类别；读取后台异常，避免未经处理的原始异常写入日志。
        tasks[identity].add_done_callback(
            lambda task: None if task.cancelled() else task.exception()
        )
        return response({"id": identity, "state": "starting"}, 202)

    async def retry_task(request):
        return response(service().retry(request.path_params["id"]))

    async def followup(request):
        data = FollowupInput.model_validate(await read_json(request))
        return response(inbox().add_followup(data.question, data.source_run_id), 201)

    async def change_notification(request):
        identity, action = request.path_params["id"], request.path_params["action"]
        if action == "read":
            return response(inbox().mark_read(identity))
        if action == "resolve":
            return response(inbox().resolve(identity))
        from work_observer.connectors.mcp_probe import ProbeError

        raise ProbeError("INBOX_ACTION_DENIED")

    async def tick(request):
        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "已有研究或任务正在执行。"}, 409
            )
        async with operation_lock:
            return response(await service().tick(settings, run=False, limit=1))

    return [
        Route("/api/operations", overview),
        Route("/api/watchsets", list_watchsets),
        Route("/api/schedules", list_schedules),
        Route("/api/tasks", list_tasks),
        Route("/api/tasks/{id}", get_task),
        Route("/api/inbox", list_inbox),
        Route("/api/collection-runs", list_collection_runs),
        Route("/api/collection-runs/{id}", get_collection_run),
        Route("/api/watchsets", watchset, methods=["POST"]),
        Route("/api/schedules", schedule, methods=["POST"]),
        Route("/api/tasks", create_task, methods=["POST"]),
        Route("/api/tasks/{id}/run", run_task, methods=["POST"]),
        Route("/api/tasks/{id}/retry", retry_task, methods=["POST"]),
        Route("/api/operations/tick", tick, methods=["POST"]),
        Route("/api/inbox/followup", followup, methods=["POST"]),
        Route("/api/inbox/{id}/{action}", change_notification, methods=["POST"]),
    ]
