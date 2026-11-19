"""Profiles consume the saved work-type vocabulary, retaining revision and erasure lineage."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

from test_profiles import ProfileModel
from test_profiles import profile_store as profile_store

from work_observer.config import Settings
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.memory.lifecycle import forget_personal
from work_observer.memory.service import MemoryService
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog


class OpenTypeModel(ProfileModel):
    async def turn(self, history):
        calls, raw = await super().turn(history)
        if calls[0]["name"] == "finish_profile":
            self.definitions = json.loads(history[-1]["content"])["domain_definitions"]
            value = json.loads(calls[0]["arguments"])
            value["domains"] = (
                [{**value["domains"][0], "domain": self.definitions[0]["domain_key"]}]
                if self.definitions
                else []
            )
            calls[0]["arguments"] = json.dumps(value)
        return calls, raw


def analyze(service, repo, job):
    model = OpenTypeModel(job, Catalog(repo).evidence(job)[0]["id"])
    return asyncio.run(service.analyze(job, Settings(model_name="synthetic"), model=model)), model


def test_definition_revision_changes_profile_context_without_rewriting_history(profile_store):
    profiles, repo, _, job = profile_store
    knowledge = DomainKnowledgeService(repo)
    initial = knowledge.list_domains()[0]
    knowledge.review_domain(initial["id"], "withdraw", "合成改用实际保存的工作类型")
    first = knowledge.propose_domain("rag_delivery", "RAG服务交付", "开发RAG应用并交付服务接口")
    knowledge.review_domain(first["id"], "accept", "合成定义采纳")
    profile, model = analyze(profiles, repo, job)
    assert profile["status"] == "completed" and not profile["stale"]
    assert [row["domain_key"] for row in model.definitions] == ["rag_delivery"]
    candidate = profile["result"]["domains"][0]
    assert candidate["definition_id"] == first["id"] and candidate["definition_version"] == 1
    original = deepcopy(profile["result"])
    second = knowledge.propose_domain(
        "rag_delivery",
        "知识检索服务交付",
        "开发RAG检索并交付接口",
        previous_id=first["id"],
        change_kind="revise",
    )
    knowledge.review_domain(second["id"], "accept", "合成工作类型修订")
    stale = profiles.get(job)
    assert stale["stale"] and stale["result"]["domains"] == original["domains"]
    fresh, _ = analyze(profiles, repo, job)
    assert fresh["id"] != profile["id"] and not fresh["stale"]
    assert fresh["result"]["domains"][0]["definition_id"] == second["id"]
    assert (
        profiles.get(job, profile["id"])["result"]["classification_definitions"]
        == original["classification_definitions"]
    )


def test_no_effective_definitions_leaves_classification_unknown(profile_store):
    profiles, repo, _, job = profile_store
    knowledge = DomainKnowledgeService(repo)
    knowledge.review_domain(knowledge.list_domains()[0]["id"], "withdraw", "合成无有效定义")
    output, model = analyze(profiles, repo, job)
    assert output["status"] == "completed" and not output["stale"]
    assert (
        model.definitions == output["result"]["domains"] == output["classification_options"] == []
    )
    assert output["result"]["interview_questions"]


def test_forgotten_definition_context_clears_profiles_and_copied_correction_labels(
    profile_store, tmp_path
):
    profiles, repo, _, job = profile_store
    path = Path(repo.engine.url.database).resolve()
    store = ResearchStore(tmp_path / "checkpoints.db", str(path))
    repo.bind_research_store(store)
    try:
        memory = MemoryService(repo)
        private = memory.create("preference", "SYNTHETIC_PRIVATE_TYPE")
        evidence = Catalog(repo).evidence(job)
        source = store.create({"question": "合成定义来源"})
        store.save(
            source["id"],
            state="finished",
            result=dict(
                run_id=source["id"],
                status="completed",
                scope=Catalog(repo).query(job_ids=[job]),
                memory_used=[private],
                evidence=evidence,
                claims=[
                    dict(
                        category="task",
                        basis="direct",
                        requirement="unspecified",
                        text="合成原文任务",
                        evidence_ids=[evidence[0]["id"]],
                    )
                ],
            ),
        )
        knowledge = DomainKnowledgeService(repo)
        defined = knowledge.propose_domain(
            "private_type",
            "SYNTHETIC_PRIVATE_TYPE",
            "合成工作定义",
            source_context=dict(
                run_id=source["id"],
                job_ids=[job],
                public_document_ids=[],
                evidence_ids=[evidence[0]["id"]],
                project_id=None,
            ),
        )
        knowledge.review_domain(defined["id"], "accept", "合成定义")

        class NoRecall:
            def recall(self, *args, **kwargs):
                return []

        # Isolate classification lineage: the profile does not directly receive the private memory.
        profiles.memory = NoRecall()
        output, _ = analyze(profiles, repo, job)
        assert output["status"] == "completed" and not output["result"]["memory_used"]
        assert defined["id"] in {row["id"] for row in output["result"]["knowledge_used"]}
        correction = knowledge.correct_job_domains(job, [defined["id"]], "合成明确归类")
        assert "SYNTHETIC_PRIVATE_TYPE" in correction["content"]
        erased = forget_personal(repo, store, private["id"], tmp_path / "reports")
        assert output["id"] in erased["deleted_profile_ids"]
        assert profiles.get(job)["status"] == "not_analyzed"
        assert "SYNTHETIC_PRIVATE_TYPE" not in str(memory.list(include_history=True))
        assert not knowledge.dependent_domain_corrections([defined["id"]])
    finally:
        store.close()
