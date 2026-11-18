"""本机页面与薄 HTTP 入口，复用 CLI 业务，不提供招聘采集或认证操作。"""

import asyncio
import json
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from work_observer.api.imports import import_routes
from work_observer.api.operations import operations_routes
from work_observer.api.product import product_routes
from work_observer.api.schema import schema_routes
from work_observer.api.security import DeploymentGuard, deployment_settings
from work_observer.collection.service import error_code
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.source_status import source_status
from work_observer.evidence import redact
from work_observer.memory.service import MemoryService
from work_observer.reports.results import list_results, read_result, render, save_result
from work_observer.research.agent import research
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog, Filters
from work_observer.storage.archive import RawArchive
from work_observer.storage.locks import exclusive
from work_observer.storage.repository import Repository

ASSETS = Path(__file__).parent / "assets"
MAX_BODY = 512_000
PRIVATE_KEYS = {
    "access_context",
    "source_job_id",
    "source_company_id",
    "security_id",
    "lid",
    "path",
    "document_path",
    "access_captured_at",
    "field_observed_at",
}


class JobQuery(Filters):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)
    job_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)
    filters: Filters = Field(default_factory=Filters)
    offline: bool = False
    max_calls: int = Field(default=10, ge=2, le=12)
    timeout: int = Field(default=180, ge=1, le=300)
    allow_public: bool = False


class MemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern="^(preference|correction|knowledge|hypothesis|method)$")
    content: str = Field(default="", max_length=4000)
    job_id: str | None = None
    source_run_id: str | None = None
    claim_index: int | None = Field(default=None, ge=0, le=23)
    scope: str | None = Field(default=None, pattern="^(global|project|job)$")
    project_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    valid_from: str | None = None
    valid_until: str | None = None
    origin: str = Field(default="user", pattern="^(user|agent)$")


class MemoryRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=4000)


def public(value, credentials):
    if isinstance(value, dict):
        value = {
            key: public(item, credentials) for key, item in value.items() if key not in PRIVATE_KEYS
        }
    elif isinstance(value, list):
        value = [public(item, credentials) for item in value]
    return redact(value, credentials)


class LocalGuard:
    def __init__(self, app, token, public_origin=""):
        self.app, self.token, self.public_origin = app, token, public_origin

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        hostname = request.url.hostname
        denied = (
            hostname != urlsplit(self.public_origin).hostname
            if self.public_origin
            else hostname not in {"127.0.0.1", "localhost", "[::1]", "::1"}
        )
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            denied |= bool(
                origin and origin != (self.public_origin or str(request.base_url).rstrip("/"))
            )
            denied |= request.headers.get("sec-fetch-site") == "cross-site"
        if request.method not in {"GET", "HEAD"} and not scope.get("wo_bearer_authenticated"):
            denied |= not secrets.compare_digest(
                request.headers.get("x-wo-token", "").encode(), self.token.encode()
            )
        if denied:
            return await JSONResponse(
                {"error_code": "LOCAL_ACCESS_DENIED", "message": "请从本机工作页面发起操作。"}, 403
            )(scope, receive, send)

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; "
                            b"style-src 'self'; img-src 'self' data:; connect-src 'self'; "
                            b"frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                        ),
                    ]
                )
            await send(message)

        await self.app(scope, receive, secure_send)


async def read_json(request):
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise ProbeError("JSON_BODY_REQUIRED")
    size, chunks = 0, []
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise ProbeError("IMPORT_TOO_LARGE")
        chunks.append(chunk)
    return json.loads(b"".join(chunks))


def create_app(
    settings: Settings | None = None,
    *,
    reports_dir=Path("reports"),
    model=None,
    checkpoint_path=None,
):
    settings = settings or Settings.load()
    reports_dir = Path(reports_dir)
    credentials = [
        settings.model_api_key.get_secret_value(),
        settings.tavily_api_key.get_secret_value(),
        settings.access_token.get_secret_value(),
    ]
    token = secrets.token_urlsafe(32)
    tasks, operation_tasks, import_lock = {}, {}, threading.Lock()
    operation_lock = asyncio.Lock()
    repository = store = memory = None

    def response(data, status=200):
        from work_observer.api.privacy import result_read_blocked, unavailable

        if result_read_blocked(store):
            return unavailable()
        return JSONResponse(public(data, credentials), status)

    @asynccontextmanager
    async def lifespan(app):
        nonlocal repository, store, memory
        with exclusive(settings.database_path, purpose="serve"):
            repository = Repository(settings.database_path)
            memory = MemoryService(repository)
            store = ResearchStore(
                Path(checkpoint_path)
                if checkpoint_path
                else settings.database_path.parent / "checkpoints.db",
                namespace=str(settings.database_path.resolve()),
            )
            from work_observer.research.projects import ProjectService

            try:
                with exclusive(settings.database_path):
                    for run in store.list():
                        if run["state"] == "running":
                            store.save(run["id"], state="interrupted")
                    ProjectService(store).recover()
            except ProbeError as exc:
                if exc.code != "RESEARCH_BUSY":
                    raise
            from work_observer.memory.lifecycle import resume_erasures

            resume_erasures(repository, store, reports_dir)
            try:
                yield
            finally:
                pending = [
                    task for task in [*tasks.values(), *operation_tasks.values()] if not task.done()
                ]
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for identity in tasks:
                    if store.get(identity)["state"] == "running":
                        store.save(identity, state="interrupted")
                store.close()
                repository.close()

    async def index(request):
        html = (ASSETS / "index.html").read_text(encoding="utf-8").replace("__WO_TOKEN__", token)
        for name in ("knowledge.html", "quality.html", "data-quality.html", "updates.html"):
            html = html.replace("</main>", (ASSETS / name).read_text(encoding="utf-8") + "</main>")
        return HTMLResponse(html)

    async def asset(request):
        name = request.path_params["name"]
        if name not in {
            "app.js",
            "projects.js",
            "knowledge.js",
            "quality.js",
            "data-quality.js",
            "updates.js",
            "app.css",
        }:
            return Response(status_code=404)
        return Response(
            (ASSETS / name).read_bytes(),
            media_type="text/css" if name.endswith(".css") else "text/javascript",
        )

    async def overview(request):
        counts = repository.counts()
        catalog = Catalog(repository).query(limit=1)
        try:
            status = source_status(settings.load_mcp())
        except Exception:
            status = {"state": "unknown", "checked": "local_only"}
        return response(
            {
                "jobs": counts["jobs"],
                "details": catalog["counts"]["candidate_details"],
                "companies": counts["companies"],
                "source": status,
                "model_configured": bool(
                    settings.model_base_url
                    and settings.model_name
                    and settings.model_api_key.get_secret_value()
                ),
                "active_research": next(
                    (key for key, task in tasks.items() if not task.done()), None
                ),
            }
        )

    async def jobs(request):
        query = JobQuery.model_validate({k: v for k, v in request.query_params.items() if v != ""})
        filters = Filters.model_validate(query.model_dump(exclude={"limit", "offset"}))
        return response(Catalog(repository).query(filters, limit=query.limit, offset=query.offset))

    async def job(request):
        return response(repository.job(request.path_params["id"]))

    async def history(request):
        return response(repository.history(request.path_params["id"]))

    async def companies(request):
        return response(repository.companies(100, name=request.query_params.get("name")))

    async def company(request):
        return response(repository.company(request.path_params["id"]))

    async def source(request):
        return response(Catalog(repository).document(request.path_params["id"]))

    async def search(request):
        return response(
            Catalog(repository).search(
                request.query_params.getlist("term"),
                filters=Filters(
                    city=request.query_params.get("city"),
                    company=request.query_params.get("company"),
                ),
                limit=20,
            )
        )

    async def manual(request):
        jd = ManualJD.model_validate(await read_json(request))

        def save():
            with import_lock:
                return import_jd(repository, RawArchive(settings.raw_directory, credentials), jd)

        return response(await run_in_threadpool(save), 201)

    def busy():
        return operation_lock.locked() or any(
            not task.done() for task in [*tasks.values(), *operation_tasks.values()]
        )

    async def run_research(identity, data, resume=False):
        try:
            result = await research(
                repository,
                data.question,
                settings,
                filters=data.filters,
                job_ids=data.job_ids,
                offline=data.offline,
                max_calls=data.max_calls,
                timeout=data.timeout,
                model=model,
                checkpoint=(store, identity),
                resume=resume,
                memory=memory,
                allow_public=data.allow_public,
            )
            store.save(identity, result=result, state="finished")
            from work_observer.reports.inbox import InboxService

            try:
                InboxService(repository).create(
                    "research",
                    "研究更新 · " + data.question[:100],
                    "状态："
                    + {
                        "completed": "研究完成",
                        "evidence_only": "仅整理原文证据",
                        "insufficient_evidence": "正文资料不足",
                        "incomplete": "达到研究上限",
                        "failed": "研究未完成",
                        "partial": "已保留部分结果",
                    }.get(result["status"], "研究已停止")
                    + "。关键结论仍需核对原文。"
                    + "；".join(result.get("gaps", [])[:3]),
                    related_id=identity,
                    dedupe_key="research:" + identity,
                )
            except Exception:
                store.save(identity, error_code="INBOX_UPDATE_FAILED")
        except asyncio.CancelledError:
            store.save(identity, state="interrupted")
            raise
        except Exception as exc:
            store.save(identity, state="failed", error_code=error_code(exc))

    def launch(identity, data, resume=False):
        store.save(identity, state="running")
        tasks[identity] = asyncio.create_task(run_research(identity, data, resume))

    async def start_research(request):
        data = ResearchInput.model_validate(await read_json(request))
        if not data.question.strip():
            raise ProbeError("INVALID_QUESTION")
        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "已有研究正在进行，请先等待它完成。"},
                409,
            )
        run = store.create(data.model_dump(mode="json"))
        launch(run["id"], data)
        return response({"id": run["id"], "state": "running"}, 202)

    def get_run(identity):
        run = store.get(identity)
        if not run:
            raise ProbeError("RESEARCH_NOT_FOUND")
        return run

    async def list_research(request):
        # 检查点、模型上下文不交给浏览器，历史仅展示业务问题与状态。
        return response(
            [
                {key: run.get(key) for key in ("id", "state", "created_at", "saved", "error_code")}
                | {
                    "question": run.get("input", {}).get("question", "研究"),
                    "status": (run.get("result") or {}).get("status"),
                }
                for run in store.list()
            ]
        )

    async def get_research(request):
        run = get_run(request.path_params["id"])
        data = {
            key: run.get(key)
            for key in ("id", "state", "created_at", "result", "saved", "error_code")
        }
        checkpoint = store.load_checkpoint(run["id"])
        if checkpoint:
            partial = checkpoint.get("result") or {}
            data["progress"] = {
                key: partial[key]
                for key in ("plan", "trace", "model_calls", "scope")
                if key in partial
            }
        data["project_id"] = run.get("input", {}).get("project_id")
        data["resumable"] = bool(
            checkpoint and run["state"] in {"interrupted", "failed"} and not data["project_id"]
        )
        data["result"] = audited(data.get("result"))
        return response(data)

    async def resume_research(request):
        run = get_run(request.path_params["id"])
        if run.get("input", {}).get("project_id"):
            return response(
                {
                    "error_code": "PROJECT_RUN_RESUME_FROM_PROJECT",
                    "message": "请从持续研究项目继续此步骤，以保留项目范围和总预算。",
                },
                409,
            )
        if busy():
            return response({"error_code": "RESEARCH_BUSY", "message": "已有研究正在进行。"}, 409)
        if run["state"] not in {"interrupted", "failed"} or not store.load_checkpoint(run["id"]):
            return response(
                {
                    "error_code": "RESEARCH_NOT_RESUMABLE",
                    "message": "这次研究没有可继续的中断进度。",
                },
                409,
            )
        data = ResearchInput.model_validate(run["input"])
        launch(run["id"], data, resume=True)
        return response({"id": run["id"], "state": "running"}, 202)

    async def cancel_research(request):
        identity = request.path_params["id"]
        get_run(identity)
        task = tasks.get(identity)
        project_id = get_run(identity).get("input", {}).get("project_id")
        if project_id:
            task = operation_tasks.get("project:" + project_id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if get_run(identity)["state"] == "running":
                store.save(identity, state="interrupted")
        return response({"id": identity, "state": get_run(identity)["state"]})

    async def save_research(request):
        run = get_run(request.path_params["id"])
        if run["state"] != "finished" or not run["result"]:
            return response(
                {"error_code": "RESULT_NOT_READY", "message": "结果尚未生成，暂时不能保存。"}, 409
            )
        if not run.get("saved"):
            saved = save_result(public(run["result"], credentials), reports_dir)
            store.save(run["id"], saved={"report_id": saved["report_id"]})
        return response(get_run(run["id"])["saved"])

    def audited(result):
        from work_observer.quality.reviews import QualityReviewService
        from work_observer.reports.results import audit_result

        if not result:
            return result
        business_review = {"status": "pending", "reviewer_kind": None}
        if result.get("status") == "completed" and result.get("run_id"):
            try:
                reviews = QualityReviewService(store, repository).list_run(result["run_id"])
                latest = next((r for r in reviews if not r["stale_result"]), None)
                if latest:
                    business_review = {
                        key: latest.get(key) for key in ("status", "reviewer_kind", "decision")
                    }
            except ProbeError:
                pass
        return {
            **result,
            "audit": audit_result(result, repository),
            "business_review": business_review,
        }

    async def forget_memory(request):
        if busy():
            return response(
                {
                    "error_code": "RESEARCH_BUSY",
                    "message": "请先暂停或等待正在进行的研究与任务，再忘记记录并清除派生结果。",
                },
                409,
            )
        from work_observer.memory.lifecycle import forget_personal

        return response(forget_personal(repository, store, request.path_params["id"], reports_dir))

    async def list_memories(request):
        items = memory.list(include_history=request.query_params.get("history") == "1")
        project_id = request.query_params.get("project_id")
        if project_id:
            items = [
                item
                for item in items
                if item["scope"] != "project" or item["project_id"] == project_id
            ]
        return response([{**item, "validity": memory.validity(item["id"])} for item in items])

    async def create_memory(request):
        data = MemoryInput.model_validate(await read_json(request))
        kwargs = {
            key: getattr(data, key)
            for key in (
                "job_id",
                "scope",
                "project_id",
                "subject",
                "valid_from",
                "valid_until",
                "origin",
            )
        }
        content = data.content
        if data.kind == "knowledge":
            if data.source_run_id is None or data.claim_index is None:
                raise ProbeError("KNOWLEDGE_RESEARCH_REQUIRED")
            run = get_run(data.source_run_id)
            result = run.get("result") or {}
            claims = result.get("claims", [])
            if result.get("status") != "completed" or data.claim_index >= len(claims):
                raise ProbeError("KNOWLEDGE_RESEARCH_REQUIRED")
            claim = claims[data.claim_index]
            content = claim["text"]
            evidence = {item["id"]: item for item in result.get("evidence", [])}
            kwargs.update(
                evidence=[evidence[key] for key in claim["evidence_ids"]],
                source_run_id=run["id"],
                origin="agent",
            )
        return response(memory.create(data.kind, content, **kwargs), 201)

    async def change_memory(request):
        identity, action = request.path_params["id"], request.path_params["action"]
        if action == "revise":
            data = MemoryRevision.model_validate(await read_json(request))
            return response(memory.revise(identity, data.content))
        if action == "withdraw":
            return response(memory.withdraw(identity))
        if action == "activate":
            return response(memory.activate(identity))
        if action in {"accept", "reject"}:
            return response(memory.resolve(identity, action))
        raise ProbeError("MEMORY_ACTION_DENIED")

    async def reports(request):
        return response(list_results(reports_dir, limit=100))

    async def report(request):
        return response(audited(read_result(request.path_params["id"], reports_dir)))

    async def download(request):
        result = public(audited(read_result(request.path_params["id"], reports_dir)), credentials)
        fmt = request.path_params["format"]
        if fmt not in {"json", "md"}:
            return Response(status_code=404)
        content = (
            json.dumps(result, ensure_ascii=False, indent=2) if fmt == "json" else render(result)
        )
        return Response(
            content,
            media_type="application/json" if fmt == "json" else "text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{result["report_id"]}.{fmt}"'},
        )

    async def handle_error(request, exc):
        if isinstance(exc, (ValidationError, ValueError)):
            code, message, status = (
                "INVALID_INPUT",
                "输入不符合要求，请检查必填内容、筛选条件和时间格式。",
                422,
            )
        else:
            code = error_code(exc)
            status = 404 if code.endswith("NOT_FOUND") else 400
            message = {
                "MANUAL_IDENTITY_CONFLICT": "该资料编号已用于另一岗位或公司，请更换资料编号。",
                "IMPORT_TOO_LARGE": "内容过大，请限制在 500 KB 以内。",
                "JSON_BODY_REQUIRED": "请使用页面表单或 JSON 格式提交。",
                "RESEARCH_NOT_FOUND": "找不到这次研究，请从研究历史重新选择。",
                "JOB_NOT_FOUND": "找不到该岗位，请刷新资料列表。",
                "REPORT_NOT_FOUND": "找不到这份已存研究。",
                "CSV_TOO_LARGE": "CSV内容请控制在500KB以内。",
                "CSV_ROW_LIMIT": "每批最多20行，请分批预览。",
                "INVALID_CSV_HEADERS": (
                    "CSV需要title、company、description表头，其他列请使用已支持的人工资料字段。"
                ),
                "INVALID_CSV_FORMAT": "CSV格式无法读取，请检查引号、分隔符与UTF-8编码。",
                "CSV_EMPTY": "CSV没有可预览的数据行。",
                "IMPORT_IMAGE_TOO_LARGE": "图片请控制在5MB以内，支持PNG、JPEG和WebP。",
                "INVALID_IMPORT_IMAGE": "请上传PNG、JPEG或WebP图片字节，不接受链接或其他格式。",
                "IMPORT_IMAGE_TYPE_MISMATCH": "图片格式与文件类型不一致，请重新选择原图。",
                "IMPORT_ASSET_NOT_FOUND": "找不到这张已归档图片，请重新选择并核对。",
                "IMPORT_ASSET_INTEGRITY_FAILED": "原图缺失或指纹已改变，请重新上传核对。",
                "IMAGE_MODEL_CONSENT_REQUIRED": "请明确勾选允许把这张图片发送到已配置模型。",
                "IMPORT_ASSET_DATA_KIND_MISMATCH": (
                    "图片与岗位草稿的真实或合成性质不一致，请重新核对。"
                ),
                "STRATEGY_EVALUATION_NOT_ACCEPTED": "这项候选尚未通过固定评测，暂时不能启用。",
                "STRATEGY_BASELINE_CHANGED_REEVALUATE": "当前基线已变化，请重新评测候选后再启用。",
                "STRATEGY_REQUIRES_NEW_CANDIDATE": "此版本已被拒绝或回退，请提出新的候选版本。",
                "STRATEGY_ALREADY_BASELINE": "当前已经使用稳定基线，无需回退。",
                "INVALID_RETRIEVAL_TIME": "历史截止时间需要明确时区，请使用页面时间选择框。",
                "KNOWLEDGE_RESEARCH_REQUIRED": "请选择已完成研究中的一条结论保存知识候选。",
                "INVALID_MEMORY_EVIDENCE": (
                    "知识候选需要可核对的岗位原文引用。公开搜索摘要暂不支持采纳。"
                ),
                "MEMORY_NOT_FOUND": "找不到这条记录，请刷新知识与偏好页面。",
                "MEMORY_SCOPE_VIOLATION": "原文引用与适用岗位不一致，请核对范围。",
                "MEMORY_SOURCE_INTEGRITY_FAILED": (
                    "引用的原始文件缺失或已改变，暂时不能采纳这条知识。"
                ),
                "RESEARCH_MEMORY_CHANGED_RESTART": (
                    "研究使用的偏好或纠正已变化，请按最新记录开始新研究。"
                ),
                "PROJECT_CHANGED_REFRESH": "项目已被其他操作更新，请刷新项目后再保存。",
                "PROJECT_ROUND_LIMIT": "已达到项目轮次上限。请保留本项目结果，按新目标建立新项目。",
                "STEP_SCOPE_CHANGED_REPLAN": "目标或范围已修订，请在当前范围新增调查步骤。",
                "STEP_NEW_ROUND_REQUIRED": "本步没有可恢复的检查点，请补充资料后新增调查轮次。",
                "STEP_EVIDENCE_REQUIRED": "本步尚未形成带原文引用的模型回答，不能标为已核对完成。",
                "PROJECT_FORGOTTEN_RESTART": "相关记忆已忘记，项目上下文已清除，请建立新项目。",
            }.get(code, "操作未完成，请核对输入；已有资料不会因此删除。")
        return response({"error_code": code, "message": message}, status)

    routes = [
        Route("/", index),
        Route("/assets/{name}", asset),
        Route("/api/overview", overview),
        Route("/api/jobs", jobs),
        Route("/api/jobs/{id}/history", history),
        Route("/api/jobs/{id}", job),
        Route("/api/companies", companies),
        Route("/api/companies/{id}", company),
        Route("/api/sources/{id}", source),
        Route("/api/search", search),
        Route("/api/import", manual, methods=["POST"]),
        Route("/api/research", start_research, methods=["POST"]),
        Route("/api/research", list_research),
        Route("/api/research/{id}/resume", resume_research, methods=["POST"]),
        Route("/api/research/{id}/cancel", cancel_research, methods=["POST"]),
        Route("/api/memories", list_memories),
        Route("/api/memories/{id}", forget_memory, methods=["DELETE"]),
        Route("/api/memories", create_memory, methods=["POST"]),
        Route("/api/memories/{id}/{action}", change_memory, methods=["POST"]),
        Route("/api/research/{id}/save", save_research, methods=["POST"]),
        Route("/api/research/{id}", get_research),
        Route("/api/reports", reports),
        Route("/api/reports/{id}/download/{format}", download),
        Route("/api/reports/{id}", report),
    ]
    routes.extend(
        product_routes(
            repository=lambda: repository,
            settings=settings,
            model=model,
            response=response,
            read_json=read_json,
            busy=busy,
            operation_lock=operation_lock,
        )
    )
    routes.extend(
        operations_routes(
            repository=lambda: repository,
            settings=settings,
            response=response,
            read_json=read_json,
            busy=busy,
            operation_lock=operation_lock,
            tasks=operation_tasks,
        )
    )
    routes.extend(
        import_routes(
            repository=lambda: repository,
            settings=settings,
            credentials=credentials,
            response=response,
            read_json=read_json,
            busy=busy,
            operation_lock=operation_lock,
            import_lock=import_lock,
        )
    )
    routes.extend(schema_routes())
    from work_observer.api.data_quality import data_quality_routes
    from work_observer.api.knowledge import knowledge_routes
    from work_observer.api.projects import project_routes
    from work_observer.api.quality import quality_routes
    from work_observer.api.updates import update_routes

    routes.extend(
        knowledge_routes(
            repository=lambda: repository, response=response, read_json=read_json, busy=busy
        )
    )
    routes.extend(
        quality_routes(
            repository=lambda: repository,
            store=lambda: store,
            response=response,
            read_json=read_json,
            busy=busy,
        )
    )
    routes.extend(
        data_quality_routes(
            repository=lambda: repository, response=response, read_json=read_json, busy=busy
        )
    )
    routes.extend(
        update_routes(
            repository=lambda: repository,
            store=lambda: store,
            response=response,
            read_json=read_json,
            busy=busy,
        )
    )

    routes.extend(
        project_routes(
            repository=lambda: repository,
            store=lambda: store,
            settings=settings,
            model=model,
            response=response,
            read_json=read_json,
            busy=busy,
            tasks=operation_tasks,
            reports_dir=reports_dir,
        )
    )
    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers={
            ProbeError: handle_error,
            ValidationError: handle_error,
            ValueError: handle_error,
            Exception: handle_error,
        },
    )
    config = deployment_settings(settings)
    from work_observer.api.privacy import PrivacyRecoveryGuard
    from work_observer.memory.lifecycle import resume_erasures

    app.add_middleware(
        PrivacyRecoveryGuard,
        store=lambda: store,
        recover=lambda: resume_erasures(repository, store, reports_dir),
    )
    app.add_middleware(LocalGuard, token=token, public_origin=config[0] if config else "")
    app.add_middleware(DeploymentGuard, settings=settings)
    return app
