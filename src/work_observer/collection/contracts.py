"""M1 的来源合同、取样预算和内容指纹；不处理分析或调度。"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field, field_validator

from work_observer.connectors.mcp_probe import ProbeError, envelope


def now() -> str:
    return datetime.now(UTC).isoformat()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class WatchsetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    source: Literal["boss", "manual"] = "boss"
    kind: Literal["fixed", "exploration"] = "fixed"
    query: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=50)
    page_limit: int = Field(default=1, ge=1, le=5)
    detail_limit: int = Field(default=2, ge=0, le=10)
    request_limit: int = Field(default=3, ge=1, le=15)

    @field_validator("query", "city")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("查询与城市不可为空")
        return value


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    job_id: str = Field(min_length=1)
    title: str
    company: str

    @field_validator("job_id")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("岗位标识不可为空")
        return value


class Capture(BaseModel):
    raw: dict
    request: dict
    observed_at: str
    provenance: dict = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def utc_time(cls, value):
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError("采集时间需要时区")
        return stamp.astimezone(UTC).isoformat()

    def body(self) -> dict:
        if "json_rpc_error" in self.raw:
            raise ProbeError("MCP_PROTOCOL_ERROR")
        return envelope(CallToolResult.model_validate(self.raw))


def parse_page(capture: Capture, requested_page: int):
    body = capture.body()
    data = body.get("data")
    jobs = data if isinstance(data, list) else data.get("jobs") if isinstance(data, dict) else None
    pagination = body.get("pagination")
    if not isinstance(jobs, list):
        raise ProbeError("MALFORMED_LIST")
    if (
        not isinstance(pagination, dict)
        or type(pagination.get("page")) is not int
        or pagination["page"] != requested_page
        or type(pagination.get("has_more")) is not bool
    ):
        raise ProbeError("MALFORMED_PAGINATION")
    for job in jobs:
        JobRecord.model_validate(job)
    return jobs, pagination


def parse_detail(capture: Capture, source_job_id: str) -> dict:
    data = capture.body().get("data")
    if not isinstance(data, dict):
        raise ProbeError("MALFORMED_DETAIL")
    JobRecord.model_validate(data)
    if data["job_id"] != source_job_id:
        raise ProbeError("DETAIL_ID_MISMATCH")
    if not isinstance(data.get("description"), str) or not data["description"].strip():
        raise ProbeError("MISSING_DETAIL_DESCRIPTION")
    return data


# 访问上下文和排序、招聘者活跃度不作为岗位内容变化。新增业务字段需升指纹版本。
CONTENT_VERSION = "job-content-v1"
CONTENT_FIELDS = {
    "title",
    "company",
    "salary",
    "city",
    "district",
    "experience",
    "education",
    "skills",
    "welfare",
    "industry",
    "scale",
    "stage",
    "job_labels",
    "raw_job_type",
    "employment_type",
    "days_per_week",
    "least_month",
    "pay_type",
    "description",
    "address",
}
ACCESS_FIELDS = {"security_id", "lid", "job_url"}


def content(job: dict) -> dict:
    # 缺失、空字符串、空列表保留区别；不补造时间或合并列表与详情。
    return {k: v for k, v in job.items() if k in CONTENT_FIELDS}


def access(job: dict) -> dict:
    return {k: v for k, v in job.items() if k in ACCESS_FIELDS}
