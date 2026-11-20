"""与运行路由和Pydantic入参同步的离线API合同，无外部CDN依赖。"""

import html
import re

from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route


def openapi(routes):
    from work_observer import __version__
    from work_observer.analysis.profiles import PersonalPreferences
    from work_observer.api.career import (
        CareerGoalInput,
        CareerInput,
        CareerResearchInput,
        ExperimentInput,
        InsightInput,
        ResumeInput,
        StoryInput,
        TaskImport,
        TaskUpdate,
    )
    from work_observer.api.data_quality import SCHEMA_MODELS as DATA_QUALITY_MODELS
    from work_observer.api.imports import CSVCommitInput, CSVPreviewInput, ImageExtractInput
    from work_observer.api.knowledge import (
        DomainCollectionInput,
        DomainInput,
        KnowledgeDomainCorrection,
        KnowledgeReviewInput,
        RelationInput,
        ResearchKnowledgeInput,
        UnifiedInput,
    )
    from work_observer.api.operations import (
        CollectionTaskInput,
        FollowupInput,
        ScheduleInput,
        WatchsetInput,
    )
    from work_observer.api.product import (
        DomainCorrectionInput,
        MatchInput,
        ProfileInput,
        PublicDocumentInput,
        PublicDocumentQuery,
        RetrievalInput,
        RollbackInput,
        StrategyInput,
        WorkMaterialInput,
        WorkMaterialRevisionInput,
    )
    from work_observer.api.profile_quality import SCHEMA_MODELS as PROFILE_QUALITY_MODELS
    from work_observer.api.projects import (
        ProjectInput,
        ProjectRevision,
        ProjectRunInput,
        ProjectTitle,
        StepInput,
        StepRefresh,
        StepReview,
    )
    from work_observer.api.quality import QualityReviewInput
    from work_observer.api.research_benchmarks import SCHEMA_MODELS as BENCHMARK_MODELS
    from work_observer.api.trials import (
        TrialFeedbackInput,
        TrialReviewInput,
        TrialRollbackInput,
        TrialSearchInput,
        TrialShadowInput,
    )
    from work_observer.api.updates import (
        UpdateCaptureInput,
        UpdateCompareInput,
        UpdateFollowupInput,
    )
    from work_observer.api.web import JobQuery, MemoryInput, MemoryRevision, ResearchInput
    from work_observer.api.workflows import WorkflowInput, WorkflowRunInput, WorkflowScopeInput
    from work_observer.connectors.manual import ManualJD
    from work_observer.research.run_history import HistoryQuery

    models = {
        ("/api/career", "POST"): CareerInput,
        ("/api/career/{id}", "PATCH"): CareerGoalInput,
        ("/api/career/{id}/stories", "POST"): StoryInput,
        ("/api/career/{id}/stories/{story_id}", "PATCH"): StoryInput,
        ("/api/career/{id}/prepare", "POST"): CareerResearchInput,
        ("/api/career/{id}/resume", "PATCH"): ResumeInput,
        ("/api/career/{id}/insights", "POST"): InsightInput,
        ("/api/career/{id}/experiments", "POST"): ExperimentInput,
        ("/api/career/{id}/tasks", "POST"): TaskImport,
        ("/api/career/{id}/tasks/{task_id}", "PATCH"): TaskUpdate,
        ("/api/workflows", "POST"): WorkflowInput,
        ("/api/workflows/{id}", "PATCH"): WorkflowScopeInput,
        ("/api/workflows/{id}/run", "POST"): WorkflowRunInput,
        ("/api/trials/shadows", "POST"): TrialShadowInput,
        ("/api/trials/{id}/review", "POST"): TrialReviewInput,
        ("/api/trials/{id}/search", "POST"): TrialSearchInput,
        ("/api/trials/{id}/rollback", "POST"): TrialRollbackInput,
        ("/api/trials/{id}/feedback", "POST"): TrialFeedbackInput,
        ("/api/projects/{id}/steps/{step_id}/refresh", "POST"): StepRefresh,
        ("/api/updates/captures", "POST"): UpdateCaptureInput,
        ("/api/updates/compare", "POST"): UpdateCompareInput,
        ("/api/updates/reports/{id}/followup", "POST"): UpdateFollowupInput,
        ("/api/retrieval/unified", "POST"): UnifiedInput,
        ("/api/knowledge/domains", "POST"): DomainInput,
        ("/api/knowledge/domains/{id}/review", "POST"): KnowledgeReviewInput,
        ("/api/knowledge/relations", "POST"): RelationInput,
        ("/api/knowledge/research/{id}", "POST"): ResearchKnowledgeInput,
        ("/api/knowledge/relations/{id}/review", "POST"): KnowledgeReviewInput,
        ("/api/knowledge/collection", "POST"): DomainCollectionInput,
        ("/api/knowledge/jobs/{id}/domains", "POST"): KnowledgeDomainCorrection,
        ("/api/quality/runs/{id}/reviews", "POST"): QualityReviewInput,
        ("/api/projects", "POST"): ProjectInput,
        ("/api/projects/{id}", "PATCH"): ProjectRevision,
        ("/api/projects/{id}/title", "POST"): ProjectTitle,
        ("/api/projects/{id}/steps", "POST"): StepInput,
        ("/api/projects/{id}/run", "POST"): ProjectRunInput,
        ("/api/projects/{id}/steps/{step_id}/review", "POST"): StepReview,
        ("/api/imports/csv/preview", "POST"): CSVPreviewInput,
        ("/api/imports/csv/commit", "POST"): CSVCommitInput,
        ("/api/import-assets/{id}/extract", "POST"): ImageExtractInput,
        ("/api/import", "POST"): ManualJD,
        ("/api/research", "POST"): ResearchInput,
        ("/api/public-documents", "POST"): PublicDocumentInput,
        ("/api/work-materials", "POST"): WorkMaterialInput,
        ("/api/work-materials/{id}/revisions", "POST"): WorkMaterialRevisionInput,
        ("/api/memories", "POST"): MemoryInput,
        ("/api/memories/{id}/{action}", "POST"): MemoryRevision,
        ("/api/profiles/{id}", "POST"): ProfileInput,
        ("/api/profiles/{id}/correction", "POST"): DomainCorrectionInput,
        ("/api/matches", "POST"): MatchInput,
        ("/api/preferences", "POST"): PersonalPreferences,
        ("/api/retrieval", "POST"): RetrievalInput,
        ("/api/strategies", "POST"): StrategyInput,
        ("/api/strategies/rollback", "POST"): RollbackInput,
        ("/api/watchsets", "POST"): WatchsetInput,
        ("/api/schedules", "POST"): ScheduleInput,
        ("/api/tasks", "POST"): CollectionTaskInput,
        ("/api/inbox/followup", "POST"): FollowupInput,
    }
    models.update(DATA_QUALITY_MODELS)
    models.update(PROFILE_QUALITY_MODELS)
    models.update(BENCHMARK_MODELS)
    schemas = {
        "Error": {
            "type": "object",
            "required": ["error_code", "message"],
            "properties": {"error_code": {"type": "string"}, "message": {"type": "string"}},
        },
        "Counts": {
            "type": "object",
            "properties": {
                key: {"type": "integer", "minimum": 0}
                for key in ("scope_total", "matched", "unknown", "excluded", "candidate_details")
            },
        },
        "ResearchRecord": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "state": {
                    "type": "string",
                    "enum": ["running", "finished", "failed", "interrupted", "invalidated"],
                },
                "created_at": {"type": "string", "format": "date-time"},
                "result": {
                    "type": ["object", "null"],
                    "description": "问题、范围、计划、判断、证据、缺口、轨迹、"
                    "记忆/策略版本、复盘和用量。",
                },
                "resumable": {"type": "boolean"},
                "audit": {"type": "object"},
            },
        },
    }
    descriptions = {
        "profile-quality": "完整画像的原文判断、领域依据及核实问题逐项审核与缓存资格",
        "research-benchmarks": "冻结业务问题与方法、权威输出登记、匿名核对和同题配对",
        "workflows": "日常研究的有界画像、持续项目、审核等待、领域观察和变化报告",
        "trials": "冻结开发查询的旁路比较、独立人审、局部限额检索及自动回退",
        "projects": "持久目标与范围、追问澄清、调查队列、审核接续和整项目遗忘",
        "knowledge": "领域定义版本、工作关系与反例审核、完整集合及人工纠正",
        "quality": "逐判断语义支持与业务质量核对，区分人工与Agent辅助评审",
        "updates": "冻结观察面板，分离原文/样本/方法变化与明确个人目标影响",
        "data-quality": "跨入口疑似重复审核及截图文字精确人工区域引用",
        "jobs": "岗位资料与SQL筛选",
        "companies": "公司档案",
        "sources": "招聘原始资料完整性与版本",
        "research": "有界持久研究、进度、恢复及显式报告保存",
        "memories": "分层偏好、纠正、知识、假设与方法；有效期、来源和冲突审核",
        "reports": "已存结果与历史有效性",
        "profiles": "有证据的工作画像、领域及人工纠正",
        "matches": "显式个人条件逐项匹配与未知原因",
        "preferences": "结构化条件版本",
        "retrieval": "别名/范围/历史检索与字面统计",
        "strategies": "固定评测、显式启用及护栏回退",
        "operations": "观察任务、时段与更新收件箱",
        "watchsets": "观察范围配置版本",
        "schedules": "默认关闭的北京时间观察时段",
        "tasks": "有限采集任务与执行状态",
        "inbox": "本地后续问题、已读及处理状态",
        "public-documents": "已归档公开网页与完整性",
        "work-materials": "粘贴工作资料原文与来源说明；与公开网页获取分开标记",
        "imports": "CSV草稿预览与逐行明确导入",
        "import-assets": "截图归档、明确同意后的单次视觉草稿及原图核对",
    }
    paths = {}
    for route in routes:
        if (
            not isinstance(route, Route)
            or not route.path.startswith("/api/")
            or route.path in {"/api/docs", "/api/openapi.json"}
        ):
            continue
        for method in sorted(route.methods - {"HEAD"}):
            area = route.path.split("/")[2]
            parameters = [
                {"in": "path", "name": name, "required": True, "schema": {"type": "string"}}
                for name in re.findall(r"{(\w+)}", route.path)
            ]
            if route.path == "/api/jobs" and method == "GET":
                parameters.extend(
                    {"in": "query", "name": key, "required": False, "schema": schema}
                    for key, schema in JobQuery.model_json_schema()["properties"].items()
                )
            if route.path == "/api/research-history" and method == "GET":
                parameters.extend(
                    {"in": "query", "name": key, "required": False, "schema": schema}
                    for key, schema in HistoryQuery.model_json_schema()["properties"].items()
                )
            if route.path == "/api/public-documents" and method == "GET":
                parameters.extend(
                    {"in": "query", "name": key, "required": False, "schema": schema}
                    for key, schema in PublicDocumentQuery.model_json_schema()["properties"].items()
                )
            if route.path == "/api/search":
                parameters.extend(
                    [
                        {
                            "in": "query",
                            "name": "term",
                            "required": True,
                            "schema": {"type": "array", "items": {"type": "string"}},
                            "style": "form",
                            "explode": True,
                        },
                        *[
                            {"in": "query", "name": key, "schema": {"type": "string"}}
                            for key in ("city", "company")
                        ],
                    ]
                )
            if route.path == "/api/memories" and method == "GET":
                parameters.append(
                    {
                        "in": "query",
                        "name": "history",
                        "schema": {"type": "string", "enum": ["0", "1"]},
                    }
                )
            if route.path == "/api/reports" and method == "GET":
                parameters.extend(
                    [
                        {
                            "in": "query",
                            "name": "q",
                            "schema": {"type": "string", "maxLength": 200},
                        },
                        {"in": "query", "name": "status", "schema": {"type": "string"}},
                    ]
                )
            response_schema = {"type": "object", "additionalProperties": True}
            if (
                route.path
                in {
                    "/api/reports",
                    "/api/companies",
                    "/api/memories",
                    "/api/watchsets",
                    "/api/schedules",
                    "/api/tasks",
                    "/api/inbox",
                    "/api/collection-runs",
                }
                and method == "GET"
            ):
                response_schema = {"type": "array", "items": {"type": "object"}}
            if route.path == "/api/research" and method == "GET":
                response_schema = {"type": "array", "items": {"type": "object"}}
            elif route.path == "/api/research/{id}" and method == "GET":
                response_schema = {"$ref": "#/components/schemas/ResearchRecord"}
            elif route.path == "/api/jobs":
                response_schema = {
                    "type": "object",
                    "properties": {
                        "counts": {"$ref": "#/components/schemas/Counts"},
                        "jobs": {"type": "array", "items": {"type": "object"}},
                        "truncated": {"type": "boolean"},
                    },
                }
            success = (
                "202"
                if method == "POST"
                and (route.path == "/api/research" or route.path.endswith(("/run", "/resume")))
                else "201"
                if method == "POST"
                and route.path
                in {
                    "/api/import",
                    "/api/memories",
                    "/api/strategies",
                    "/api/watchsets",
                    "/api/schedules",
                    "/api/tasks",
                    "/api/inbox/followup",
                    "/api/profiles/{id}/correction",
                    "/api/import-assets",
                    "/api/public-documents",
                    "/api/work-materials",
                    "/api/work-materials/{id}/revisions",
                }
                else "200"
            )
            operation = {
                "operationId": method.lower()
                + "_"
                + re.sub(r"[^a-zA-Z0-9]+", "_", route.path).strip("_"),
                "summary": descriptions.get(area, "本地资料与状态"),
                "tags": [area],
                "parameters": parameters,
                "security": [{"BearerAuth": []}, {"SessionCookie": []}],
                "responses": {
                    success: {
                        "description": "已接受后台操作"
                        if success == "202"
                        else "成功；来源/分析/未知字段保持各自语义",
                        "content": {"application/json": {"schema": response_schema}},
                    }
                },
            }
            for status, description in (
                ("400", "业务参数或当前状态不允许"),
                ("401", "部署模式未登录"),
                ("403", "Host、Origin或写操作令牌不符"),
                ("404", "记录不存在"),
                ("409", "已有运行、结果未就绪或不可恢复"),
                ("422", "入参字段/范围/时间格式无效"),
            ):
                operation["responses"][status] = {
                    "description": description,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
                    },
                }
            model = models.get((route.path, method))
            if model:
                schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
                schemas.update(schema.pop("$defs", {}))
                schemas[model.__name__] = schema
                operation["requestBody"] = {
                    "required": "{action}" not in route.path
                    and route.path != "/api/projects/{id}/run",
                    "description": "revise修订需要content；activate采纳、withdraw撤回、"
                    "accept选择冲突值、reject否决冲突值均无需请求体。"
                    if "{action}" in route.path
                    else "只接受已定义字段，不接受认证参数或任意SQL。",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{model.__name__}"}
                        }
                    },
                }
            if route.path == "/api/import-assets" and method == "POST":
                operation["parameters"].append(
                    {
                        "in": "query",
                        "name": "data_kind",
                        "schema": {
                            "type": "string",
                            "enum": ["user_provided", "synthetic"],
                            "default": "user_provided",
                        },
                    }
                )
                operation["requestBody"] = {
                    "required": True,
                    "description": "最多5MB的PNG/JPEG/WebP原始字节；"
                    "只归档，不自动发送模型或入岗位库。",
                    "content": {
                        mime: {"schema": {"type": "string", "format": "binary"}}
                        for mime in ("image/png", "image/jpeg", "image/webp")
                    },
                }
            if route.path == "/api/imports/documents/extract" and method == "POST":
                operation["parameters"].append(
                    {
                        "in": "query",
                        "name": "filename",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                )
                operation["requestBody"] = {
                    "required": True,
                    "description": "最多8MB的DOCX/PDF字节；仅在本地提取正文，不保存、不调用模型。",
                    "content": {
                        "application/octet-stream": {
                            "schema": {"type": "string", "format": "binary"}
                        }
                    },
                }
            if route.path == "/api/import-assets/{id}/image":
                operation["responses"][success]["content"] = {
                    mime: {"schema": {"type": "string", "format": "binary"}}
                    for mime in ("image/png", "image/jpeg", "image/webp")
                }
            if "/download/" in route.path:
                operation["responses"][success]["content"] = {
                    "application/json": {"schema": {"type": "object"}},
                    "text/markdown": {"schema": {"type": "string"}},
                }
            paths.setdefault(route.path, {})[method.lower()] = operation
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Work Observer API",
            "version": __version__,
            "description": "单用户中文研究产品。默认仅本机访问；部署模式需要Bearer或签名会话。"
            "浏览器写操作另需主页meta中的x-wo-token；Bearer调用无需该CSRF令牌。"
            "招聘来源暂停不能通过API解除。时间为UTC ISO8601，观察不是发布时间，未知不是符合。",
        },
        "paths": paths,
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"},
                "SessionCookie": {"type": "apiKey", "in": "cookie", "name": "wo_session"},
            },
        },
    }


def schema_routes():
    async def specification(request):
        return JSONResponse(openapi(request.app.routes))

    async def documentation(request):
        schema = openapi(request.app.routes)
        rows = []
        for path, operations in schema["paths"].items():
            for method, operation in operations.items():
                rows.append(
                    "<tr><td>"
                    + method.upper()
                    + "</td><td><code>"
                    + html.escape(path)
                    + "</code></td><td>"
                    + html.escape(operation["summary"])
                    + "</td></tr>"
                )
        return HTMLResponse(
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>接口说明 · Work Observer</title><link rel="stylesheet" href="/assets/app.css">'
            '<main class="panel"><h1>Work Observer 接口说明</h1><p>'
            + html.escape(schema["info"]["description"])
            + "</p>"
            '<p><a href="/">返回工作空间</a> · '
            '<a href="/api/openapi.json">下载完整OpenAPI合同</a></p>'
            "<h2>操作合同</h2><p>POST /api/research 返回运行编号后轮询 GET /api/research/{id}；"
            "中断后显式继续，共用原预算。画像生成是有界等待接口，最多235秒；读取已存画像不调用模型。</p>"
            "<p>参数详情、JSON Schema及响应状态见OpenAPI文件；源码docs/API合同.md提供完整中文示例。"
            "公开正文接口只读取已归档记录，不接受任意URL访问。研究、补录和原文不会公网发布。</p>"
            '<div class="table-scroll"><table><thead><tr><th>方法</th>'
            "<th>地址</th><th>业务能力</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div></main></html>"
        )

    return [Route("/api/openapi.json", specification), Route("/api/docs", documentation)]
