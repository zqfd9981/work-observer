"""岗位当前字段投影 v1；迁移复用此版本，后续规则用新函数版本扩展。"""

import re
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5


def salary_v1(raw):
    result = dict.fromkeys(
        ("salary_min", "salary_max", "salary_currency", "salary_unit", "salary_months")
    )
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*"
        r"(K|k|万|千|元)(?:\s*[/／]\s*(月|年|天|日|小时|时))?"
        r"(?:\s*[·•]\s*(\d{1,2})薪)?\s*",
        raw,
    )
    if not match:
        return result
    low, high, magnitude, unit, months = match.groups()
    multiplier = {"K": 1000, "k": 1000, "千": 1000, "万": 10000, "元": 1}[magnitude]
    if not unit and magnitude == "元":
        return result
    low, high = Decimal(low) * multiplier, Decimal(high) * multiplier
    if low > high or high >= Decimal("10000000000"):
        return result
    period = {"月": "month", "年": "year", "天": "day", "日": "day", "小时": "hour", "时": "hour"}
    result.update(
        salary_min=low,
        salary_max=high,
        salary_currency="CNY",
        salary_unit=period.get(unit, "month"),
        salary_months=int(months) if months and 1 <= int(months) <= 24 else None,
    )
    return result


def experience_v1(raw):
    result = dict.fromkeys(("experience_min_years", "experience_max_years"))
    match = re.fullmatch(r"\s*(\d+)\s*[-–]\s*(\d+)年\s*", raw)
    if match and int(match[1]) <= int(match[2]) < 100:
        result.update(
            experience_min_years=Decimal(match[1]), experience_max_years=Decimal(match[2])
        )
    return result


def published_v1(raw):
    if not isinstance(raw, str):
        return None
    try:
        stamp = datetime.fromisoformat(raw)
        return stamp.astimezone(UTC).isoformat() if stamp.tzinfo is not None else None
    except ValueError:
        return None


def origin_v1(provenance):
    origin = provenance.get("origin")
    return {
        "website": "website",
        "cache": "cache",
        "real_m0_replay": "replay",
        "client_failure": "client_error",
        "simulated_test_only": "test",
        "manual": "manual",
    }.get(origin, "unknown")


def company_v1(source, job_id, record):
    name = record.get("company")
    if not isinstance(name, str) or not name.strip():
        return None
    identity = record.get("source_company_id")
    identity = str(identity) if identity is not None and str(identity).strip() else None
    key = "id:" + identity if identity else "job:" + job_id
    return {
        "id": uuid5(NAMESPACE_URL, source + ":company:" + key).hex,
        "source": source,
        "source_company_id": identity,
        "identity_key": key,
        "identity_status": "source_id" if identity else "unverified",
        "name": name,
        "industry_raw": record.get("industry"),
        "scale_raw": record.get("scale"),
        "stage_raw": record.get("stage"),
        "introduction": record.get("company_introduction"),
    }


def project_job_v1(current, record, kind, stamp, document_id):
    """非空字段按各自观察时间更新；较旧详情仍可补齐从未取得的正文。"""
    current = dict(current)
    changes = {}
    clocks = dict(current.get("field_observed_at") or {})
    documents = dict(current.get("field_document_ids") or {})

    def put(group, values):
        if clocks.get(group, "") > stamp:
            return
        if any(current.get(k) != v for k, v in values.items()):
            changes["content_updated_at"] = max(current.get("content_updated_at") or "", stamp)
        changes.update(values)
        clocks[group] = stamp
        documents[group] = document_id

    fields = {
        "title": "title",
        "company": "company_name_raw",
        "city": "city",
        "district": "district",
        "address": "address",
        "employment_type": "employment_type",
        "description": "description_text",
        "skills": "source_skills",
        "welfare": "welfare_tags",
        "job_labels": "job_labels",
        "source_position_code": "source_position_code",
        "source_position_name": "source_position_name",
        "days_per_week": "days_per_week_raw",
        "least_month": "least_month_raw",
        "pay_type": "pay_type_raw",
        "recruitment_count": "recruitment_count_raw",
    }
    for source, target in fields.items():
        value = record.get(source)
        if value is not None and value != "" and value != []:
            put(target, {target: value})
    if type(record.get("raw_job_type")) is int:
        put("raw_job_type", {"raw_job_type": record["raw_job_type"]})
    for source, target, parser in (
        ("salary", "salary_raw", salary_v1),
        ("experience", "experience_raw", experience_v1),
    ):
        raw = record.get(source)
        if isinstance(raw, str) and raw.strip():
            put(target, {target: raw, **parser(raw)})
    education = record.get("education")
    if isinstance(education, str) and education.strip():
        known = {"不限", "学历不限", "中专", "高中", "大专", "本科", "硕士", "博士"}
        put(
            "education_raw",
            {
                "education_raw": education,
                "education_level": education if education in known else None,
            },
        )
    raw_published = record.get("source_published_raw")
    published = published_v1(record.get("source_published_at"))
    if published or isinstance(raw_published, str) and raw_published.strip():
        put(
            "source_published_at",
            {
                "source_published_at": published,
                "source_published_raw": raw_published,
            },
        )
    raw_status = record.get("source_status_raw")
    if isinstance(raw_status, dict):
        text = raw_status.get("jobStatusDesc")
        status = {"招聘中": "active", "职位已关闭": "closed", "已关闭": "closed"}.get(text)
        if status and clocks.get("status", "") <= stamp:
            changes.update(status=status, source_status_raw=raw_status, status_observed_at=stamp)
            clocks["status"] = stamp
            documents["status"] = document_id
            if status == "closed" and not current.get("first_closed_observed_at"):
                changes["first_closed_observed_at"] = stamp
    context = {k: record[k] for k in ("security_id", "lid", "job_url") if record.get(k)}
    if context and (current.get("access_captured_at") or "") <= stamp:
        prior = current.get("access_context") or {}
        # security_id 改变时不能沿用上一组 lid；仅相同访问标识允许补齐缺项。
        context = (
            {**prior, **context}
            if context.get("security_id") == prior.get("security_id")
            else context
        )
        changes.update(access_context=context, access_captured_at=stamp)
        url = record.get("job_url")
        if isinstance(url, str):
            parts = urlsplit(url)
            if parts.scheme in {"http", "https"} and parts.hostname and not parts.username:
                changes["job_url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    if kind == "list":
        changes["last_seen_in_search_at"] = max(current.get("last_seen_in_search_at") or "", stamp)
    elif kind == "detail":
        changes["detail_collected_at"] = max(current.get("detail_collected_at") or "", stamp)
        changes["detail_state"] = "detail"
    changes["field_observed_at"] = clocks
    changes["field_document_ids"] = documents
    return changes
