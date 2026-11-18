"""用户明确上传的截图原始字节索引，不把视觉抽取当作事实。"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from work_observer.storage.models import Base


class ImportAsset(Base):
    __tablename__ = "import_assets"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    mime: Mapped[str]
    path: Mapped[str]
    sha256: Mapped[str]
    size: Mapped[int]
    created_at: Mapped[str]
    data_kind: Mapped[str]
    extraction_status: Mapped[str]
    extractor_model: Mapped[str | None]
