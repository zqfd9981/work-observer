"""疑似重复审核与人工截图区域的共用服务入口。"""

from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from work_observer.data_quality.service import DataQualityService


class DuplicateScanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_ids: list[str] | None = Field(default=None, min_length=1, max_length=300)
    limit: int = Field(default=50, ge=1, le=100)


class DuplicateReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left_job_id: str = Field(min_length=1, max_length=100)
    right_job_id: str = Field(min_length=1, max_length=100)
    decision: str = Field(pattern="^(linked|distinct|withdrawn)$")
    reason: str = Field(min_length=1, max_length=1200)


class ScreenshotRegionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    asset_id: str = Field(pattern="^[a-f0-9]{32}$")
    job_id: str = Field(min_length=1, max_length=100)
    snapshot_id: str = Field(pattern="^[a-f0-9]{32}$")
    document_id: str = Field(pattern="^[a-f0-9]{32}$")
    bbox: list[float] = Field(min_length=4, max_length=4)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=700)
    reviewed: bool = False
    note: str = Field(default="", max_length=1200)


SCHEMA_MODELS = {
    ("/api/data-quality/duplicates/scan", "POST"): DuplicateScanInput,
    ("/api/data-quality/duplicates/review", "POST"): DuplicateReviewInput,
    ("/api/data-quality/regions", "POST"): ScreenshotRegionInput,
}


def data_quality_routes(*, repository, response, read_json, busy):
    def service():
        return DataQualityService(repository() if callable(repository) else repository)

    async def scan(request):
        data = DuplicateScanInput.model_validate(await read_json(request))
        return response(
            await run_in_threadpool(service().duplicates, data.job_ids, limit=data.limit)
        )

    async def reviews(request):
        return response(service().reviews())

    async def review(request):
        if busy():
            return response(
                {
                    "error_code": "RESEARCH_BUSY",
                    "message": "请先暂停或等待当前研究，再保存关联审核。",
                },
                409,
            )
        data = DuplicateReviewInput.model_validate(await read_json(request))
        return response(
            service().review_duplicate(
                data.left_job_id, data.right_job_id, data.decision, data.reason
            ),
            201,
        )

    async def targets(request):
        return response(service().screenshot_targets())

    async def regions(request):
        return response(service().regions(request.query_params.get("job_id")))

    async def save_region(request):
        if busy():
            return response(
                {
                    "error_code": "RESEARCH_BUSY",
                    "message": "请先暂停或等待当前研究，再保存人工区域引用。",
                },
                409,
            )
        data = ScreenshotRegionInput.model_validate(await read_json(request))
        return response(service().create_region(**data.model_dump()), 201)

    async def withdraw_region(request):
        return response(service().withdraw_region(request.path_params["id"]))

    return [
        Route("/api/data-quality/duplicates/scan", scan, methods=["POST"]),
        Route("/api/data-quality/duplicates/reviews", reviews),
        Route("/api/data-quality/duplicates/review", review, methods=["POST"]),
        Route("/api/data-quality/screenshot-targets", targets),
        Route("/api/data-quality/regions", regions),
        Route("/api/data-quality/regions", save_region, methods=["POST"]),
        Route("/api/data-quality/regions/{id}/withdraw", withdraw_region, methods=["POST"]),
    ]
