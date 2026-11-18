"""分层记忆隔离机制验收；资料是合成样例，不代表研究语义质量。"""

import hashlib
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.orm import Session

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.connectors.public_models import PublicDocument
from work_observer.memory.service import MemoryService
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import engine_for, migration_config, upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def layered(tmp_path):
    path = tmp_path / "memory.db"
    upgrade(path)
    repo = Repository(path)
    job = import_jd(
        repo,
        RawArchive(tmp_path / "raw", []),
        ManualJD(
            title="合成岗位", company="合成公司", external_id="a", description="维护 RAG 评估集。"
        ),
    )["job_id"]
    yield MemoryService(repo), repo, job
    repo.close()


def test_project_scope_survives_reopen_without_leaking(layered):
    memory, repo, job = layered
    scoped = memory.create("preference", "重视 RAG 评估", project_id="a" * 32)
    assert scoped["scope"] == "project"
    repo.close()
    reopened = Repository(Path(repo.engine.url.database))
    try:
        service = MemoryService(reopened)
        assert not service.recall("RAG", [job])
        assert not service.recall("RAG", [job], project_id="b" * 32)
        assert service.recall("RAG", [job], project_id="a" * 32) == [scoped]
    finally:
        reopened.close()


def test_conflict_does_not_overwrite_or_guess_and_explicit_resolution(layered):
    memory, _, job = layered
    old = memory.create("preference", "只考虑上海", subject="工作地点")
    new = memory.create("preference", "只考虑北京", subject="工作地点")
    assert new["status"] == "conflict"
    assert len(memory.conflicts()) == 2
    assert not memory.recall("工作地点", [job])
    with pytest.raises(ProbeError, match="MEMORY_NOT_A_CANDIDATE"):
        memory.activate(new["id"])
    with pytest.raises(ProbeError, match="MEMORY_VERSION_NOT_CURRENT"):
        memory.revise(old["id"], "通过改写绕过冲突")
    accepted = memory.resolve(new["id"], "accept")
    assert memory.recall("工作地点", [job]) == [accepted]
    memory.withdraw(new["id"])
    assert not memory.recall("工作地点", [job])  # 旧值不会复活。


def test_conflict_graph_resolution_with_three_candidates(layered):
    memory, _, job = layered
    items = [memory.create("preference", str(i), subject="薪资") for i in range(3)]
    accepted = memory.resolve(items[0]["id"], "accept")
    assert not memory.conflicts()
    assert memory.recall("薪资", [job]) == [accepted]
    assert len([item for item in memory.list(True) if item["status"] == "withdrawn"]) == 2


def test_effective_time_and_nonoverlapping_versions(layered):
    memory, _, job = layered
    before = memory.create(
        "preference",
        "仅限上海",
        subject="地点",
        valid_from="2026-01-01T00:00:00+08:00",
        valid_until="2026-02-01T00:00:00+08:00",
    )
    after = memory.create(
        "preference",
        "接受北京",
        subject="地点",
        valid_from="2026-02-01T00:00:00+08:00",
    )
    assert not memory.conflicts()
    assert memory.recall("地点", [job], at="2026-01-15T00:00:00Z") == [before]
    assert memory.recall("地点", [job], at="2026-02-01T00:00:00+08:00") == [after]
    assert not memory.recall("地点", [job], at="2025-01-01T00:00:00Z")
    for values in (
        {"valid_from": "2026-01-01"},
        {"valid_from": "invalid"},
        {
            "valid_from": "2026-02-01T00:00:00Z",
            "valid_until": "2026-01-01T00:00:00Z",
        },
    ):
        with pytest.raises(ProbeError, match="INVALID_MEMORY_TIME"):
            memory.create("preference", "无效时间", **values)


def test_resolving_overlap_chain_does_not_withdraw_nonoverlapping_future_value(layered):
    memory, _, job = layered
    first = memory.create(
        "preference", "一月偏好", subject="地点", valid_until="2026-02-01T00:00:00Z"
    )
    memory.create(
        "preference",
        "跨月冲突",
        subject="地点",
        valid_from="2026-01-15T00:00:00Z",
        valid_until="2026-02-15T00:00:00Z",
    )
    future = memory.create(
        "preference", "二月偏好", subject="地点", valid_from="2026-02-01T00:00:00Z"
    )
    memory.resolve(first["id"], "accept")
    # 远端冲突项不因选择一月偏好而自动被否决，仍须用户明确审核。
    assert [item["id"] for item in memory.conflicts()] == [future["id"]]
    accepted = memory.resolve(future["id"], "accept")
    assert memory.recall("地点", [job], at="2026-02-03T00:00:00Z") == [accepted]


def test_model_inferred_preferences_and_hypotheses_require_review(layered):
    memory, _, job = layered
    inferred = memory.create("preference", "推测用户喜欢 RAG", origin="agent")
    hypothesis = memory.create("hypothesis", "RAG 岗位或许偏重评估", origin="agent")
    method = memory.create("method", "RAG 研究应补查反例", origin="agent")
    assert not memory.recall("RAG", [job])
    for item in (inferred, hypothesis, method):
        assert item["status"] == "candidate"
        memory.activate(item["id"])
    recalled = memory.recall("RAG", [job])
    assert {item["kind"] for item in recalled} == {"preference", "hypothesis", "method"}
    assert all(item["origin"] == "agent" for item in recalled)
    memory.invalidate_research([])


def public_document(repo, tmp_path, identity, text, observed_at):
    path = tmp_path / f"{identity}.html"
    raw = ("<body>" + text + "</body>").encode()
    path.write_bytes(raw)
    document = PublicDocument(
        id=identity,
        url="https://example.org/business",
        final_url="https://example.org/business",
        publisher="example.org",
        title="合成公开业务资料",
        content_type="text/html",
        path=str(path),
        sha256=hashlib.sha256(raw).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        observed_at=observed_at,
        source_published_at=None,
        extractor_version="test",
    )
    with Session(repo.engine) as session, session.begin():
        session.add(document)
        session.flush()
        return PublicDocumentService._evidence(document)


def test_public_knowledge_revalidates_and_never_proves_job_scope(layered, tmp_path):
    memory, repo, job = layered
    evidence = public_document(
        repo, tmp_path, "c" * 32, "RAG 是公司产品方向。", "2026-01-01T00:00:00Z"
    )
    with pytest.raises(ProbeError, match="MEMORY_SCOPE_VIOLATION"):
        memory.create("knowledge", "该岗位负责 RAG", evidence=evidence, job_id=job)
    candidate = memory.create("knowledge", "公司公开资料提到 RAG 产品", evidence=evidence)
    active = memory.activate(candidate["id"])
    assert memory.recall("RAG", [job]) == [active]
    public_document(repo, tmp_path, "d" * 32, "公司产品已变为数据整理。", "2026-02-01T00:00:00Z")
    assert not memory.recall("RAG", [job])
    assert memory.list()[0]["status"] == "active"  # 保留历史，召回时判定过时。


def test_public_quote_and_file_tampering_rejected(layered, tmp_path):
    memory, repo, _ = layered
    evidence = public_document(repo, tmp_path, "e" * 32, "RAG 产品说明。", "2026-01-01T00:00:00Z")
    with pytest.raises(ProbeError, match="INVALID_MEMORY_EVIDENCE"):
        memory.create("knowledge", "伪造", evidence=[{**evidence[0], "quote": "模型报告断言"}])
    candidate = memory.create("knowledge", "RAG 产品", evidence=evidence)
    (tmp_path / ("e" * 32 + ".html")).write_text("改变文件", encoding="utf-8")
    with pytest.raises(ProbeError, match="MEMORY_SOURCE_INTEGRITY_FAILED"):
        memory.activate(candidate["id"])


def test_forgetting_erases_subject_and_derived_hypothesis(layered):
    memory, _, _ = layered
    item = memory.create("preference", "私有文本", subject="私有主体")
    forgotten = memory.forget(item["id"])
    assert forgotten["forgotten_memory_ids"] == [item["id"]]
    stored = memory.list(True)[0]
    assert stored["subject"] is None
    method = memory.create("method", "派生私有文本", source_run_id="a" * 32)
    assert memory.invalidate_research(["a" * 32])["affected_memory_ids"] == [method["id"]]
    assert all(row["content"] == "[已忘记]" for row in memory.list(True))


def test_additive_upgrade_preserves_old_memory_and_infers_job_scope(tmp_path):
    path = tmp_path / "old.db"
    engine = engine_for(path)
    with engine.begin() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "e8b1f5c4a086")
    engine.dispose()
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO jobs(id,source,source_job_id,first_observed_at,last_observed_at) "
            "VALUES('job','manual','job','2026-01-01','2026-01-01')"
        )
        db.execute(
            "INSERT INTO memory_records(id,root_id,version,kind,content,status,job_id,evidence,"
            "created_at,updated_at) VALUES('old','old',1,'correction','旧明确纠正','active','job',"
            "'[]','2026-01-01','2026-01-01')"
        )
        old_columns = [row[1] for row in db.execute("PRAGMA table_info(memory_records)")]
        before = db.execute("SELECT * FROM memory_records").fetchall()
        db.commit()
    upgrade(path)  # 自带SQLite backup和全部旧列值指纹检查。
    with sqlite3.connect(path) as db:
        selected = ",".join('"' + column + '"' for column in old_columns)
        assert db.execute(f"SELECT {selected} FROM memory_records").fetchall() == before
        assert db.execute(
            "SELECT scope,subject,origin,conflict_ids FROM memory_records"
        ).fetchone() == ("job", None, "user", "[]")
    assert list((tmp_path / "backups").glob("before-upgrade-*/old.db"))
