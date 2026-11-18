"""领域定义版本与研究关系，均为派生记录而非来源事实。"""

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from work_observer.storage.models import Base


class DomainDefinition(Base):
    __tablename__ = "domain_definitions"
    __table_args__ = (
        UniqueConstraint("domain_key", "version"),
        Index("ix_domain_status", "status", "domain_key"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    domain_key: Mapped[str]
    version: Mapped[int]
    previous_id: Mapped[str | None] = mapped_column(ForeignKey("domain_definitions.id"))
    name: Mapped[str]
    definition: Mapped[str] = mapped_column(Text)
    inclusion: Mapped[str] = mapped_column(Text)
    exclusion: Mapped[str] = mapped_column(Text)
    status: Mapped[str]
    change_kind: Mapped[str]
    related_ids: Mapped[list] = mapped_column(JSON)
    review_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str]
    reviewed_at: Mapped[str | None]


class WorkRelation(Base):
    __tablename__ = "work_relations"
    __table_args__ = (Index("ix_work_relation_domain_status", "domain_id", "status"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    domain_id: Mapped[str] = mapped_column(ForeignKey("domain_definitions.id"))
    source_kind: Mapped[str]
    source_text: Mapped[str]
    target_kind: Mapped[str]
    target_text: Mapped[str]
    predicate: Mapped[str]
    scope: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[list] = mapped_column(JSON)
    counterevidence: Mapped[list] = mapped_column(JSON)
    conflict_ids: Mapped[list] = mapped_column(JSON)
    status: Mapped[str]
    review_reason: Mapped[str | None] = mapped_column(Text)
    source_run_id: Mapped[str | None]
    created_at: Mapped[str]
    reviewed_at: Mapped[str | None]
