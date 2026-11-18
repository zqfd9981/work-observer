"""整项目遗忘、跨项目派生与失败重启；全部为隔离合成机制材料。"""

import asyncio
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.collection.contracts import now
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.knowledge.models import DomainDefinition, WorkRelation
from work_observer.memory.lifecycle import (
    forget_personal,
    forget_project,
    pending_erasures,
    resume_erasures,
)
from work_observer.memory.service import MemoryService
from work_observer.quality.reviews import QualityReviewService
from work_observer.reports.domain_updates import DomainUpdateService
from work_observer.reports.inbox import InboxService
from work_observer.reports.results import save_result
from work_observer.research.projects import ProjectService
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.models import MemoryRecord
from work_observer.storage.repository import Repository

PRIVATE = "SYNTHETIC_PROJECT_PRIVATE_CONTENT"


@pytest.fixture
def erasure(tmp_path):
    path = tmp_path / "app.db"
    upgrade(path)
    repo = Repository(path)
    job = import_jd(
        repo,
        RawArchive(tmp_path / "raw", []),
        ManualJD(
            title="合成遗忘测试岗位",
            company="合成公司",
            external_id="erasure",
            description="负责 Python 开发并交付接口服务。",
            data_kind="synthetic",
        ),
    )["job_id"]
    store = ResearchStore(tmp_path / "checkpoints.db", str(path.resolve()))
    yield repo, store, job, tmp_path
    store.close()
    repo.close()


def completed_run(repo, store, project_id, job, text, *, continued_from=(), memories=()):
    projects = ProjectService(store)
    project = projects.get(project_id)
    project = projects.add(project_id, text, revision=project["revision"])
    step = projects.claim(project_id)
    evidence = Catalog(repo).evidence(job)
    result = {
        "run_id": step["run_id"],
        "project_id": project_id,
        "question": text,
        "status": "completed",
        "created_at": now(),
        "scope": Catalog(repo).query(job_ids=[job]),
        "claims": [
            {
                "category": "task",
                "requirement": "unspecified",
                "text": text,
                "evidence_ids": [evidence[0]["id"]],
            }
        ],
        "evidence": evidence,
        "gaps": [],
        "memory_used": list(memories),
        "continued_from": list(continued_from),
    }
    store.save(step["run_id"], state="finished", result=result)
    projects.finish(project_id, step["id"], state="completed")
    return result


def derived_artifacts(repo, store, run_id, job):
    evidence = Catalog(repo).evidence(job)
    with Session(repo.engine) as session, session.begin():
        session.add(
            DomainDefinition(
                id="d" * 32,
                domain_key="synthetic",
                version=1,
                previous_id=None,
                name="合成领域",
                definition="合成边界",
                inclusion="开发",
                exclusion="未知",
                status="active",
                change_kind="create",
                related_ids=[],
                review_reason="合成机制",
                created_at=now(),
                reviewed_at=now(),
            )
        )
        session.flush()
        session.add(
            WorkRelation(
                id="e" * 32,
                domain_id="d" * 32,
                source_kind="task",
                source_text=PRIVATE,
                target_kind="ability",
                target_text=PRIVATE,
                predicate="requires",
                scope={"job_ids": [job]},
                evidence=evidence,
                counterevidence=[],
                conflict_ids=[],
                status="active",
                review_reason=PRIVATE,
                source_run_id=run_id,
                created_at=now(),
                reviewed_at=now(),
            )
        )
    QualityReviewService(store)
    updates = DomainUpdateService(store, repo)
    with store.lock, store.db:
        store.db.execute(
            "INSERT INTO quality_reviews VALUES(?,?,?,?)",
            (
                store.namespace,
                "f" * 32,
                run_id,
                json.dumps({"id": "f" * 32, "run_id": run_id, "note": PRIVATE}),
            ),
        )
        updates._write(
            "domain_update_captures",
            {
                "id": "1" * 32,
                "state": "active",
                "created_at": now(),
                "source_run_ids": [run_id],
                "title": PRIVATE,
            },
        )
        updates._write(
            "domain_update_reports",
            {
                "id": "2" * 32,
                "state": "active",
                "created_at": now(),
                "before_id": "1" * 32,
                "after_id": "1" * 32,
                "body": PRIVATE,
            },
        )
    inbox = InboxService(repo)
    inbox.create("research", PRIVATE, PRIVATE, related_id=run_id)
    inbox.add_followup(PRIVATE, "2" * 32)


def assert_online_text_cleared(repo, store, project_ids, run_ids):
    for project_id in project_ids:
        assert PRIVATE not in json.dumps(ProjectService(store).get(project_id))
    for run_id in run_ids:
        assert store.get(run_id)["state"] == "invalidated"
        assert store.load_checkpoint(run_id) is None
    with store.lock:
        for table in (
            "research_checkpoints",
            "research_projects",
            "quality_reviews",
            "domain_update_captures",
            "domain_update_reports",
            "privacy_erasures",
        ):
            rows = store.db.execute(
                f"SELECT record FROM {table} WHERE namespace=?", (store.namespace,)
            ).fetchall()
            assert all(PRIVATE not in encoded for (encoded,) in rows)
    with Session(repo.engine) as session:
        assert all(
            PRIVATE not in row.content and PRIVATE not in (row.subject or "")
            for row in session.scalars(select(MemoryRecord))
        )
        relation = session.get(WorkRelation, "e" * 32)
        assert relation.status == "invalidated" and relation.review_reason is None
    assert all(
        PRIVATE not in row["body"] and PRIVATE not in row["title"]
        for row in InboxService(repo).list()
    )


def test_whole_project_forget_clears_all_memory_kinds_and_cross_project_downstream(erasure):
    repo, store, job, root = erasure
    original_job = repo.job(job)
    projects, memory = ProjectService(store), MemoryService(repo)
    project = projects.create(PRIVATE, PRIVATE, [job])
    scoped = []
    for kind in ("preference", "correction", "knowledge", "hypothesis", "method"):
        scoped.append(
            memory.create(
                kind,
                PRIVATE,
                project_id=project["id"],
                subject=PRIVATE,
                evidence=Catalog(repo).evidence(job) if kind == "knowledge" else None,
            )
        )
    scoped = [memory.activate(row["id"]) if row["status"] == "candidate" else row for row in scoped]
    source = completed_run(repo, store, project["id"], job, PRIVATE, memories=scoped)
    derived = memory.create(
        "knowledge", PRIVATE, evidence=Catalog(repo).evidence(job), source_run_id=source["run_id"]
    )
    memory.activate(derived["id"])
    next_project = projects.create("派生项目", "综合已有研究", [job])
    child = completed_run(
        repo, store, next_project["id"], job, PRIVATE, continued_from=[source["run_id"]]
    )
    sibling = completed_run(repo, store, next_project["id"], job, "同项目其他轮次")
    for result in (source, child, sibling):
        saved = save_result(result, root / "reports")
        store.save(result["run_id"], saved=saved)
    derived_artifacts(repo, store, source["run_id"], job)
    independent = projects.create("独立项目", "独立目标", [job])
    unrelated_memory = memory.create("preference", "独立偏好")
    response = forget_project(repo, store, project["id"], root / "reports")
    run_ids = {source["run_id"], child["run_id"], sibling["run_id"]}
    assert set(response["affected_run_ids"]) == run_ids
    assert {row["id"] for row in scoped} | {derived["id"]} <= set(response["affected_memory_ids"])
    assert response["invalidated_update_report_ids"] == ["2" * 32]
    assert_online_text_cleared(repo, store, [project["id"], next_project["id"]], run_ids)
    assert not list((root / "reports").glob("*"))
    assert repo.job(job) == original_job
    assert projects.get(independent["id"])["goal"] == "独立目标"
    assert unrelated_memory["id"] in {row["id"] for row in memory.list()}
    assert (
        set(forget_project(repo, store, project["id"], root / "reports")["affected_run_ids"])
        == run_ids
    )
    assert resume_erasures(repo, store, root / "reports")["resumed_erasure_ids"] == []


def test_personal_forget_follows_relation_source_run_context_even_without_memory_used(erasure):
    repo, store, job, root = erasure
    projects, memory = ProjectService(store), MemoryService(repo)
    personal = memory.create("preference", PRIVATE)
    project = projects.create("源研究", "合成研究", [job])
    source = completed_run(repo, store, project["id"], job, PRIVATE, memories=[personal])
    child_project = projects.create("读取关系的研究", "合成关系续接", [job])
    child = completed_run(
        repo, store, child_project["id"], job, PRIVATE, continued_from=[source["run_id"]]
    )
    derived_artifacts(repo, store, source["run_id"], job)
    response = forget_personal(repo, store, personal["id"], root / "reports")
    assert set(response["affected_run_ids"]) == {source["run_id"], child["run_id"]}
    assert_online_text_cleared(
        repo, store, [project["id"], child_project["id"]], response["affected_run_ids"]
    )


def test_interrupted_erasure_resumes_from_id_journal_after_dependency_text_is_gone(
    erasure, monkeypatch
):
    repo, store, job, root = erasure
    projects = ProjectService(store)
    project = projects.create(PRIVATE, PRIVATE, [job])
    source = completed_run(repo, store, project["id"], job, PRIVATE)
    child_project = projects.create("派生项目", PRIVATE, [job])
    child = completed_run(
        repo, store, child_project["id"], job, PRIVATE, continued_from=[source["run_id"]]
    )
    derived_artifacts(repo, store, source["run_id"], job)
    saved = save_result(child, root / "reports")
    store.save(child["run_id"], saved=saved)
    invalidate = store.invalidate_runs

    def failing_once(identities):
        invalidate(identities)
        raise RuntimeError("synthetic crash after clearing unique run dependencies")

    monkeypatch.setattr(store, "invalidate_runs", failing_once)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        forget_project(repo, store, project["id"], root / "reports")
    assert store.get(child["run_id"])["result"] is None
    reopened = ResearchStore(store.path, store.namespace)
    try:
        resumed = resume_erasures(repo, reopened, root / "reports")
        assert resumed["resumed_erasure_ids"] == ["project:" + project["id"]]
        assert_online_text_cleared(
            repo,
            reopened,
            [project["id"], child_project["id"]],
            [source["run_id"], child["run_id"]],
        )
        assert not Path(saved["json"]).exists()
        assert resume_erasures(repo, reopened, root / "reports")["resumed_erasure_ids"] == []
    finally:
        reopened.close()


def test_project_delete_http_uses_custom_reports_directory_and_keeps_sources(tmp_path):
    db = tmp_path / "app.db"
    upgrade(db)
    settings = Settings(database_path=db, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "custom-reports"), base_url="http://127.0.0.1"
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        auth = {"X-WO-Token": token}
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成岗位",
                "company": "合成公司",
                "description": "合成 Python 工作",
                "data_kind": "synthetic",
            },
        ).json()["job_id"]
        project = client.post(
            "/api/projects",
            headers=auth,
            json={"title": PRIVATE, "goal": PRIVATE, "job_ids": [job]},
        ).json()
        client.post(
            "/api/memories",
            headers=auth,
            json={"kind": "method", "content": PRIVATE, "project_id": project["id"]},
        )
        assert client.delete("/api/projects/" + project["id"]).status_code == 403
        erased = client.delete("/api/projects/" + project["id"], headers=auth)
        assert erased.status_code == 200 and erased.json()["erased_project_id"] == project["id"]
        current = client.get("/api/projects/" + project["id"]).json()
        assert PRIVATE not in json.dumps(current) and current["state"] == "invalidated"
        assert client.get("/api/overview").json()["jobs"] == 1
        assert (
            client.post(
                "/api/projects/" + project["id"] + "/steps",
                headers=auth,
                json={"revision": current["revision"], "question": "不能复活"},
            ).status_code
            == 400
        )


def test_project_delete_rejects_running_worker_then_succeeds_after_pause(tmp_path):
    class WaitingModel:
        async def turn(self, history):
            await asyncio.Event().wait()

    db = tmp_path / "busy.db"
    upgrade(db)
    settings = Settings(database_path=db, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports", model=WaitingModel()),
        base_url="http://127.0.0.1",
    ) as client:
        token = re.search(r'name="wo-token" content="([^\"]+)"', client.get("/").text)[1]
        auth = {"X-WO-Token": token}
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成岗位",
                "company": "合成公司",
                "description": "合成 Python 工作",
                "data_kind": "synthetic",
            },
        ).json()["job_id"]
        project = client.post(
            "/api/projects",
            headers=auth,
            json={"title": PRIVATE, "goal": PRIVATE, "job_ids": [job]},
        ).json()
        client.post(
            "/api/projects/" + project["id"] + "/steps",
            headers=auth,
            json={"revision": project["revision"], "question": PRIVATE},
        )
        assert (
            client.post("/api/projects/" + project["id"] + "/run", headers=auth).status_code == 202
        )
        rejected = client.delete("/api/projects/" + project["id"], headers=auth)
        assert rejected.status_code == 409 and rejected.json()["error_code"] == "RESEARCH_BUSY"
        assert (
            client.post("/api/projects/" + project["id"] + "/pause", headers=auth).status_code
            == 200
        )
        assert client.delete("/api/projects/" + project["id"], headers=auth).status_code == 200


def test_resume_only_uses_current_namespace_and_rejects_unrequested_running_erase(erasure):
    repo, store, job, root = erasure
    project = ProjectService(store).create("正在领取", "合成目标", [job])
    ProjectService(store).add(project["id"], "合成待运行问题", revision=project["revision"])
    ProjectService(store).claim(project["id"])
    with pytest.raises(ProbeError, match="PROJECT_RUNNING"):
        forget_project(repo, store, project["id"], root / "reports")
    resume_erasures(repo, store, root / "reports")
    with store.lock, store.db:
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM privacy_erasures WHERE namespace=?", (store.namespace,)
            ).fetchone()[0]
            == 0
        )
        store.db.execute(
            "INSERT INTO privacy_erasures VALUES(?,?,?)",
            (
                "foreign-namespace",
                "project:" + "a" * 32,
                json.dumps({"id": "project:" + "a" * 32, "completed": False}),
            ),
        )
    assert resume_erasures(repo, store, root / "reports")["resumed_erasure_ids"] == []
    assert ProjectService(store).get(project["id"])["title"] == "正在领取"


def test_pending_erasure_rejects_wrong_report_directory_without_marking_complete(
    erasure, monkeypatch
):
    repo, store, job, root = erasure
    project = ProjectService(store).create(PRIVATE, PRIVATE, [job])
    run = completed_run(repo, store, project["id"], job, PRIVATE)
    saved = save_result(run, root / "custom-reports")
    store.save(run["run_id"], saved=saved)
    original = store.invalidate_runs

    def crash(identities):
        original(identities)
        raise RuntimeError("synthetic interrupted erase")

    monkeypatch.setattr(store, "invalidate_runs", crash)
    with pytest.raises(RuntimeError):
        forget_project(repo, store, project["id"], root / "custom-reports")
    assert pending_erasures(store) == 1
    reopened = ResearchStore(store.path, store.namespace)
    try:
        with pytest.raises(ProbeError, match="PRIVACY_REPORT_DIRECTORY_MISMATCH"):
            resume_erasures(repo, reopened, root / "wrong-reports")
        assert pending_erasures(reopened) == 1
        assert Path(saved["json"]).exists()
        resume_erasures(repo, reopened, root / "custom-reports")
        assert pending_erasures(reopened) == 0 and not Path(saved["json"]).exists()
    finally:
        reopened.close()
