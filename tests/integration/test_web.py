"""本机 HTTP 层的真实业务集成测试；资料与模型均为隔离测试材料。"""

import asyncio
import json
import re
import time

import pytest
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


@pytest.fixture
def web(tmp_path):
    db = tmp_path / "web.db"
    upgrade(db)
    settings = Settings(database_path=db, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        html = client.get("/")
        token = re.search(r'name="wo-token" content="([^"]+)"', html.text)[1]
        yield client, {"X-WO-Token": token}, settings, tmp_path


def jd(**changes):
    return {
        "title": "测试岗位（非真实招聘）",
        "company": "测试公司",
        "description": "模拟 JD：必备 Python，加分 Docker。",
        "city": "上海",
        "external_id": "isolated-test",
        **changes,
    }


def poll(client, identity):
    for _ in range(50):
        data = client.get("/api/research/" + identity).json()
        if data["state"] != "running":
            return data
        time.sleep(0.01)
    pytest.fail("测试研究未在预期短时间内结束")


def test_page_assets_headers_and_overview(web):
    client, _, _, _ = web
    page = client.get("/")
    assert "岗位资料" in page.text and "__WO_TOKEN__" not in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/app.css").status_code == 200
    assert client.get("/assets/not-an-asset").status_code == 404
    data = client.get("/api/overview").json()
    assert data["jobs"] == data["details"] == 0 and data["model_configured"] is False


def test_same_origin_and_csrf_protect_all_writes(web):
    client, headers, _, _ = web
    assert client.post("/api/import", json=jd()).status_code == 403
    assert (
        client.post(
            "/api/import", json=jd(), headers={**headers, "Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/jobs", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/jobs", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert (
        client.post(
            "/api/import", json=jd(), headers={**headers, "Origin": "http://127.0.0.1"}
        ).status_code
        == 201
    )


def test_import_query_detail_source_history_and_company_share_business(web):
    client, headers, _, _ = web
    first = client.post("/api/import", json=jd(salary="20-30K"), headers=headers)
    assert first.status_code == 201
    identity = first.json()["job_id"]
    second = client.post("/api/import", json=jd(salary="20-30K"), headers=headers).json()
    assert second["job_id"] == identity and second["stats"]["snapshots_new"] == 0
    jobs = client.get("/api/jobs?salary_min=25000&city=上海&detail=detail").json()
    assert jobs["counts"]["matched"] == jobs["counts"]["candidate_details"] == 1
    assert client.get("/api/jobs?salary_min=50000").json()["jobs"] == []
    job = client.get("/api/jobs/" + identity).json()
    assert job["source"] == "manual" and job["current"]["source_published_at"] is None
    company = client.get("/api/companies/" + job["current"]["company_id"]).json()
    assert company["identity_status"] == "unverified" and company["jobs"][0]["id"] == identity
    history = client.get("/api/jobs/" + identity + "/history").json()
    assert len(history) == 2 and history[0]["response_origin"] == "manual"
    search = client.get("/api/search?term=Python").json()
    source = client.get("/api/sources/" + search["evidence"][0]["document_id"]).json()
    assert source["integrity"] == "verified" and "path" not in source
    assert "document_path" not in json.dumps(history)
    assert not any(
        private in json.dumps(job) for private in ("security_id", "access_context", "source_job_id")
    )


@pytest.mark.parametrize(
    "payload",
    [
        jd(description="https://example.com/job"),
        jd(description=""),
        jd(source_published_at="2026-11-18"),
        jd(security_id="must-not-echo"),
        [jd()],
    ],
)
def test_import_validation_never_echoes_raw_invalid_data(web, payload):
    client, headers, _, _ = web
    response = client.post("/api/import", json=payload, headers=headers)
    assert response.status_code == 422
    assert "must-not-echo" not in response.text
    assert client.get("/api/overview").json()["jobs"] == 0


def test_bad_queries_missing_ids_large_bodies_and_no_collection_route(web):
    client, headers, _, _ = web
    assert client.get("/api/jobs?limit=10000").status_code == 422
    assert client.get("/api/jobs?salary_min=50000&salary_max=1").status_code == 422
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.get("/api/reports/missing").status_code in {400, 404}
    assert client.get("/api/collect").status_code == 404
    assert (
        client.post(
            "/api/import",
            content=b"x" * 512001,
            headers={**headers, "Content-Type": "application/json"},
        ).json()["error_code"]
        == "IMPORT_TOO_LARGE"
    )
    assert (
        client.post("/api/import", content="{}", headers=headers).json()["error_code"]
        == "JSON_BODY_REQUIRED"
    )


def test_offline_research_explicit_save_idempotency_and_download(web):
    client, headers, _, _ = web
    identity = client.post("/api/import", json=jd(), headers=headers).json()["job_id"]
    started = client.post(
        "/api/research",
        json={"question": "模拟证据研究", "job_ids": [identity], "offline": True},
        headers=headers,
    )
    assert started.status_code == 202
    run_id = started.json()["id"]
    run = poll(client, run_id)
    assert run["result"]["status"] == "evidence_only" and run["result"]["model_calls"] == 0
    assert client.get("/api/reports").json() == []
    saved = client.post(f"/api/research/{run_id}/save", headers=headers).json()
    assert client.post(f"/api/research/{run_id}/save", headers=headers).json() == saved
    assert len(client.get("/api/reports").json()) == 1
    report_id = saved["report_id"]
    result = client.get("/api/reports/" + report_id).json()
    assert result["evidence"] == run["result"]["evidence"]
    assert "模拟证据研究" in client.get(f"/api/reports/{report_id}/download/md").text
    assert client.get(f"/api/reports/{report_id}/download/json").json()["status"] == "evidence_only"
    assert client.get(f"/api/reports/{report_id}/download/html").status_code == 404


def test_unconfigured_model_and_insufficient_details_are_not_success(web):
    client, headers, _, _ = web
    empty = client.post("/api/research", json={"question": "没有资料"}, headers=headers).json()
    assert poll(client, empty["id"])["result"]["status"] == "insufficient_evidence"
    client.post("/api/import", json=jd(), headers=headers)
    started = client.post("/api/research", json={"question": "模拟"}, headers=headers).json()
    result = poll(client, started["id"])["result"]
    assert result["status"] == "failed" and result["stop_reason"] == "MODEL_CONFIG_MISSING"
    assert client.get("/api/reports").json() == []


class SlowModel:
    async def turn(self, history):
        await asyncio.sleep(5)


def test_research_is_single_flight_reads_remain_available_and_shutdown_cancels(tmp_path):
    root = tmp_path
    db = root / "single-flight.db"
    upgrade(db)
    settings = Settings(database_path=db, raw_directory=root / "raw")
    with TestClient(
        create_app(settings, reports_dir=root / "reports", model=SlowModel()),
        base_url="http://127.0.0.1",
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        headers = {"X-WO-Token": token}
        client.post("/api/import", json=jd(), headers=headers)
        first = client.post(
            "/api/research", json={"question": "模拟慢研究"}, headers=headers
        ).json()
        assert (
            client.post("/api/research", json={"question": "重复启动"}, headers=headers).status_code
            == 409
        )
        assert client.get("/api/jobs").status_code == 200
        assert client.post(f"/api/research/{first['id']}/save", headers=headers).status_code == 409
        assert client.get("/api/overview").json()["active_research"] == first["id"]
