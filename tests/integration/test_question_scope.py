"""Question-driven investigation may cite relevant sources without filling unrelated jobs."""

import asyncio
import json
from pathlib import Path

import pytest
from test_source_first_research import source_workspace as source_workspace
from typer.testing import CliRunner

from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors import public_documents
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.research.agent import method_fingerprint, research


class SubsetModel:
    async def turn(self, history):
        outputs = [
            json.loads(r["output"]) for r in history if r.get("type") == "function_call_output"
        ]
        if not outputs:
            name, arguments = "query_jobs", {}
        elif not any(row.get("evidence") for row in outputs):
            if "body_preview" in outputs[0]["jobs"][0]:
                assert "接口开发" in outputs[0]["jobs"][0]["body_preview"]
                assert outputs[0]["jobs"][0]["preview_not_evidence"] is True
                assert (
                    "body_preview"
                    not in json.loads(history[1]["content"])["fixed_scope"]["jobs"][0]
                )
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


class PublicToolModel:
    def __init__(self, category, skip_query=False):
        self.category = category
        self.skip_query = skip_query

    async def turn(self, history):
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        sources = next((row["evidence"] for row in outputs if row.get("evidence")), None)
        if not outputs and not self.skip_query:
            name, arguments = "query_jobs", {}
        elif sources is None:
            name, arguments = "search_archived_sources", {"terms": ["checkpoint"]}
        else:
            source = next(row for row in sources if row.get("public_document_id"))
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": self.category,
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "合成技术文档说明checkpoint保存执行状态。",
                            "evidence_ids": [source["id"]],
                        }
                    ],
                    "gaps": ["工具说明不能证明企业采用或个人权限。"],
                },
            )
        call = dict(
            type="function_call",
            name=name,
            arguments=json.dumps(arguments),
            call_id=str(len(history)),
        )
        return [call], call


@pytest.mark.parametrize(
    "category,expected", [("tool", "completed"), ("responsibility", "incomplete")]
)
@pytest.mark.parametrize(
    "public_only,coverage", [(False, "question"), (True, "question"), (True, "all")]
)
def test_public_document_can_explain_tool_but_cannot_prove_job_responsibility(
    source_workspace, monkeypatch, tmp_path, category, expected, public_only, coverage
):
    repo, _, jobs = source_workspace

    async def fetch(url):
        return 200, {"content-type": "text/plain"}, b"checkpoint preserves execution state."

    monkeypatch.setattr(public_documents, "pinned_request", fetch)
    asyncio.run(PublicDocumentService(repo, tmp_path / "public").read("https://example.com/docs"))
    result = asyncio.run(
        research(
            repo,
            "合成工具说明",
            Settings(),
            job_ids=[] if public_only else jobs,
            coverage_mode=coverage,
            max_calls=3,
            model=PublicToolModel(category, skip_query=public_only),
        )
    )
    assert result["status"] == expected
    assert result["model_calls"] == (2 if public_only and category == "tool" else 3)
    if public_only:
        assert result["scope"]["jobs"] == []
        assert result["scope"]["counts"]["candidate_details"] == 0
        assert result["scope"]["public_document_titles"][0]["id"]
        assert all(ev.get("public_document_id") for ev in result["evidence"])
        assert result["trace"][0]["tool"] == "search_archived_sources"
        assert result["research_method_sha256"] == method_fingerprint(
            coverage_mode=coverage,
            public_only=True,
        )


def test_empty_public_library_never_falls_back_to_jobs_or_calls_model(source_workspace):
    repo, _, _ = source_workspace
    result = asyncio.run(
        research(
            repo,
            "没有公开正文的合成问题",
            Settings(),
            job_ids=[],
            coverage_mode="question",
            model=PublicToolModel("tool"),
        )
    )
    assert result["status"] == "insufficient_evidence"
    assert result["model_calls"] == 0
    assert not result["scope"]["jobs"] and not result["evidence"]


def test_cli_public_only_excludes_existing_jobs(source_workspace, monkeypatch, tmp_path):
    repo, store, _ = source_workspace

    async def fetch(url):
        return 200, {"content-type": "text/plain"}, b"checkpoint preserves execution state."

    monkeypatch.setattr(public_documents, "pinned_request", fetch)
    asyncio.run(PublicDocumentService(repo, tmp_path / "public").read("https://example.com/docs"))
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
            "checkpoint",
            "--db",
            str(repo.engine.url.database),
            "--public-only",
            "--offline",
        ],
    )
    assert response.exit_code == 0, response.output
    run = store.list()[0]
    assert run["input"]["job_ids"] == [] and run["input"]["coverage_mode"] == "question"
    assert run["result"]["scope"]["jobs"] == []
    assert "公开资料范围：1份归档正文" in response.output
