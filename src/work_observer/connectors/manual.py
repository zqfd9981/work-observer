"""人工 JD 导入：独立来源身份，不覆盖平台原文，不发网络请求。"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.collection.contracts import Capture, WatchsetSpec, digest, now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.evidence import redact
from work_observer.storage.models import Job


class ManualJD(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=100000)
    external_id: str | None = Field(default=None, min_length=1, max_length=200)
    related_job_id: str | None = None
    city: str | None = None
    salary: str | None = None
    education: str | None = None
    experience: str | None = None
    job_url: str | None = None
    source_published_at: str | None = None
    source_published_raw: str | None = None
    note: str | None = None
    data_kind: Literal["user_provided", "synthetic"] = "user_provided"
    import_asset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    ocr_reviewed: bool = False

    @model_validator(mode="after")
    def image_review(self):
        if bool(self.import_asset_id) != self.ocr_reviewed:
            raise ValueError("截图需要原图关联和明确人工核对；没有原图不能声明OCR核对")
        return self

    @field_validator("description")
    @classmethod
    def body_required(cls, value):
        if value.startswith(("https://", "http://")) and not any(char.isspace() for char in value):
            raise ValueError("链接不等于正文，请粘贴完整 JD")
        return value

    @field_validator("source_published_at")
    @classmethod
    def publication(cls, value):
        from work_observer.storage.projection import published_v1

        if value is not None and not published_v1(value):
            raise ValueError("来源发布时间必须明确且含时区")
        return published_v1(value) if value else None

    @field_validator("job_url")
    @classmethod
    def clean_url(cls, value):
        from urllib.parse import urlsplit, urlunsplit

        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
            raise ValueError("仅接受无凭据的 HTTP(S) 链接")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def load_manual(path: Path, *, title=None, company=None, **overrides):
    if path.stat().st_size > 512000:
        raise ProbeError("IMPORT_TOO_LARGE")
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text) if path.suffix.lower() == ".json" else {"description": text}
    if not isinstance(data, dict):
        raise ProbeError("IMPORT_EXPECTS_ONE_OBJECT")
    data.update(
        {
            key: value
            for key, value in {"title": title, "company": company, **overrides}.items()
            if value is not None
        }
    )
    return ManualJD.model_validate(data)


def import_jd(repository, archive, jd: ManualJD):
    asset = None
    if jd.import_asset_id:
        from work_observer.connectors.import_drafts import ImportDraftService

        asset, _ = ImportDraftService(repository, Path(".")).read(jd.import_asset_id)
        if asset["data_kind"] != jd.data_kind:
            raise ProbeError("IMPORT_ASSET_DATA_KIND_MISMATCH")
    values = jd.model_dump(exclude_none=True)
    if not asset:
        values.pop("ocr_reviewed", None)  # 保持既有无图片、无显式ID导入的内容身份。
    data = redact(values, archive.secrets)
    identity = jd.external_id or digest(data)
    if jd.related_job_id:
        repository.job(jd.related_job_id)  # 只关联，不用人工内容改写原岗位。
    with Session(repository.engine) as session:
        existing = session.scalar(
            select(Job).where(Job.source == "manual", Job.source_job_id == identity)
        )
        if existing and (existing.title != jd.title or existing.company_name_raw != jd.company):
            raise ProbeError("MANUAL_IDENTITY_CONFLICT")
    record = {
        key: value
        for key, value in data.items()
        if key not in {"external_id", "related_job_id", "note", "import_asset_id", "ocr_reviewed"}
    }
    record["job_id"] = identity
    stamp = now()
    run_id = repository.begin_run(
        "manual-jd",
        WatchsetSpec(source="manual", query="用户补录", city=jd.city or "未知"),
        "manual",
        kind="manual_import",
        transport="manual",
    )
    try:
        capture = archive.sanitize(
            Capture(
                raw={"manual_jd": data},
                request={"operation": "manual_import"},
                observed_at=stamp,
                provenance={
                    "origin": "manual",
                    "transport": "manual",
                    "related_job_id": jd.related_job_id,
                    "data_kind": jd.data_kind,
                    "import_asset_id": jd.import_asset_id,
                    "input_kind": (
                        "ocr_manual_review"
                        if asset["extraction_status"] == "extracted"
                        else "image_manual_review"
                    )
                    if asset
                    else "manual_text",
                    "extractor_model": asset["extractor_model"] if asset else None,
                },
            )
        )
        path, sha = archive.save(capture.raw)
        doc = repository.document(run_id, "detail", capture, path, sha)
        step = repository.start_step(run_id, "details", 1, identity)
        repository.detail(run_id, "manual", 1, record, doc, stamp, step)
        report = repository.finish(run_id, "success", "manual_imported", False, False)
    except Exception:
        repository.finish(run_id, "failed", "manual_import_failed", False, False)
        raise
    with Session(repository.engine) as session:
        job_id = session.scalar(
            select(Job.id).where(Job.source == "manual", Job.source_job_id == identity)
        )
    return {
        "job_id": job_id,
        "run_id": run_id,
        "source": "manual",
        "imported_at": stamp,
        "related_job_id": jd.related_job_id,
        "stats": report["stats"],
    }
