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
        assert html.count('data-demo-step="') == 8
        assert 'data-demo-tourbar aria-label="演示导览"' in html
        assert 'data-demo-direction="-1"' in html and 'data-demo-direction="1"' in html
        assert "共用工具并不等于承担相同工作" in html
        assert "较新不自动代表更正确" in html
        auth = {"X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', html)[1]}
        main = app.links["main"]
        data = client.get(f"/api/career/{main}").json()
        assert len(client.get("/api/career").json()) == 3
        assert len(data["requirements"]) == 7
        assert len(data["pitches"]) == 1
        assert data["tasks"][0]["state"] == "done"
        task = data["tasks"][0]
        assert len(task["comparison_rows"]) == 2
        assert all("write=2" in row["observed"] and "虚构预置" in row["observed"]
                   for row in task["comparison_rows"])
        assert all(row["input"] and row["expected"] for row in task["comparison_rows"])
        story = next(row for row in data["stories"] if row["id"] == app.links["story"])
        assert story["source_task_id"] == task["id"]
        archived_story = client.get("/api/public-documents/" + story["document_id"]).json()
        assert "由个人练习整理" in archived_story["text"]
        start = client.get("/api/career/" + app.links["start_goal"]).json()
        assert start["profile"] is None and not start["jobs"] and not start["results"]
        assert start["focus_question_id"] == app.links["start_question"]
        assert start["questions"][0]["material_ids"] == [start["materials"][0]["id"]]
        prepared_start = client.post(
            f"/api/career/{start['id']}/prepare", headers=auth,
            json={"kind": "plan", "question_id": start["focus_question_id"]},
        )
        assert prepared_start.status_code == 201, prepared_start.text
        client.post(f"/api/projects/{start['id']}/run", headers=auth,
                    json={"step_id": prepared_start.json()["step_id"]})
        for _ in range(200):
            starting = client.get(f"/api/career/{start['id']}").json()
            if not starting["running"] and starting["results"][0]["result"]:
                break
            time.sleep(0.01)
        start_result = starting["results"][0]["result"]
        assert start_result["status"] == "completed", start_result.get("stop_reason")
        assert start_result["application_plan"]["purpose"] == "understanding_check"
        cases = start_result["application_plan"]["actions"][0]["comparison_rows"]
        assert len(cases) == 2 and "差异为10" in cases[1]["expected"]
        assert "谁决定验收仍未知" in cases[1]["expected"]
        synthesis = next(row for row in data["results"] if row["step_id"] == app.links["synthesis"])
        assert synthesis["result"]["status"] == "completed"
        assert synthesis["insight_ids"] == [app.links[key]
                                            for key in ("old_insight", "insight", "work_insight")]
        inputs = synthesis["result"]["career_learning_context"]["selected_notes"]
        assert len(inputs) == 3 and not inputs[0]["use_for_research"]
        assert data["insights"][0]["use_for_research"] is False
        assert data["insights"][1]["use_for_research"] is True
        inquiry = next(row for row in data["questions"] if row["id"] == app.links["question"])
        assert data["focus_question_id"] == inquiry["id"]
        assert inquiry["hypothesis_a"] and inquiry["hypothesis_b"]
        assert inquiry["source_passage"]["quote"] and inquiry["evidence_passages"][0]["quote"]
        assert inquiry["state"] == "open" and "原解释不足" in inquiry["conclusion"]
        mapped = next(row for row in data["results"] if row["step_id"] == app.links["map"])
        assert len(mapped["result"]["work_map"]["work_types"]) == 2
        assert {row["predicate"] for row in mapped["result"]["work_map"]["work_relations"]} == {
            "requires",
            "produces",
        }
        old_id, revised_id = app.links["old_insight"], app.links["insight"]
        recalled = [
            note["id"]
            for row in data["results"]
            for note in (row.get("result") or {})
            .get("career_learning_context", {})
            .get("notes", [])
        ]
        assert old_id in recalled and revised_id in recalled
        challenge = next(row for row in data["results"] if row["kind"] == "challenge")
        assert challenge["question_id"] == inquiry["id"]
        assert inquiry["evidence_passages"][0]["public_document_id"] in {
            row.get("public_document_id") for row in challenge["result"]["evidence"]
        }
        assert (
            len([row for row in data["results"] if row.get("question_id") == app.links["question"]])
            >= 3
        )
        answer = next(row for row in data["results"] if row["kind"] == "answer")
        assert answer["understanding_check"] and answer["question_id"] == inquiry["id"]
        assert any(
            row.get("public_document_id") == answer["answer_document_id"]
            for row in answer["result"]["evidence"]
        )
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
        # The walkthrough must also support starting from working material before choosing a JD.
        material_goal = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "虚构资料起步",
                "goal": "先理解交付与未知",
                "material_title": "虚构操作说明",
                "material_text": "虚构说明：保留失败样例与运行记录。",
            },
        ).json()
        prepared = client.post(
            f"/api/career/{material_goal['id']}/prepare", headers=auth, json={"kind": "role"}
        )
        assert prepared.status_code == 201, prepared.text
        client.post(
            f"/api/projects/{material_goal['id']}/run",
            headers=auth,
            json={"step_id": prepared.json()["step_id"]},
        )
        for _ in range(200):
            current = client.get(f"/api/career/{material_goal['id']}").json()
            if not current["running"] and current["results"][0]["result"]:
                break
            time.sleep(0.01)
        assert current["results"][0]["result"]["status"] == "completed"
        assert current["results"][0]["result"]["evidence"]
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
