"""使用项目 SQLite 配置，不在日志显示连接配置。"""

from alembic import context

from work_observer.config import Settings
from work_observer.storage.database import engine_for
from work_observer.storage.models import Base


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


provided = context.config.attributes.get("connection")
if provided is not None:
    run(provided)
else:
    engine = engine_for(Settings.load().database_path)
    try:
        with engine.begin() as connection:
            run(connection)
    finally:
        engine.dispose()
