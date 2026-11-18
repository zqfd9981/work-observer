"""有界采集与原文归档。每次来源读取前后独立提交业务事务。"""

import httpx
from jsonschema import SchemaError
from jsonschema import ValidationError as ArgumentError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from work_observer.collection.contracts import Capture, now, parse_detail, parse_page
from work_observer.connectors.mcp_probe import ProbeError

AUTH_CODES = {
    "AUTH_REQUIRED",
    "AUTH_EXPIRED",
    "LOGIN_EXPIRED",
    "SESSION_EXPIRED",
    "TOKEN_REFRESH_FAILED",
    "BROWSER_SESSION_NOT_FOUND",
    "CDP_UNAVAILABLE",
}
STOP_CODES = AUTH_CODES | {
    "ACCOUNT_RISK",
    "ENVIRONMENT_RISK",
    "ENVIRONMENT_RISK_LOCKED",
    "LOGIN_RISK_CONTROL",
    "RATE_LIMITED",
    "REQUEST_BUDGET_EXHAUSTED",
    "TIMEOUT",
    "NETWORK_ERROR",
    "MCP_PROTOCOL_ERROR",
    "CONFIG_OR_PROTOCOL_ERROR",
    "INVALID_TOOL_ARGUMENTS",
    "INVALID_TOOL_SCHEMA",
    "ARCHIVE_CORRUPTED",
    "LOCAL_STORAGE_ERROR",
    "INVALID_SOURCE_SCHEMA",
    "DETAIL_ID_MISMATCH",
    "MALFORMED_DETAIL",
    "NOT_SUPPORTED",
    "BROWSER_DISABLED",
    "SOURCE_ERROR",
    "MCP_TOOL_ERROR",
    "UNEXPECTED_ENVELOPE",
}


def error_code(exc):
    if isinstance(exc, BaseExceptionGroup):
        codes = [error_code(item) for item in exc.exceptions]
        return next((code for code in codes if code in AUTH_CODES | STOP_CODES), codes[0])
    if isinstance(exc, ProbeError):
        return exc.code
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "TIMEOUT"
    if isinstance(exc, httpx.TransportError):
        return "NETWORK_ERROR"
    if isinstance(exc, ArgumentError):
        return "INVALID_TOOL_ARGUMENTS"
    if isinstance(exc, SchemaError):
        return "INVALID_TOOL_SCHEMA"
    if isinstance(exc, ValidationError):
        return "INVALID_SOURCE_SCHEMA"
    if isinstance(exc, (OSError, SQLAlchemyError)):
        return "LOCAL_STORAGE_ERROR"
    return "CONFIG_OR_PROTOCOL_ERROR"


async def collect(repository, archive, source, name, spec):
    run_id = repository.begin_run(name, spec, source.mode)
    codes = []
    budget = spec.request_limit
    jobs_seen = {}
    list_limited = True
    details_limited = False
    stop_reason = "page_limit"

    async def attempt(stage, page, job, fetch, process):
        nonlocal budget
        step_id = repository.start_step(run_id, stage, page, job["job_id"] if job else None)
        budget -= 1
        capture = None
        document_id = None
        try:
            capture = archive.sanitize(await fetch())
            path, sha = archive.save(capture.raw)
            document_id = repository.document(
                run_id,
                "list" if stage == "pages" else "detail",
                capture,
                path,
                sha,
                page,
                job["job_id"] if job else None,
            )
            return process(capture, document_id, step_id), None
        except Exception as exc:
            code = error_code(exc)
            if capture is None:
                # 客户端失败与服务原始响应明确分开，不伪造业务信封或空岗位列表。
                capture = Capture(
                    raw={"client_error": {"code": code}},
                    observed_at=now(),
                    request={"stage": stage, "page": page},
                    provenance={"origin": "client_failure", "mode": source.mode},
                )
                path, sha = archive.save(capture.raw)
                document_id = repository.document(
                    run_id,
                    "client_error",
                    capture,
                    path,
                    sha,
                    page,
                    job["job_id"] if job else None,
                )
            repository.issue(run_id, code, stage, step_id, document_id)
            codes.append(code)
            return None, code

    try:
        async with source.open():
            for page in range(1, spec.page_limit + 1):
                if budget <= 0:
                    stop_reason = "request_limit"
                    break

                def process_page(capture, doc, step, page=page):
                    jobs, pagination = parse_page(capture, page)
                    repository.page(
                        run_id, spec.source, page, jobs, pagination, doc, capture.observed_at, step
                    )
                    return jobs, pagination

                result, code = await attempt(
                    "pages",
                    page,
                    None,
                    lambda page=page: source.search(spec, page),
                    process_page,
                )
                if code:
                    stop_reason = code
                    break
                jobs, pagination = result
                for job in jobs:
                    jobs_seen.setdefault(job["job_id"], (page, job))
                if not pagination["has_more"]:
                    list_limited = False
                    stop_reason = "source_end"
                    break
            if not codes:
                selected = list(jobs_seen.values())[: spec.detail_limit]
                details_limited = len(jobs_seen) > len(selected)
                for page, job in selected:
                    if budget <= 0:
                        details_limited = True
                        stop_reason = "request_limit"
                        break

                    def process_detail(capture, doc, step, page=page, job=job):
                        data = parse_detail(capture, job["job_id"])
                        repository.detail(
                            run_id, spec.source, page, data, doc, capture.observed_at, step
                        )
                        return data

                    _, code = await attempt(
                        "details",
                        page,
                        job,
                        lambda job=job: source.detail(job),
                        process_detail,
                    )
                    if code and code in STOP_CODES:
                        details_limited = True
                        stop_reason = code
                        break
    except Exception as exc:
        code = error_code(exc)
        codes.append(code)
        stop_reason = code
        repository.issue(run_id, code, "connection")

    report = repository.run(run_id)
    if any(code in AUTH_CODES for code in codes):
        status = "needs_auth"
    elif codes:
        status = "partial" if report["stats"]["pages_succeeded"] else "failed"
    else:
        status = "success"
    if codes:
        details_limited = True
    return repository.finish(run_id, status, stop_reason, list_limited, details_limited)
