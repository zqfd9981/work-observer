"""人工重复关联审核与截图区域引用；不合并或改写原始岗位。"""

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from work_observer.storage.models import Base


class DuplicateReview(Base):
    __tablename__ = "duplicate_reviews"
    __table_args__ = (
        UniqueConstraint("pair_key", "version"),
        Index("ix_duplicate_pair", "pair_key"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    pair_key: Mapped[str]
    version: Mapped[int]
    previous_id: Mapped[str | None] = mapped_column(ForeignKey("duplicate_reviews.id"))
    left_job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    right_job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    decision: Mapped[str]
    reason: Mapped[str] = mapped_column(Text)
    basis: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str]


class ScreenshotRegion(Base):
    __tablename__ = "screenshot_regions"
    __table_args__ = (UniqueConstraint("signature"), Index("ix_region_job", "job_id"))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("import_assets.id"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("job_snapshots.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"))
    image_sha256: Mapped[str]
    document_sha256: Mapped[str]
    content_sha256: Mapped[str]
    bbox: Mapped[list] = mapped_column(JSON)
    start: Mapped[int]
    end: Mapped[int]
    quote: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text)
    selection_method: Mapped[str]
    status: Mapped[str]
    signature: Mapped[str]
    created_at: Mapped[str]
