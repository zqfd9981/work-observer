"""只读 M0 探针：只调用搜索、详情；工具结构始终来自实际 MCP 服务。"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import timedelta

from jsonschema import validate
from mcp import ClientSession, McpError, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from work_observer.config import MCPConfig
from work_observer.evidence import Evidence

READ_TOOLS = {"boss_search", "boss_detail"}


class ProbeError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def envelope(result) -> dict:
    """保留完整 MCP 响应；只从 JSON 信封读取业务成功状态。"""
    body = result.structuredContent
    if not isinstance(body, dict) or "ok" not in body:
        body = None
        for block in result.content:
            if block.type == "text":
                try:
                    candidate = json.loads(block.text)
                except (ValueError, TypeError):
                    continue
                if isinstance(candidate, dict) and "ok" in candidate:
                    body = candidate
                    break
    if not isinstance(body, dict):
        raise ProbeError("MCP_TOOL_ERROR" if result.isError else "UNEXPECTED_ENVELOPE")
    if result.isError or body.get("ok") is not True:
        code = (body.get("error") or {}).get("code", "MCP_TOOL_ERROR")
        # 错误消息可能含敏感原文；摘要只允许已知错误类别。
        known = {
            "AUTH_REQUIRED",
            "RATE_LIMITED",
            "RISK_CONTROL",
            "NOT_SUPPORTED",
            "INVALID_ARGUMENT",
            "INVALID_ARGUMENTS",
            "VALIDATION_ERROR",
            "NETWORK_ERROR",
            "ACCOUNT_RISK",
            "ENVIRONMENT_RISK",
            "SESSION_EXPIRED",
            "BROWSER_SESSION_NOT_FOUND",
            "CDP_UNAVAILABLE",
            "BROWSER_DISABLED",
            "AUTH_EXPIRED",
            "LOGIN_EXPIRED",
            "LOGIN_RISK_CONTROL",
            "INVALID_PARAM",
            "REQUEST_BUDGET_EXHAUSTED",
            "ENVIRONMENT_RISK_LOCKED",
            "JOB_NOT_FOUND",
            "TOKEN_REFRESH_FAILED",
            "BROWSER_KERNEL_MISSING",
            "BROWSER_NAV_TIMEOUT",
        }
        raise ProbeError(code if code in known else "SOURCE_ERROR")
    return body


@asynccontextmanager
async def connect(config: MCPConfig):
    if config.transport == "stdio":
        params = StdioServerParameters(
            command=config.command, args=config.args, cwd=config.cwd, env=config.env
        )
        # 不将第三方进程日志转发到终端或落盘，以免泄露登录资料。
        with open(os.devnull, "w") as err:
            async with stdio_client(params, errlog=err) as streams:
                async with ClientSession(
                    *streams, read_timeout_seconds=timedelta(seconds=config.timeout_seconds)
                ) as session:
                    yield session
    else:
        headers = {}
        if config.bearer_token_env:
            token = os.getenv(config.bearer_token_env)
            if not token:
                raise ProbeError("MISSING_MCP_TOKEN")
            headers["Authorization"] = f"Bearer {token}"
        transport = streamablehttp_client if config.transport == "streamable-http" else sse_client
        async with transport(
            config.url,
            headers=headers,
            timeout=config.timeout_seconds,
            sse_read_timeout=config.timeout_seconds,
        ) as streams:
            async with ClientSession(
                streams[0],
                streams[1],
                read_timeout_seconds=timedelta(seconds=config.timeout_seconds),
            ) as session:
                yield session


async def call_read(session, tools, name, args, evidence, filename):
    if name not in READ_TOOLS:
        raise ProbeError("READ_ONLY_TOOL_DENIED")
    if name not in tools:
        raise ProbeError("MISSING_REQUIRED_TOOL")
    validate(args, tools[name].inputSchema)
    evidence.save(filename.replace(".json", ".request.json"), {"tool": name, "arguments": args})
    result = await session.call_tool(name, args)
    evidence.save(filename, result)
    return envelope(result)


async def probe_recruitment(
    config: MCPConfig,
    evidence: Evidence,
    query: str,
    city: str,
    details: int,
    error_probe: bool = False,
    tools_only: bool = False,
    progress: dict | None = None,
):
    summary = progress if progress is not None else {}
    summary.update(status="failed", transport=config.transport, details_received=0)
    # 每次协议调用及整个连接均有上限；不自动重试来源错误。
    async with asyncio.timeout(config.timeout_seconds * (details + 5)):
        async with connect(config) as session:
            initialized = await session.initialize()
            evidence.save("mcp.initialize.json", initialized)
            tools = {}
            cursor = None
            for page in range(10):
                result = await session.list_tools(cursor=cursor)
                evidence.save(f"mcp.tools.{page + 1}.json", result)
                tools.update({t.name: t for t in result.tools})
                cursor = result.nextCursor
                if not cursor:
                    break
            if cursor:
                raise ProbeError("TOOL_PAGINATION_LIMIT")
            summary["tools_count"] = len(tools)
            summary["read_tool_inputs"] = {
                name: tools[name].inputSchema for name in sorted(READ_TOOLS) if name in tools
            }
            if error_probe:
                # 缺失参数应在服务端校验层被拒绝，不访问招聘平台。
                if "boss_detail" not in tools:
                    raise ProbeError("MISSING_REQUIRED_TOOL")
                try:
                    result = await session.call_tool("boss_detail", {})
                    evidence.save("mcp.error.invalid-arguments.json", result)
                    summary["error_probe"] = {"mcp_is_error": result.isError}
                except McpError as exc:
                    evidence.save("mcp.error.invalid-arguments.json", exc.error)
                    summary["error_probe"] = {"json_rpc_error_code": exc.error.code}
                    summary["error_probe"]["standard_invalid_params"] = exc.error.code == -32602
            if tools_only:
                summary["status"] = "discovered"
                return summary
            search = await call_read(
                session,
                tools,
                "boss_search",
                {"query": query, "city": city, "page": 1},
                evidence,
                "mcp.search.json",
            )
            data = search.get("data")
            jobs = (
                data
                if isinstance(data, list)
                else (data.get("jobs") if isinstance(data, dict) else None)
            )
            if not isinstance(jobs, list) or not jobs:
                raise ProbeError("EMPTY_OR_UNEXPECTED_LIST")
            summary.update(
                {
                    "query": query,
                    "city": city,
                    "page_requested": 1,
                    "jobs_received": len(jobs),
                    "list_fields": sorted(jobs[0]),
                    "pagination": search.get("pagination"),
                }
            )
            try:
                for index, job in enumerate(jobs[:details], 1):
                    if not job.get("security_id") or not job.get("job_id"):
                        raise ProbeError("MISSING_JOB_IDENTIFIERS")
                    detail = await call_read(
                        session,
                        tools,
                        "boss_detail",
                        {"security_id": job["security_id"], "job_id": job["job_id"]},
                        evidence,
                        f"mcp.detail.{index}.json",
                    )
                    content = detail.get("data")
                    if not isinstance(content, dict) or not content:
                        raise ProbeError("EMPTY_OR_UNEXPECTED_DETAIL")
                    description = content.get("description")
                    if not isinstance(description, str) or not description.strip():
                        raise ProbeError("MISSING_DETAIL_DESCRIPTION")
                    if content.get("job_id") != job["job_id"]:
                        raise ProbeError("DETAIL_ID_MISMATCH")
                    summary.setdefault("detail_fields", []).append(sorted(content))
                    summary["details_received"] += 1
                if summary["details_received"] != details:
                    raise ProbeError("INSUFFICIENT_DETAILS")
                summary["status"] = "passed"
            except ProbeError as exc:
                summary.update(status="partial", error_code=exc.code)
            return summary
