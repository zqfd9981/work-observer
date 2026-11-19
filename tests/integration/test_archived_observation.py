"""Archive changes link old claims to a bounded original-project recheck, without network."""

import asyncio
import re
from copy import deepcopy

import pytest
from starlette.testclient import TestClient
from test_source_first_research import source_workspace as source_workspace
from test_work_materials import MaterialModel

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors import public_documents
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.memory.lifecycle import forget_personal
from work_observer.memory.service import MemoryService
from work_observer.reports.domain_updates import DomainUpdateService
from work_observer.research.agent import research
from work_observer.research.projects import ProjectService


@pytest.mark.parametrize("kind", ["manual", "web"])
def test_archive_change_rechecks_original_claim_and_advances_only_same_selected_source(
    source_workspace, tmp_path, monkeypatch, kind
):
    repo, store, _ = source_workspace
    private = MemoryService(repo).create("preference", "合成私人研究关注点")
    archive = PublicDocumentService(repo, tmp_path / "materials")
    text = "checkpoint检查任务：整理核对清单。"

    async def response(url):
        return 200, {"content-type": "text/plain"}, text.encode()

    monkeypatch.setattr(public_documents, "pinned_request", response)
    if kind == "manual":
        first = archive.archive_text("合成技术说明", text, "合成来源")["document"]
    else:
        first = asyncio.run(archive.read("https://example.com/synthetic"))["document"]
    projects = ProjectService(store)
    project = projects.create(
        "合成归档研究", "解释checkpoint任务", [], public_document_ids=[first["id"]]
    )
    project = projects.add(
        project["id"],
        "checkpoint任务",
        revision=project["revision"],
        max_calls=2,
        coverage_mode="question",
    )
    step = projects.claim(project["id"])
    result = asyncio.run(
        research(
            repo,
            step["question"],
            Settings(),
            job_ids=[],
            public_document_ids=[first["id"]],
            project_id=project["id"],
            coverage_mode="question",
            max_calls=2,
            checkpoint=(store, step["run_id"]),
            model=MaterialModel(category="task" if kind == "manual" else "business"),
        )
    )
    assert result["status"] == "completed"
    projects.finish(project["id"], step["id"], state="completed")
    original = deepcopy(store.get(step["run_id"]))
    updates = DomainUpdateService(store, repo)
    before = updates.capture("旧归档观察", job_ids=[], include_archived=True)
    text = "checkpoint检查任务：先验证原文，再由负责人复核清单。"
    if kind == "manual":
        second = archive.revise_text(first["id"], first["title"], text)["document"]
    else:
        second = asyncio.run(archive.read("https://example.com/synthetic"))["document"]
    unrelated = archive.archive_text("合成其他来源", "无关材料，不应加入原研究。")["document"]
    after = updates.capture("新归档观察", job_ids=[], include_archived=True)
    report = updates.compare(before["id"], after["id"])
    assert report["content_changes"] == []  # No invented job/task change.
    assert report["archived_changes"]["after_count"] == 2
    assert report["archived_changes"]["added"][0]["id"] == unrelated["id"]
    change = report["archived_changes"]["changes"][0]
    assert change["change_kind"] == (
        "user_text_revision" if kind == "manual" else "archive_text_changed"
    )
    assert change["complete"] and change["text_changed"]
    assert "负责人" in change["diff"]
    settings = Settings(database_path=tmp_path / "app.db", raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        path = "/api/updates/reports/" + report["id"]
        impact = client.get(path).json()["research_impact"]
        assert impact["total_runs"] == impact["direct_claim_count"] == 1
        linked = impact["runs"][0]
        assert linked["claims"][0]["index"] == 0
        assert linked["document_updates"][0]["after_id"] == second["id"]
        body = {
            "run_id": step["run_id"],
            "note": "比较checkpoint资料版本，核对任务解释是否需要修订。",
        }
        saved = client.post(path + "/followup", headers=auth, json=body)
        assert saved.status_code == 201, saved.text
        again = client.post(path + "/followup", headers=auth, json=body)
        assert again.json()["step_id"] == saved.json()["step_id"]
        current = projects.get(project["id"])
        assert current["public_document_ids"] == [second["id"]]
        assert current["scope_history"][-1]["public_document_ids"] == [first["id"]]
        assert len(current["steps"]) == 2 and current["steps"][-1]["state"] == "queued"
        assert current["steps"][-1]["reply_to_step_id"] == step["id"]
        context = projects.context(project["id"], current["steps"][-1], repo)
        assert context["historical_reply"]["derived_claims"][0]["previous_claim_index"] == 0
        assert store.get(step["run_id"]) == original
    assert archive.document(first["id"])["integrity"] == "verified"
    forget_personal(repo, store, private["id"], tmp_path / "reports")
    assert updates.report(report["id"])["research_impact"]["total_runs"] == 0
    assert archive.document(first["id"])["integrity"] == "verified"
    assert archive.document(second["id"])["integrity"] == "verified"


def test_missing_baseline_repeated_archive_and_unavailable_archive_keep_distinct_meanings(
    source_workspace, tmp_path
):
    repo, store, _ = source_workspace
    archive = PublicDocumentService(repo, tmp_path / "materials")
    first = archive.archive_text("合成说明", "checkpoint原文")["document"]
    updates = DomainUpdateService(store, repo)
    disabled = updates.capture("未观察归档", job_ids=[])
    a = updates.capture("首次观察", job_ids=[], include_archived=True)
    missing = updates.compare(disabled["id"], a["id"])["archived_changes"]
    assert missing["status"] == "baseline_unavailable" and not missing["added"]
    b = updates.capture("重复观察", job_ids=[], public_document_ids=[first["id"]])
    repeated = updates.compare(a["id"], b["id"])["archived_changes"]
    assert repeated["changes"] == [] and repeated["added"] == []
    (tmp_path / "materials" / (first["id"] + ".txt")).write_text("合成损坏样本", encoding="utf-8")
    c = updates.capture("资料不可用", job_ids=[], include_archived=True)
    change = updates.compare(b["id"], c["id"])["archived_changes"]["changes"][0]
    assert change["change_kind"] == "integrity_unavailable" and change["text_changed"] is None
