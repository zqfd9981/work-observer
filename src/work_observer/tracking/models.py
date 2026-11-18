"""检索策略、固定评测与显式启用/回退事件。"""

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from work_observer.storage.models import Base


class RetrievalStrategy(Base):
    __tablename__ = "retrieval_strategies"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    config: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str]
    created_at: Mapped[str]


class StrategyExperiment(Base):
    __tablename__ = "strategy_experiments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("retrieval_strategies.id"), index=True)
    suite_version: Mapped[str]
    contract: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str]
    created_at: Mapped[str]


class StrategyEvent(Base):
    __tablename__ = "strategy_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("retrieval_strategies.id"))
    previous_strategy_id: Mapped[str | None] = mapped_column(ForeignKey("retrieval_strategies.id"))
    action: Mapped[str]
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str]
