"""已审核领域口径应形成可续接的新材料；范围和资格必须与研究工具一致。"""

import asyncio

import pytest

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.research.materials import material_state
from work_observer.research.projects import ProjectService, execute_project
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def material_corpus(tmp_path):
    path = tmp_path / "app.db"
    upgrade(path)
    repo = Repository(path)
    archive = RawArchive(tmp_path / "raw", [])
    jobs = [
        import_jd(
            repo,
            archive,
            ManualJD(
                title="合成岗位",
                company="合成公司",
                external_id=key,
                description="RAG 评估与 Python 开发。",
                data_kind="synthetic",
            ),
        )["job_id"]
        for key in ("a", "b")
    ]
    store = ResearchStore(tmp_path / "checkpoints.db", str(path.resolve()))
    repo.bind_research_store(store)
    yield repo, store, jobs
    store.close()
    repo.close()


def definition(service, key="rag_domain", name="RAG领域"):
    row = service.propose_domain(
        key, name, name + "的明确边界", inclusion=name, exclusion="未知任务"
    )
    return service.review_domain(row["id"], "accept", "合成机制核对，不是实际人类质量评估")


def relation(service, repo, domain, job, project_id=None):
    row = service.propose_relation(
        domain["id"],
        "task",
        "RAG 评估",
        "ability",
        "Python",
        Catalog(repo).evidence(job),
        project_id=project_id,
    )
    return service.review_relation(row["id"], "accept", "合成原文核对")


def test_accepted_domain_is_material_change_and_enables_waiting_project_refresh(material_corpus):
    repo, store, jobs = material_corpus
    projects = ProjectService(store)
    project = projects.create("合成项目", "RAG工作领域", jobs[:1])
    project = projects.add(project["id"], "RAG工作领域", revision=project["revision"], offline=True)
    project = asyncio.run(execute_project(projects, project["id"], repo, Settings(), max_steps=1))
    before = material_state(repo, "RAG工作领域", job_ids=jobs[:1], project_id=project["id"])
    assert project["steps"][0]["state"] == "waiting_material"
    definition(DomainKnowledgeService(repo))
    after = material_state(repo, "RAG工作领域", job_ids=jobs[:1], project_id=project["id"])
    assert before["signature"] != after["signature"]
    assert before["basis"]["jobs"] == after["basis"]["jobs"]
    refreshed = projects.refresh_waiting(
        project["id"],
        project["steps"][0]["id"],
        repo,
        revision=project["revision"],
        note="新增已审核的RAG领域口径",
        offline=True,
    )
    assert len(refreshed["steps"]) == 2 and refreshed["steps"][-1]["state"] == "queued"


def test_pending_and_irrelevant_definitions_do_not_count_as_effective_material(material_corpus):
    repo, _, jobs = material_corpus
    service = DomainKnowledgeService(repo)
    before = material_state(repo, "RAG", job_ids=jobs[:1])
    pending = service.propose_domain("rag_candidate", "RAG待审", "尚未通过审核")
    assert before["signature"] == material_state(repo, "RAG", job_ids=jobs[:1])["signature"]
    definition(service, key="unrelated", name="仓储物流")
    assert before["signature"] == material_state(repo, "RAG", job_ids=jobs[:1])["signature"]
    service.review_domain(pending["id"], "accept", "合成明确审核")
    assert before["signature"] != material_state(repo, "RAG", job_ids=jobs[:1])["signature"]


def test_relation_changes_only_covered_job_scope_and_withdrawal_changes_fingerprint(
    material_corpus,
):
    repo, _, jobs = material_corpus
    service = DomainKnowledgeService(repo)
    domain = definition(service)
    first = material_state(repo, "RAG", job_ids=jobs[:1])
    other = material_state(repo, "RAG", job_ids=jobs[1:])
    row = relation(service, repo, domain, jobs[0])
    changed = material_state(repo, "RAG", job_ids=jobs[:1])
    assert first["signature"] != changed["signature"]
    assert other["signature"] == material_state(repo, "RAG", job_ids=jobs[1:])["signature"]
    assert len(changed["basis"]["knowledge_dependencies"]) == 2
    service.review_relation(row["id"], "withdraw", "合成撤回")
    assert changed["signature"] != material_state(repo, "RAG", job_ids=jobs[:1])["signature"]


def test_project_scoped_relation_is_not_new_material_for_other_projects(material_corpus):
    repo, _, jobs = material_corpus
    service = DomainKnowledgeService(repo)
    domain = definition(service)
    before = material_state(repo, "RAG", job_ids=jobs[:1], project_id="b" * 32)
    own_before = material_state(repo, "RAG", job_ids=jobs[:1], project_id="a" * 32)
    relation(service, repo, domain, jobs[0], project_id="a" * 32)
    assert (
        before["signature"]
        == material_state(repo, "RAG", job_ids=jobs[:1], project_id="b" * 32)["signature"]
    )
    assert (
        own_before["signature"]
        != material_state(repo, "RAG", job_ids=jobs[:1], project_id="a" * 32)["signature"]
    )
