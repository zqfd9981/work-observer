"""日常研究流程CLI，与网页共用持久服务。"""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer


def register(app):
    @app.command("workflow")
    def workflow(
        action: Annotated[str, typer.Argument()] = "list",
        id: str | None = None,
        file: Path | None = None,
        allow_model: bool = False,
        retry_failed: bool = False,
        new_cycle: bool = False,
        max_calls: Annotated[int, typer.Option(min=0, max=36)] = 36,
        max_seconds: Annotated[int, typer.Option(min=1, max=900)] = 900,
        db: Path | None = None,
        reports_dir: Path = Path("reports"),
        env_file: Path = Path(".env"),
    ):
        """create仅保存；run默认只整理原文，--allow-model才明确启用本批有限模型调用。"""
        from work_observer.api.workflows import WorkflowInput, WorkflowScopeInput
        from work_observer.cli import collection_error
        from work_observer.connectors.mcp_probe import ProbeError
        from work_observer.product_cli import echo, session
        from work_observer.workflow.service import WorkflowService, execute_workflow

        try:
            with session(db, env_file, reports_dir) as (settings, repository, store):
                service = WorkflowService(store, repository)
                if action == "list":
                    result = service.list()
                elif action == "create":
                    if not file:
                        raise ProbeError("WORKFLOW_JSON_FILE_REQUIRED")
                    data = WorkflowInput.model_validate(
                        json.loads(file.read_text(encoding="utf-8-sig"))
                    )
                    result = service.create(**data.model_dump())
                elif action == "get":
                    result = service.get(id)
                elif action == "refine":
                    if not file:
                        raise ProbeError("WORKFLOW_JSON_FILE_REQUIRED")
                    data = WorkflowScopeInput.model_validate(
                        json.loads(file.read_text(encoding="utf-8-sig"))
                    )
                    result = service.refine(id, **data.model_dump())
                elif action == "run":
                    result = asyncio.run(
                        execute_workflow(
                            service,
                            id,
                            settings,
                            allow_model=allow_model,
                            retry_failed=retry_failed,
                            new_cycle=new_cycle,
                            max_calls=max_calls,
                            max_seconds=max_seconds,
                        )
                    )
                else:
                    raise ProbeError("WORKFLOW_ACTION_DENIED")
                echo(result)
        except Exception as exc:
            collection_error(exc)
