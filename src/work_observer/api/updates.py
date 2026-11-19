"""领域更新面板：显式冻结、比较与后续调查，不自动调用模型。"""

from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from work_observer.reports.domain_updates import DomainUpdateService
from work_observer.retrieval.catalog import Filters


class UpdateCaptureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=150)
    domain_id: str | None = None
    filters: Filters = Field(default_factory=Filters)
    job_ids: list[str] | None = Field(default=None, max_length=2000)
    terms: list[str] = Field(default_factory=list, max_length=10)
    include_personal: bool = False
    include_archived: bool = False
    public_document_ids: list[str] | None = Field(default=None, max_length=20)
    as_of: str | None = Field(
        default=None, max_length=64, description="历史来源截止，须含时区；空值冻结当前观察"
    )


class UpdateCompareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before_id: str = Field(pattern="^[a-f0-9]{32}$")
    after_id: str = Field(pattern="^[a-f0-9]{32}$")


class UpdateFollowupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=2000)
    run_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


def update_routes(*, repository, store, response, read_json, busy):
    def service():
        return DomainUpdateService(store(), repository())

    async def listing(request):
        return response(await run_in_threadpool(service().list))

    async def capture(request):
        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "请在研究结束或暂停后冻结面板。"}, 409
            )
        data = UpdateCaptureInput.model_validate(await read_json(request))
        return response(await run_in_threadpool(service().capture, **data.model_dump()), 201)

    async def compare(request):
        data = UpdateCompareInput.model_validate(await read_json(request))
        return response(await run_in_threadpool(service().compare, **data.model_dump()), 201)

    async def report(request):
        return response(await run_in_threadpool(service().report, request.path_params["id"]))

    async def followup(request):
        data = UpdateFollowupInput.model_validate(await read_json(request))
        if data.run_id and busy():
            return response(
                {
                    "error_code": "RESEARCH_BUSY",
                    "message": "请在当前调查结束或暂停后保存复核问题。",
                },
                409,
            )
        return response(
            await run_in_threadpool(
                service().followup, request.path_params["id"], **data.model_dump()
            ),
            201,
        )

    return [
        Route("/api/updates", listing),
        Route("/api/updates/captures", capture, methods=["POST"]),
        Route("/api/updates/compare", compare, methods=["POST"]),
        Route("/api/updates/reports/{id}", report),
        Route("/api/updates/reports/{id}/followup", followup, methods=["POST"]),
    ]
