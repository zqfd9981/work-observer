"""独立命令入口。终端仅显示固定状态和本地证据路径，不显示来源原文。"""

import asyncio
import json
import logging
import os
import re
import tomllib
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import httpx
import typer

from work_observer.config import Settings
from work_observer.connectors.http_probes import probe_model, probe_search
from work_observer.connectors.mcp_probe import ProbeError, probe_recruitment
from work_observer.evidence import Evidence

app = typer.Typer(
    help="Work Observer：岗位档案、人工补录与有据可查的研究。", pretty_exceptions_enable=False
)


class Target(StrEnum):
    all = "all"
    recruitment = "recruitment"
    model = "model"
    search = "search"


class ResearchApproach(StrEnum):
    standard = "standard"
    source_first = "source_first"
    work_map = "work_map"


class ResearchCoverage(StrEnum):
    all = "all"
    question = "question"


def failure(exc: Exception):
    if isinstance(exc, BaseExceptionGroup):
        return failure(exc.exceptions[0])
    if isinstance(exc, ProbeError):
        return {"status": "failed", "error_code": exc.code}
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return {"status": "failed", "error_code": "TIMEOUT"}
    if isinstance(exc, httpx.TransportError):
        return {"status": "failed", "error_code": "NETWORK_ERROR"}
    if isinstance(exc, FileNotFoundError):
        return {"status": "missing_config", "error_code": "CONFIG_OR_EXECUTABLE_NOT_FOUND"}
    # 不输出异常文本：可能包含密钥、命令行参数、认证信息或来源响应。
    return {"status": "failed", "error_code": "CONFIG_OR_PROTOCOL_ERROR"}


async def run_checks(settings, only, query, city, details, error_probe, tools_only=False):
    evidence = Evidence(
        secrets=[
            settings.model_api_key.get_secret_value(),
            settings.tavily_api_key.get_secret_value(),
        ]
    )
    report = {
        "milestone": "M0",
        "real_calls_only": True,
        "started_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "checks": {},
    }
    for name in ("recruitment", "model", "search"):
        if only not in ("all", name):
            continue
        try:
            progress = {}
            if name == "recruitment":
                config = settings.load_mcp()
                from work_observer.connectors.source_status import require_source_available

                require_source_available(config)
                if config.bearer_token_env:
                    evidence.secrets.append(os.getenv(config.bearer_token_env, ""))
                evidence.secrets.extend(
                    value
                    for key, value in config.env.items()
                    if re.search(r"key|token|secret|password|cookie|authorization", key, re.I)
                )
                result = await probe_recruitment(
                    config,
                    evidence,
                    query,
                    city,
                    details,
                    error_probe,
                    tools_only,
                    progress,
                )
            elif name == "model":
                result = await probe_model(settings, evidence)
            else:
                result = await probe_search(settings, evidence)
        except Exception as exc:
            result = {**progress, **failure(exc)}
            if progress.get("jobs_received"):
                result["status"] = "partial"
        report["checks"][name] = result
    report["m0_accepted"] = set(report["checks"]) == {"recruitment", "model", "search"} and all(
        r["status"] == "passed" for r in report["checks"].values()
    )
    report["finished_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    evidence.finish(report)
    return report, evidence.path


def execute(
    env_file, only, query="Agent", city="上海", details=2, error_probe=False, tools_only=False
):
    # 第三方库日志可能包含完整请求或响应，检查命令不转发。
    logging.disable(logging.CRITICAL)
    try:
        settings = Settings.load(env_file)
        report, path = asyncio.run(
            run_checks(
                settings,
                only,
                query,
                city,
                details,
                error_probe,
                tools_only,
            )
        )
    except Exception as exc:
        typer.echo(json.dumps(failure(exc), ensure_ascii=False))
        raise typer.Exit(1) from None
    for name, result in report["checks"].items():
        safe = {
            k: result[k]
            for k in (
                "status",
                "error_code",
                "required",
                "tools_count",
                "jobs_received",
                "details_received",
                "results_received",
                "structured_output",
                "tool_calling",
                "provider",
                "model",
                "api",
                "search_calls",
                "citations_received",
            )
            if k in result
        }
        typer.echo(f"{name}: {json.dumps(safe, ensure_ascii=False)}")
    typer.echo(f"本地证据：{path.resolve()}")
    typer.echo(f"M0 全部验收：{'通过' if report['m0_accepted'] else '未通过（见各项状态）'}")
    if any(r["status"] not in {"passed", "discovered"} for r in report["checks"].values()):
        raise typer.Exit(1)


@app.command()
def doctor(
    only: Target = Target.all,
    env_file: Path = Path(".env"),
    query: str = typer.Option("Agent", help="只搜索这一关键词的一页"),
    city: str = "上海",
    details: int = typer.Option(2, min=1, max=3),
    error_probe: bool = typer.Option(False, help="附加一次缺少详情必填参数的服务端校验"),
):
    """真实调用招聘、模型与搜索；缺少配置或失败返回非零退出码。"""
    execute(env_file, only.value, query, city, details, error_probe)


@app.command("mcp-tools")
def mcp_tools(env_file: Path = Path(".env")):
    """仅握手和保存工具结构，不搜索岗位；不能作为招聘验收通过。"""
    execute(env_file, "recruitment", tools_only=True)


def load_watchset(path, name):
    from work_observer.collection.contracts import WatchsetSpec

    with path.open("rb") as stream:
        specs = tomllib.load(stream).get("watchsets", {})
    if name not in specs:
        raise ProbeError("WATCHSET_NOT_FOUND")
    return WatchsetSpec.model_validate(specs[name])


def collection_summary(report):
    return {
        "run_id": report["id"],
        "watchset": report["watchset"],
        "watchset_version": report["watchset_version"],
        "mode": report["mode"],
        "status": report["status"],
        "stats": report["stats"],
        "list_coverage_limited": report["coverage"]["list_limited"],
        "detail_coverage_limited": report["coverage"]["details_limited"],
        "error_codes": [issue["code"] for issue in report["issues"]],
        "stop_reason": report["stop_reason"],
    }


def collection_error(exc):
    from work_observer.collection.service import error_code

    code = error_code(exc)
    messages = {
        "SOURCE_PAUSED_USE_LOCAL_DATA": "招聘来源处于本地暂停状态，未发送平台请求；"
        "可继续查询、人工导入和研究。",
        "INVALID_SOURCE_SCHEMA": "输入字段不符合要求；请核对必填字段、时间格式和选项取值。",
        "MANUAL_IDENTITY_CONFLICT": "此人工资料 ID 已用于其他标题或公司，请换一个 external_id。",
        "IMPORT_EXPECTS_ONE_OBJECT": "JSON 导入每次接受一个岗位对象。",
        "JOB_NOT_FOUND": "找不到该内部岗位 ID，请先运行 jobs。",
    }
    result = {"status": "failed", "error_code": code}
    if code in messages:
        result["message"] = messages[code]
    typer.echo(json.dumps(result, ensure_ascii=False))
    raise typer.Exit(1) from None


@app.command("db-init")
def db_init(db: Path | None = None, env_file: Path = Path(".env")):
    """初始化或升级 M1 SQLite；不启动采集。"""
    from work_observer.storage.database import upgrade

    logging.disable(logging.CRITICAL)
    try:
        path = db or Settings.load(env_file).database_path
        upgrade(path)
        typer.echo(f"业务数据库已就绪（已有库升级前自动备份并核对旧记录）：{path.resolve()}")
    except Exception as exc:
        collection_error(exc)


from work_observer.product_cli import register as register_product_commands  # noqa: E402

register_product_commands(app)

from work_observer.research.worker_cli import register as register_research_worker  # noqa: E402

register_research_worker(app)

from work_observer.workflow.cli import register as register_workflows  # noqa: E402

register_workflows(app)


def execute_collection(watchset, watchsets, db, env_file, bundle=None):
    from work_observer.collection.service import collect
    from work_observer.connectors.recruitment import M0ReplaySource, MCPSource
    from work_observer.storage.archive import RawArchive
    from work_observer.storage.repository import Repository

    logging.disable(logging.CRITICAL)
    repository = None
    try:
        settings = Settings.load(env_file)
        spec = load_watchset(watchsets, watchset)
        path = db or settings.database_path
        secrets = [
            settings.model_api_key.get_secret_value(),
            settings.tavily_api_key.get_secret_value(),
        ]
        if bundle is None:
            config = settings.load_mcp()
            from work_observer.connectors.source_status import require_source_available

            require_source_available(config)
            secrets.extend(
                value
                for key, value in config.env.items()
                if re.search(
                    r"key|token|secret|password|cookie|authorization",
                    key,
                    re.I,
                )
            )
            if config.bearer_token_env:
                secrets.append(os.getenv(config.bearer_token_env, ""))
            source = MCPSource(config)
        else:
            if path.resolve() == settings.database_path.resolve():
                raise ProbeError("REPLAY_CANNOT_USE_LIVE_DATABASE")
            source = M0ReplaySource(bundle)
        repository = Repository(path)
        from work_observer.storage.locks import exclusive

        with exclusive(path, purpose="collection"):
            report = asyncio.run(
                collect(
                    repository,
                    RawArchive(settings.raw_directory, secrets),
                    source,
                    watchset,
                    spec,
                )
            )
        typer.echo(json.dumps(collection_summary(report), ensure_ascii=False, indent=2))
        typer.echo(f"数据库：{path.resolve()}")
    except Exception as exc:
        collection_error(exc)
    finally:
        if repository is not None:
            repository.close()
    if report["status"] != "success":
        raise typer.Exit(1)


@app.command("collect")
def collect_jobs(
    watchset: str = "ai-dev",
    watchsets: Path = Path("configs/watchsets.toml"),
    db: Path | None = None,
    env_file: Path = Path(".env"),
):
    """按观察配置手动采集并入库；没有定时、投递、模型分析或自动登录。"""
    execute_collection(watchset, watchsets, db, env_file)


@app.command("replay-m0")
def replay_m0(
    bundle: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    watchset: str = "ai-dev",
    watchsets: Path = Path("configs/watchsets.toml"),
    db: Path = Path("data/replay.db"),
    env_file: Path = Path(".env"),
):
    """回放带指纹的 M0 真实响应；原采集时间保留，与实时库隔离。"""
    execute_collection(watchset, watchsets, db, env_file, bundle)


def read_repository(db, env_file, operation):
    from work_observer.storage.repository import Repository

    repository = None
    try:
        repository = Repository(db or Settings.load(env_file).database_path)
        typer.echo(json.dumps(operation(repository), ensure_ascii=False, indent=2))
    except Exception as exc:
        collection_error(exc)
    finally:
        if repository:
            repository.close()


@app.command("db-stats")
def db_stats(db: Path | None = None, env_file: Path = Path(".env")):
    """查看各业务表记录数，不输出平台访问标识。"""
    read_repository(db, env_file, lambda repo: repo.counts())


@app.command("runs")
def runs(
    db: Path | None = None,
    limit: int = typer.Option(10, min=1, max=100),
    env_file: Path = Path(".env"),
):
    """查看有限采集运行及失败原因。"""
    read_repository(db, env_file, lambda repo: [collection_summary(r) for r in repo.runs(limit)])


@app.command("jobs")
def jobs(
    db: Path | None = None,
    limit: int = typer.Option(20, min=1, max=100),
    env_file: Path = Path(".env"),
    city: str | None = None,
    company: str | None = None,
    keyword: str | None = None,
    education: str | None = None,
    experience: str | None = None,
    salary_min: float | None = typer.Option(None, min=0, help="CNY 薪资区间下界，按同周期区间相交"),
    salary_max: float | None = typer.Option(None, min=0),
    salary_unit: str = typer.Option("month", help="month/year/day/hour"),
    detail: str = typer.Option("all", help="all/detail/list_only"),
    source: str | None = None,
    offset: int = typer.Option(0, min=0),
):
    """SQL 筛选和总体计数；匹配及未知分别标记，分页不改变统计。"""
    from work_observer.retrieval.catalog import Catalog, Filters

    read_repository(
        db,
        env_file,
        lambda repo: Catalog(repo).query(
            Filters(
                city=city,
                company=company,
                keyword=keyword,
                education=education,
                experience=experience,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_unit=salary_unit,
                detail=detail,
                source=source,
            ),
            limit=limit,
            offset=offset,
        ),
    )


@app.command("companies")
def companies(
    db: Path | None = None,
    limit: int = typer.Option(20, min=1, max=100),
    env_file: Path = Path(".env"),
    name: str | None = None,
):
    """查看已保存公司；缺少来源公司编号的记录明确标为未核实。"""
    read_repository(db, env_file, lambda repo: repo.companies(limit, name=name))


@app.command("job")
def job(
    id: str = typer.Option(..., help="jobs 命令中的内部岗位 ID"),
    db: Path | None = None,
    env_file: Path = Path(".env"),
):
    """查看岗位列表内容、详情全文及各自的来源文档引用。"""
    read_repository(db, env_file, lambda repo: repo.job(id))


@app.command("history")
def history(
    job_id: Annotated[str, typer.Option(help="jobs 命令中的内部岗位 ID")],
    limit: int = typer.Option(20, min=1, max=100),
    db: Path | None = None,
    env_file: Path = Path(".env"),
):
    """按岗位查看观察、快照内容和原始文件引用；不显示访问上下文。"""
    read_repository(db, env_file, lambda repo: repo.history(job_id, limit))


@app.command("company")
def company_detail(
    id: str = typer.Option(...), db: Path | None = None, env_file: Path = Path(".env")
):
    """按内部 ID 查看公司及关联岗位；不按同名强行归并。"""
    read_repository(db, env_file, lambda repo: repo.company(id))


@app.command("source-status")
def local_source_status(env_file: Path = Path(".env")):
    """只读本地来源暂停状态；不访问网站。"""
    from work_observer.connectors.source_status import source_status

    try:
        typer.echo(
            json.dumps(
                source_status(Settings.load(env_file).load_mcp()), ensure_ascii=False, indent=2
            )
        )
    except Exception as exc:
        collection_error(exc)


@app.command("import-jd")
def import_manual(
    file: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    title: str | None = None,
    company: str | None = None,
    external_id: str | None = typer.Option(None, help="人工资料稳定身份；同 ID 的新正文留存为版本"),
    related_job_id: str | None = typer.Option(None, help="关联原岗位，但不覆盖其来源原文"),
    db: Path | None = None,
    env_file: Path = Path(".env"),
):
    """导入一个 UTF-8 JD 文本/JSON；文本须给标题及公司。无任何平台请求。"""
    from work_observer.connectors.manual import import_jd, load_manual
    from work_observer.storage.archive import RawArchive

    def operation(repo):
        settings = Settings.load(env_file)
        archive = RawArchive(
            settings.raw_directory,
            [settings.model_api_key.get_secret_value(), settings.tavily_api_key.get_secret_value()],
        )
        return import_jd(
            repo,
            archive,
            load_manual(
                file,
                title=title,
                company=company,
                external_id=external_id,
                related_job_id=related_job_id,
            ),
        )

    read_repository(db, env_file, operation)


@app.command("search")
def search_documents(
    term: Annotated[list[str], typer.Option(help="字面关键词，可重复传入，按 OR 匹配")],
    city: str | None = None,
    company: str | None = None,
    job_id: Annotated[list[str] | None, typer.Option()] = None,
    limit: int = typer.Option(10, min=1, max=30),
    db: Path | None = None,
    env_file: Path = Path(".env"),
):
    """SQL 范围内检索原文，返回岗位总命中数和带版本的片段。"""
    from work_observer.retrieval.catalog import Catalog, Filters

    read_repository(
        db,
        env_file,
        lambda repo: Catalog(repo).search(
            term, filters=Filters(city=city, company=company), job_ids=job_id, limit=limit
        ),
    )


@app.command("source")
def source_document(
    id: str = typer.Option(...), db: Path | None = None, env_file: Path = Path(".env")
):
    """核对文档指纹并查看关联版本；不打印原始访问参数。"""
    from work_observer.retrieval.catalog import Catalog

    read_repository(db, env_file, lambda repo: Catalog(repo).document(id))


def execute_research(
    question,
    job_id,
    city,
    company,
    keyword,
    detail,
    db,
    env_file,
    offline,
    save,
    reports_dir,
    max_calls,
    timeout,
    allow_public=False,
    approach="standard",
    review_run_id=None,
    coverage_mode="all",
    public_document_ids=None,
):
    from work_observer.reports.results import render, save_result
    from work_observer.research.agent import research
    from work_observer.research.store import ResearchStore
    from work_observer.retrieval.catalog import Filters
    from work_observer.storage.repository import Repository

    logging.disable(logging.CRITICAL)
    repo = store = None
    try:
        settings = Settings.load(env_file)
        repo = Repository(db or settings.database_path)
        path = db or settings.database_path
        store = ResearchStore(path.parent / "checkpoints.db", str(path.resolve()))
        parameters = {
            "question": question,
            "job_ids": job_id,
            "filters": Filters(
                city=city, company=company, keyword=keyword, detail=detail
            ).model_dump(mode="json"),
            "offline": offline,
            "max_calls": max_calls,
            "timeout": timeout,
            "allow_public": allow_public,
            "approach": approach,
            "coverage_mode": coverage_mode,
        }
        if public_document_ids is not None:
            parameters["public_document_ids"] = public_document_ids
        if review_run_id:
            parameters["review_run_id"] = review_run_id
        run = store.create(parameters)
        result = asyncio.run(
            research(
                repo,
                question,
                settings,
                job_ids=job_id,
                filters=Filters(city=city, company=company, keyword=keyword, detail=detail),
                offline=offline,
                max_calls=max_calls,
                timeout=timeout,
                checkpoint=(store, run["id"]),
                allow_public=allow_public,
                approach=approach,
                review_run_id=review_run_id,
                coverage_mode=coverage_mode,
                public_document_ids=public_document_ids,
            )
        )
        store.save(run["id"], state="finished", result=result)
        typer.echo(render(result))
        typer.echo(
            json.dumps(
                {
                    "status": result["status"],
                    "stop_reason": result["stop_reason"],
                    "model_calls": result["model_calls"],
                    "run_id": run["id"],
                },
                ensure_ascii=False,
            )
        )
        if save:
            saved = save_result(result, reports_dir)
            store.save(run["id"], saved={"report_id": saved["report_id"]})
            typer.echo(json.dumps(saved, ensure_ascii=False))
        if result["status"] not in {"completed", "evidence_only"}:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        collection_error(exc)
    finally:
        if repo:
            repo.close()
        if store:
            store.close()


@app.command("research")
def research_question(
    question: Annotated[str, typer.Option(help="要研究的问题")],
    job_id: Annotated[list[str] | None, typer.Option(help="内部岗位 ID，可重复指定")] = None,
    city: str | None = None,
    company: str | None = None,
    keyword: str | None = None,
    detail: str = "all",
    offline: bool = typer.Option(False, help="只生成证据包，明确不进行模型分析"),
    save: bool = typer.Option(False, help="保存问题、范围、分析及引用到 reports"),
    reports_dir: Path = Path("reports"),
    max_calls: int = typer.Option(10, min=2, max=12),
    timeout: int = typer.Option(180, min=1, max=300),
    db: Path | None = None,
    env_file: Path = Path(".env"),
    allow_public: bool = typer.Option(False, help="允许必要的公开搜索，最多两次；不访问招聘来源"),
    approach: Annotated[
        ResearchApproach,
        typer.Option(help="standard标准判断；work_map工作地图；source_first来源维度约束试验"),
    ] = ResearchApproach.standard,
    review_run_id: str | None = typer.Option(
        None, help="明确参照此运行的当前拒绝复核；原问题、岗位和筛选须相同，新预算另计"
    ),
    coverage_mode: Annotated[
        ResearchCoverage, typer.Option(help="all要求逐岗覆盖；question按问题选择必要资料")
    ] = ResearchCoverage.all,
    document_id: Annotated[
        list[str] | None, typer.Option(help="限定归档原文ID，可重复指定，最多20份")
    ] = None,
    public_only: bool = typer.Option(
        False,
        "--materials-only",
        "--public-only",
        help="只研究本机归档资料（网页与粘贴原文），不使用岗位；按问题选证据",
    ),
):
    """一个有数量与时间预算的研究 Agent；不会访问招聘网站或改写岗位。"""
    if public_only and job_id:
        raise typer.BadParameter("只研究归档资料时不能同时指定岗位。")
    execute_research(
        question,
        [] if public_only else job_id,
        city,
        company,
        keyword,
        detail,
        db,
        env_file,
        offline,
        save,
        reports_dir,
        max_calls,
        timeout,
        allow_public,
        approach.value,
        review_run_id,
        "question" if public_only else coverage_mode.value,
        document_id,
    )


@app.command("compare")
def compare_jobs(
    job_id: Annotated[list[str], typer.Option(help="重复传入 2–5 个内部岗位 ID")],
    offline: bool = False,
    save: bool = False,
    reports_dir: Path = Path("reports"),
    db: Path | None = None,
    env_file: Path = Path(".env"),
):
    """比较指定岗位的任务、责任、能力和工具，区分必备、加分及未知。"""
    if not 2 <= len(set(job_id)) <= 5:
        raise typer.BadParameter("请指定 2–5 个不同岗位")
    execute_research(
        "比较这些岗位的任务、责任、能力和工具；区分必备、加分和资料缺失。",
        job_id,
        None,
        None,
        None,
        "all",
        db,
        env_file,
        offline,
        save,
        reports_dir,
        10,
        180,
    )


@app.command("reports")
def reports(reports_dir: Path = Path("reports"), limit: int = typer.Option(20, min=1, max=100)):
    """列出已保存研究；读取时不调用模型。"""
    from work_observer.reports.results import list_results

    try:
        typer.echo(json.dumps(list_results(reports_dir, limit), ensure_ascii=False, indent=2))
    except Exception as exc:
        collection_error(exc)


@app.command("report")
def report(id: str = typer.Option(...), reports_dir: Path = Path("reports")):
    """再次查看已保存的分析、范围和冻结原文证据。"""
    from work_observer.reports.results import read_result, render

    try:
        typer.echo(render(read_result(id, reports_dir)))
    except Exception as exc:
        collection_error(exc)


@app.command("serve")
def serve(
    port: int = typer.Option(8765, min=1024, max=65535),
    db: Path | None = None,
    reports_dir: Path = Path("reports"),
    env_file: Path = Path(".env"),
    host: str = typer.Option("127.0.0.1", help="默认本机；0.0.0.0需显式部署访问配置"),
    demo: bool = typer.Option(False, help="用临时数据打开虚构示例，不读取服务密钥"),
):
    """启动仅本机访问的中文页面；Ctrl+C 停止，不启动招聘采集。"""
    import uvicorn

    from work_observer.api.security import deployment_settings
    from work_observer.api.web import create_app
    from work_observer.storage.repository import Repository

    logging.disable(logging.CRITICAL)
    try:
        if demo:
            from tempfile import TemporaryDirectory

            from work_observer.career_demo import create_demo_app

            if host not in {"127.0.0.1", "::1"} or db is not None:
                raise typer.BadParameter("示例入口仅在本机运行，使用临时数据，无需指定数据库。")
            with TemporaryDirectory(prefix="work-observer-demo-") as directory:
                typer.echo("正在准备虚构示例，不连接模型或招聘平台…")
                example = create_demo_app(Path(directory))
                address = f"http://[::1]:{port}" if host == "::1" else f"http://127.0.0.1:{port}"
                typer.echo(f"虚构示例：{address}")
                typer.echo("使用预置脚本，不调用真实模型；Ctrl+C 关闭，可在页面导出准备包。")
                uvicorn.run(
                    example,
                    host=host,
                    port=port,
                    access_log=False,
                    proxy_headers=False,
                    log_level="critical",
                )
            return
        settings = Settings.load(env_file)
        if host not in {"127.0.0.1", "::1", "0.0.0.0"}:
            raise ProbeError("INVALID_BIND_HOST")
        deployment = deployment_settings(settings)
        if host == "0.0.0.0" and not deployment:
            raise ProbeError("DEPLOYMENT_ACCESS_CONFIG_REQUIRED")
        if db:
            settings = settings.model_copy(update={"database_path": db})
        repository = Repository(settings.database_path)
        repository.close()
        typer.echo(f"Work Observer：{deployment[0] if deployment else f'http://127.0.0.1:{port}'}")
        typer.echo("按 Ctrl+C 停止；研究过程自动留存，报告可按需导出；来源暂停保持不变。")
        uvicorn.run(
            create_app(settings, reports_dir=reports_dir),
            host=host,
            port=port,
            access_log=False,
            proxy_headers=False,
            log_level="critical",
        )
    except Exception as exc:
        collection_error(exc)
