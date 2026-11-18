"""公开网页权威归档索引，与招聘来源及研究派生结果分开。"""

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from work_observer.storage.models import Base


class PublicDocument(Base):
    __tablename__ = "public_documents"
    __table_args__ = (Index("ix_public_documents_url_time", "url", "observed_at"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    url: Mapped[str]
    final_url: Mapped[str]
    publisher: Mapped[str]
    title: Mapped[str]
    content_type: Mapped[str]
    path: Mapped[str]
    sha256: Mapped[str]
    text_sha256: Mapped[str]
    text: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[str]
    source_published_at: Mapped[str | None]
    extractor_version: Mapped[str]
