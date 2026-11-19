"""统一资料检索、领域版本与人工审核关系的薄HTTP入口。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.retrieval.catalog import Filters
from work_observer.retrieval.unified import UnifiedRetrieval


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UnifiedInput(KnowledgeInput):
    terms: list[str] = Field(min_length=1, max_length=10)
    filters: Filters = Field(default_factory=Filters)
    job_ids: list[str] | None = Field(default=None, max_length=5000)
    public_document_ids: list[str] | None = Field(default=None, max_length=5000)
    project_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    as_of: str | None = None
    limit: int = Field(default=10, ge=1, le=20)
    aliases: bool = True
    include_knowledge: bool = True


class DomainInput(KnowledgeInput):
    domain_key: str = Field(pattern="^[a-z][a-z0-9_]{1,79}$")
    name: str = Field(min_length=1, max_length=160)
    definition: str = Field(min_length=1, max_length=4000)
    inclusion: str = Field(default="", max_length=4000)
    exclusion: str = Field(default="", max_length=4000)
    previous_id: str | None = None
    change_kind: Literal["create", "revise", "merge", "split"] = "create"
    related_ids: list[str] = Field(default_factory=list, max_length=20)


class KnowledgeReviewInput(KnowledgeInput):
    decision: Literal["accept", "reject", "withdraw"]
    reason: str = Field(min_length=1, max_length=1200)


class ResearchKnowledgeInput(KnowledgeInput):
    work_type_index: int | None = Field(default=None, ge=0, le=7)
    ability_relation_index: int | None = Field(default=None, ge=0, le=11)
    work_relation_index: int | None = Field(default=None, ge=0, le=17)
    domain_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    previous_domain_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    previous_relation_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class RelationInput(KnowledgeInput):
    domain_id: str
    source_kind: Literal["business", "task", "deliverable", "responsibility", "ability", "tool"]
    source_text: str = Field(min_length=1, max_length=1200)
    target_kind: Literal["business", "task", "deliverable", "responsibility", "ability", "tool"]
    target_text: str = Field(min_length=1, max_length=1200)
    evidence: list[dict] = Field(min_length=1, max_length=10)
    predicate: Literal["supports", "requires", "produces", "contradicts"] = "supports"
    counterevidence: list[dict] = Field(default_factory=list, max_length=10)
    conflict_ids: list[str] = Field(default_factory=list, max_length=20)
    project_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_run_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class DomainCollectionInput(KnowledgeInput):
    domain_id: str | None = None
    filters: Filters = Field(default_factory=Filters)
    job_ids: list[str] | None = Field(default=None, max_length=5000)
    project_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    as_of: str | None = None
    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class KnowledgeDomainCorrection(KnowledgeInput):
    domain_ids: list[str] = Field(max_length=10)
    reason: str = Field(min_length=1, max_length=1200)


class KnowledgeListQuery(KnowledgeInput):
    include_history: bool = False
    domain_id: str | None = None
    project_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


def knowledge_routes(*, repository, response, read_json, busy, store):
    def service():
        return DomainKnowledgeService(repository())

    def conflict():
        if busy():
            return response(
                {
                    "error_code": "RESEARCH_BUSY",
                    "message": "请在本轮研究结束后修改领域或审核知识。",
                },
                409,
            )
        return None

    async def unified(request):
        data = UnifiedInput.model_validate(await read_json(request))
        result = await run_in_threadpool(UnifiedRetrieval(repository()).search, **data.model_dump())
        return response(result)

    async def research_knowledge(request):
        from work_observer.knowledge.research import ResearchKnowledgeService

        transfer = ResearchKnowledgeService(repository(), store())
        identity = request.path_params["id"]
        if request.method == "GET":
            return response(await run_in_threadpool(transfer.preview, identity))
        if refused := conflict():
            return refused
        data = ResearchKnowledgeInput.model_validate(await read_json(request))
        return response(await run_in_threadpool(transfer.save, identity, **data.model_dump()), 201)

    async def domains(request):
        query = KnowledgeListQuery.model_validate(dict(request.query_params))
        return response(
            {"domains": await run_in_threadpool(service().list_domains, query.include_history)}
        )

    async def create_domain(request):
        if refused := conflict():
            return refused
        data = DomainInput.model_validate(await read_json(request))
        return response(await run_in_threadpool(service().propose_domain, **data.model_dump()), 201)

    async def review_domain(request):
        if refused := conflict():
            return refused
        data = KnowledgeReviewInput.model_validate(await read_json(request))
        return response(
            await run_in_threadpool(
                service().review_domain, request.path_params["id"], **data.model_dump()
            )
        )

    async def relations(request):
        query = KnowledgeListQuery.model_validate(dict(request.query_params))
        return response(
            {"relations": await run_in_threadpool(service().list_relations, **query.model_dump())}
        )

    async def create_relation(request):
        if refused := conflict():
            return refused
        data = RelationInput.model_validate(await read_json(request))
        return response(
            await run_in_threadpool(service().propose_relation, **data.model_dump()), 201
        )

    async def review_relation(request):
        if refused := conflict():
            return refused
        data = KnowledgeReviewInput.model_validate(await read_json(request))
        return response(
            await run_in_threadpool(
                service().review_relation, request.path_params["id"], **data.model_dump()
            )
        )

    async def collection(request):
        data = DomainCollectionInput.model_validate(await read_json(request))
        return response(await run_in_threadpool(service().collection, **data.model_dump()))

    async def correction(request):
        if refused := conflict():
            return refused
        data = KnowledgeDomainCorrection.model_validate(await read_json(request))
        return response(
            await run_in_threadpool(
                service().correct_job_domains, request.path_params["id"], **data.model_dump()
            )
        )

    return [
        Route("/api/knowledge/research/{id}", research_knowledge, methods=["GET", "POST"]),
        Route("/api/retrieval/unified", unified, methods=["POST"]),
        Route("/api/knowledge/domains", domains, methods=["GET"]),
        Route("/api/knowledge/domains", create_domain, methods=["POST"]),
        Route("/api/knowledge/domains/{id}/review", review_domain, methods=["POST"]),
        Route("/api/knowledge/relations", relations, methods=["GET"]),
        Route("/api/knowledge/relations", create_relation, methods=["POST"]),
        Route("/api/knowledge/relations/{id}/review", review_relation, methods=["POST"]),
        Route("/api/knowledge/collection", collection, methods=["POST"]),
        Route("/api/knowledge/jobs/{id}/domains", correction, methods=["POST"]),
    ]
