"""备份/恢复和演示使用临时合成资料，不读取正式库或真实密钥。"""

import asyncio
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.connectors.public_models import PublicDocument
from work_observer.demo import create_demo
from work_observer.maintenance import (
    backup_workspace,
    diagnose,
    file_sha,
    restore_workspace,
    snapshot_database,
)
from work_observer.reports.results import read_result, save_result
from work_observer.research.agent import research
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.locks import exclusive
from work_observer.storage.models import CollectionRun, Job, JobSnapshot, SourceDocument
from work_observer.storage.repository import Repository


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "original"
    result = create_demo(root)
    database = Path(result["database"])
    repository = Repository(database)
    public_path = root / "public.html"
    public_path.write_text("<p>合成公开业务说明。</p>", encoding="utf-8")
    text = "合成公开业务说明。"
    with Session(repository.engine) as session, session.begin():
        session.add(
            PublicDocument(
                id="c" * 32,
                url="https://example.com/product",
                final_url="https://example.com/product",
                publisher="example.com",
                title="合成产品资料",
                content_type="text/html",
                path=str(public_path),
                sha256=file_sha(public_path),
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                text=text,
                observed_at="2026-11-18T00:00:00+00:00",
                source_published_at=None,
                extractor_version="synthetic-test",
            )
        )
    settings = Settings(database_path=database)
    offline = asyncio.run(research(repository, "整理合成资料证据", settings, offline=True))
    report = save_result(offline, root / "reports")
    (root / ".env").write_text("PRIVATE_TEST_SENTINEL_DO_NOT_COPY", encoding="utf-8")
    store = ResearchStore(root / "checkpoints.db", str(database))
    record = store.create({"question": "未完成的合成问题"})
    store.checkpoint(record["id"], {"version": 1, "pending_since": None, "synthetic": True})
    store.close()
    other = ResearchStore(root / "checkpoints.db", "another-database-namespace")
    other.create({"question": "其他库不能泄漏"})
    other.close()
    yield root, database, repository, report["report_id"], record["id"]
    repository.close()


def make_backup(workspace, tmp_path):
    root, database, _, _, _ = workspace
    bundle = tmp_path / "bundle"
    backup_workspace(database, bundle, root / "reports")
    return bundle


def manifest(bundle):
    return json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))


def write_manifest(bundle, value):
    (bundle / "manifest.json").write_text(json.dumps(value), encoding="utf-8")


def test_backup_restore_rebases_all_archives_reports_and_checkpoint_namespace(workspace, tmp_path):
    _, database, _, report_id, record_id = workspace
    bundle = make_backup(workspace, tmp_path)
    payload = manifest(bundle)
    assert {item["table"] for item in payload["documents"]} == {
        "source_documents",
        "public_documents",
    }
    assert "app.db" in payload["files"] and "checkpoints.db" in payload["files"]
    assert not any(".env" in item for item in payload["files"])
    assert not any(name.endswith(("-wal", "-shm")) for name in payload["files"])
    destination = tmp_path / "restored"
    restored = restore_workspace(bundle, destination)
    assert restored["status"] == "restored_to_new_directory"
    repository = Repository(Path(restored["database"]))
    try:
        assert repository.counts()["jobs"] == 4
        with Session(repository.engine) as session:
            for document in session.scalars(select(SourceDocument)):
                assert Path(document.path).is_relative_to(destination)
                assert Catalog(repository).document(document.id)["integrity"] == "verified"
        assert (
            PublicDocumentService(repository, destination / "unused").document("c" * 32)[
                "integrity"
            ]
            == "verified"
        )
        assert read_result(report_id, Path(restored["reports_dir"]))["status"] == "evidence_only"
        store = ResearchStore(destination / "checkpoints.db", str(destination / "app.db"))
        assert len(store.list()) == 2 and store.get(record_id)["state"] == "interrupted"
        assert sum(row["state"] == "finished" for row in store.list()) == 1
        assert store.load_checkpoint(record_id)["synthetic"] is True
        store.close()
        with closing(sqlite3.connect(destination / "checkpoints.db")) as db:
            assert db.execute("SELECT DISTINCT namespace FROM research_checkpoints").fetchall() == [
                (str(destination / "app.db"),)
            ]
    finally:
        repository.close()
    assert database.is_file()  # 恢复只创建新目录。


def test_sqlite_backup_includes_committed_wal_and_never_overwrites(tmp_path):
    source, target = tmp_path / "wal.db", tmp_path / "snapshot.db"
    with closing(sqlite3.connect(source)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE wal_probe(id INTEGER PRIMARY KEY,value TEXT)")
        writer.execute("INSERT INTO wal_probe VALUES(1,'committed-in-wal')")
        writer.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        snapshot_database(source, target)
        with closing(sqlite3.connect(target)) as snapshot:
            assert (
                snapshot.execute("SELECT value FROM wal_probe").fetchone()[0] == "committed-in-wal"
            )
        before = file_sha(target)
        with pytest.raises(ProbeError, match="BACKUP_DESTINATION_EXISTS"):
            snapshot_database(source, target)
        assert file_sha(target) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_app",
        "missing_document",
        "wrong_document_table",
        "wrong_document_file",
        "duplicate_document",
        "untracked_report",
        "absolute",
        "traversal",
        "windows_drive",
        "backslash",
        "executable",
    ],
)
def test_untrusted_manifest_rejected_before_creating_destination(workspace, tmp_path, mutation):
    bundle = make_backup(workspace, tmp_path)
    value = manifest(bundle)
    if mutation == "missing_app":
        value["files"].pop("app.db")
    elif mutation == "missing_document":
        value["documents"].pop()
    elif mutation == "wrong_document_table":
        value["documents"][0]["table"] = 'source_documents"; DROP TABLE jobs;--'
    elif mutation == "wrong_document_file":
        value["documents"][0]["file"] = "app.db"
    elif mutation == "duplicate_document":
        value["documents"].append(value["documents"][0])
    elif mutation == "untracked_report":
        value["reports"] = []
    else:
        relative = {
            "absolute": str(bundle / "app.db"),
            "traversal": "../app.db",
            "windows_drive": "C:/outside/app.db",
            "backslash": "raw\\file.json",
            "executable": "startup.py",
        }[mutation]
        value["files"][relative] = value["files"]["app.db"]
    original_hash = file_sha(bundle / "app.db")
    write_manifest(bundle, value)
    destination = tmp_path / "rejected"
    with pytest.raises(ProbeError):
        restore_workspace(bundle, destination)
    assert not destination.exists()
    assert file_sha(bundle / "app.db") == original_hash


def test_changed_archive_and_database_trigger_are_rejected(workspace, tmp_path):
    bundle = make_backup(workspace, tmp_path)
    value = manifest(bundle)
    raw = bundle / value["documents"][0]["file"]
    original = raw.read_bytes()
    raw.write_bytes(b"tampered")
    with pytest.raises(ProbeError, match="BACKUP_FILE_INTEGRITY_FAILED"):
        restore_workspace(bundle, tmp_path / "changed-raw")
    raw.write_bytes(original)
    with closing(sqlite3.connect(bundle / "app.db")) as db, db:
        db.execute(
            "CREATE TRIGGER unsafe_restore AFTER UPDATE OF path ON source_documents "
            "BEGIN DELETE FROM jobs; END"
        )
    value["files"]["app.db"] = file_sha(bundle / "app.db")
    write_manifest(bundle, value)
    with pytest.raises(ProbeError, match="UNSAFE_BACKUP_DATABASE"):
        restore_workspace(bundle, tmp_path / "unsafe-db")
    assert not (tmp_path / "unsafe-db").exists()


def test_mixed_checkpoint_namespace_and_duplicate_manifest_keys_are_rejected(workspace, tmp_path):
    bundle = make_backup(workspace, tmp_path)
    value = manifest(bundle)
    with closing(sqlite3.connect(bundle / "checkpoints.db")) as db, db:
        db.execute("UPDATE research_checkpoints SET namespace='unrelated-private-workspace'")
    value["files"]["checkpoints.db"] = file_sha(bundle / "checkpoints.db")
    write_manifest(bundle, value)
    with pytest.raises(ProbeError, match="INVALID_BACKUP_CHECKPOINT"):
        restore_workspace(bundle, tmp_path / "mixed-namespace")
    (bundle / "manifest.json").write_text('{"version":1,"version":1}', encoding="utf-8")
    with pytest.raises(ProbeError, match="INVALID_BACKUP_MANIFEST"):
        restore_workspace(bundle, tmp_path / "duplicate-keys")


def test_backup_and_restore_do_not_overwrite_or_run_while_collection_active(workspace, tmp_path):
    root, database, _, _, _ = workspace
    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ProbeError, match="BACKUP_DESTINATION_EXISTS"):
        backup_workspace(database, existing, root / "reports")
    bundle = make_backup(workspace, tmp_path)
    with pytest.raises(ProbeError, match="RESTORE_DESTINATION_EXISTS"):
        restore_workspace(bundle, existing)
    assert sentinel.read_text() == "keep"
    with exclusive(database, "collection"):
        with pytest.raises(ProbeError, match="DATABASE_IN_USE"):
            backup_workspace(database, tmp_path / "busy-backup", root / "reports")
    assert not (tmp_path / "busy-backup").exists()


def test_demo_is_synthetic_four_jobs_with_first_job_two_versions_and_zero_network(
    tmp_path, monkeypatch
):
    def no_network(*args, **kwargs):
        raise AssertionError("合成演示不得访问网络")

    monkeypatch.setattr("httpx.AsyncClient", no_network)
    monkeypatch.setattr("work_observer.connectors.mcp_probe.connect", no_network)
    result = create_demo(tmp_path / "demo")
    assert (
        result["jobs"] == 4 and result["network_calls"] == 0 and result["data_kind"] == "synthetic"
    )
    repo = Repository(Path(result["database"]))
    try:
        with Session(repo.engine) as session:
            assert session.scalar(select(func.count()).select_from(Job)) == 4
            assert session.scalar(select(func.count()).select_from(JobSnapshot)) == 5
            assert (
                sorted(
                    session.execute(
                        select(JobSnapshot.job_id, func.count()).group_by(JobSnapshot.job_id)
                    ).all(),
                    key=lambda item: item[1],
                )[-1][1]
                == 2
            )
            assert all("合成" in row.title for row in session.scalars(select(Job)))
            assert all(
                row.provenance["data_kind"] == "synthetic"
                for row in session.scalars(select(SourceDocument))
            )
            assert {row.mode for row in session.scalars(select(CollectionRun))} == {"manual"}
        assert (
            diagnose(
                Settings(
                    database_path=Path(result["database"]), mcp_config=tmp_path / "missing.toml"
                )
            )["network_checks"]
            == 0
        )
    finally:
        repo.close()
    with pytest.raises(ProbeError, match="DEMO_DESTINATION_EXISTS"):
        create_demo(tmp_path / "demo")


def test_diagnose_does_not_create_a_missing_database(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(ProbeError, match="DATABASE_NOT_FOUND"):
        diagnose(Settings(database_path=path))
    assert not path.exists()


def test_import_image_asset_original_bytes_are_preserved_and_rebased(workspace, tmp_path):
    """这里只验证模拟PNG字节的归档，不声称验证OCR或图片模型。"""
    root, database, _, _, _ = workspace
    image = root / "synthetic-screen.png"
    original = b"\x89PNG\r\n\x1a\nsynthetic-backup-asset-only"
    image.write_bytes(original)
    sha = file_sha(image)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "INSERT INTO import_assets(id,mime,path,sha256,size,created_at,data_kind,"
            "extraction_status,extractor_model) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "d" * 32,
                "image/png",
                str(image),
                sha,
                len(original),
                "2026-11-19T00:00:00+00:00",
                "synthetic",
                "pending",
                None,
            ),
        )
    bundle = make_backup(workspace, tmp_path)
    assert any(item["table"] == "import_assets" for item in manifest(bundle)["documents"])
    image.write_bytes(b"original-location-is-no-longer-authoritative")
    destination = tmp_path / "image-restored"
    restore_workspace(bundle, destination)
    with closing(sqlite3.connect(destination / "app.db")) as db:
        path, saved_sha, size, mime = db.execute(
            "SELECT path,sha256,size,mime FROM import_assets WHERE id=?",
            ("d" * 32,),
        ).fetchone()
    assert Path(path).is_relative_to(destination)
    assert Path(path).read_bytes() == original
    assert file_sha(Path(path)) == saved_sha == sha
    assert size == len(original) and mime == "image/png"
