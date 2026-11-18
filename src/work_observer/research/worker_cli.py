"""独立有界研究worker的显式CLI注册，无常驻或系统计划。"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer


def register(app):
    @app.command("research-worker")
    def research_worker(
        once: Annotated[
            bool, typer.Option("--once", help="显式处理一次有限队列，不启动常驻任务")
        ] = False,
        project_id: str | None = None,
        max_steps: Annotated[int, typer.Option(min=1, max=6)] = 3,
        max_calls: Annotated[int, typer.Option(min=0, max=36)] = 36,
        max_seconds: Annotated[int, typer.Option(min=1, max=900)] = 900,
        max_public: Annotated[int, typer.Option(min=0, max=4)] = 4,
        db: Path | None = None,
        reports_dir: Path = Path("reports"),
        env_file: Path = Path(".env"),
    ):
        """显式扫描持久调查队列；恢复不重置项目累计预算，审核或资料等待不占执行位。"""
        from work_observer.cli import collection_error
        from work_observer.connectors.mcp_probe import ProbeError
        from work_observer.product_cli import echo, session
        from work_observer.research.projects import ProjectService
        from work_observer.research.worker import run_research_worker

        try:
            if not once:
                raise ProbeError("WORKER_EXPLICIT_ONCE_REQUIRED")
            with session(db, env_file, reports_dir) as (settings, repository, store):
                echo(
                    asyncio.run(
                        run_research_worker(
                            ProjectService(store),
                            repository,
                            settings,
                            project_id=project_id,
                            max_steps=max_steps,
                            max_calls=max_calls,
                            max_seconds=max_seconds,
                            max_public=max_public,
                        )
                    )
                )
        except Exception as exc:
            collection_error(exc)
