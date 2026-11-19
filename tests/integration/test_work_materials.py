"""Pasted material keeps its acquisition provenance through research and memory."""

import asyncio
import hashlib
import json
import time
from pathlib import Path

import pytest
from test_question_scope import PublicToolModel, SubsetModel
from test_source_first_research import source_workspace as source_workspace
from test_web import web as web
from typer.testing import CliRunner

from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors import public_documents
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.memory.service import MemoryService
from work_observer.reports.results import audit_result, render
from work_observer.research.agent import method_fingerprint, research


def test_pasted_source_is_exact_local_text_in_library_retrieval_and_offline_research(
    web, monkeypatch
):
    client, headers, _, _ = web

    async def forbidden(url):
        raise AssertionError("Pasting, browsing and offline research must not fetch a website")

    monkeypatch.setattr(public_documents, "pinned_request", forbidden)
    payload = {
        "title": "合成工作说明",
        "text": "\n交付复核：整理原文清单。\n<script>literal text</script>\n",
        "source_name": "合成项目说明，未独立核实",
    }
    assert client.post("/api/work-materials", json=payload).status_code == 403
    saved = client.post("/api/work-materials", headers=headers, json=payload)
    assert saved.status_code == 201
    document = saved.json()["document"]
    assert document["evidence_kind"] == "work_material" and document["source"] == "manual_material"
    assert document["response_origin"] == "manual" and document["source_published_at"] is None
    assert document["sha256"] == hashlib.sha256(payload["text"].encode()).hexdigest()
    assert "path" not in document
    full = client.get("/api/public-documents/" + document["id"]).json()
    assert full["text"] == payload["text"] and full["integrity"] == "verified"
    found = client.get("/api/public-documents?q=合成项目说明").json()
    assert found["documents"][0]["id"] == document["id"]
    evidence = client.post(
        "/api/retrieval/unified", headers=headers, json={"terms": ["交付复核"], "job_ids": []}
    ).json()["evidence"]
    assert evidence[0]["evidence_kind"] == "work_material"
    assert evidence[0]["source_fetched_at"] is None and evidence[0]["transport"] == "local_text"
    run_id = client.post(
        "/api/research",
        headers=headers,
        json={"question": "交付复核", "job_ids": [], "offline": True},
    ).json()["id"]
    for _ in range(50):
        run = client.get("/api/research/" + run_id).json()
        if run["state"] != "running":
            break
        time.sleep(0.01)
    assert run["result"]["model_calls"] == 0
    assert run["result"]["scope"]["jobs"] == []
    assert run["result"]["evidence"][0]["source"] == "manual_material"
    assert "粘贴工作资料" in render(run["result"])
    assert "岗位 `None`" not in render(run["result"])


class MaterialModel:
    def __init__(self, *, category="task", requirement="unspecified", interrupt=False):
        self.category, self.requirement, self.interrupt = category, requirement, interrupt

    async def turn(self, history):
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = "search_archived_sources", {"terms": ["checkpoint"]}
        else:
            if self.interrupt:
                raise asyncio.CancelledError()
            source = outputs[0]["evidence"][0]
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": self.category,
                            "basis": "direct",
                            "requirement": self.requirement,
                            "text": "合成工作资料写明checkpoint检查任务。",
                            "evidence_ids": [source["id"]],
                        }
                    ],
                    "gaps": ["本题只解释材料写明的任务，不证明已执行或成为招聘资格。"],
                },
            )
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(len(history))
        )
        return [call], call


@pytest.mark.parametrize(
    "requirement,expected", [("unspecified", "completed"), ("required", "incomplete")]
)
def test_material_can_state_work_but_is_not_promoted_to_a_job_qualification(
    source_workspace, tmp_path, requirement, expected
):
    repo, _, _ = source_workspace
    material = PublicDocumentService(repo, tmp_path / "materials").archive_text(
        "合成SOP",
        "checkpoint检查任务：整理核对清单。",
        "合成来源",
    )
    result = asyncio.run(
        research(
            repo,
            "checkpoint任务",
            Settings(),
            job_ids=[],
            coverage_mode="question",
            max_calls=3,
            model=MaterialModel(requirement=requirement),
        )
    )
    assert result["status"] == expected
    assert result["scope"]["work_material_ids"] == [material["document"]["id"]]
    assert result["research_method_sha256"] == method_fingerprint(
        coverage_mode="question",
        public_only=True,
        work_materials=True,
        archived_sources=True,
    )
    if requirement == "unspecified":
        assert result["model_calls"] == 2 and not audit_result(result, repo)["changed_sources"]
        forged = [
            {**item, "source": "public_web", "evidence_kind": "public_document"}
            for item in result["evidence"]
        ]
        memory = MemoryService(repo).create(
            "knowledge",
            result["claims"][0]["text"],
            evidence=forged,
            source_run_id=result["run_id"],
        )
        assert memory["evidence"][0]["source"] == "manual_material"
        assert memory["evidence"][0]["evidence_kind"] == "work_material"


def test_new_material_does_not_change_an_existing_frozen_research_scope(
    source_workspace, tmp_path, monkeypatch
):
    repo, store, _ = source_workspace
    service = PublicDocumentService(repo, tmp_path / "materials")

    async def fetch(url):
        return 200, {"content-type": "text/plain"}, b"checkpoint documentation."

    monkeypatch.setattr(public_documents, "pinned_request", fetch)
    original = asyncio.run(service.read("https://example.com/docs"))["document"]["id"]
    run = store.create(
        {
            "question": "checkpoint",
            "job_ids": [],
            "coverage_mode": "question",
            "max_calls": 4,
            "timeout": 180,
        }
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "checkpoint",
                Settings(),
                job_ids=[],
                coverage_mode="question",
                max_calls=4,
                checkpoint=(store, run["id"]),
                model=MaterialModel(interrupt=True),
            )
        )
    added = service.archive_text("后补合成资料", "checkpoint任务")
    result = asyncio.run(
        research(
            repo,
            "checkpoint",
            Settings(),
            job_ids=[],
            coverage_mode="question",
            max_calls=4,
            checkpoint=(store, run["id"]),
            resume=True,
            model=MaterialModel(category="tool"),
        )
    )
    assert result["status"] == "completed"
    assert result["scope"]["archived_public_ids"] == [original]
    assert added["document"]["id"] not in result["scope"]["archived_public_ids"]
    assert "work_material_ids" not in result["scope"]


def test_materials_only_cli_uses_local_archive_without_jobs(
    source_workspace, tmp_path, monkeypatch
):
    repo, store, _ = source_workspace
    PublicDocumentService(repo, tmp_path / "materials").archive_text(
        "合成SOP",
        "checkpoint检查任务",
        "合成来源说明",
    )
    monkeypatch.setattr(
        Settings,
        "load",
        classmethod(
            lambda cls, *a, **kw: Settings(
                database_path=Path(repo.engine.url.database),
                raw_directory=tmp_path / "raw",
            )
        ),
    )
    response = CliRunner().invoke(
        app,
        [
            "research",
            "--question",
            "checkpoint",
            "--db",
            str(repo.engine.url.database),
            "--materials-only",
            "--offline",
        ],
    )
    assert response.exit_code == 0, response.output
    assert store.list()[0]["result"]["scope"]["jobs"] == []
    assert "归档资料范围：1份归档正文" in response.output
    assert "粘贴工作资料" in response.output


@pytest.mark.parametrize("web_only", [False, True])
def test_scope_notice_describes_read_sources_instead_of_unused_pasted_material(
    source_workspace, tmp_path, monkeypatch, web_only
):
    repo, _, jobs = source_workspace
    service = PublicDocumentService(repo, tmp_path / "materials")
    service.archive_text("未用于本题的合成资料", "交付事项", "合成说明")
    if web_only:

        async def fetch(url):
            return 200, {"content-type": "text/plain"}, b"checkpoint documentation."

        monkeypatch.setattr(public_documents, "pinned_request", fetch)
        asyncio.run(service.read("https://example.com/docs"))
    result = asyncio.run(
        research(
            repo,
            "checkpoint" if web_only else "接口任务",
            Settings(),
            job_ids=[] if web_only else jobs[:1],
            coverage_mode="question",
            max_calls=3,
            model=PublicToolModel("tool") if web_only else SubsetModel(),
        )
    )
    assert result["status"] == "completed"
    assert all(ev.get("evidence_kind") != "work_material" for ev in result["evidence"])
    assert all("粘贴材料" not in gap for gap in result["gaps"])
    assert "公开正文" in result["gaps"][0] if web_only else "不代表全市场" in result["gaps"][0]
