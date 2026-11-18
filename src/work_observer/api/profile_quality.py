"""完整画像的逐条语义与补充质量审核入口。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from starlette.routing import Route

from work_observer.api.quality import ClaimReview, DimensionReview
from work_observer.quality.profile_reviews import ProfileQualityReviewService


class ProfileDomainReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int = Field(ge=0, le=5)
    support: Literal["supported", "unsupported", "unknown"] = "unknown"
    scope: Literal["correct", "incorrect", "unknown"] = "unknown"
    note: str = Field(min_length=1, max_length=1200)


class ProfileClaimReview(ClaimReview):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int = Field(ge=0, le=23)


class ProfileQuestionReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int = Field(ge=0, le=7)
    direction: Literal["correct", "incorrect", "unknown"] = "unknown"
    relevance: Literal["correct", "incorrect", "unknown"] = "unknown"
    note: str = Field(min_length=1, max_length=1200)


class ProfileQualityReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    artifact_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    reviewer: str = Field(min_length=1, max_length=100)
    reviewer_kind: Literal["human", "agent_assisted"] = "human"
    decision: Literal["approve", "reject", "pending"] = "pending"
    note: str = Field(min_length=1, max_length=2000)
    dimensions: dict[str, DimensionReview]
    claim_reviews: list[ProfileClaimReview] = Field(max_length=24)
    domain_reviews: list[ProfileDomainReview] = Field(max_length=6)
    question_reviews: list[ProfileQuestionReview] = Field(max_length=8)


SCHEMA_MODELS = {
    ("/api/profile-quality/analyses/{id}/reviews", "POST"): ProfileQualityReviewInput,
}


def profile_quality_routes(*, repository, store, response, read_json, busy):
    def service():
        return ProfileQualityReviewService(store(), repository())

    async def overview(request):
        return response(service().overview())

    async def packet(request):
        if request.query_params.get("blind") == "1":
            return response(service().blind_packet(request.path_params["id"]))
        return response(service().packet(request.path_params["id"]))

    async def reviews(request):
        return response(service().list_reviews(request.path_params["id"]))

    async def submit(request):
        if busy():
            return response(
                {
                    "error_code": "RESEARCH_BUSY",
                    "message": "请在研究或画像完成后保存完整画像核对。",
                },
                409,
            )
        data = ProfileQualityReviewInput.model_validate(await read_json(request))
        return response(service().submit(request.path_params["id"], data.model_dump()), 201)

    return [
        Route("/api/profile-quality", overview),
        Route("/api/profile-quality/analyses/{id}", packet),
        Route("/api/profile-quality/analyses/{id}/reviews", reviews),
        Route("/api/profile-quality/analyses/{id}/reviews", submit, methods=["POST"]),
    ]
