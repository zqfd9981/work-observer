"""The Agent's six-dimension map survives export and existing knowledge services."""

import asyncio
import json
from copy import deepcopy

import pytest
from test_cognition_research import MapModel
from test_source_first_research import source_workspace as source_workspace
from test_work_materials import MaterialModel

from work_observer.config import Settings
from work_observer.connectors import public_documents
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.knowledge.research import ResearchKnowledgeService
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.reports.cognition import checked_map
from work_observer.reports.results import read_result, render, save_result
from work_observer.research.agent import research
from work_observer.research.cognition import VERSION
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive

NODES = dict(
    business="减少人工核对遗漏",
    task="checkpoint原文检查",
    deliverable="核对清单",
    responsibility="复核角色确认清单",
    ability="原文定位能力",
    tool="Python检查脚本",
)
EDGES = [
    ("business", "task", "supports"),
    ("task", "deliverable", "produces"),
    ("responsibility", "ability", "requires"),
    ("tool", "task", "supports"),
    ("responsibility", "deliverable", "supports"),
]


def add_map(calls, public):
    if calls[0]["name"] != "finish_research":
        return
    args = json.loads(calls[0]["arguments"])
    reference = args["claims"][0]["evidence_ids"]
    args["claims"] = [
        dict(
            category=key,
            text="合成资料描述：" + text,
            basis="inference" if public and key not in {"business", "tool"} else "direct",
            requirement="unspecified",
            evidence_ids=reference,
        )
        for key, text in NODES.items()
    ]
    positions = {key: index for index, key in enumerate(NODES)}
    args["work_map"] = dict(
        version=VERSION,
        scope_note="隔离合成材料，非真实研究质量证据",
        work_types=[
            dict(
                name="核对交付",
                problem=NODES["business"],
                tasks=NODES["task"],
                deliverables=NODES["deliverable"],
                basis="synthesis",
                claim_indices=[0, 1, 2],
                boundary="只说明本资料中的核对流程，不推广为招聘通用要求",
                next_check="核实执行和责任主体",
            )
        ],
        work_relations=[
            dict(
                source_claim_index=positions[a],
                target_claim_index=positions[b],
                predicate=predicate,
                basis="inference",
                rationale="合成的关系解释，仍需核对",
                transfer_limit="不证明任职必备、独立交付或实际执行",
            )
            for a, b, predicate in EDGES
        ],
        comparisons=[],
        unknowns=["资料未证明实际执行"],
    )
    args["revisions"] = []
    calls[0]["arguments"] = json.dumps(args)


class JobMap(MapModel):
    async def turn(self, history):
        calls, raw = await super().turn(history)
        add_map(calls, False)
        return calls, raw


class DocumentMap(MaterialModel):
    def __init__(self, public):
        super().__init__(category="business")
        self.public = public

    async def turn(self, history):
        calls, raw = await super().turn(history)
        add_map(calls, self.public)
        return calls, raw


class ComparedJobMap(MapModel):
    async def turn(self, history):
        calls, raw = await super().turn(history)
        if calls[0]["name"] == "finish_research":
            args = json.loads(calls[0]["arguments"])
            # Two already-read synthetic jobs supply distinct sides of the comparison.
            sides = args["claims"][:2]
            args["claims"] = [
                dict(side, category=category, text=text, requirement="required")
                for side, label in zip(sides, ("平台", "内容"), strict=True)
                for category, text in (
                    ("task", label + "接口开发"),
                    ("ability", "精通" + label + "系统：" + "合成条件；" * 110),
                )
            ]
            args["work_map"]["work_relations"] = [
                dict(
                    source_claim_index=i,
                    target_claim_index=i + 1,
                    predicate="requires",
                    basis="inference",
                    rationale="仅为合成关联",
                    transfer_limit="未证明独立交付",
                )
                for i in (0, 2)
            ]
            args["work_map"]["comparisons"] = [
                dict(
                    relation_indices=[0, 1],
                    common_ground="都涉及接口工作",
                    differences="系统对象不同",
                    transfer_conditions="核实个人分工与规模",
                    basis="inference",
                    unknowns=["不能直接认定可以迁移"],
                )
            ]
            calls[0]["arguments"] = json.dumps(args)
        return calls, raw


def test_saved_relation_carries_comparison_and_evidence_from_both_jobs(source_workspace):
    repo, store, jobs = source_workspace
    result = asyncio.run(
        research(
            repo,
            "合成比较",
            Settings(),
            job_ids=jobs[:2],
            approach="work_map",
            max_calls=4,
            model=ComparedJobMap(),
        )
    )
    assert result["status"] == "completed", result
    original = deepcopy(store.get(result["run_id"])["result"])
    transfer = ResearchKnowledgeService(repo, store)
    preview = transfer.preview(result["run_id"])
    assert preview["work_relations"][0]["comparisons"][0]["claim_indices"] == [0, 1, 2, 3]
    support = preview["work_relations"][0]["supporting_claims"]
    assert [row["claim_index"] for row in support] == [0, 1, 2, 3]
    assert support[1]["text"] == result["claims"][1]["text"]
    assert support[1]["requirement"] == "required" and support[1]["basis"] == "direct"
    assert {ref["job_id"] for row in support for ref in row["source_references"]} == set(jobs[:2])
    domain = transfer.save(result["run_id"], work_type_index=0)["record"]
    body = dict(work_relation_index=0, domain_id=domain["id"])
    row = transfer.save(result["run_id"], **body)["record"]
    assert set(row["scope"]["job_ids"]) == set(jobs[:2])
    assert row["scope"]["research_map"]["claim_indices"] == [0, 1, 2, 3]
    assert row["scope"]["research_map"]["comparisons"] == result["work_map"]["comparisons"]
    assert row["target_text"] == result["claims"][1]["text"] and len(row["target_text"]) > 500
    assert transfer.save(result["run_id"], **body)["record"]["id"] == row["id"]
    knowledge = DomainKnowledgeService(repo)
    knowledge.review_domain(domain["id"], "accept", "合成机制核对")
    knowledge.review_relation(row["id"], "accept", "合成机制核对")
    listed = next(record for record in knowledge.list_relations() if record["id"] == row["id"])
    assert listed["supporting_claims"] == support
    reused = knowledge.browse_for_research(["接口"], job_ids=jobs[:2], public_document_ids=[])
    packet = next(
        item for item in reused["supporting_findings"] if item["run_id"] == result["run_id"]
    )
    assert packet["claims"] == support
    assert packet["omitted_claims"] == 0 and not packet["independent_source"]
    assert "requires不自动等于招聘必备" in reused["rules"]
    assert store.get(result["run_id"])["result"] == original


@pytest.mark.parametrize("origin", ["job", "manual", "public"])
def test_six_dimensions_from_engine_to_knowledge_keep_direction_and_source_scope(
    source_workspace, tmp_path, monkeypatch, origin
):
    repo, store, _ = source_workspace
    text = "合成工作说明：" + "；".join(NODES.values())
    public_ids, jobs = [], []
    if origin == "job":
        jobs = [
            import_jd(
                repo,
                RawArchive(tmp_path / "raw"),
                ManualJD(
                    title="合成核对岗位",
                    company="合成公司",
                    description=text,
                    data_kind="synthetic",
                ),
            )["job_id"]
        ]
        model, calls = JobMap(), 3
    else:
        archive = PublicDocumentService(repo, tmp_path / "materials")
        if origin == "manual":
            document = archive.archive_text("合成流程说明", text)["document"]
        else:

            async def response(url):
                return 200, {"content-type": "text/plain"}, text.encode()

            monkeypatch.setattr(public_documents, "pinned_request", response)
            document = asyncio.run(archive.read("https://example.com/synthetic"))["document"]
        public_ids = [document["id"]]
        model, calls = DocumentMap(origin == "public"), 2
    result = asyncio.run(
        research(
            repo,
            "checkpoint工作关系",
            Settings(),
            job_ids=jobs,
            public_document_ids=public_ids,
            approach="work_map",
            coverage_mode="question",
            max_calls=calls,
            model=model,
        )
    )
    assert result["status"] == "completed", result
    assert result["work_map"]["version"] == VERSION
    assert "ability_relations" not in result["work_map"]
    assert set(NODES) == {
        edge[key]
        for edge in result["work_map"]["work_relations"]
        for key in ("source_kind", "target_kind")
    }
    original = deepcopy(store.get(result["run_id"])["result"])
    saved_report = save_result(result, tmp_path / "reports")
    loaded = read_result(saved_report["report_id"], tmp_path / "reports")
    assert loaded["work_map"] == result["work_map"]
    assert "业务与工作关系" in render(loaded) and "产出" in render(loaded)
    transfer = ResearchKnowledgeService(repo, store)
    assert len(transfer.preview(result["run_id"])["work_relations"]) == 5
    domain = transfer.save(result["run_id"], work_type_index=0)["record"]
    knowledge = DomainKnowledgeService(repo)
    knowledge.review_domain(domain["id"], "accept", "合成机制核对，非真实人审")
    for index, (source, target, predicate) in enumerate(EDGES):
        body = dict(work_relation_index=index, domain_id=domain["id"])
        row = transfer.save(result["run_id"], **body)["record"]
        assert row["source_kind"] == source and row["target_kind"] == target
        assert row["predicate"] == predicate
        assert (
            row["scope"]["evidence_scope"]
            == {"job": "job", "manual": "work_material", "public": "public_context"}[origin]
        )
        assert transfer.save(result["run_id"], **body)["record"]["id"] == row["id"]
        knowledge.review_relation(row["id"], "accept", "合成关系核对，非真实人审")
    reused = knowledge.browse_for_research(["核对"], job_ids=jobs, public_document_ids=public_ids)
    assert len(reused["relations"]) == 5
    if public_ids:
        assert not knowledge.browse_for_research(["核对"], job_ids=[], public_document_ids=[])[
            "relations"
        ]
    assert store.get(result["run_id"])["result"] == original


def test_existing_ability_map_can_still_be_read_and_saved_without_rewriting_it(source_workspace):
    repo, store, jobs = source_workspace
    evidence = Catalog(repo).evidence(jobs[0])
    run = store.create({"question": "合成旧地图存档"})
    value = dict(
        run_id=run["id"],
        status="completed",
        question="合成旧地图存档",
        scope=Catalog(repo).query(job_ids=jobs[:1]),
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
        work_map=dict(
            version="work-map-v2-revisions",
            scope_note="既有合成地图",
            work_types=[],
            ability_relations=[
                dict(
                    task="接口开发",
                    ability="接口设计",
                    rationale="待核对",
                    basis="inference",
                    transfer_limit="未知",
                    claim_indices=[0],
                )
            ],
            unknowns=["尚待核实"],
        ),
    )
    store.save(run["id"], state="finished", result=value)
    assert "work_relations" not in checked_map(value)
    knowledge = DomainKnowledgeService(repo)
    domain = knowledge.propose_domain("legacy_api", "接口工作", "合成边界")
    transfer = ResearchKnowledgeService(repo, store)
    saved = transfer.save(run["id"], ability_relation_index=0, domain_id=domain["id"])["record"]
    assert saved["source_kind"] == "task" and saved["target_kind"] == "ability"
    assert transfer.preview(run["id"])["ability_relations"][0]["saved_id"] == saved["id"]
    assert store.get(run["id"])["result"] == value
