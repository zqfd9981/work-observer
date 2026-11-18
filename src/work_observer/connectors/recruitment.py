"""实时 MCP 和可验证的 M0 真实样例回放；均不负责业务入库。"""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

from jsonschema import validate
from mcp import McpError

from work_observer.collection.contracts import Capture, now
from work_observer.connectors.mcp_probe import READ_TOOLS, ProbeError, connect


class MCPSource:
    mode = "live"

    def __init__(self, config):
        self.config = config

    @asynccontextmanager
    async def open(self):
        from work_observer.connectors.source_status import require_source_available

        require_source_available(self.config)
        async with connect(self.config) as session:
            await asyncio.wait_for(session.initialize(), self.config.timeout_seconds)
            self.tools = {}
            cursor = None
            for _ in range(10):
                tools = await session.list_tools(cursor=cursor)
                self.tools.update({t.name: t for t in tools.tools})
                cursor = tools.nextCursor
                if not cursor:
                    break
            if cursor:
                raise ProbeError("TOOL_PAGINATION_LIMIT")
            self.session = session
            yield self

    async def _call(self, name, arguments):
        if name not in READ_TOOLS:
            raise ProbeError("READ_ONLY_TOOL_DENIED")
        if name not in self.tools:
            raise ProbeError("MISSING_REQUIRED_TOOL")
        validate(arguments, self.tools[name].inputSchema)
        try:
            result = await self.session.call_tool(name, arguments)
            raw = result.model_dump(mode="json", by_alias=True)
        except McpError as exc:
            raw = {"json_rpc_error": exc.error.model_dump(mode="json")}
        return Capture(
            raw=raw,
            request={"tool": name, "arguments": arguments},
            observed_at=now(),
            provenance={"origin": "live"},
        )

    async def search(self, spec, page):
        return await self._call(
            "boss_search", {"query": spec.query, "city": spec.city, "page": page}
        )

    async def detail(self, job):
        if not job.get("security_id"):
            raise ProbeError("MISSING_ACCESS_CONTEXT")
        return await self._call(
            "boss_detail",
            {
                "job_id": job["job_id"],
                "security_id": job["security_id"],
            },
        )


class M0ReplaySource:
    """仅接收带指纹与真实调用声明的 M0 文件；不假装产生新平台调用。"""

    mode = "replay"

    def __init__(self, bundle: Path):
        self.bundle = bundle.resolve()
        self.report = json.loads((self.bundle / "report.json").read_text(encoding="utf-8"))
        if (
            self.report.get("milestone") != "M0"
            or self.report.get("real_calls_only") is not True
            or self.report.get("checks", {}).get("recruitment", {}).get("status") != "passed"
        ):
            raise ProbeError("NOT_A_VERIFIED_M0_BUNDLE")
        self.stamp = self.report["finished_at"]
        self.page_capture = self._capture("mcp.search.json", "mcp.search.request.json")
        self.details = {}
        # M0 的探针上限是三条；只读取明确格式的文件，忽略模型等无关内容。
        for index in range(1, 4):
            name = f"mcp.detail.{index}.json"
            if name in self.report.get("evidence_sha256", {}):
                capture = self._capture(name, f"mcp.detail.{index}.request.json")
                job_id = capture.request["arguments"]["job_id"]
                if job_id in self.details:
                    raise ProbeError("DUPLICATE_REPLAY_DETAIL")
                self.details[job_id] = capture

    def _read(self, name):
        path = (self.bundle / name).resolve()
        if not path.is_relative_to(self.bundle):
            raise ProbeError("INVALID_REPLAY_PATH")
        data = path.read_bytes()
        expected = self.report.get("evidence_sha256", {}).get(name)
        if not expected or hashlib.sha256(data).hexdigest() != expected:
            raise ProbeError("REPLAY_HASH_MISMATCH")
        return json.loads(data)

    def _capture(self, response, request):
        return Capture(
            raw=self._read(response),
            request=self._read(request),
            observed_at=self.stamp,
            provenance={
                "origin": "real_m0_replay",
                "original_file": str(self.bundle / response),
                "original_sha256": self.report["evidence_sha256"][response],
                "time_precision": "m0_batch_finished_at",
            },
        )

    @asynccontextmanager
    async def open(self):
        yield self

    async def search(self, spec, page):
        arguments = self.page_capture.request.get("arguments", {})
        if arguments != {"query": spec.query, "city": spec.city, "page": page}:
            raise ProbeError("REPLAY_QUERY_NOT_RECORDED")
        return self.page_capture

    async def detail(self, job):
        capture = self.details.get(job["job_id"])
        if capture is None:
            raise ProbeError("REPLAY_DETAIL_NOT_RECORDED")
        if capture.request["arguments"].get("security_id") != job.get("security_id"):
            raise ProbeError("REPLAY_ACCESS_CONTEXT_MISMATCH")
        return capture
