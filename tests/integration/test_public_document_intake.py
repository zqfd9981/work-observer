"""Public source intake reuses bounded archiving and cannot bypass paused recruitment."""

import time

import pytest
from test_web import web as web

from work_observer.connectors import public_documents


@pytest.mark.parametrize("public_only", [False, True])
def test_archive_becomes_retrievable_source_and_next_research_freezes_it(
    web, monkeypatch, public_only
):
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
        json={"question": "checkpoint", "job_ids": [] if public_only else [job], "offline": True},
    ).json()["id"]
    for _ in range(30):
        result = client.get("/api/research/" + run).json()
        if result["state"] != "running":
            break
        time.sleep(0.01)
    assert doc["id"] in result["result"]["scope"]["archived_public_ids"]
    assert result["result"]["model_calls"] == 0
    if public_only:
        assert result["result"]["scope"]["jobs"] == []
        assert all(ev.get("public_document_id") for ev in result["result"]["evidence"])
        project = client.post(
            "/api/projects",
            headers=headers,
            json={"title": "合成文档研究", "goal": "checkpoint", "job_ids": []},
        ).json()
        for question in ("checkpoint说明什么？", "为什么？"):
            previous = project["steps"][-1]["id"] if project["steps"] else None
            project = client.post(
                "/api/projects/" + project["id"] + "/steps",
                headers=headers,
                json={
                    "revision": project["revision"],
                    "question": question,
                    "offline": True,
                    "coverage_mode": "question",
                    "reply_to_step_id": previous,
                },
            ).json()
            assert (
                client.post(
                    "/api/projects/" + project["id"] + "/run",
                    headers=headers,
                ).status_code
                == 202
            )
            for _ in range(50):
                project = client.get("/api/projects/" + project["id"]).json()
                if not project["worker_running"]:
                    break
                time.sleep(0.01)
            assert project["steps"][-1]["result"]["scope"]["jobs"] == []
            assert project["steps"][-1]["result"]["scope"]["archived_public_ids"] == [doc["id"]]
        assert project["usage"]["calls"] == 0
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


def test_public_library_searches_latest_versions_without_refetching_or_erasing_history(
    web, monkeypatch
):
    client, headers, settings, _ = web
    titles = iter(["Original draft", "Current 100% state", "Separate document"])

    async def fetch(url):
        body = f"<title>{next(titles)}</title><main>checkpoint documentation</main>".encode()
        return 200, {"content-type": "text/html"}, body

    monkeypatch.setattr(public_documents, "pinned_request", fetch)
    archived = [
        client.post(
            "/api/public-documents",
            headers=headers,
            json={"url": url},
        ).json()["document"]
        for url in (
            "https://example.com/docs",
            "https://example.com/docs",
            "https://example.com/other",
        )
    ]

    async def forbidden(url):
        raise AssertionError("Browsing the library must not refetch a website")

    monkeypatch.setattr(public_documents, "pinned_request", forbidden)
    first = client.get("/api/public-documents?limit=1").json()
    second = client.get("/api/public-documents?limit=1&offset=1").json()
    assert first["total"] == second["total"] == 2
    assert first["documents"][0]["id"] != second["documents"][0]["id"]
    assert all("text" not in row and "path" not in row for row in first["documents"])
    assert client.get("/api/public-documents", params={"q": "Original"}).json()["total"] == 0
    found = client.get("/api/public-documents", params={"q": "%"}).json()
    assert found["total"] == 1 and found["documents"][0]["id"] == archived[1]["id"]
    assert found["documents"][0]["integrity"] == "verified"
    assert client.get("/api/public-documents?q=example.com").json()["total"] == 2
    old = client.get("/api/public-documents/" + archived[0]["id"]).json()
    assert old["title"] == "Original draft" and old["integrity"] == "verified"
    (settings.raw_directory / "public" / (archived[1]["id"] + ".html")).write_bytes(b"changed")
    changed = client.get("/api/public-documents", params={"q": "%"}).json()
    assert changed["documents"][0]["integrity"] == "missing_or_changed"
    schema = client.get("/api/openapi.json").json()
    assert {p["name"] for p in schema["paths"]["/api/public-documents"]["get"]["parameters"]} == {
        "q",
        "limit",
        "offset",
    }


@pytest.mark.parametrize("query", ["limit=51", "offset=-1", "q=" + "x" * 201])
def test_public_library_bounds_are_validated(web, query):
    client, _, _, _ = web
    assert client.get("/api/public-documents?" + query).status_code == 422
