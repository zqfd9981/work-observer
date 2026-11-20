"""The product walkthrough uses disposable data and no model/search provider."""

import re
import time

from starlette.testclient import TestClient
from typer.testing import CliRunner

from work_observer.career_demo import create_demo_app
from work_observer.cli import app as cli
from work_observer.config import Settings
from work_observer.connectors import public_documents


def test_demo_walkthrough_ignores_user_configuration_and_keeps_provider_calls_at_zero(
    tmp_path, monkeypatch
):
    protected = tmp_path / "original.db"
    protected.write_bytes(b"Existing user data must remain untouched.")
    monkeypatch.setenv("WO_DATABASE_PATH", str(protected))
    monkeypatch.setenv("WO_MODEL_API_KEY", "synthetic-do-not-load")

    def no_settings(*args, **kwargs):
        raise AssertionError("Demo must not load user settings")

    async def no_network(*args, **kwargs):
        raise AssertionError("Demo must not connect to providers")

    monkeypatch.setattr(Settings, "load", no_settings)
    monkeypatch.setattr(public_documents, "pinned_request", no_network)
    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    directory = tmp_path / "demo"
    directory.mkdir()
    app = create_demo_app(directory)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        html = client.get("/").text
        assert 'name="wo-demo"' in html and "预置脚本演示" in html
        assert "不代表真实模型研究效果" in html and "synthetic-do-not-load" not in html
        auth = {"X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', html)[1]}
        main = app.links["main"]
        data = client.get(f"/api/career/{main}").json()
        assert len(client.get("/api/career").json()) == 2
        assert len(data["requirements"]) == 7
        assert len(data["pitches"]) == 1
        assert data["tasks"][0]["state"] == "done"
        assert data["insights"][0]["use_for_research"] is False
        assert data["insights"][1]["use_for_research"] is True
        assert (
            len([row for row in data["results"] if row.get("question_id") == app.links["question"]])
            >= 3
        )
        answer = next(row for row in data["results"] if row["kind"] == "answer")
        original = client.get("/api/public-documents/" + answer["answer_document_id"]).json()
        assert "虚构回答" in original["text"]
        transferred = client.get("/api/career/" + app.links["next_goal"]).json()
        assert transferred["questions"][0]["state"] == "open"
        assert transferred["questions"][0]["carried_understanding"]
        prepared = client.post(f"/api/career/{main}/prepare", headers=auth, json={"kind": "role"})
        assert prepared.status_code == 201, prepared.text
        running = client.post(
            f"/api/projects/{main}/run", headers=auth, json={"step_id": prepared.json()["step_id"]}
        )
        assert running.status_code == 202, running.text
        for _ in range(200):
            data = client.get(f"/api/career/{main}").json()
            if not data["running"] and data["results"][0]["result"]:
                break
            time.sleep(0.01)
        assert data["results"][0]["result"]["status"] == "completed"
        assert (
            client.post(
                "/api/public-documents", headers=auth, json={"url": "https://example.com"}
            ).status_code
            == 403
        )
        assert client.post("/api/operations/tick", headers=auth, json={}).status_code == 403
    assert protected.read_bytes() == b"Existing user data must remain untouched."


def test_serve_demo_does_not_load_the_normal_environment(monkeypatch):
    expected = object()
    paths, starts = [], []

    def factory(directory):
        paths.append(directory)
        assert directory.is_dir()
        return expected

    def no_settings(*args, **kwargs):
        raise AssertionError("Normal settings were loaded")

    monkeypatch.setattr(Settings, "load", no_settings)
    monkeypatch.setattr("work_observer.career_demo.create_demo_app", factory)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: starts.append((args, kwargs)))
    result = CliRunner().invoke(cli, ["serve", "--demo", "--port", "19069"])
    assert result.exit_code == 0, result.output
    assert "预置脚本" in result.output
    assert starts[0][0][0] is expected and starts[0][1]["port"] == 19069
    assert not paths[0].exists()
