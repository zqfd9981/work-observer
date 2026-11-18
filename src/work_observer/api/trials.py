"""受限本地检索试用入口，不返回预留题，不接受路径/题集/门槛变更。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from work_observer.quality.releases import LocalRetrievalTrialService


class TrialShadowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle_id: str = Field(pattern="^(legacy-real-v1|[a-f0-9]{32})$")
    job_ids: list[str] = Field(min_length=1, max_length=20)
    allowed_terms: list[str] = Field(min_length=1, max_length=10)
    max_uses: int = Field(default=10, ge=1, le=20)
    expires_hours: int = Field(default=4, ge=1, le=24)
    source_run_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class TrialReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str = Field(min_length=1, max_length=100)
    reviewer_kind: Literal["human", "agent_assisted"] = "human"
    decision: Literal["approve", "reject", "pending"] = "pending"
    reason: str = Field(min_length=1, max_length=2000)
    labels_independent_confirmed: bool = False


class TrialSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    terms: list[str] = Field(min_length=1, max_length=10)
    request_key: str = Field(min_length=1, max_length=100)
    job_ids: list[str] | None = Field(default=None, max_length=20)


class TrialRollbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2000)


class TrialFeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=100)
    rating: Literal["pass", "fail", "unknown"] = "unknown"
    note: str = Field(min_length=1, max_length=2000)
    reviewer_kind: Literal["human", "agent_assisted"] = "human"


def trial_routes(*, repository, store, response, read_json, busy):
    def service():
        return LocalRetrievalTrialService(store(), repository())

    async def listing(request):
        svc = service()
        return response(
            {
                "bundles": await run_in_threadpool(svc.bundles),
                "trials": await run_in_threadpool(svc.list),
                "notice": (
                    "仅对明确局部范围和已验证开发查询试用，不改变默认检索。"
                    "独立人工标签与显式人审不足时保持基线。"
                ),
            }
        )

    async def get(request):
        svc = service()
        return response(
            {
                "trial": await run_in_threadpool(svc.get, request.path_params["id"]),
                "events": await run_in_threadpool(svc.events, request.path_params["id"]),
            }
        )

    async def mutate(request, model, operation):
        if busy() and operation not in {"rollback", "feedback"}:
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "请在研究结束或暂停后操作检索试用。"},
                409,
            )
        data = model.model_validate(await read_json(request))
        svc = service()
        kwargs = data.model_dump()
        if "id" in request.path_params:
            return response(
                await run_in_threadpool(
                    getattr(svc, operation), request.path_params["id"], **kwargs
                ),
                201,
            )
        return response(await run_in_threadpool(getattr(svc, operation), **kwargs), 201)

    async def shadow(request):
        return await mutate(request, TrialShadowInput, "shadow")

    async def review(request):
        return await mutate(request, TrialReviewInput, "review")

    async def search(request):
        return await mutate(request, TrialSearchInput, "search")

    async def rollback(request):
        return await mutate(request, TrialRollbackInput, "rollback")

    async def feedback(request):
        return await mutate(request, TrialFeedbackInput, "feedback")

    return [
        Route("/api/trials", listing),
        Route("/api/trials/shadows", shadow, methods=["POST"]),
        Route("/api/trials/{id}", get),
        Route("/api/trials/{id}/review", review, methods=["POST"]),
        Route("/api/trials/{id}/search", search, methods=["POST"]),
        Route("/api/trials/{id}/rollback", rollback, methods=["POST"]),
        Route("/api/trials/{id}/feedback", feedback, methods=["POST"]),
    ]
