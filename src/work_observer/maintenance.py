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
CHECKPOINT_TABLES = (
    "research_checkpoints",
    "research_projects",
    "quality_reviews",
    "domain_update_captures",
    "domain_update_reports",
    "privacy_erasures",
    "research_workflows",
    "retrieval_trials",
    "retrieval_trial_events",
)
TRIAL_FIXED_FILES = {
    "corpus.db",
    "manifest.json",
    "suite.json",
    "holdout-attempt.json",
    "holdout-result.json",
    "baseline-aliases.json",
}


def _trial_filename(name):
    return name in TRIAL_FIXED_FILES or bool(re.fullmatch(r"candidate-[a-f0-9]{64}\.json", name))


def _validate_trial_artifacts(directory, *, include_stage=False):
    """只验证新固定布局；不改冻结字节，也不把备份验证当成人审通过。"""
    from work_observer.quality.service import SOURCE_TABLES, digest, load_corpus, load_suite
    from work_observer.tracking.evaluation import validate_aliases

    if directory.is_symlink() or directory.parent.is_symlink() or not directory.is_dir():
        raise ProbeError("INVALID_TRIAL_BACKUP_ARTIFACTS")
    files = [path for path in directory.iterdir() if _trial_filename(path.name)]
    required = {"corpus.db", "manifest.json"}
    if not required <= {path.name for path in files} or not len(files) <= 32:
        raise ProbeError("INVALID_TRIAL_BACKUP_ARTIFACTS")
    decoded = {}
    for path in files:
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > (512_000_000 if path.suffix == ".db" else 16_000_000)
        ):
            raise ProbeError("INVALID_TRIAL_BACKUP_ARTIFACTS")
        if path.suffix == ".json":
            try:
                decoded[path.name] = json.loads(
                    path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys
                )
            except (ValueError, UnicodeError) as exc:
                raise ProbeError("INVALID_TRIAL_BACKUP_ARTIFACTS") from exc
    corpus = load_corpus(directory)
    suite = load_suite(directory)[1] if "suite.json" in decoded else None
    if corpus.get("frozen_table_scope") != "source_only_without_personal_memory_or_access_context":
        raise ProbeError("TRIAL_BACKUP_REQUIRES_NEW_SOURCE_ONLY_CORPUS")
    baseline = validate_aliases(decoded.get("baseline-aliases.json", {}))
    for name, lock in decoded.items():
        if not name.startswith("candidate-"):
            continue
        if (
            not suite
            or not isinstance(lock, dict)
            or set(lock) != {"suite_sha256", "baseline_config_sha256", "candidate_config_sha256"}
            or any(
                not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
                for value in lock.values()
            )
            or lock["suite_sha256"] != suite["suite_sha256"]
            or lock["baseline_config_sha256"] != digest(baseline)
            or name != "candidate-" + digest(lock) + ".json"
        ):
            raise ProbeError("TRIAL_BACKUP_FROZEN_DIGEST_MISMATCH")
    attempt = decoded.get("holdout-attempt.json")
    if "holdout-attempt.json" in decoded:
        if not suite or not isinstance(attempt, dict):
            raise ProbeError("INVALID_TRIAL_BACKUP_ARTIFACTS")
        lock = {
            key: attempt.get(key)
            for key in ("suite_sha256", "baseline_config_sha256", "candidate_config_sha256")
        }
        if decoded.get("candidate-" + digest(lock) + ".json") != lock or not isinstance(
            attempt.get("started_at"), str
        ):
            raise ProbeError("TRIAL_BACKUP_FROZEN_DIGEST_MISMATCH")
    if "holdout-result.json" in decoded:
        report = decoded["holdout-result.json"]
        if not suite or not isinstance(report, dict) or not isinstance(attempt, dict):
            raise ProbeError("INVALID_TRIAL_BACKUP_ARTIFACTS")
        candidate = validate_aliases(report.get("candidate_aliases"))
        lock = {
            "suite_sha256": suite["suite_sha256"],
            "baseline_config_sha256": digest(baseline),
            "candidate_config_sha256": digest(candidate),
        }
        if (
            report.get("corpus_sha256") != corpus["corpus_sha256"]
            or report.get("phase") != "holdout"
            or any(report.get(key) != value for key, value in lock.items())
            or decoded.get("candidate-" + digest(lock) + ".json") != lock
            or any(attempt.get(key) != value for key, value in lock.items())
        ):
            raise ProbeError("TRIAL_BACKUP_FROZEN_DIGEST_MISMATCH")
    with readonly_database(directory / "corpus.db") as db:
        _plain_database(db)
        if db.execute("pragma journal_mode").fetchone()[0] != "delete":
            raise ProbeError("TRIAL_BACKUP_SINGLE_FILE_CORPUS_REQUIRED")
        tables = {
            row[0]
            for row in db.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            )
        }
        if (
            tables != SOURCE_TABLES
            or db.execute("select 1 from jobs where access_context!='{}' limit 1").fetchone()
            or db.execute(
                "select 1 from job_observations where access_context!='{}' limit 1"
            ).fetchone()
            or db.execute("select 1 from source_documents where request!='{}' limit 1").fetchone()
        ):
            raise ProbeError("TRIAL_BACKUP_CONTAINS_NON_SOURCE_CONTEXT")
    stage = (
        "evaluated"
        if "holdout-result.json" in decoded
        else "evaluation_draft"
        if attempt is not None
        else "labeled_draft"
        if suite
        else "frozen_draft"
    )
    names = sorted(path.name for path in files)
    return (names, stage) if include_stage else names


def _backup_trial_artifacts(database, destination, manifest):
    root = database.parent / "quality-trials"
    manifest["trial_bundles"] = []
    manifest["trial_bundle_stages"] = {}
    manifest["legacy_quality_artifacts"] = (
        "not_copied; missing legacy artifacts safely revert trials to baseline"
    )
    if not root.is_dir():
        return
    if root.is_symlink():
        raise ProbeError("INVALID_TRIAL_BACKUP_ARTIFACTS")
    directories = [path for path in root.iterdir() if re.fullmatch(r"[a-f0-9]{32}", path.name)]
    if len(directories) > 100:
        raise ProbeError("TRIAL_BACKUP_BUNDLE_LIMIT_100")
    for directory in sorted(directories):
        if directory.is_symlink() or not directory.is_dir():
            raise ProbeError("INVALID_TRIAL_BACKUP_ARTIFACTS")
        files, stage = _validate_trial_artifacts(directory, include_stage=True)
        target = destination / "quality-trials" / directory.name
        target.mkdir(parents=True)
        for name in files:
            shutil.copyfile(directory / name, target / name)
        _, copied_stage = _validate_trial_artifacts(target, include_stage=True)
        if copied_stage != stage:
            raise ProbeError("TRIAL_BACKUP_STAGE_CHANGED_DURING_COPY")
        manifest["trial_bundles"].append(directory.name)
        manifest["trial_bundle_stages"][directory.name] = stage


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
        checkpoints = database.parent / "checkpoints.db"
        if checkpoints.is_file():
            # 未完成擦除的报告目录必须与本次备份组件一致；只读校验，不改源工作区。
            signature = hashlib.sha256(str(Path(reports_dir).resolve()).encode("utf-8")).hexdigest()
            with readonly_database(checkpoints) as checkpoint_db:
                has_journal = checkpoint_db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='privacy_erasures'"
                ).fetchone()
                if has_journal:
                    for (encoded,) in checkpoint_db.execute(
                        "SELECT record FROM privacy_erasures WHERE namespace=?", (str(database),)
                    ):
                        try:
                            journal = json.loads(encoded)
                        except (ValueError, TypeError) as exc:
                            raise ProbeError("INVALID_BACKUP_CHECKPOINT") from exc
                        if not isinstance(journal, dict):
                            raise ProbeError("INVALID_BACKUP_CHECKPOINT")
                        if (
                            journal.get("completed") is not True
                            and journal.get("reports_directory_sha256") != signature
                        ):
                            raise ProbeError("PRIVACY_REPORT_DIRECTORY_MISMATCH")
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
        if checkpoints.is_file():
            snapshot_database(checkpoints, destination / "checkpoints.db")
            # 同目录可能有其他库的研究，仅备份目标业务库的作用域。
            with closing(sqlite3.connect(destination / "checkpoints.db")) as db:
                with db:
                    tables = {
                        row[0]
                        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    }
                    for table in CHECKPOINT_TABLES:
                        if table in tables:
                            db.execute(
                                f'DELETE FROM "{table}" WHERE namespace != ?', (str(database),)
                            )
                # 删除其他作用域后的副本压实，避免空闲页保留无关会话。
                db.execute("VACUUM")
        for source in Path(reports_dir).glob("*"):
            if source.is_file() and re.fullmatch(r"[a-f0-9]{32}\.(json|md)", source.name):
                target = destination / "reports" / source.name
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(source, target)
                manifest["reports"].append("reports/" + source.name)
        _backup_trial_artifacts(database, destination, manifest)
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
        or re.fullmatch(r"quality-trials/[a-f0-9]{32}/[^/]+", value)
        and _trial_filename(value.rsplit("/", 1)[1])
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
    trial_bundles = manifest.get("trial_bundles", [])
    actual_trial_files = {name for name in files if name.startswith("quality-trials/")}
    if (
        not isinstance(trial_bundles, list)
        or any(
            not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity)
            for identity in trial_bundles
        )
        or len(trial_bundles) != len(set(trial_bundles))
        or len(trial_bundles) > 100
        or {name.split("/")[1] for name in actual_trial_files} != set(trial_bundles)
    ):
        raise ProbeError("INVALID_TRIAL_BACKUP_MANIFEST")
    stages = manifest.get("trial_bundle_stages")
    if stages is not None and (
        not isinstance(stages, dict)
        or set(stages) != set(trial_bundles)
        or any(
            not isinstance(stage, str)
            or stage not in {"frozen_draft", "labeled_draft", "evaluation_draft", "evaluated"}
            for stage in stages.values()
        )
    ):
        raise ProbeError("INVALID_TRIAL_BACKUP_STAGE")
    for identity in trial_bundles:
        directory = bundle / "quality-trials" / identity
        names, stage = _validate_trial_artifacts(directory, include_stage=True)
        expected_trial_files = {f"quality-trials/{identity}/{name}" for name in names}
        if {
            name for name in actual_trial_files if name.startswith(f"quality-trials/{identity}/")
        } != expected_trial_files:
            raise ProbeError("INVALID_TRIAL_BACKUP_MANIFEST")
        if stages is not None and stages.get(identity) != stage:
            raise ProbeError("INVALID_TRIAL_BACKUP_STAGE")
        if stages is None and stage != "evaluated":
            raise ProbeError("INVALID_TRIAL_BACKUP_STAGE")
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
            tables = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in CHECKPOINT_TABLES[1:]:
                if table not in tables:
                    continue
                for namespace, identity, raw in db.execute(
                    f'SELECT namespace,id,record FROM "{table}"'
                ):
                    try:
                        record = json.loads(raw)
                    except (ValueError, TypeError) as exc:
                        raise ProbeError("INVALID_BACKUP_CHECKPOINT") from exc
                    if (
                        namespace != manifest["original_database"]
                        or not isinstance(record, dict)
                        or record.get("id") != identity
                    ):
                        raise ProbeError("INVALID_BACKUP_CHECKPOINT")
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
            tables = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in CHECKPOINT_TABLES:
                if table in tables:
                    db.execute(
                        f'UPDATE "{table}" SET namespace=? WHERE namespace=?',
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
            if "research_projects" in tables:
                for identity, raw in db.execute(
                    "SELECT id,record FROM research_projects"
                ).fetchall():
                    record = json.loads(raw)
                    for step in record.get("steps", []):
                        if step["state"] == "running":
                            step.update(
                                state="interrupted", stop_reason="restored_explicit_resume_required"
                            )
                    db.execute(
                        "UPDATE research_projects SET record=? WHERE id=?",
                        (json.dumps(record, ensure_ascii=False), identity),
                    )
            if "privacy_erasures" in tables:
                for identity, raw in db.execute(
                    "SELECT id,record FROM privacy_erasures"
                ).fetchall():
                    record = json.loads(raw)
                    record["reports_directory_sha256"] = hashlib.sha256(
                        str((destination / "reports").resolve()).encode("utf-8")
                    ).hexdigest()
                    db.execute(
                        "UPDATE privacy_erasures SET record=? WHERE id=?",
                        (json.dumps(record, ensure_ascii=False), identity),
                    )
    return {
        "database": str(destination / "app.db"),
        "reports_dir": str(destination / "reports"),
        "verified_files": len(manifest["files"]),
        "status": "restored_to_new_directory",
        "restored_trial_bundles": len(manifest.get("trial_bundles", [])),
        "restored_trial_bundle_stages": manifest.get("trial_bundle_stages", {}),
        "trial_artifact_note": "冻结包字节不重定位；legacy旧包未复制，缺失时试用保持或回到基线。",
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
