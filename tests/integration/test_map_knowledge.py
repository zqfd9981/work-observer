"""Synthetic map → knowledge → revision → forgetting; no provider calls."""

import asyncio
import json
import re
from copy import deepcopy

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient
from test_cognition_research import MapModel
from test_source_first_research import source_workspace as source_workspace

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.knowledge.models import DomainDefinition, WorkRelation
from work_observer.knowledge.research import ResearchKnowledgeService
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.memory.lifecycle import forget_personal
from work_observer.memory.service import MemoryService
from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import DIMENSIONS
from work_observer.research.agent import research
from work_observer.research.projects import ProjectService


class RelationMap(MapModel):
    async def turn(self, history):
        calls, raw = await super().turn(history)
        if calls[0]["name"] == "finish_research":
            args = json.loads(calls[0]["arguments"])
            args["work_map"]["work_relations"] = [
                dict(
                    source_claim_index=0,
                    target_claim_index=1,
                    predicate="supports",
                    rationale="合成待验证解释",
                    transfer_limit="不证明独立平台交付",
                    basis="inference",
                )
            ]
            calls[0]["arguments"] = json.dumps(args)
        return calls, raw


def run_map(repo, jobs, project_id=None):
    step = None
    if project_id:
        projects = ProjectService(repo.research_store)
        project = projects.get(project_id)
        projects.add(
            project_id, "合成地图", revision=project["revision"], approach="work_map", max_calls=4
        )
        step = projects.claim(project_id)
    result = asyncio.run(
        research(
            repo,
            "合成地图",
            Settings(),
            job_ids=jobs,
            approach="work_map",
            max_calls=4,
            model=RelationMap(),
            project_id=project_id,
            checkpoint=(repo.research_store, step["run_id"]) if step else None,
        )
    )
    assert result["status"] == "completed"
    if step:
        projects.finish(project_id, step["id"], state="completed")
    return result


def test_map_http_retention_revisions_reuse_and_forgetting(source_workspace, tmp_path):
    repo, store, jobs = source_workspace
    private = MemoryService(repo).create("preference", "合成私密接口偏好")
    first, second = run_map(repo, jobs), run_map(repo, jobs)
    originals = deepcopy([store.get(row["run_id"])["result"] for row in (first, second)])
    knowledge = DomainKnowledgeService(repo)
    transfer = ResearchKnowledgeService(repo, store)
    settings = Settings(database_path=tmp_path / "app.db", raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        headers = {"X-WO-Token": token}
        path = f"/api/knowledge/research/{first['run_id']}"
        preview = client.get(path)
        assert preview.status_code == 200
        assert preview.json()["work_relations"][0]["basis"] == "inference"
        saved = client.post(path, headers=headers, json={"work_type_index": 0})
        assert saved.status_code == 201, saved.text
        domain = saved.json()["record"]
        assert domain["status"] == "candidate"
        assert domain["source_context"]["run_id"] == first["run_id"]
        assert (
            client.post(path, headers=headers, json={"work_type_index": 0}).json()["record"]["id"]
            == domain["id"]
        )
        assert (
            client.post(
                f"/api/knowledge/domains/{domain['id']}/review",
                headers=headers,
                json={"decision": "accept", "reason": "合成机制核对"},
            ).status_code
            == 200
        )
        body = {"work_relation_index": 0, "domain_id": domain["id"]}
        saved = client.post(path, headers=headers, json=body)
        assert saved.status_code == 201, saved.text
        relation = saved.json()["record"]
        assert relation["scope"]["research_map"]["transfer_limit"] == "不证明独立平台交付"
        assert (
            client.post(path, headers=headers, json=body).json()["record"]["id"] == relation["id"]
        )
        knowledge.review_relation(relation["id"], "accept", "合成机制核对")

    reused = knowledge.browse_for_research(["接口"], job_ids=jobs, public_document_ids=[])
    assert {row["id"] for row in reused["domains"]} == {domain["id"]}
    assert {row["id"] for row in reused["relations"]} == {relation["id"]}
    assert not knowledge.browse_for_research(["接口"], job_ids=jobs[:1], public_document_ids=[])[
        "domains"
    ]
    revised = transfer.save(second["run_id"], work_type_index=0, previous_domain_id=domain["id"])[
        "record"
    ]
    assert revised["version"] == 2 and revised["domain_key"] == domain["domain_key"]
    knowledge.review_domain(revised["id"], "accept", "合成新地图修订")
    replacement = transfer.save(
        second["run_id"],
        work_relation_index=0,
        domain_id=revised["id"],
        previous_relation_id=relation["id"],
    )["record"]
    with pytest.raises(ProbeError, match="RELATION_CONFLICT_REQUIRES_REVIEW"):
        knowledge.review_relation(replacement["id"], "accept", "合成冲突不能静默覆盖")
    knowledge.review_relation(relation["id"], "withdraw", "合成明确替换")
    knowledge.review_relation(replacement["id"], "accept", "合成修订核对")
    reused = knowledge.browse_for_research(["接口"], job_ids=jobs, public_document_ids=[])
    assert {row["id"] for row in reused["domains"]} == {revised["id"]}
    assert {row["id"] for row in reused["relations"]} == {replacement["id"]}
    assert originals == [store.get(row["run_id"])["result"] for row in (first, second)]

    child = store.create({"question": "只使用结构化知识的合成下游"})
    store.save(
        child["id"],
        state="finished",
        result={
            **deepcopy(second),
            "run_id": child["id"],
            "memory_used": [],
            "context_memory_used": [],
            "continued_from": [],
            "knowledge_used": reused["dependencies"],
        },
    )
    raw_jobs = [repo.job(job) for job in jobs]
    erased = forget_personal(repo, store, private["id"], tmp_path / "reports")
    assert {first["run_id"], second["run_id"], child["id"]} <= set(erased["affected_run_ids"])
    with Session(repo.engine) as session:
        assert all(
            row.status == "invalidated" and row.definition == "[上游研究已失效]"
            for row in session.scalars(select(DomainDefinition))
        )
        assert all(
            row.status == "invalidated" and not row.evidence
            for row in session.scalars(select(WorkRelation))
        )
    assert raw_jobs == [repo.job(job) for job in jobs]
    assert all(not row["supporting_claims"] for row in knowledge.list_domains(include_history=True))
    assert all(
        not row["supporting_claims"] for row in knowledge.list_relations(include_history=True)
    )


def test_rejected_map_stops_saved_work_type_reuse(source_workspace):
    repo, store, jobs = source_workspace
    project = ProjectService(store).create("合成地图项目", "合成工作类型研究", jobs)
    result = run_map(repo, jobs, project["id"])
    transfer = ResearchKnowledgeService(repo, store)
    saved = transfer.save(result["run_id"], work_type_index=0)["record"]
    knowledge = DomainKnowledgeService(repo)
    knowledge.review_domain(saved["id"], "accept", "合成机制核对")
    relation = transfer.save(result["run_id"], work_relation_index=0, domain_id=saved["id"])[
        "record"
    ]
    assert relation["scope"]["project_id"] == project["id"]
    knowledge.review_relation(relation["id"], "accept", "合成项目内核对")
    assert knowledge.browse_for_research(
        ["接口"], job_ids=jobs, public_document_ids=[], project_id=project["id"]
    )["relations"]
    assert not knowledge.browse_for_research(["接口"], job_ids=jobs, public_document_ids=[])[
        "relations"
    ]
    quality = QualityReviewService(store, repo)
    packet = quality.packet(result["run_id"])
    quality.submit(
        result["run_id"],
        dict(
            result_sha256=packet["result_sha256"],
            reviewer="合成测试",
            reviewer_kind="agent_assisted",
            decision="reject",
            note="合成来源否决",
            dimensions={key: {"rating": "fail", "reason": "合成"} for key in DIMENSIONS},
            claim_reviews=[
                dict(index=i, support="unsupported", requirement="correct", note="合成否决")
                for i in range(len(packet["claims"]))
            ],
            work_map_review={"rating": "fail", "reason": "合成边界错误"},
        ),
    )
    assert knowledge.list_domains()[0]["stale"]
    assert not knowledge.browse_for_research(["接口"], job_ids=jobs, public_document_ids=[])[
        "domains"
    ]
    with pytest.raises(ProbeError, match="KNOWLEDGE_RESEARCH_SOURCE_STALE"):
        transfer.save(result["run_id"], work_type_index=0)
