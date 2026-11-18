"""离线完整备份/恢复与本地诊断；备份不包含环境密钥。"""

import hashlib
import json
import re
import shutil
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.storage.database import row_fingerprints
from work_observer.storage.locks import exclusive

ARCHIVE_TABLES = ("source_documents", "public_documents", "import_assets")


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def readonly_database(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA query_only=ON")
        yield db


def snapshot_database(source, target):
    source, target = Path(source), Path(target)
    if not source.is_file():
        raise ProbeError("DATABASE_NOT_FOUND")
    if target.exists():
        raise ProbeError("BACKUP_DESTINATION_EXISTS")
    with readonly_database(source) as db, closing(sqlite3.connect(target)) as backup:
        before = row_fingerprints(db)
        db.backup(backup)
        # 将副本变成独立单文件，不能把短暂的WAL/SHM边车列进可恢复清单。
        backup.execute("PRAGMA journal_mode=DELETE")
        if (
            row_fingerprints(backup) != before
            or backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
        ):
            raise ProbeError("BACKUP_VERIFICATION_FAILED")


def backup_workspace(database, destination, reports_dir=Path("reports")):
    database, destination = Path(database).resolve(), Path(destination).resolve()
    if not database.is_file():
        raise ProbeError("DATABASE_NOT_FOUND")
    if destination.exists():
        raise ProbeError("BACKUP_DESTINATION_EXISTS")
    with exclusive(database, "serve"), exclusive(database), exclusive(database, "collection"):
        destination.mkdir(parents=True)
        snapshot_database(database, destination / "app.db")
        manifest = {
            "version": 1,
            "created_at": now(),
            "original_database": str(database),
            "files": {},
            "documents": [],
            "reports": [],
        }
        with readonly_database(destination / "app.db") as db:
            tables = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in ARCHIVE_TABLES:
                if table not in tables:
                    continue
                for identity, value, sha in db.execute(f'SELECT id,path,sha256 FROM "{table}"'):
                    source = Path(value)
                    if not source.is_file() or file_sha(source) != sha:
                        raise ProbeError("SOURCE_ARCHIVE_INTEGRITY_FAILED")
                    relative = f"raw/{sha}.json"
                    target = destination / relative
                    target.parent.mkdir(exist_ok=True)
                    if not target.exists():
                        shutil.copyfile(source, target)
                    manifest["documents"].append({"table": table, "id": identity, "file": relative})
        checkpoints = database.parent / "checkpoints.db"
        if checkpoints.is_file():
            snapshot_database(checkpoints, destination / "checkpoints.db")
            # 同目录可能有其他库的研究，仅备份目标业务库的作用域。
            with closing(sqlite3.connect(destination / "checkpoints.db")) as db, db:
                db.execute(
                    "DELETE FROM research_checkpoints WHERE namespace != ?", (str(database),)
                )
        for source in Path(reports_dir).glob("*"):
            if source.is_file() and re.fullmatch(r"[a-f0-9]{32}\.(json|md)", source.name):
                target = destination / "reports" / source.name
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(source, target)
                manifest["reports"].append("reports/" + source.name)
        manifest["files"] = {
            str(path.relative_to(destination)).replace("\\", "/"): file_sha(path)
            for path in destination.rglob("*")
            if path.is_file()
        }
        (destination / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return {
        "backup": str(destination),
        "verified_files": len(manifest["files"]),
        "note": "包含私有原始资料与研究，不能当作公开演示包分发；不含.env和认证配置。",
    }


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProbeError("INVALID_BACKUP_MANIFEST")
        result[key] = value
    return result


def _relative_file(value):
    """包内路径仅限固定布局，拒绝绝对路径、跨盘、别名和可执行文件。"""
    if not isinstance(value, str) or not (
        value in {"app.db", "checkpoints.db"}
        or re.fullmatch(r"raw/[a-f0-9]{64}\.json", value)
        or re.fullmatch(r"reports/[a-f0-9]{32}\.(json|md)", value)
    ):
        raise ProbeError("INVALID_BACKUP_PATH")
    return value


def _plain_database(db):
    # 备份包的数据库也属于不可信输入，不执行其中的触发器/视图/虚拟表。
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') "
        "OR upper(ltrim(sql)) LIKE 'CREATE VIRTUAL TABLE%' LIMIT 1"
    ).fetchone():
        raise ProbeError("UNSAFE_BACKUP_DATABASE")
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ProbeError("BACKUP_VERIFICATION_FAILED")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ProbeError("RESTORED_FOREIGN_KEY_CHECK_FAILED")


def _validated_manifest(bundle):
    path = bundle / "manifest.json"
    if not path.is_file() or path.stat().st_size > 16_000_000:
        raise ProbeError("INVALID_BACKUP_MANIFEST")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError) as exc:
        raise ProbeError("INVALID_BACKUP_MANIFEST") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != 1
        or not isinstance(manifest.get("files"), dict)
        or not isinstance(manifest.get("documents"), list)
        or not isinstance(manifest.get("reports"), list)
        or not isinstance(manifest.get("original_database"), str)
        or not 1 <= len(manifest["original_database"]) <= 4000
        or "app.db" not in manifest["files"]
    ):
        raise ProbeError("INVALID_BACKUP_MANIFEST")
    files = manifest["files"]
    for relative, sha in files.items():
        _relative_file(relative)
        source = (bundle / relative).resolve()
        if (
            not isinstance(sha, str)
            or not re.fullmatch(r"[a-f0-9]{64}", sha)
            or not source.is_relative_to(bundle)
            or not source.is_file()
            or file_sha(source) != sha
        ):
            raise ProbeError("BACKUP_FILE_INTEGRITY_FAILED")
    expected_reports = {name for name in files if name.startswith("reports/")}
    if (
        any(not isinstance(name, str) for name in manifest["reports"])
        or len(manifest["reports"]) != len(set(manifest["reports"]))
        or set(manifest["reports"]) != expected_reports
    ):
        raise ProbeError("INVALID_BACKUP_MANIFEST")
    with readonly_database(bundle / "app.db") as db:
        _plain_database(db)
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {
            "alembic_version",
            "jobs",
            "job_snapshots",
            "job_observations",
            "source_documents",
        }.issubset(tables):
            raise ProbeError("INVALID_BACKUP_DATABASE")
        expected = {}
        for table in ARCHIVE_TABLES:
            if table in tables:
                for identity, sha in db.execute(f'SELECT id,sha256 FROM "{table}"'):
                    expected[(table, identity)] = sha
        found = {}
        for document in manifest["documents"]:
            if (
                not isinstance(document, dict)
                or set(document) != {"table", "id", "file"}
                or not isinstance(document["table"], str)
                or not isinstance(document["id"], str)
                or not isinstance(document["file"], str)
            ):
                raise ProbeError("INVALID_BACKUP_MANIFEST")
            key = document["table"], document["id"]
            relative = document["file"]
            if (
                key not in expected
                or key in found
                or not relative.startswith("raw/")
                or relative not in files
                or files[relative] != expected[key]
                or relative != f"raw/{expected[key]}.json"
            ):
                raise ProbeError("INVALID_BACKUP_MANIFEST")
            found[key] = relative
        if set(found) != set(expected) or {value for value in found.values()} != {
            name for name in files if name.startswith("raw/")
        }:
            raise ProbeError("INVALID_BACKUP_MANIFEST")
    if "checkpoints.db" in files:
        with readonly_database(bundle / "checkpoints.db") as db:
            _plain_database(db)
            for namespace, identity, raw in db.execute(
                "SELECT namespace,id,record FROM research_checkpoints"
            ):
                try:
                    record = json.loads(raw)
                except (ValueError, TypeError) as exc:
                    raise ProbeError("INVALID_BACKUP_CHECKPOINT") from exc
                if (
                    namespace != manifest["original_database"]
                    or not isinstance(record, dict)
                    or record.get("id") != identity
                    or record.get("state")
                    not in {"running", "finished", "interrupted", "failed", "invalidated"}
                ):
                    raise ProbeError("INVALID_BACKUP_CHECKPOINT")
    return manifest


def restore_workspace(bundle, destination):
    """只恢复到一个全新目录；不覆盖已有工作目录。"""
    bundle, destination = Path(bundle).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ProbeError("RESTORE_DESTINATION_EXISTS")
    manifest = _validated_manifest(bundle)
    destination.mkdir(parents=True)
    for relative in manifest["files"]:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundle / relative, target)
    with closing(sqlite3.connect(destination / "app.db")) as db, db:
        db.execute("PRAGMA trusted_schema=OFF")
        for document in manifest["documents"]:
            table = document["table"]
            db.execute(
                f'UPDATE "{table}" SET path=? WHERE id=?',
                (str((destination / document["file"]).resolve()), document["id"]),
            )
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ProbeError("RESTORED_FOREIGN_KEY_CHECK_FAILED")
    checkpoints = destination / "checkpoints.db"
    if checkpoints.is_file():
        with closing(sqlite3.connect(checkpoints)) as db, db:
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute(
                "UPDATE research_checkpoints SET namespace=? WHERE namespace=?",
                (str((destination / "app.db").resolve()), manifest["original_database"]),
            )
            # 未完成任务不自动重启，用户查看后才能继续消费预算。
            for identity, raw in db.execute(
                "SELECT id,record FROM research_checkpoints"
            ).fetchall():
                record = json.loads(raw)
                if record["state"] == "running":
                    record["state"] = "interrupted"
                    db.execute(
                        "UPDATE research_checkpoints SET record=? WHERE id=?",
                        (json.dumps(record, ensure_ascii=False), identity),
                    )
    return {
        "database": str(destination / "app.db"),
        "reports_dir": str(destination / "reports"),
        "verified_files": len(manifest["files"]),
        "status": "restored_to_new_directory",
    }


def diagnose(settings):
    from work_observer.connectors.source_status import source_status
    from work_observer.storage.repository import Repository

    if not settings.database_path.is_file():
        raise ProbeError("DATABASE_NOT_FOUND")
    with readonly_database(settings.database_path) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = not db.execute("PRAGMA foreign_key_check").fetchall()
        revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    repo = Repository(settings.database_path)
    try:
        result = {
            "status": "ready" if integrity == "ok" and foreign_keys else "degraded",
            "integrity": integrity,
            "foreign_keys_valid": foreign_keys,
            "schema_revision": revision,
            "counts": repo.counts(),
            "model_configured": bool(
                settings.model_name
                and settings.model_base_url
                and settings.model_api_key.get_secret_value()
            ),
            "network_checks": 0,
        }
        try:
            result["source"] = source_status(settings.load_mcp())
        except Exception:
            result["source"] = {"state": "unconfigured", "checked": "local_only"}
        return result
    finally:
        repo.close()
