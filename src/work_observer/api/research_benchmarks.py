"""冻结业务题的薄入口：匿名核对前不返回方法映射或旧评分。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from starlette.routing import Route

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.quality.research_benchmark import BlindReview, ResearchBenchmarkService


class BenchmarkSealInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    record_missing: bool = False


class BenchmarkSubmissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: str = Field(min_length=1, max_length=60)
    arm: Literal["baseline", "candidate"]
    source_id: str = Field(pattern="^[a-f0-9]{32}$")


SCHEMA_MODELS = {
    ("/api/research-benchmarks/{id}/submissions", "POST"): BenchmarkSubmissionInput,
    ("/api/research-benchmarks/{id}/phases/{phase}/seal", "POST"): BenchmarkSealInput,
    ("/api/research-benchmarks/{id}/packets/{packet_id}/reviews", "POST"): BlindReview,
}


def benchmark_routes(*, repository, store, response, read_json, busy):
    def service():
        return ResearchBenchmarkService(store(), repository())

    def phase(request):
        value = request.path_params["phase"]
        if value not in {"development", "holdout"}:
            raise ProbeError("BENCHMARK_INVALID_PHASE")
        return value

    async def overview(request):
        return response(service().overview(request.path_params.get("id")))

    async def tasks(request):
        return response(service().development_tasks(request.path_params["id"]))

    async def phase_state(request):
        svc = service()
        identity, selected = request.path_params["id"], phase(request)
        svc.overview(identity)
        try:
            record = svc._round(identity, selected)
        except ProbeError as exc:
            if exc.code != "BENCHMARK_RECORD_NOT_FOUND":
                raise
            return response({"phase": selected, "state": "not_opened", "packet_ids": []})
        return response(
            {
                "phase": selected,
                "state": record["state"],
                "packet_ids": [row["id"] for row in record.get("packets", [])]
                if record["state"] == "reviewing"
                else [],
            }
        )

    async def packet(request):
        return response(
            service().blind_packet(request.path_params["id"], request.path_params["packet_id"])
        )

    async def report(request):
        return response(service().paired_report(request.path_params["id"], phase(request)))

    async def mutate(request, operation, model=None):
        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "请在研究停止后保存核对。"}, 409
            )
        data = await read_json(request)
        svc, identity = service(), request.path_params["id"]
        if model:
            values = model.model_validate(data).model_dump()
        elif data != {}:
            raise ProbeError("BENCHMARK_EMPTY_ACTION_BODY_REQUIRED")
        else:
            values = {}
        if operation == "register":
            saved = svc.register(identity, **values)
            return response(
                {
                    "id": saved["id"],
                    "state": saved["state"],
                    "contract_issues": saved["contract_issues"],
                },
                201,
            )
        if operation == "submit_review":
            saved = svc.submit_review(identity, request.path_params["packet_id"], values)
            return response(
                {
                    "id": saved["id"],
                    "saved": True,
                    "notice": "匿名核对已保存，封评前不返回旧评分。",
                },
                201,
            )
        result = getattr(svc, operation)(identity, phase(request), **values)
        return response(result, 201)

    async def open_phase(request):
        return await mutate(request, "open_phase")

    async def seal_phase(request):
        return await mutate(request, "seal_phase", BenchmarkSealInput)

    async def close_phase(request):
        return await mutate(request, "close_phase")

    async def register(request):
        return await mutate(request, "register", BenchmarkSubmissionInput)

    async def review(request):
        return await mutate(request, "submit_review", BlindReview)

    return [
        Route("/api/research-benchmarks", overview),
        Route("/api/research-benchmarks/{id}", overview),
        Route("/api/research-benchmarks/{id}/development", tasks),
        Route("/api/research-benchmarks/{id}/submissions", register, methods=["POST"]),
        Route("/api/research-benchmarks/{id}/phases/{phase}", phase_state),
        Route("/api/research-benchmarks/{id}/phases/{phase}/open", open_phase, methods=["POST"]),
        Route("/api/research-benchmarks/{id}/phases/{phase}/seal", seal_phase, methods=["POST"]),
        Route("/api/research-benchmarks/{id}/phases/{phase}/close", close_phase, methods=["POST"]),
        Route("/api/research-benchmarks/{id}/phases/{phase}/report", report),
        Route("/api/research-benchmarks/{id}/packets/{packet_id}", packet),
        Route(
            "/api/research-benchmarks/{id}/packets/{packet_id}/reviews", review, methods=["POST"]
        ),
    ]
