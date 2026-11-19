"""Question-driven investigation may cite relevant sources without filling unrelated jobs."""

import asyncio
import json
from pathlib import Path

import pytest
from test_source_first_research import source_workspace as source_workspace
from typer.testing import CliRunner

from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.agent import method_fingerprint, research


class SubsetModel:
    async def turn(self, history):
        outputs = [
            json.loads(r["output"]) for r in history if r.get("type") == "function_call_output"
        ]
        if not outputs:
            name, arguments = "query_jobs", {}
        elif not any(row.get("evidence") for row in outputs):
            name, arguments = "read_job", {"job_id": outputs[0]["jobs"][0]["id"]}
        else:
            source = next(row["evidence"][0] for row in outputs if row.get("evidence"))
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "该合成材料描述接口开发任务",
                            "evidence_ids": [source["id"]],
                        }
                    ],
                    "gaps": ["本题只检查一份材料，不代表其他岗位。"],
                },
            )
        call = dict(
            type="function_call",
            name=name,
            arguments=json.dumps(arguments),
            call_id=str(len(history)),
        )
        return [call], call


@pytest.mark.parametrize("mode,expected", [("question", "completed"), ("all", "incomplete")])
def test_partial_relevant_answer_is_deliverable_but_explicit_full_comparison_is_not(
    source_workspace, mode, expected
):
    repo, store, jobs = source_workspace
    result = asyncio.run(
        research(
            repo,
            "查看接口开发任务这一问题",
            Settings(),
            job_ids=jobs,
            coverage_mode=mode,
            max_calls=4,
            model=SubsetModel(),
        )
    )
    assert result["status"] == expected
    assert result["scope"]["counts"]["candidate_details"] == 2
    assert result["research_method_sha256"] == method_fingerprint(coverage_mode=mode)
    if mode == "question":
        assert result["model_calls"] == 3
        assert result["question_scope"]["read_job_fragments"] == 1
        assert len(result["question_scope"]["unread_job_ids"]) == 1
    else:
        assert not result["claims"]
        assert result["model_calls"] == 4


def test_coverage_cannot_switch_during_resume_including_legacy_input(source_workspace):
    _, store, _ = source_workspace
    for original in (None, "all", "question"):
        parameters = {"question": "合成旧研究"}
        if original:
            parameters["coverage_mode"] = original
        run = store.create(parameters)
        with pytest.raises(ProbeError, match="RESEARCH_INPUT_CHANGED_NEW_RUN_REQUIRED"):
            store.prepare_execution(
                run["id"],
                {"coverage_mode": "all" if original == "question" else "question"},
                resume=True,
                supplied=["coverage_mode"],
            )
        assert store.get(run["id"])["input"] == parameters


def test_cli_question_scope_is_explicit_and_persisted(source_workspace, monkeypatch):
    repo, store, jobs = source_workspace
    monkeypatch.setattr(
        Settings,
        "load",
        classmethod(lambda cls, *a, **kw: Settings(database_path=Path(repo.engine.url.database))),
    )
    response = CliRunner().invoke(
        app,
        [
            "research",
            "--question",
            "合成范围",
            "--db",
            str(repo.engine.url.database),
            "--job-id",
            jobs[0],
            "--coverage-mode",
            "question",
            "--offline",
        ],
    )
    assert response.exit_code == 0, response.output
    assert store.list()[0]["input"]["coverage_mode"] == "question"
