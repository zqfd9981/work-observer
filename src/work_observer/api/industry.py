"""Industry observation reading and source-scoped follow-up."""

from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from work_observer.reports.industry import IndustryObservationInput, IndustryObservationService


class IndustryInquiryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    finding_index: int | None = Field(default=None, strict=True, ge=0)
    question: str = Field(min_length=1, max_length=1500)


def industry_routes(*, repository, store, reports_dir, response, read_json):
    def service():
        return IndustryObservationService(repository(), reports_dir)

    async def listing(request):
        return response(await run_in_threadpool(service().listing))

    async def save(request):
        data = IndustryObservationInput.model_validate(await read_json(request))
        return response(await run_in_threadpool(service().save, data.model_dump()), 201)

    async def report(request):
        return response(await run_in_threadpool(service().get, request.path_params["id"]))

    async def inquiry(request):
        data = IndustryInquiryInput.model_validate(await read_json(request))
        return response(await run_in_threadpool(service().inquiry, request.path_params["id"],
                                                data.finding_index, data.question, store()), 201)

    return [
        Route("/api/industry", listing),
        Route("/api/industry", save, methods=["POST"]),
        Route("/api/industry/{id}", report),
        Route("/api/industry/{id}/inquiries", inquiry, methods=["POST"]),
    ]
