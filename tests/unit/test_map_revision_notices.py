"""Map-derived knowledge carries provisional corrections without changing adoption."""

from copy import deepcopy

from test_dependency_eligibility import dependencies as dependencies
from test_dependency_eligibility import source

from work_observer.collection.contracts import now
from work_observer.knowledge.research import ResearchKnowledgeService
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.memory.dependencies import DependencyAudit
from work_observer.memory.lifecycle import forget_personal
from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import DIMENSIONS
from work_observer.research.projects import ProjectService


def setup_map(workspace):
    repo, store, memory, jobs, _ = workspace
    original = source(repo, store, jobs)
    original["claims"].append({**original["claims"][0], "text": "合成 RAG 接口开发"})
    original["work_map"] = dict(
        version="existing-map",
        scope_note="合成测试，非真实知识",
        unknowns=["实际权限未知"],
        work_types=[
            dict(
                name="RAG研究" + str(i),
                problem="RAG工作",
                tasks="RAG核对",
                deliverables="清单",
                boundary="只限合成资料",
                next_check="实际分工",
                basis="inference",
                claim_indices=[i],
            )
            for i in (0, 1)
        ],
        work_relations=[
            dict(
                source_kind="task",
                source_text="RAG评估",
                target_kind="ability",
                target_text="RAG核对能力",
                predicate="requires",
                rationale="待验证关系",
                basis="inference",
                transfer_limit="实际权限未知",
                claim_indices=[0, 1],
            )
        ],
    )
    store.save(original["run_id"], state="finished", result=original)
    transfer, knowledge = ResearchKnowledgeService(repo, store), DomainKnowledgeService(repo)
    domains = [transfer.save(original["run_id"], work_type_index=i)["record"] for i in (0, 1)]
    for domain in domains:
        knowledge.review_domain(domain["id"], "accept", "合成核对，非真实采纳")
    relation = transfer.save(original["run_id"], work_relation_index=0, domain_id=domains[0]["id"])[
        "record"
    ]
    knowledge.review_relation(relation["id"], "accept", "合成核对，非真实采纳")
    return original, domains, relation, knowledge


def make_revision(workspace, original, *, memories=(), project_id=None, all_jobs=False):
    repo, store, _, jobs, _ = workspace
    later = source(
        repo, store, jobs if all_jobs else jobs[:1], memories=memories, project_id=project_id
    )
    later["claims"][0]["text"] = "RAG任务不证明个人上线权限。"
    later["cognition_revisions"] = [
        dict(
            previous_run_id=original["run_id"],
            previous_claim_index=0,
            previous_statement=original["claims"][0]["text"],
            decision="revise",
            trigger="recheck",
            new_claim_indices=[0],
            new_statements=[later["claims"][0]["text"]],
            evidence_ids=[later["evidence"][0]["id"]],
            reason="合成原任务与权限边界不同",
        )
    ]
    store.save(later["run_id"], state="finished", result=later)
    return later


def test_map_notices_show_exact_support_and_reach_research_without_changing_status(dependencies):
    repo, store, _, jobs, _ = dependencies
    original, domains, relation, knowledge = setup_map(dependencies)
    before = deepcopy(store.get(original["run_id"])["result"])
    baseline = knowledge.browse_for_research(["RAG"], job_ids=jobs[:1], public_document_ids=[])
    earlier = now()
    later = make_revision(dependencies, original)
    later["knowledge_used"] = baseline["dependencies"]
    store.save(later["run_id"], result=later)
    assert DependencyAudit(repo).run(later["run_id"])["eligible"]  # No notice/knowledge cycle.
    definitions = {row["id"]: row for row in knowledge.list_domains()}
    assert definitions[domains[0]["id"]]["revision_notices"][0]["run_id"] == later["run_id"]
    assert not definitions[domains[1]["id"]]["revision_notices"]
    assert all(row["status"] == "active" and not row["stale"] for row in definitions.values())
    listed = knowledge.list_relations()[0]
    assert listed["id"] == relation["id"] and listed["revision_notices"]
    assert listed["status"] == "active" and not listed["stale"]
    recalled = knowledge.browse_for_research(["RAG"], job_ids=jobs[:1], public_document_ids=[])
    assert recalled["relations"][0]["revision_notices"][0]["previous_claim_index"] == 0
    assert later["run_id"] in recalled["source_run_ids"]
    assert store.get(original["run_id"])["result"] == before
    # A historical cutoff keeps the original knowledge and excludes the later notice.
    old = knowledge.browse_for_research(
        ["RAG"], job_ids=jobs[:1], public_document_ids=[], as_of=earlier
    )
    assert len(old["relations"]) == 1
    assert later["run_id"] not in old["source_run_ids"]
    # Rejecting the later interpretation removes only its notice, not old knowledge.
    reviews = QualityReviewService(store, repo)
    packet = reviews.packet(later["run_id"])
    reviews.submit(
        later["run_id"],
        dict(
            result_sha256=packet["result_sha256"],
            decision="reject",
            reviewer="合成复核",
            reviewer_kind="agent_assisted",
            note="合成否决",
            dimensions={key: dict(rating="fail", reason="合成否决") for key in DIMENSIONS},
            claim_reviews=[
                dict(index=0, support="unsupported", requirement="correct", note="合成否决")
            ],
        ),
    )
    assert not knowledge.list_relations()[0]["revision_notices"]
    assert knowledge.list_relations()[0]["status"] == "active"


def test_notice_text_cannot_survive_forgetting_its_private_source(dependencies, tmp_path):
    repo, store, memory, jobs, _ = dependencies
    original, _, _, knowledge = setup_map(dependencies)
    private = memory.create("preference", "合成私有核实重点")
    later = make_revision(dependencies, original, memories=[private])
    recalled = knowledge.browse_for_research(["RAG"], job_ids=jobs[:1], public_document_ids=[])
    child = source(repo, store, jobs[:1], continued_from=recalled["source_run_ids"])
    # Legacy memory recall notices also carry private text and need erasure lineage.
    saved = memory.create(
        "knowledge",
        original["claims"][0]["text"],
        evidence=original["evidence"][:1],
        source_run_id=original["run_id"],
        origin="agent",
    )
    saved = memory.activate(saved["id"])
    memory_child = source(
        repo,
        store,
        jobs[:1],
        memories=[dict(saved, revision_notices=[dict(run_id=later["run_id"], reason="私有提示")])],
    )
    erased = forget_personal(repo, store, private["id"], tmp_path / "reports")
    assert {later["run_id"], child["run_id"], memory_child["run_id"]} <= set(
        erased["affected_run_ids"]
    )
    assert original["run_id"] not in erased["affected_run_ids"]
    assert not knowledge.list_relations()[0]["revision_notices"]
    assert knowledge.list_relations()[0]["status"] == "active"


def test_notices_respect_project_and_selected_material_scope(dependencies):
    _, store, _, jobs, _ = dependencies
    original, _, _, knowledge = setup_map(dependencies)
    project = ProjectService(store).create("合成私有项目", "合成范围", jobs[:1])
    later = make_revision(dependencies, original, project_id=project["id"])
    generic = knowledge.browse_for_research(["RAG"], job_ids=jobs[:1], public_document_ids=[])
    assert "revision_notices" not in generic["relations"][0]
    scoped = knowledge.browse_for_research(
        ["RAG"], job_ids=jobs[:1], public_document_ids=[], project_id=project["id"]
    )
    assert scoped["relations"][0]["revision_notices"][0]["run_id"] == later["run_id"]
    outside = make_revision(dependencies, original, all_jobs=True)
    generic = knowledge.browse_for_research(["RAG"], job_ids=jobs[:1], public_document_ids=[])
    notice = generic["relations"][0]["revision_notices"][0]
    assert notice["run_id"] == outside["run_id"] and not notice.get("scope_limited")
    # Reading a second job does not expand this particular correction's support scope.
    both = knowledge.browse_for_research(["RAG"], job_ids=jobs, public_document_ids=[])
    assert both["relations"][0]["revision_notices"][0]["run_id"] == outside["run_id"]
