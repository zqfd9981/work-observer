"""SQLite 连接与显式版本迁移；外部调用不持有事务。"""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import URL, create_engine, event, inspect

from work_observer.connectors.mcp_probe import ProbeError

ROOT = Path(__file__).resolve().parents[3]


def engine_for(path: Path):
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite", database=str(path)),
        connect_args={"autocommit": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def configure(dbapi, _):
        previous = dbapi.autocommit
        dbapi.autocommit = True
        try:
            dbapi.execute("PRAGMA foreign_keys=ON")
            dbapi.execute("PRAGMA busy_timeout=5000")
            dbapi.execute("PRAGMA journal_mode=WAL")
        finally:
            dbapi.autocommit = previous

    return engine


def migration_config():
    migrations = ROOT / "migrations"
    if not migrations.is_dir():
        migrations = Path(__file__).resolve().parents[1] / "_migrations"
    config = Config()
    config.set_main_option("script_location", str(migrations))
    return config


def upgrade(path: Path):
    path = Path(path)
    before = None
    if path.is_file() and path.stat().st_size:
        with sqlite3.connect(path) as source:
            before = row_fingerprints(source)
            backup_dir = (
                path.parent
                / "backups"
                / (
                    "before-upgrade-"
                    + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                    + "-"
                    + uuid4().hex[:8]
                )
            )
            backup_dir.mkdir(parents=True)
            with sqlite3.connect(backup_dir / path.name) as backup:
                source.backup(backup)
                if (
                    row_fingerprints(backup) != before
                    or backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                ):
                    raise ProbeError("DATABASE_BACKUP_VERIFICATION_FAILED")
    engine = engine_for(path)
    try:
        with engine.begin() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            if before is not None:
                # 指纹只比较升级前的所有业务列；迁移版本号变化属预期。
                dbapi = connection.connection.driver_connection
                if row_fingerprints(dbapi, before) != before:
                    raise ProbeError("DATABASE_EXISTING_ROWS_CHANGED")
    finally:
        engine.dispose()


def row_fingerprints(connection, template=None):
    tables = template or {
        row[0]: None
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        )
    }
    result = {}
    for name, spec in tables.items():
        escaped = name.replace('"', '""')
        columns = (
            spec["columns"]
            if spec
            else [row[1] for row in connection.execute(f'PRAGMA table_info("{escaped}")')]
        )
        selected = ",".join('"' + column.replace('"', '""') + '"' for column in columns)
        rows = sorted(
            json.dumps(list(row), ensure_ascii=False, default=str)
            for row in connection.execute(f'SELECT {selected} FROM "{escaped}"')
        )
        result[name] = {
            "columns": columns,
            "count": len(rows),
            "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest(),
        }
    return result


def require_schema(engine):
    from work_observer.storage.models import Base

    if not set(Base.metadata.tables).issubset(inspect(engine).get_table_names()):
        raise ProbeError("DATABASE_NOT_INITIALIZED")
    with engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    if revision != ScriptDirectory.from_config(migration_config()).get_current_head():
        raise ProbeError("DATABASE_MIGRATION_REQUIRED")
