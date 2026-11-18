"""隔离的故障/边界测试；这些返回均为模拟，不是外部连通验收。"""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp import McpError
from mcp.types import CallToolResult, ErrorData, TextContent, Tool
from pydantic import ValidationError
from typer.testing import CliRunner

from work_observer import cli
from work_observer.config import MCPConfig, Settings, validate_url
from work_observer.connectors import http_probes, mcp_probe
from work_observer.evidence import Evidence, redact


def reply(body, is_error=False):
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(body))],
        isError=is_error,
    )


def test_auth_failure_is_not_empty_success():
    result = reply({"ok": False, "data": None, "error": {"code": "AUTH_REQUIRED"}})
    with pytest.raises(mcp_probe.ProbeError, match="AUTH_REQUIRED"):
        mcp_probe.envelope(result)


def test_mcp_error_overrides_business_ok():
    with pytest.raises(mcp_probe.ProbeError):
        mcp_probe.envelope(reply({"ok": True, "data": {}}, True))


def test_unexpected_response_fails_closed():
    with pytest.raises(mcp_probe.ProbeError, match="UNEXPECTED_ENVELOPE"):
        mcp_probe.envelope(reply({"jobs": [{"title": "模拟"}]}))


def test_preserve_schema_and_business_fields_redact_secrets(tmp_path):
    evidence = Evidence(secrets=["test-secret"], root=tmp_path)
    payload = {
        "cookie": "private",
        "page": 1,
        "security_id": "platform-access-id",
        "description": "中文1 utf-8",
        "text": "Bearer test-secret",
    }
    evidence.save("sample.json", payload)
    saved = json.loads((evidence.path / "sample.json").read_text(encoding="utf-8"))
    assert saved["cookie"] == "[REDACTED]"
    assert saved["page"] == 1
    assert saved["security_id"] == "platform-access-id"
    assert saved["description"] == "中文1 utf-8"
    assert "test-secret" not in saved["text"]
    assert (
        evidence.files["sample.json"]
        == hashlib.sha256((evidence.path / "sample.json").read_bytes()).hexdigest()
    )
    assert redact({"nested": [{"api_key": "x"}]})["nested"][0]["api_key"] == "[REDACTED]"


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.com",
        "https://example.com?key=secret",
        "http://external.example.com",
        "file:///private",
    ],
)
def test_reject_unsafe_connection_url(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_stdio_requires_executable():
    with pytest.raises(ValidationError):
        MCPConfig()


def test_exception_summary_does_not_leak_credentials():
    secret = "private-key-example"
    err = ExceptionGroup("group", [RuntimeError(f"Authorization: Bearer {secret}")])
    assert secret not in json.dumps(cli.failure(err))
    assert cli.failure(ExceptionGroup("group", [TimeoutError()]))["error_code"] == "TIMEOUT"


def test_missing_external_configs_make_no_requests(tmp_path):
    evidence = Evidence(root=tmp_path)
    assert asyncio.run(http_probes.probe_model(Settings(), evidence))["status"] == "missing_config"
    assert asyncio.run(http_probes.probe_search(Settings(), evidence))["status"] == "missing_config"
    assert evidence.files == {}


def test_write_tool_is_denied(tmp_path):
    with pytest.raises(mcp_probe.ProbeError, match="READ_ONLY_TOOL_DENIED"):
        asyncio.run(
            mcp_probe.call_read(None, {}, "boss_greet", {}, Evidence(root=tmp_path), "x.json")
        )


def test_live_schema_is_checked_before_call(tmp_path):
    tools = {
        "boss_search": Tool(
            name="boss_search",
            inputSchema={
                "type": "object",
                "properties": {"new_required": {"type": "string"}},
                "required": ["new_required"],
            },
        )
    }
    from jsonschema import ValidationError as SchemaError

    with pytest.raises(SchemaError):
        asyncio.run(
            mcp_probe.call_read(
                None,
                tools,
                "boss_search",
                {"query": "Agent"},
                Evidence(root=tmp_path),
                "x.json",
            )
        )


class FakeSession:
    """只供测试，不接触真实平台。"""

    def __init__(self, mode):
        self.mode = mode
        self.calls = []

    async def initialize(self):
        return {"test_double": True}

    async def list_tools(self, cursor=None):
        from mcp.types import ListToolsResult

        return ListToolsResult(
            tools=[
                Tool(name="boss_search", inputSchema={"type": "object"}),
                Tool(name="boss_detail", inputSchema={"type": "object"}),
            ]
        )

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if not args:
            raise McpError(ErrorData(code=0, message="'security_id'"))
        if name == "boss_search":
            jobs = (
                []
                if self.mode == "empty"
                else [{"job_id": str(i), "security_id": "simulated"} for i in range(2)]
            )
            return reply({"ok": True, "data": jobs, "pagination": {"page": 1, "has_more": True}})
        if args["job_id"] == "1" and self.mode == "auth_failure":
            return reply({"ok": False, "error": {"code": "AUTH_EXPIRED"}})
        description = "" if self.mode == "empty_detail" else "模拟 JD，仅供故障测试"
        return reply({"ok": True, "data": {"job_id": args["job_id"], "description": description}})


@pytest.mark.parametrize(
    "mode,status,received",
    [
        ("normal", "passed", 2),
        ("auth_failure", "partial", 1),
        ("empty_detail", "partial", 0),
    ],
)
def test_detail_validation_and_partial_progress(monkeypatch, tmp_path, mode, status, received):
    session = FakeSession(mode)

    @asynccontextmanager
    async def connect(_):
        yield session

    monkeypatch.setattr(mcp_probe, "connect", connect)
    result = asyncio.run(
        mcp_probe.probe_recruitment(
            MCPConfig(command="unused"),
            Evidence(root=tmp_path),
            "Agent",
            "上海",
            2,
            True,
        )
    )
    assert result["status"] == status
    assert result["details_received"] == received
    assert result["error_probe"]["json_rpc_error_code"] == 0
    assert {name for name, _ in session.calls} <= mcp_probe.READ_TOOLS


def test_empty_list_cannot_pass(monkeypatch, tmp_path):
    @asynccontextmanager
    async def connect(_):
        yield FakeSession("empty")

    monkeypatch.setattr(mcp_probe, "connect", connect)
    with pytest.raises(mcp_probe.ProbeError, match="EMPTY_OR_UNEXPECTED_LIST"):
        asyncio.run(
            mcp_probe.probe_recruitment(
                MCPConfig(command="unused"),
                Evidence(root=tmp_path),
                "Agent",
                "上海",
                2,
            )
        )


def test_http_auth_error_is_saved_but_not_returned(tmp_path):
    async def run():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                401,
                json={"error": "bad test-secret"},
                request=request,
            )
        )
        evidence = Evidence(secrets=["test-secret"], root=tmp_path)
        async with httpx.AsyncClient(transport=transport) as client:
            body, result = await http_probes.post(
                client,
                "https://example.com",
                "test-secret",
                {},
                evidence,
                "test",
            )
        assert body is None
        assert result == {"status": "failed", "error_code": "AUTH_REQUIRED", "http_status": 401}
        assert "test-secret" not in (evidence.path / "test.json").read_text()

    asyncio.run(run())


def test_doctor_nonzero_on_missing_config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.Settings, "load", lambda _: Settings())
    result = CliRunner().invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "missing_config" in result.stdout
    report_path = next(tmp_path.glob("data/raw/m0/*/report.json"))
    assert json.loads(report_path.read_text(encoding="utf-8"))["m0_accepted"] is False


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("normal", "passed"),
        ("invalid_json_schema", "failed"),
        ("tool_rejected", "partial"),
    ],
)
@pytest.mark.parametrize("api", ["responses", "chat-completions"])
def test_model_capabilities_are_verified_separately(monkeypatch, tmp_path, mode, expected, api):
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "tools" in payload:
            if mode == "tool_rejected":
                return httpx.Response(400, json={"error": "unsupported tools"})
            message = {
                "tool_calls": [
                    {
                        "function": {
                            "name": "connection_probe",
                            "arguments": '{"status":"连接成功"}',
                        }
                    }
                ]
            }
        else:
            message = {
                "content": '{"status":"错误值"}'
                if mode == "invalid_json_schema"
                else '{"status":"连接成功"}'
            }
        if api == "responses":
            output = (
                [{"type": "function_call", **message["tool_calls"][0]["function"]}]
                if "tools" in payload
                else [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": message["content"]},
                        ],
                    }
                ]
            )
            return httpx.Response(200, json={"status": "completed", "output": output})
        return httpx.Response(200, json={"choices": [{"message": message}]})

    factory = httpx.AsyncClient
    monkeypatch.setattr(
        http_probes.httpx,
        "AsyncClient",
        lambda **kwargs: factory(
            transport=httpx.MockTransport(respond),
            **kwargs,
        ),
    )
    settings = Settings(
        model_base_url="https://example.com/v1",
        model_name="simulated",
        model_api_key="test-secret",
        model_api=api,
    )
    result = asyncio.run(http_probes.probe_model(settings, Evidence(root=tmp_path)))
    assert result["status"] == expected
    assert len(requests) == (1 if mode == "invalid_json_schema" else 2)


@pytest.mark.parametrize(
    "results,status",
    [
        ([], "failed"),
        ([{"url": "https://example.com", "content": "模拟摘要"}], "passed"),
        ([{"title": "缺少来源"}], "failed"),
    ],
)
def test_search_requires_nonempty_sourced_results(monkeypatch, tmp_path, results, status):
    factory = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"results": results}))
    monkeypatch.setattr(
        http_probes.httpx,
        "AsyncClient",
        lambda **kwargs: factory(
            transport=transport,
            **kwargs,
        ),
    )
    result = asyncio.run(
        http_probes.probe_search(
            Settings(tavily_api_key="test-secret", search_provider="tavily"),
            Evidence(root=tmp_path),
        )
    )
    assert result["status"] == status


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("normal", "passed"),
        ("too_many", "failed"),
        ("searching", "failed"),
        ("no_sources", "failed"),
        ("no_citations", "failed"),
        ("incomplete", "failed"),
    ],
)
def test_openai_search_requires_completed_calls_sources_and_citations(
    monkeypatch,
    tmp_path,
    mode,
    expected,
):
    call = {
        "type": "web_search_call",
        "status": "searching" if mode == "searching" else "completed",
        "action": {
            "sources": []
            if mode == "no_sources"
            else [
                {"type": "url", "url": "https://example.com"},
            ]
        },
    }
    body = {
        "status": "incomplete" if mode == "incomplete" else "completed",
        "output": [
            call,
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "模拟搜索说明",
                        "annotations": []
                        if mode == "no_citations"
                        else [
                            {"type": "url_citation", "url": "https://example.com"},
                        ],
                    }
                ],
            },
        ],
    }
    if mode == "too_many":
        body["output"].append(call)
    factory = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    monkeypatch.setattr(
        http_probes.httpx,
        "AsyncClient",
        lambda **kwargs: factory(
            transport=transport,
            **kwargs,
        ),
    )
    settings = Settings(
        model_base_url="https://example.com/v1", model_name="simulated", model_api_key="test-secret"
    )
    result = asyncio.run(http_probes.probe_search(settings, Evidence(root=tmp_path)))
    assert result["status"] == expected
