"""岗位画像与个人匹配的薄HTTP入口，复用可测试业务服务。"""

from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from work_observer.retrieval.catalog import Filters


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offline: bool = False


class PublicDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=3000)


class PublicDocumentQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(default="", max_length=200)
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


class MatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: Filters = Field(default_factory=Filters)
    preferences: dict


class DomainCorrectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domains: list[str] = Field(max_length=6)
    reason: str = Field(min_length=1, max_length=1200)


class RetrievalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    terms: list[str] = Field(min_length=1, max_length=10)
    filters: Filters = Field(default_factory=Filters)
    job_ids: list[str] | None = Field(default=None, max_length=20)
    as_of: str | None = None
    aliases: bool = True


class StrategyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    aliases: dict[str, list[str]]


class RollbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)


def product_routes(*, repository, settings, model, response, read_json, busy, operation_lock):
    async def compare_history(request):
        from work_observer.research.history import HistoryService

        identity = request.path_params["id"]
        repo = repository()
        result = HistoryService(repo).compare(identity)
        return response(result)

    async def public_document(request):
        from work_observer.connectors.public_documents import PublicDocumentService

        return response(
            PublicDocumentService(repository(), settings.raw_directory / "public").document(
                request.path_params["id"]
            )
        )

    async def public_documents(request):
        from work_observer.connectors.public_documents import PublicDocumentService

        query = PublicDocumentQuery.model_validate(dict(request.query_params))
        return response(
            PublicDocumentService(repository(), settings.raw_directory / "public").catalog(
                **query.model_dump()
            )
        )

    async def archive_public_document(request):
        from work_observer.connectors.public_documents import PublicDocumentService
        from work_observer.storage.locks import exclusive

        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "请在本轮调查结束后补充网页。"}, 409
            )
        data = PublicDocumentInput.model_validate(await read_json(request))
        async with operation_lock:
            with exclusive(settings.database_path):
                result = await PublicDocumentService(
                    repository(), settings.raw_directory / "public"
                ).read(data.url)
        return response(result, 201)

    async def retrieval(request):
        from work_observer.retrieval.enhanced import RetrievalService

        data = RetrievalInput.model_validate(await read_json(request))
        service = RetrievalService(repository())
        kwargs = {"filters": data.filters, "job_ids": data.job_ids, "as_of": data.as_of}
        return response(
            {
                "retrieval": service.search(data.terms, aliases=data.aliases, **kwargs),
                "statistics": service.stats(data.terms, **kwargs),
            }
        )

    async def strategies(request):
        from work_observer.retrieval.enhanced import DEFAULT_ALIASES
        from work_observer.tracking.evaluation import StrategyService

        service = StrategyService(repository())
        return response(
            {
                "strategies": service.list(),
                "experiments": service.experiments(),
                "events": service.events(),
                "active_config": service.active_config(),
                "template": DEFAULT_ALIASES,
            }
        )

    async def monitor_strategy(request):
        from work_observer.tracking.evaluation import StrategyService

        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "请在研究结束后检查当前策略。"}, 409
            )
        async with operation_lock:
            result = await run_in_threadpool(StrategyService(repository()).monitor)
        return response(result)

    async def create_strategy(request):
        from work_observer.tracking.evaluation import StrategyService

        data = StrategyInput.model_validate(await read_json(request))
        return response(StrategyService(repository()).create(data.name, data.aliases), 201)

    async def evaluate_strategy(request):
        from work_observer.tracking.evaluation import StrategyService

        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "已有研究正在进行，请稍后再评测。"}, 409
            )
        async with operation_lock:
            result = await run_in_threadpool(
                StrategyService(repository()).evaluate, request.path_params["id"]
            )
        return response(result)

    async def activate_strategy(request):
        from work_observer.tracking.evaluation import StrategyService

        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "请在研究结束后切换检索策略。"}, 409
            )
        return response(StrategyService(repository()).activate(request.path_params["id"]))

    async def rollback_strategy(request):
        from work_observer.tracking.evaluation import StrategyService

        data = RollbackInput.model_validate(await read_json(request))
        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "请在研究结束后回退检索策略。"}, 409
            )
        return response(StrategyService(repository()).rollback(data.reason))

    async def get_preferences(request):
        from work_observer.analysis.profiles import ProfileService

        return response(ProfileService(repository()).get_preferences())

    async def save_preferences(request):
        from work_observer.analysis.profiles import PersonalPreferences, ProfileService

        preferences = PersonalPreferences.model_validate(await read_json(request))
        return response(
            ProfileService(repository()).save_preferences(preferences.model_dump(mode="json"))
        )

    def audited_profile(profile):
        from work_observer.reports.results import audit_result

        if profile.get("result"):
            profile["result"]["audit"] = audit_result(profile["result"], repository())
        return profile

    async def get_profile(request):
        from work_observer.analysis.profiles import ProfileService

        return response(
            audited_profile(ProfileService(repository()).get(request.path_params["id"]))
        )

    async def analyze_profile(request):
        from work_observer.analysis.profiles import ProfileService

        data = ProfileInput.model_validate(await read_json(request))
        if busy():
            return response(
                {
                    "error_code": "RESEARCH_BUSY",
                    "message": "已有研究或画像正在进行，请先等待它完成。",
                },
                409,
            )
        async with operation_lock:
            result = await ProfileService(repository()).analyze(
                request.path_params["id"], settings, model=model, offline=data.offline
            )
        return response(audited_profile(result))

    async def match(request):
        from work_observer.analysis.profiles import PersonalPreferences, ProfileService

        data = MatchInput.model_validate(await read_json(request))
        preferences = PersonalPreferences.model_validate(data.preferences)
        return response(
            ProfileService(repository()).compare_personal(data.filters, preferences, limit=100)
        )

    async def correct_domain(request):
        from work_observer.analysis.profiles import ProfileService

        data = DomainCorrectionInput.model_validate(await read_json(request))
        return response(
            ProfileService(repository()).set_domain_correction(
                request.path_params["id"], data.domains, data.reason
            ),
            201,
        )

    return [
        Route("/api/jobs/{id}/compare-history", compare_history),
        Route("/api/public-documents/{id}", public_document),
        Route("/api/public-documents", public_documents),
        Route("/api/public-documents", archive_public_document, methods=["POST"]),
        Route("/api/retrieval", retrieval, methods=["POST"]),
        Route("/api/strategies", strategies),
        Route("/api/strategies", create_strategy, methods=["POST"]),
        Route("/api/strategies/monitor", monitor_strategy, methods=["POST"]),
        Route("/api/strategies/rollback", rollback_strategy, methods=["POST"]),
        Route("/api/strategies/{id}/evaluate", evaluate_strategy, methods=["POST"]),
        Route("/api/strategies/{id}/activate", activate_strategy, methods=["POST"]),
        Route("/api/preferences", get_preferences),
        Route("/api/preferences", save_preferences, methods=["POST"]),
        Route("/api/profiles/{id}/correction", correct_domain, methods=["POST"]),
        Route("/api/profiles/{id}", get_profile),
        Route("/api/profiles/{id}", analyze_profile, methods=["POST"]),
        Route("/api/matches", match, methods=["POST"]),
    ]
