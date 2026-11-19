"""Public source intake reuses bounded archiving and cannot bypass paused recruitment."""

import time

import pytest
from test_web import web as web

from work_observer.connectors import public_documents


def test_archive_becomes_retrievable_source_and_next_research_freezes_it(web, monkeypatch):
    client, headers, _, _ = web
    calls = []

    async def fetch(url):
        calls.append(url)
        return (
            200,
            {"content-type": "text/html"},
            b"<html><title>Synthetic docs</title><main>"
            b"<p>checkpoint preserves task execution state.</p></main></html>",
        )

    monkeypatch.setattr(public_documents, "pinned_request", fetch)
    assert (
        client.post("/api/public-documents", json={"url": "https://example.com/docs"}).status_code
        == 403
    )
    response = client.post(
        "/api/public-documents", headers=headers, json={"url": "https://example.com/docs"}
    )
    assert response.status_code == 201
    doc = response.json()["document"]
    assert calls == ["https://example.com/docs"]
    assert doc["integrity"] == "verified" and doc["source_published_at"] is None
    assert "path" not in response.text
    assert "checkpoint preserves" in client.get("/api/public-documents/" + doc["id"]).json()["text"]
    found = client.post(
        "/api/retrieval/unified", headers=headers, json={"terms": ["checkpoint"]}
    ).json()
    assert found["evidence"][0]["public_document_id"] == doc["id"]
    job = client.post(
        "/api/import",
        headers=headers,
        json={
            "title": "合成岗位",
            "company": "合成公司",
            "description": "合成状态管理任务",
            "data_kind": "synthetic",
        },
    ).json()["job_id"]
    run = client.post(
        "/api/research",
        headers=headers,
        json={"question": "checkpoint", "job_ids": [job], "offline": True},
    ).json()["id"]
    for _ in range(30):
        result = client.get("/api/research/" + run).json()
        if result["state"] != "running":
            break
        time.sleep(0.01)
    assert doc["id"] in result["result"]["scope"]["archived_public_ids"]
    assert result["result"]["model_calls"] == 0
    schema = client.get("/api/openapi.json").json()
    assert "201" in schema["paths"]["/api/public-documents"]["post"]["responses"]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.zhipin.com/job_detail/test",
        "https://api.bosszhipin.com/test",
        "https://127.0.0.1/",
        "https://example.com/?token=private",
    ],
)
def test_invalid_and_paused_sources_never_connect(web, monkeypatch, url):
    client, headers, _, _ = web

    async def forbidden(url):
        raise AssertionError("No network request should be sent")

    monkeypatch.setattr(public_documents, "pinned_request", forbidden)
    response = client.post("/api/public-documents", headers=headers, json={"url": url})
    assert response.status_code == 400
    assert response.json()["error_code"] in {
        "PUBLIC_DOCUMENT_URL_DENIED",
        "PUBLIC_DOCUMENT_RECRUITMENT_PAUSED",
    }


def test_redirect_to_paused_recruitment_is_blocked_before_second_request(web, monkeypatch):
    client, headers, _, _ = web
    calls = []

    async def fetch(url):
        calls.append(url)
        return 302, {"location": "https://www.zhipin.com/"}, b""

    monkeypatch.setattr(public_documents, "pinned_request", fetch)
    response = client.post(
        "/api/public-documents", headers=headers, json={"url": "https://example.com/docs"}
    )
    assert response.json()["error_code"] == "PUBLIC_DOCUMENT_RECRUITMENT_PAUSED"
    assert calls == ["https://example.com/docs"]
