"""One isolated observation → affected research → original-project followup flow."""

import json
import re
from copy import deepcopy

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient
from test_map_knowledge import run_map
from test_source_first_research import source_workspace as source_workspace
from typer.testing import CliRunner

from work_observer.api.web import create_app
from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.knowledge.research import ResearchKnowledgeService
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.memory.lifecycle import forget_personal
from work_observer.memory.service import MemoryService
from work_observer.reports.domain_updates import DomainUpdateService
from work_observer.research.projects import ProjectService
from work_observer.storage.archive import RawArchive
from work_observer.storage.models import Job


def test_observed_source_change_identifies_claims_and_reuses_original_project(
    source_workspace, tmp_path, monkeypatch
):
    repo, store, jobs = source_workspace
    memory = MemoryService(repo).create("preference", "合成个人研究背景")
    projects = ProjectService(store)
    project = projects.create("合成连续研究", "核对接口交付工作", jobs)
    result = run_map(repo, jobs, project["id"])
    original = deepcopy(store.get(result["run_id"]))
    domain = ResearchKnowledgeService(repo, store).save(result["run_id"], work_type_index=0)[
        "record"
    ]
    knowledge = DomainKnowledgeService(repo)
    knowledge.review_domain(domain["id"], "accept", "合成来源核对")
    dependencies = knowledge.browse_for_research(
        ["接口"], job_ids=jobs, public_document_ids=[], project_id=project["id"]
    )["dependencies"]
    child = store.create({"question": "合成知识依赖"})
    stable_evidence = next(row for row in result["evidence"] if row["job_id"] == jobs[1])
    child_result = {
        **deepcopy(result),
        "run_id": child["id"],
        "project_id": None,
        "question": "只通过工作类型知识关联的下游",
        "evidence": [stable_evidence],
        "claims": [
            {**result["claims"][0], "text": "合成下游认识", "evidence_ids": [stable_evidence["id"]]}
        ],
        "memory_used": [],
        "context_memory_used": [],
        "continued_from": [],
        "knowledge_used": dependencies,
        "work_map": None,
    }
    store.save(child["id"], state="finished", result=child_result)
    service = DomainUpdateService(store, repo)
    before = service.capture("变化前", job_ids=jobs)
    assert result["run_id"] in before["source_run_ids"]  # Definition-only lineage is retained.
    with Session(repo.engine) as session:
        old_job = session.get(Job, jobs[0])
    imported = import_jd(
        repo,
        RawArchive(tmp_path / "raw"),
        ManualJD(
            title=old_job.title,
            company=old_job.company_name_raw,
            external_id=old_job.source_job_id,
            description="岗位职责：\n负责 Go 接口开发；与平台团队协作。",
            data_kind="synthetic",
        ),
    )
    assert imported["job_id"] == jobs[0]
    after = service.capture("变化后", job_ids=jobs)
    report = service.compare(before["id"], after["id"])
    assert report["method_changes"]["definition_validity_changed"]
    assert not report["method_changes"]["domain_definitions_changed"]
    settings = Settings(database_path=tmp_path / "app.db", raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        headers = {"X-WO-Token": token}
        path = f"/api/updates/reports/{report['id']}"
        response = client.get(path)
        assert response.status_code == 200, response.text
        impact = response.json()["research_impact"]
        linked = {row["run_id"]: row for row in impact["runs"]}
        assert set(linked) == {result["run_id"], child["id"]}
        assert len(linked[result["run_id"]]["claims"]) == 1
        assert linked[result["run_id"]]["reasons"] == ["source_content_changed"]
        assert linked[child["id"]]["claims"] == []
        assert "linked_knowledge_changed" in linked[child["id"]]["reasons"]
        body = {
            "run_id": result["run_id"],
            "note": "比较 Go 与 Python 原文，核对接口任务认识是否需修订",
        }
        first = client.post(path + "/followup", headers=headers, json=body)
        assert first.status_code == 201, first.text
        second = client.post(path + "/followup", headers=headers, json=body)
        assert second.json()["step_id"] == first.json()["step_id"]
        saved = projects.get(project["id"])
        step = next(row for row in saved["steps"] if row["id"] == first.json()["step_id"])
        assert step["state"] == "queued" and step["run_id"] is None
        assert step["job_ids"] == jobs and step["approach"] == "work_map"
        assert step["reply_to_step_id"] == saved["steps"][0]["id"]
        context = projects.context(project["id"], step, repo)
        assert context["historical_reply"]["reason"] == "source_version_changed"
        assert store.get(result["run_id"]) == original
        assert not any(
            "research_impact" in row
            for row in [service._get("domain_update_reports", report["id"])]
        )
        forged = client.post(path + "/followup", headers=headers, json={**body, "run_id": "f" * 32})
        assert forged.status_code == 400
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls, *args: settings))
    runner = CliRunner()
    shared = ["--db", str(tmp_path / "app.db"), "--reports-dir", str(tmp_path / "reports")]
    preview = runner.invoke(
        app, ["product", "research-knowledge", "get", "--id", result["run_id"], *shared]
    )
    # Source changed: CLI shares the refusal instead of saving stale map content.
    assert preview.exit_code != 0 and "KNOWLEDGE_RESEARCH_SOURCE_STALE" in preview.stdout
    data = tmp_path / "followup.json"
    data.write_text(json.dumps(body), encoding="utf-8")
    repeated = runner.invoke(
        app, ["product", "updates", "followup", "--id", report["id"], "--file", str(data), *shared]
    )
    assert repeated.exit_code == 0, repeated.stdout
    assert json.loads(repeated.stdout)["step_id"] == first.json()["step_id"]
    forget_personal(repo, store, memory["id"], tmp_path / "reports")
    with pytest.raises(ProbeError, match="UPDATE_MEMORY_FORGOTTEN"):
        service.report(report["id"])
    assert "合成个人研究背景" not in str(service.list())
