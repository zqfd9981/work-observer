"""记忆机制使用隔离模拟材料，不代表真实研究语义验收。"""

import sqlite3

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.service import MemoryService
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import engine_for, migration_config, upgrade
from work_observer.storage.models import MemoryEvent, SourceDocument
from work_observer.storage.repository import Repository


@pytest.fixture
def memory(tmp_path):
    path = tmp_path / "memory.db"
    upgrade(path)
    repository = Repository(path)
    archive = RawArchive(tmp_path / "raw", [])
    a, b = [
        import_jd(
            repository,
            archive,
            ManualJD(
                title=f"模拟岗位 {identifier}",
                company="模拟公司",
                external_id=identifier,
                description="职责：实现 RAG，维护评估集。必备 Python；加分 Docker。",
            ),
        )["job_id"]
        for identifier in ("a", "b")
    ]
    yield MemoryService(repository), repository, archive, a, b
    repository.close()


@pytest.fixture
def research_source(memory):
    _, repository, _, job_id, _ = memory
    path = repository.engine.url.database
    from pathlib import Path

    store = ResearchStore(Path(path).parent / "checkpoints.db", str(Path(path).resolve()))
    repository.bind_research_store(store)
    run = store.create({"question": "合成知识来源"})
    store.save(
        run["id"],
        state="finished",
        result={
            "status": "completed",
            "scope": Catalog(repository).query(job_ids=[job_id]),
            "evidence": Catalog(repository).evidence(job_id),
            "memory_used": [],
        },
    )
    yield run["id"]
    store.close()


def test_user_preference_versions_and_withdrawal_persist(memory):
    service, repository, _, a, _ = memory
    first = service.create("preference", "希望月薪不低于 20000 元")
    second = service.revise(first["id"], "希望月薪不低于 25000 元")
    assert second["previous_id"] == first["id"]
    assert second["root_id"] == first["id"]
    assert second["version"] == 2
    assert service.list() == [second]
    assert {item["status"] for item in service.list(True)} == {"superseded", "active"}
    restored = MemoryService(repository)
    assert restored.recall("这些工作怎么样", [a]) == [second]
    with pytest.raises(ProbeError, match="MEMORY_VERSION_NOT_CURRENT"):
        service.revise(first["id"], "不能修改旧版本")
    service.withdraw(second["id"])
    assert service.withdraw(second["id"])["status"] == "withdrawn"
    assert not restored.recall("这些工作怎么样", [a])
    with Session(repository.engine) as session:
        assert len(session.scalars(select(MemoryEvent)).all()) == 4


def test_correction_scope_and_relevance(memory):
    service, _, _, a, b = memory
    scoped = service.create("correction", "这是实施型工作，不能归为模型训练", job_id=a)
    global_correction = service.create("correction", "RAG 不等于模型训练")
    assert scoped in service.recall("工作任务", [a])
    assert scoped not in service.recall("工作任务", [b])
    assert global_correction not in service.recall("工作任务", [b])
    assert global_correction in service.recall("RAG 要求", [b])


def test_knowledge_candidate_accept_revision_and_recall(memory, research_source):
    service, repository, _, a, b = memory
    evidence = Catalog(repository).evidence(a)
    candidate = service.create(
        "knowledge",
        "该岗位需维护 RAG 评估集",
        job_id=a,
        evidence=evidence,
        source_run_id=research_source,
    )
    assert candidate["status"] == "candidate"
    assert not service.recall("RAG", [a])
    assert (
        service.create(
            "knowledge",
            candidate["content"],
            job_id=a,
            evidence=evidence,
            source_run_id=research_source,
        )["id"]
        == candidate["id"]
    )
    active = service.activate(candidate["id"])
    assert service.recall("RAG", [a]) == [active]
    assert not service.recall("RAG", [b])
    revised = service.revise(candidate["id"], "该岗位承担 RAG 评估任务")
    assert revised["status"] == "candidate"
    assert not service.recall("RAG", [a])
    service.withdraw(revised["id"])
    with pytest.raises(ProbeError, match="MEMORY_NOT_A_CANDIDATE"):
        service.activate(revised["id"])


def test_knowledge_rejects_fabricated_quote_scope_and_source(memory):
    service, repository, _, a, b = memory
    evidence = Catalog(repository).evidence(a)
    with pytest.raises(ProbeError, match="MEMORY_EVIDENCE_REQUIRED"):
        service.create("knowledge", "不能没有来源")
    for change in (
        {"quote": "模型报告说这是真的"},
        {"start": True},
        {"id": "new-id"},
        {"snapshot_id": "missing"},
        {"document_id": "missing"},
    ):
        with pytest.raises(ProbeError, match="INVALID_MEMORY_EVIDENCE"):
            service.create("knowledge", "不能伪造来源", evidence=[{**evidence[0], **change}])
    with pytest.raises(ProbeError, match="MEMORY_SCOPE_VIOLATION"):
        service.create("knowledge", "不能扩大纠正范围", job_id=b, evidence=evidence)
    candidate = service.create("knowledge", "有原文的候选", evidence=evidence)
    with Session(repository.engine) as session:
        document = session.get(SourceDocument, evidence[0]["document_id"])
        from pathlib import Path

        Path(document.path).write_text("文件被改写", encoding="utf-8")
    with pytest.raises(ProbeError, match="MEMORY_SOURCE_INTEGRITY_FAILED"):
        service.activate(candidate["id"])


def test_changed_job_invalidates_default_knowledge_recall(memory):
    service, repository, archive, a, _ = memory
    candidate = service.create(
        "knowledge", "该岗位需要 RAG", job_id=a, evidence=Catalog(repository).evidence(a)
    )
    service.activate(candidate["id"])
    import_jd(
        repository,
        archive,
        ManualJD(
            title="模拟岗位 a",
            company="模拟公司",
            external_id="a",
            description="新职责：仅进行人工资料整理。",
        ),
    )
    assert not service.recall("RAG", [a])
    assert service.list()[0]["status"] == "active"  # 历史知识仍可查看，不改原文。


def test_recall_bounded_and_invalid_user_input(memory):
    service, _, _, a, _ = memory
    for index in range(12):
        service.create("preference", f"明确偏好 {index}")
    assert len(service.recall("研究工作", [a])) == 8
    for kind, content in (("unknown", "内容"), ("preference", " "), ("correction", "x" * 4001)):
        with pytest.raises(ProbeError):
            service.create(kind, content)
    with pytest.raises(ProbeError, match="JOB_NOT_FOUND"):
        service.create("correction", "范围不存在", job_id="missing")


def test_incremental_migration_preserves_all_old_rows(tmp_path):
    path = tmp_path / "upgrade.db"
    engine = engine_for(path)
    with engine.begin() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "e7b4c1a20618")
    engine.dispose()
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO jobs(id,source,source_job_id,first_observed_at,last_observed_at,title) "
            "VALUES('a','manual','a','2026-11-18','2026-11-18','模拟旧资料')"
        )
        tables = [
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0] != "alembic_version"
        ]
        before = {
            name: db.execute(f'SELECT * FROM "{name}" ORDER BY id').fetchall() for name in tables
        }
        db.commit()
        backup = tmp_path / "backup.db"
        with sqlite3.connect(backup) as target:
            db.backup(target)
    upgrade(path)
    upgrade(path)
    with sqlite3.connect(path) as db:
        assert before == {
            name: db.execute(f'SELECT * FROM "{name}" ORDER BY id').fetchall() for name in tables
        }
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            ScriptDirectory.from_config(migration_config()).get_current_head()
        )
