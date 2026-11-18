"""本地任务、显式启用的观察时段和收件箱；不承载来源事实。"""

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from work_observer.storage.models import Base


class WorkTask(Base):
    __tablename__ = "work_tasks"
    __table_args__ = (
        UniqueConstraint("dedupe_key"),
        Index("ix_work_tasks_state_created", "state", "created_at"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str]
    watchset_id: Mapped[str] = mapped_column(ForeignKey("watchsets.id"))
    mode: Mapped[str]
    state: Mapped[str]
    parameters: Mapped[dict] = mapped_column(JSON)
    progress: Mapped[dict] = mapped_column(JSON)
    collection_run_ids: Mapped[list] = mapped_column(JSON)
    result_id: Mapped[str | None] = mapped_column(ForeignKey("collection_runs.id"))
    error_code: Mapped[str | None]
    attempts: Mapped[int]
    dedupe_key: Mapped[str | None]
    created_at: Mapped[str]
    started_at: Mapped[str | None]
    finished_at: Mapped[str | None]


class ObservationSchedule(Base):
    __tablename__ = "observation_schedules"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    watchset_id: Mapped[str] = mapped_column(ForeignKey("watchsets.id"))
    hour: Mapped[int]
    minute: Mapped[int]
    timezone: Mapped[str]
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[str]
    updated_at: Mapped[str]


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("dedupe_key"),
        Index("ix_notifications_state_created", "state", "created_at"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str]
    title: Mapped[str]
    body: Mapped[str] = mapped_column(Text)
    state: Mapped[str]
    related_id: Mapped[str | None]
    dedupe_key: Mapped[str | None]
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str]
    read_at: Mapped[str | None]
    resolved_at: Mapped[str | None]
