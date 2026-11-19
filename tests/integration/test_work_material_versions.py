"""Append-only revisions remain manual sources; comparisons do not imply business change."""

import asyncio
import hashlib
from pathlib import Path

from test_source_first_research import source_workspace as source_workspace
from test_web import web as web
from test_work_materials import MaterialModel

from work_observer.config import Settings
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.memory.service import MemoryService
from work_observer.research.agent import research
from work_observer.retrieval.unified import UnifiedRetrieval
from work_observer.storage.repository import Repository


def save(client, headers, text="任务：复核原文。", **extra):
    response = client.post(
        "/api/work-materials",
        headers=headers,
        json={"title": "合成SOP", "text": text, "source_name": "合成来源", **extra},
    )
    assert response.status_code == 201
    return response.json()["document"]


def test_revision_history_and_diff_preserve_old_bytes_and_reference(web):
    client, headers, settings, _ = web
    first = save(client, headers, "\n任务：复核原文。\n")
    original = client.get("/api/public-documents/" + first["id"]).json()
    url = "/api/work-materials/" + first["id"] + "/revisions"
    payload = {"title": first["title"], "text": "\n任务：先核对原文，再由负责人确认。\n"}
    assert client.post(url, json=payload).status_code == 403
    response = client.post(url, headers=headers, json=payload)
    assert response.status_code == 201
    second = response.json()["document"]
    assert second["id"] != first["id"] and second["url"] == first["url"]
    assert second["publisher"] == first["publisher"]
    assert second["evidence_kind"] == "work_material" and second["response_origin"] == "manual"
    assert second["source_published_at"] is None
    old = client.get("/api/public-documents/" + first["id"]).json()
    assert old["text"] == original["text"] and old["sha256"] == original["sha256"]
    assert old["evidence"] == original["evidence"] and old["latest_document_id"] == second["id"]
    new = client.get("/api/public-documents/" + second["id"]).json()
    assert new["previous_document_id"] == first["id"]
    library = client.get("/api/public-documents").json()
    assert library["total"] == 1 and library["documents"][0]["id"] == second["id"]
    history = client.get(f"/api/public-documents/{first['id']}/history?limit=1").json()
    assert history["total"] == 2 and history["documents"][0]["id"] == second["id"]
    older = client.get(f"/api/public-documents/{first['id']}/history?limit=1&offset=1").json()
    assert older["documents"][0]["id"] == first["id"]
    compared = client.get(
        f"/api/public-documents/{second['id']}/compare?previous_id={first['id']}"
    ).json()
    assert compared["change_kind"] == "user_text_revision" and compared["complete"]
    assert "-任务：复核原文。" in compared["diff"] and "+任务：先核对原文" in compared["diff"]
    assert "不代表外部业务" in compared["notice"]
    # A stale editor cannot fork a second latest version or overwrite the first.
    assert client.post(url, headers=headers, json=payload).status_code == 409
    same = client.post(
        f"/api/work-materials/{second['id']}/revisions", headers=headers, json=payload
    )
    assert same.status_code == 200 and same.json()["unchanged"]
    assert client.get(f"/api/public-documents/{second['id']}/history").json()["total"] == 2
    files = list((settings.raw_directory / "public").glob("*.txt"))
    assert len(files) == 2
    assert hashlib.sha256(Path(files[0]).read_bytes()).hexdigest() in {
        first["sha256"],
        second["sha256"],
    }


def test_metadata_and_line_ending_changes_are_not_new_work_tasks(web):
    client, headers, _, _ = web
    first = save(client, headers)
    second = client.post(
        f"/api/work-materials/{first['id']}/revisions",
        headers=headers,
        json={"title": "合成SOP新标题", "text": "任务：复核原文。"},
    ).json()["document"]
    change = client.get(
        f"/api/public-documents/{second['id']}/compare?previous_id={first['id']}"
    ).json()
    assert change["change_kind"] == "metadata_only" and not change["text_changed"]
    third = client.post(
        f"/api/work-materials/{second['id']}/revisions",
        headers=headers,
        json={"title": second["title"], "text": "任务：复核原文。\n"},
    ).json()["document"]
    change = client.get(
        f"/api/public-documents/{third['id']}/compare?previous_id={second['id']}"
    ).json()
    assert change["change_kind"] == "line_endings_changed"
    unrelated = save(client, headers, "无关资料")
    assert (
        client.get(
            f"/api/public-documents/{third['id']}/compare?previous_id={unrelated['id']}"
        ).status_code
        == 400
    )


def test_same_raw_page_with_new_text_extraction_is_not_external_change(web, monkeypatch):
    client, headers, settings, _ = web
    from work_observer.connectors import public_documents

    async def fetch(url):
        return 200, {"content-type": "text/plain"}, b"Original archived response."

    monkeypatch.setattr(public_documents, "pinned_request", fetch)
    first = client.post(
        "/api/public-documents", headers=headers, json={"url": "https://example.com/versions"}
    ).json()["document"]
    repo = Repository(settings.database_path)
    try:
        service = PublicDocumentService(repo, settings.raw_directory / "public")
        monkeypatch.setattr(
            public_documents,
            "parse_page",
            lambda *args: (
                "text/plain",
                "Adjusted extraction",
                "Adjusted extracted body.",
                None,
            ),
        )
        second = asyncio.run(service.read("https://example.com/versions"))["document"]
        change = service.compare(second["id"], first["id"])
        assert change["change_kind"] == "extraction_changed" and not change["raw_changed"]
    finally:
        repo.close()
    assert (
        client.post(
            f"/api/work-materials/{first['id']}/revisions",
            headers=headers,
            json={"title": "伪装粘贴", "text": "不能改写网页身份"},
        ).status_code
        == 400
    )


def test_new_manual_version_stops_old_knowledge_recall_but_preserves_its_sources(
    source_workspace, tmp_path
):
    repo, _, _ = source_workspace
    service = PublicDocumentService(repo, tmp_path / "raw")
    first = service.archive_text("合成SOP", "checkpoint检查任务，先复核原文。", "合成说明")[
        "document"
    ]
    result = asyncio.run(
        research(
            repo,
            "checkpoint检查任务",
            Settings(),
            job_ids=[],
            public_document_ids=[first["id"]],
            coverage_mode="question",
            max_calls=2,
            model=MaterialModel(),
        )
    )
    assert result["status"] == "completed"
    memory = MemoryService(repo)
    knowledge = memory.create(
        "knowledge",
        result["claims"][0]["text"],
        evidence=result["evidence"],
        source_run_id=result["run_id"],
    )
    memory.activate(knowledge["id"])
    assert memory.validity(knowledge["id"])["eligible"]
    second = service.revise_text(first["id"], "合成SOP", "checkpoint检查任务须经平台负责人复核。")[
        "document"
    ]
    assert not memory.validity(knowledge["id"])["eligible"]
    assert memory.recall("checkpoint", []) == []
    assert memory.list()[0]["status"] == "active"  # Historical adoption is not silently rewritten.
    assert service.document(first["id"])["integrity"] == "verified"
    current = UnifiedRetrieval(repo).search(["checkpoint"], job_ids=[])
    assert {e["public_document_id"] for e in current["evidence"]} == {second["id"]}
    historical = UnifiedRetrieval(repo).search(
        ["checkpoint"], job_ids=[], as_of=first["observed_at"]
    )
    assert {e["public_document_id"] for e in historical["evidence"]} == {first["id"]}


def test_large_diff_is_explicitly_incomplete_and_corrupt_version_is_not_compared(web):
    client, headers, settings, _ = web
    first = save(client, headers, "甲" * 50000)
    second = client.post(
        f"/api/work-materials/{first['id']}/revisions",
        headers=headers,
        json={"title": first["title"], "text": "乙" * 50000},
    ).json()["document"]
    comparison = client.get(
        f"/api/public-documents/{second['id']}/compare?previous_id={first['id']}"
    ).json()
    assert not comparison["complete"] and len(comparison["diff"]) <= 40000
    (settings.raw_directory / "public" / (first["id"] + ".txt")).write_text(
        "合成损坏", encoding="utf-8"
    )
    response = client.get(f"/api/public-documents/{second['id']}/compare?previous_id={first['id']}")
    assert (
        response.status_code == 400
        and response.json()["error_code"] == "PUBLIC_DOCUMENT_INTEGRITY_FAILED"
    )


def test_revision_does_not_fabricate_a_later_timestamp(web, monkeypatch):
    from work_observer.connectors import public_documents

    client, headers, _, _ = web
    first = save(client, headers)
    monkeypatch.setattr(public_documents, "now", lambda: first["observed_at"])
    response = client.post(
        f"/api/work-materials/{first['id']}/revisions",
        headers=headers,
        json={"title": first["title"], "text": "合成新正文"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "WORK_MATERIAL_CLOCK_CONFLICT"
    assert client.get(f"/api/public-documents/{first['id']}/history").json()["total"] == 1
