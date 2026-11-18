"""分层记忆可操作入口的隔离验收；无实际模型或来源请求。"""

import json
import re

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from work_observer.api.web import create_app
from work_observer.cli import app
from work_observer.config import Settings
from work_observer.reports.results import audit_result
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def memory_web(tmp_path):
    settings = Settings(database_path=tmp_path / "app.db", raw_directory=tmp_path / "raw")
    upgrade(settings.database_path)
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        yield client, {"X-WO-Token": token}, settings


def test_memory_http_project_fields_conflict_review_and_schema(memory_web):
    client, auth, _ = memory_web
    payload = {
        "kind": "preference",
        "content": "合成偏好上海",
        "scope": "project",
        "project_id": "a" * 32,
        "subject": "工作地点",
        "valid_from": "2026-01-01T00:00:00+08:00",
        "valid_until": "2099-01-01T00:00:00+08:00",
    }
    first = client.post("/api/memories", json=payload, headers=auth)
    assert first.status_code == 201
    second = client.post("/api/memories", json={**payload, "content": "合成偏好北京"}, headers=auth)
    assert second.status_code == 201 and second.json()["status"] == "conflict"
    listed = client.get("/api/memories").json()
    assert len(listed) == 2 and all(row["status"] == "conflict" for row in listed)
    assert all(not row["validity"]["eligible"] for row in listed)
    assert client.get("/api/memories?project_id=" + "b" * 32).json() == []
    accepted = client.post("/api/memories/" + second.json()["id"] + "/accept", headers=auth)
    assert accepted.status_code == 200 and accepted.json()["status"] == "active"
    listed = client.get("/api/memories?history=1").json()
    assert {row["status"] for row in listed} == {"active", "withdrawn"}
    assert (
        client.post("/api/memories/" + first.json()["id"] + "/accept", headers=auth).status_code
        == 400
    )
    schema = client.get("/api/openapi.json").json()
    fields = schema["components"]["schemas"]["MemoryInput"]["properties"]
    assert {"scope", "project_id", "subject", "valid_from", "valid_until", "origin"}.issubset(
        fields
    )
    assert "hypothesis" in fields["kind"]["pattern"]


def test_http_model_proposals_cannot_enable_themselves_and_methods_are_not_facts(memory_web):
    client, auth, _ = memory_web
    for kind in ("preference", "correction", "hypothesis", "method"):
        created = client.post(
            "/api/memories",
            json={"kind": kind, "content": "合成 RAG 记录", "origin": "agent"},
            headers=auth,
        )
        assert created.status_code == 201 and created.json()["status"] == "candidate"
        identity = created.json()["id"]
        accepted = client.post(f"/api/memories/{identity}/activate", headers=auth)
        assert accepted.json()["status"] == "active"
    for payload in (
        {"kind": "preference", "content": "不能自设状态", "origin": "agent", "status": "active"},
        {"kind": "preference", "content": "不能伪造来源类别", "origin": "trusted"},
    ):
        assert client.post("/api/memories", json=payload, headers=auth).status_code == 422


def test_http_expired_memory_reports_reason_and_historical_result_is_stale(memory_web):
    client, auth, settings = memory_web
    item = client.post(
        "/api/memories",
        json={
            "kind": "preference",
            "content": "合成过期条件",
            "valid_until": "2020-01-01T00:00:00Z",
        },
        headers=auth,
    ).json()
    listed = client.get("/api/memories").json()[0]
    assert listed["status"] == "active"
    assert listed["validity"]["reasons"] == ["outside_effective_time"]
    repo = Repository(settings.database_path)
    try:
        audited = audit_result({"context_memory_used": [item]}, repo)
        assert audited["stale_memory"]
        assert audited["memory_issues"] == [{"id": item["id"], "reason": "outside_effective_time"}]
    finally:
        repo.close()


def test_memory_cli_scope_candidate_and_conflict_selection(memory_web, monkeypatch):
    _, _, settings = memory_web
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls, *args, **kwargs: settings))
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(app, list(args))
        assert result.exit_code == 0, (result.stdout, result.exception)
        return json.loads(result.stdout)

    first = invoke(
        "memory-add",
        "preference",
        "合成上海条件",
        "--subject",
        "地点",
        "--scope",
        "project",
        "--project-id",
        "a" * 32,
    )
    second = invoke(
        "memory-add",
        "preference",
        "合成北京条件",
        "--subject",
        "地点",
        "--scope",
        "project",
        "--project-id",
        "a" * 32,
    )
    assert first["scope"] == "project" and second["status"] == "conflict"
    assert invoke("memory-change", second["id"], "accept")["status"] == "active"
    method = invoke("memory-add", "method", "RAG 研究须补查反例", "--origin", "agent")
    assert method["status"] == "candidate"
    assert invoke("memory-change", method["id"], "activate")["status"] == "active"
