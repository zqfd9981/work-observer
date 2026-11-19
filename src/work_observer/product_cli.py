"""完整产品CLI，页面与命令共享同一服务。"""

import asyncio
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from work_observer.config import Settings
from work_observer.memory.service import MemoryService
from work_observer.research.store import ResearchStore
from work_observer.storage.repository import Repository


@contextmanager
def session(db, env_file, reports_dir=Path("reports")):
    settings = Settings.load(env_file)
    path = db or settings.database_path
    repo = Repository(path)
    store = ResearchStore(path.parent / "checkpoints.db", str(path.resolve()))
    repo.bind_research_store(store)
    try:
        from work_observer.memory.lifecycle import resume_erasures

        resume_erasures(repo, store, reports_dir)
        yield settings, repo, store
    finally:
        store.close()
        repo.close()


def echo(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def register(app):
    from work_observer.cli import collection_error

    @app.command("demo-init")
    def demo_init(directory: Path = Path("data/demo")):
        """在全新目录生成可公开分发的合成演示库；零网络调用。"""
        from work_observer.demo import create_demo

        try:
            echo(create_demo(directory))
        except Exception as exc:
            collection_error(exc)

    @app.command("import-csv")
    def import_csv(
        file: Path, commit: bool = False, db: Path | None = None, env_file: Path = Path(".env")
    ):
        """先预览最多20行CSV；核对后用--commit逐行导入，失败不回滚成功行。"""
        from work_observer.connectors.import_drafts import commit_rows, csv_preview
        from work_observer.storage.archive import RawArchive

        try:
            preview = csv_preview(file.read_text(encoding="utf-8-sig"))
            if not commit:
                echo(preview)
                return
            with session(db, env_file) as (settings, repo, _):
                rows = [
                    {"row_number": row["row_number"], "jd": row["draft"]} for row in preview["rows"]
                ]
                echo(
                    commit_rows(
                        repo,
                        RawArchive(
                            settings.raw_directory,
                            [
                                settings.model_api_key.get_secret_value(),
                                settings.tavily_api_key.get_secret_value(),
                            ],
                        ),
                        rows,
                    )
                )
        except Exception as exc:
            collection_error(exc)

    @app.command("import-image")
    def import_image(
        file: Path,
        allow_model: bool = False,
        data_kind: str = "user_provided",
        draft_file: Path | None = None,
        db: Path | None = None,
        env_file: Path = Path(".env"),
    ):
        """归档截图；显式--allow-model才发送一次视觉请求。只产生草稿，不自动写岗位。"""
        from work_observer.connectors.import_drafts import ImportDraftService
        from work_observer.connectors.mcp_probe import ProbeError

        try:
            if not file.is_file() or file.stat().st_size > 5_000_000:
                raise ProbeError("IMPORT_IMAGE_TOO_LARGE")
            with session(db, env_file) as (settings, repo, _):
                service = ImportDraftService(repo, settings.raw_directory / "import_assets")
                asset = service.upload(file.read_bytes(), data_kind=data_kind)
                result = (
                    asyncio.run(service.extract(asset["id"], settings, allow_model=True))
                    if allow_model
                    else {
                        "status": "archived_only",
                        "asset": asset,
                        "model_calls": 0,
                        "draft": None,
                    }
                )
                if draft_file and result.get("draft"):
                    draft = {
                        key: value for key, value in result["draft"].items() if value is not None
                    }
                    draft.update(
                        import_asset_id=asset["id"], ocr_reviewed=False, data_kind=data_kind
                    )
                    with draft_file.open("x", encoding="utf-8") as stream:
                        json.dump(draft, stream, ensure_ascii=False, indent=2)
                    result["draft_file"] = str(draft_file.resolve())
                    result["note"] = (
                        "请对照原图编辑草稿，确认后将ocr_reviewed改为true，再用import-jd导入。"
                    )
                echo(result)
        except Exception as exc:
            collection_error(exc)

    @app.command("status")
    def status(db: Path | None = None, env_file: Path = Path(".env")):
        """本地诊断数据库、配置与来源暂停；不做网络探测。"""
        from work_observer.maintenance import diagnose

        try:
            settings = Settings.load(env_file)
            if db:
                settings = settings.model_copy(update={"database_path": db})
            echo(diagnose(settings))
        except Exception as exc:
            collection_error(exc)

    @app.command("backup")
    def backup(
        destination: Path,
        db: Path | None = None,
        reports_dir: Path = Path("reports"),
        env_file: Path = Path(".env"),
    ):
        """停止服务后完整备份数据库、原始资料、检查点与报告；不包含.env。"""
        from work_observer.maintenance import backup_workspace

        try:
            echo(
                backup_workspace(
                    db or Settings.load(env_file).database_path, destination, reports_dir
                )
            )
        except Exception as exc:
            collection_error(exc)

    @app.command("product")
    def product(
        area: str,
        action: Annotated[str, typer.Argument()] = "list",
        id: str | None = None,
        file: Path | None = None,
        text: str | None = None,
        term: Annotated[list[str] | None, typer.Option()] = None,
        offline: bool = False,
        execute: bool = False,
        db: Path | None = None,
        reports_dir: Path = Path("reports"),
        env_file: Path = Path(".env"),
    ):
        """完整业务入口：profiles/match/retrieval/statistics/strategies/inbox/watchsets/tasks/schedules。

        结构化输入通过--file JSON；--id为岗位/任务/策略内部ID。详见docs/API合同.md。
        """
        from work_observer.analysis.profiles import ProfileService
        from work_observer.connectors.mcp_probe import ProbeError
        from work_observer.reports.inbox import InboxService
        from work_observer.retrieval.enhanced import RetrievalService
        from work_observer.tasks.service import TaskService
        from work_observer.tracking.evaluation import StrategyService

        try:
            data = json.loads(file.read_text(encoding="utf-8-sig")) if file else {}
            if not isinstance(data, dict):
                raise ProbeError("JSON_OBJECT_REQUIRED")
            with session(db, env_file, reports_dir) as (settings, repo, store):
                result = None
                if area == "projects":
                    from work_observer.api.projects import ProjectInput, StepInput, plan_project
                    from work_observer.research.projects import ProjectService, execute_project

                    service = ProjectService(store)
                    if action == "list":
                        result = service.list()
                    elif action == "get":
                        result = service.get(id)
                        result["usage"] = service.usage(result)
                    elif action == "forget":
                        from work_observer.memory.lifecycle import forget_project

                        result = forget_project(repo, store, id, reports_dir)
                    elif action == "create":
                        value = ProjectInput.model_validate(data)
                        for job_id in value.job_ids:
                            repo.job(job_id)
                        result = service.create(
                            **value.model_dump(exclude={"plan_steps", "offline"})
                        )
                        if value.plan_steps:
                            result = plan_project(service, result, value.offline)
                    elif action == "ask":
                        result = service.add(id, **StepInput.model_validate(data).model_dump())
                    elif action == "revise":
                        from work_observer.api.projects import ProjectRevision

                        value = ProjectRevision.model_validate(data)
                        for job_id in value.job_ids:
                            repo.job(job_id)
                        result = service.revise(id, **value.model_dump())
                    elif action == "review":
                        from work_observer.api.projects import StepReview

                        result = service.review(
                            id,
                            data["step_id"],
                            repository=repo,
                            **StepReview.model_validate(
                                {k: v for k, v in data.items() if k != "step_id"}
                            ).model_dump(),
                        )
                    elif action == "refresh":
                        from work_observer.api.projects import StepRefresh

                        result = service.refresh_waiting(
                            id,
                            data["step_id"],
                            repo,
                            **StepRefresh.model_validate(
                                {k: v for k, v in data.items() if k != "step_id"}
                            ).model_dump(),
                        )
                    elif action == "repair":
                        from work_observer.api.projects import StepRepair

                        result = service.repair_reviewed(
                            id,
                            data["step_id"],
                            repo,
                            **StepRepair.model_validate(
                                {k: v for k, v in data.items() if k != "step_id"}
                            ).model_dump(),
                        )
                    elif action == "run":
                        from work_observer.storage.locks import exclusive

                        with exclusive(repo.engine.url.database):
                            service.recover()
                            result = asyncio.run(
                                execute_project(service, id, repo, settings, _lock_held=True)
                            )
                elif area == "unified" and action in {"list", "run"}:
                    from work_observer.api.knowledge import UnifiedInput
                    from work_observer.retrieval.unified import UnifiedRetrieval

                    result = UnifiedRetrieval(repo).search(
                        **UnifiedInput.model_validate(
                            {**data, "terms": term or data.get("terms", [])}
                        ).model_dump()
                    )
                elif area in {"domains", "relations", "domain-collection"}:
                    from work_observer.api.knowledge import (
                        DomainCollectionInput,
                        DomainInput,
                        KnowledgeReviewInput,
                        RelationInput,
                    )
                    from work_observer.knowledge.service import DomainKnowledgeService

                    service = DomainKnowledgeService(repo)
                    if area == "domain-collection" and action in {"list", "run"}:
                        result = service.collection(
                            **DomainCollectionInput.model_validate(data).model_dump()
                        )
                    elif action == "list":
                        result = (
                            service.list_domains(include_history=True)
                            if area == "domains"
                            else service.list_relations(include_history=True)
                        )
                    elif action == "create":
                        schema, method = (
                            (DomainInput, service.propose_domain)
                            if area == "domains"
                            else (RelationInput, service.propose_relation)
                        )
                        result = method(**schema.model_validate(data).model_dump())
                    elif action == "review":
                        method = (
                            service.review_domain if area == "domains" else service.review_relation
                        )
                        result = method(
                            id, **KnowledgeReviewInput.model_validate(data).model_dump()
                        )
                elif area == "data-quality":
                    from work_observer.api.data_quality import (
                        DuplicateReviewInput,
                        DuplicateScanInput,
                        ScreenshotRegionInput,
                    )
                    from work_observer.data_quality.service import DataQualityService

                    service = DataQualityService(repo)
                    if action in {"scan", "list"}:
                        result = service.duplicates(
                            **DuplicateScanInput.model_validate(data).model_dump()
                        )
                    elif action == "review":
                        value = DuplicateReviewInput.model_validate(data)
                        result = service.review_duplicate(**value.model_dump())
                    elif action == "reviews":
                        result = service.reviews()
                    elif action == "targets":
                        result = service.screenshot_targets()
                    elif action == "regions":
                        result = service.regions(job_id=id)
                    elif action == "region-add":
                        result = service.create_region(
                            **ScreenshotRegionInput.model_validate(data).model_dump()
                        )
                    elif action == "region-withdraw":
                        result = service.withdraw_region(id)
                elif area == "profile-quality":
                    from work_observer.api.profile_quality import ProfileQualityReviewInput
                    from work_observer.quality.profile_reviews import ProfileQualityReviewService

                    service = ProfileQualityReviewService(store, repo)
                    if action == "list":
                        result = service.overview()
                    elif action == "packet":
                        result = service.packet(id)
                    elif action == "reviews":
                        result = service.list_reviews(id)
                    elif action == "review":
                        result = service.submit(
                            id, ProfileQualityReviewInput.model_validate(data).model_dump()
                        )
                elif area == "quality":
                    from work_observer.api.quality import QualityReviewInput
                    from work_observer.quality.reviews import QualityReviewService

                    service = QualityReviewService(store, repo)
                    if action == "list":
                        result = service.overview()
                    elif action == "packet":
                        result = service.packet(id)
                    elif action == "reviews":
                        result = service.list_run(id)
                    elif action == "review":
                        result = service.submit(
                            id, QualityReviewInput.model_validate(data).model_dump()
                        )
                elif area == "updates":
                    from work_observer.api.updates import UpdateCaptureInput, UpdateCompareInput
                    from work_observer.reports.domain_updates import DomainUpdateService

                    service = DomainUpdateService(store, repo)
                    if action == "list":
                        result = service.list()
                    elif action == "capture":
                        result = service.capture(
                            **UpdateCaptureInput.model_validate(data).model_dump()
                        )
                    elif action == "compare":
                        result = service.compare(
                            **UpdateCompareInput.model_validate(data).model_dump()
                        )
                    elif action == "report":
                        result = service.report(id)
                    elif action == "followup":
                        result = service.followup(id, text or data.get("note", ""))
                elif area == "profiles":
                    service = ProfileService(repo)
                    if action == "list":
                        result = service.list()
                    elif action == "get":
                        result = service.get(id)
                    elif action == "analyze":
                        result = asyncio.run(service.analyze(id, settings, offline=offline))
                    elif action == "correct":
                        result = service.set_domain_correction(id, data["domains"], data["reason"])
                elif area == "match":
                    service = ProfileService(repo)
                    if action in {"list", "run"}:
                        result = service.compare_personal(
                            filters=data.get("filters"), preferences=data.get("preferences")
                        )
                    elif action == "conditions":
                        result = service.get_preferences()
                    elif action == "save":
                        result = service.save_preferences(data)
                elif area in {"retrieval", "statistics"} and action in {"run", "list"}:
                    service = RetrievalService(repo)
                    kwargs = {
                        key: data[key] for key in ("filters", "job_ids", "as_of") if key in data
                    }
                    result = (service.search if area == "retrieval" else service.stats)(
                        term or data.get("terms"), **kwargs
                    )
                elif area == "strategies":
                    service = StrategyService(repo)
                    if action == "list":
                        result = {
                            "strategies": service.list(),
                            "experiments": service.experiments(),
                            "events": service.events(),
                            "active_config": service.active_config(),
                        }
                    elif action == "create":
                        result = service.create(data["name"], data["aliases"])
                    elif action == "evaluate":
                        result = service.evaluate(id)
                    elif action == "activate":
                        result = service.activate(id)
                    elif action == "monitor":
                        result = service.monitor()
                    elif action == "rollback":
                        result = service.rollback(text or "显式CLI回退")
                elif area == "inbox":
                    service = InboxService(repo)
                    if action in {"list", "unread"}:
                        result = service.list(unread=action == "unread")
                    elif action == "read":
                        result = service.mark_read(id)
                    elif action == "resolve":
                        result = service.resolve(id)
                    elif action == "followup":
                        result = service.add_followup(text, source_run_id=id)
                    elif action == "create":
                        result = service.create(
                            data["kind"],
                            data["title"],
                            data["body"],
                            related_id=data.get("related_id"),
                        )
                elif area == "watchsets":
                    service = TaskService(repo)
                    if action == "list":
                        result = service.watchsets(include_history=True)
                    elif action == "save":
                        result = service.save_watchset(data["name"], data["spec"])
                elif area == "tasks":
                    service = TaskService(repo)
                    if action == "list":
                        result = service.list()
                    elif action == "get":
                        result = service.get(id)
                    elif action == "create":
                        result = service.create_collection(
                            data["watchset_id"],
                            mode=data.get("mode", "live"),
                            replay_bundle=data.get("replay_bundle"),
                            dedupe_key=data.get("dedupe_key"),
                        )
                    elif action == "run":
                        result = asyncio.run(service.run(id, settings))
                    elif action == "retry":
                        result = service.retry(id)
                elif area == "schedules":
                    service = TaskService(repo)
                    if action == "list":
                        result = service.schedules()
                    elif action == "save":
                        result = service.save_schedule(data.pop("watchset_id"), **data)
                    elif action == "tick":
                        result = asyncio.run(service.tick(settings, run=execute))
                if result is None:
                    raise ProbeError("PRODUCT_ACTION_DENIED")
                echo(result)
        except Exception as exc:
            collection_error(exc)

    @app.command("worker")
    def worker(
        once: bool = False,
        interval: Annotated[int, typer.Option(min=10, max=3600)] = 30,
        db: Path | None = None,
        env_file: Path = Path(".env"),
    ):
        """显式启动本地观察时段执行器；默认无已启用时段。Ctrl+C停止，来源暂停仍有效。"""
        from work_observer.tasks.service import TaskService

        async def work():
            with session(db, env_file) as (settings, repo, _):
                service = TaskService(repo)
                while True:
                    result = await service.tick(settings, run=True, limit=1)
                    if result.get("scheduled") or result.get("executed") or once:
                        echo(result)
                    if once:
                        return
                    await asyncio.sleep(interval)

        try:
            asyncio.run(work())
        except KeyboardInterrupt:
            typer.echo("本地执行器已停止，原始资料和执行记录已保留。")
        except Exception as exc:
            collection_error(exc)

    @app.command("restore")
    def restore(bundle: Path, destination: Path):
        """校验备份并恢复到全新目录，不覆盖现有资料库。"""
        from work_observer.maintenance import restore_workspace

        try:
            echo(restore_workspace(bundle, destination))
        except Exception as exc:
            collection_error(exc)

    @app.command("research-runs")
    def research_runs(db: Path | None = None, env_file: Path = Path(".env")):
        """列出跨重启保留的研究，不调用模型。"""
        try:
            with session(db, env_file) as (_, _, store):
                echo(
                    [
                        {key: row.get(key) for key in ("id", "state", "created_at", "saved")}
                        | {
                            "question": row["input"]["question"],
                            "status": (row.get("result") or {}).get("status"),
                        }
                        for row in store.list()
                    ]
                )
        except Exception as exc:
            collection_error(exc)

    @app.command("research-run")
    def research_run(id: str, db: Path | None = None, env_file: Path = Path(".env")):
        """查看研究业务结果；不输出模型上下文或运行检查点。"""
        try:
            with session(db, env_file) as (_, _, store):
                row = store.get(id)
                echo(
                    {key: row.get(key) for key in ("id", "state", "result", "saved", "error_code")}
                )
        except Exception as exc:
            collection_error(exc)

    @app.command("research-resume")
    def research_resume(id: str, db: Path | None = None, env_file: Path = Path(".env")):
        """继续已中断研究，沿用原有范围、版本和累计预算。"""
        from work_observer.connectors.mcp_probe import ProbeError
        from work_observer.reports.results import render
        from work_observer.research.agent import research
        from work_observer.retrieval.catalog import Filters

        try:
            with session(db, env_file) as (settings, repo, store):
                row = store.get(id)
                if row["state"] == "finished" or not store.load_checkpoint(id):
                    raise ProbeError("RESEARCH_NOT_RESUMABLE")
                params = row["input"]
                if params.get("project_id"):
                    raise ProbeError("PROJECT_RUN_RESUME_FROM_PROJECT")
                result = asyncio.run(
                    research(
                        repo,
                        params["question"],
                        settings,
                        filters=Filters.model_validate(params.get("filters", {})),
                        job_ids=params.get("job_ids"),
                        checkpoint=(store, id),
                        resume=True,
                        approach=params.get("approach", "standard"),
                        coverage_mode=params.get("coverage_mode", "all"),
                    )
                )
                store.save(id, result=result, state="finished")
                typer.echo(render(result))
        except Exception as exc:
            collection_error(exc)

    @app.command("memories")
    def memories(history: bool = False, db: Path | None = None, env_file: Path = Path(".env")):
        """查看当前偏好、纠正与知识，或显式查看历史。"""
        try:
            with session(db, env_file) as (_, repo, _):
                echo(MemoryService(repo).list(include_history=history))
        except Exception as exc:
            collection_error(exc)

    @app.command("memory-add")
    def memory_add(
        kind: str,
        content: str,
        job_id: str | None = None,
        scope: str | None = None,
        project_id: str | None = None,
        subject: str | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        origin: str = "user",
        db: Path | None = None,
        env_file: Path = Path(".env"),
    ):
        """保存分层偏好、纠正、假设或方法；知识候选请用memory-propose。"""
        try:
            with session(db, env_file) as (_, repo, _):
                echo(
                    MemoryService(repo).create(
                        kind,
                        content,
                        job_id=job_id,
                        scope=scope,
                        project_id=project_id,
                        subject=subject,
                        valid_from=valid_from,
                        valid_until=valid_until,
                        origin=origin,
                    )
                )
        except Exception as exc:
            collection_error(exc)

    @app.command("memory-change")
    def memory_change(
        id: str,
        action: str,
        content: str | None = None,
        reports_dir: Path = Path("reports"),
        db: Path | None = None,
        env_file: Path = Path(".env"),
    ):
        """revise更新、withdraw撤回、activate采纳；accept/reject审核冲突。"""
        from work_observer.connectors.mcp_probe import ProbeError

        try:
            with session(db, env_file, reports_dir) as (_, repo, store):
                service = MemoryService(repo)
                if action == "revise":
                    data = service.revise(id, content)
                elif action == "withdraw":
                    data = service.withdraw(id)
                elif action == "activate":
                    data = service.activate(id)
                elif action in {"accept", "reject"}:
                    data = service.resolve(id, action)
                elif action == "forget":
                    from work_observer.memory.lifecycle import forget_personal

                    data = forget_personal(repo, store, id, reports_dir)
                else:
                    raise ProbeError("MEMORY_ACTION_DENIED")
                echo(data)
        except Exception as exc:
            collection_error(exc)

    @app.command("memory-propose")
    def memory_propose(
        run_id: str,
        claim_index: Annotated[int, typer.Argument(min=0)],
        job_id: str | None = None,
        db: Path | None = None,
        env_file: Path = Path(".env"),
    ):
        """从已完成研究结论保存知识候选，引用仍回链原始JD。"""
        from work_observer.connectors.mcp_probe import ProbeError

        try:
            with session(db, env_file) as (_, repo, store):
                result = store.get(run_id).get("result") or {}
                if result.get("status") != "completed" or claim_index >= len(result["claims"]):
                    raise ProbeError("KNOWLEDGE_RESEARCH_REQUIRED")
                claim = result["claims"][claim_index]
                evidence = {ev["id"]: ev for ev in result["evidence"]}
                echo(
                    MemoryService(repo).create(
                        "knowledge",
                        claim["text"],
                        job_id=job_id,
                        evidence=[evidence[key] for key in claim["evidence_ids"]],
                        source_run_id=run_id,
                        origin="agent",
                    )
                )
        except Exception as exc:
            collection_error(exc)

    @app.command("compare-history")
    def compare_history(
        job_id: str,
        before: str | None = None,
        after: str | None = None,
        db: Path | None = None,
        env_file: Path = Path(".env"),
    ):
        """确定性比较已保存的两个详情版本，不重新访问来源。"""
        from work_observer.research.history import HistoryService

        try:
            with session(db, env_file) as (_, repo, _):
                echo(HistoryService(repo).compare(job_id, before, after))
        except Exception as exc:
            collection_error(exc)
