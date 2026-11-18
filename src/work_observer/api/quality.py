"""业务质量送审入口；不接受文件路径、题集或门槛变更。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from starlette.routing import Route

from work_observer.quality.reviews import QualityReviewService


class DimensionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["pass", "fail", "unknown", "not_applicable"] = "unknown"
    reason: str = Field(min_length=1, max_length=1200)


class ClaimReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0, le=100)
    support: Literal["supported", "unsupported", "unknown"] = "unknown"
    requirement: Literal["correct", "incorrect", "unknown"] = "unknown"
    note: str = Field(min_length=1, max_length=1200)


class QualityReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    reviewer: str = Field(min_length=1, max_length=100)
    reviewer_kind: Literal["human", "agent_assisted"] = "human"
    decision: Literal["approve", "reject", "pending"] = "pending"
    note: str = Field(min_length=1, max_length=2000)
    dimensions: dict[str, DimensionReview]
    claim_reviews: list[ClaimReview] = Field(max_length=30)


def quality_routes(*, repository, store, response, read_json, busy):
    def service():
        return QualityReviewService(store(), repository())

    async def overview(request):
        return response(service().overview())

    async def packet(request):
        return response(service().packet(request.path_params["id"]))

    async def reviews(request):
        return response(service().list_run(request.path_params["id"]))

    async def submit(request):
        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "请在研究结束或暂停后保存核对。"}, 409
            )
        data = QualityReviewInput.model_validate(await read_json(request))
        return response(service().submit(request.path_params["id"], data.model_dump()), 201)

    return [
        Route("/api/quality", overview),
        Route("/api/quality/runs/{id}", packet),
        Route("/api/quality/runs/{id}/reviews", reviews),
        Route("/api/quality/runs/{id}/reviews", submit, methods=["POST"]),
    ]
