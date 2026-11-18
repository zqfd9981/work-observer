"""完整工作台的领域观察、后续项目幂等与重启，全部使用合成资料。"""

import re

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_updates_http_roundtrip_project_retry_scope_conflict_and_restart(tmp_path):
    database = tmp_path / "business.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    options = {"reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **options), base_url="http://127.0.0.1") as client:
        page = client.get("/").text
        auth = {"X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', page)[1]}
        assert 'id="page-updates"' in page
        assert client.get("/assets/updates.js").status_code == 200
        jobs = []
        for external_id in ("one", "two"):
            imported = client.post(
                "/api/import",
                headers=auth,
                json={
                    "title": "合成更新岗位",
                    "company": "合成公司",
                    "external_id": external_id,
                    "description": "Python业务应用开发，Docker加分",
                    "data_kind": "synthetic",
                },
            )
            assert imported.status_code == 201
            jobs.append(imported.json()["job_id"])
        captures = []
        for title in ("HTTP观察一", "HTTP观察二"):
            response = client.post(
                "/api/updates/captures", headers=auth, json={"title": title, "terms": ["Python"]}
            )
            assert response.status_code == 201
            captures.append(response.json()["id"])
        pair = {"before_id": captures[0], "after_id": captures[1]}
        report = client.post("/api/updates/compare", headers=auth, json=pair).json()
        assert report["content_changes"] == []
        assert report["statistics"]["after"] == [
            {"term": "Python", "literal_jobs": 2, "denominator": 2}
        ]
        assert report["trend_status"] == "insufficient_comparable_time_series"
        assert (
            client.post("/api/updates/compare", headers=auth, json=pair).json()["id"]
            == report["id"]
        )
        source_key = "domain-update:" + report["id"]
        project_input = {
            "title": "核对领域观察变化",
            "goal": "检查合成观察中是否真有职责变化",
            "job_ids": jobs,
            "source_key": source_key,
        }
        for _ in range(2):
            saved = client.post(
                "/api/updates/reports/" + report["id"] + "/followup",
                headers=auth,
                json={"note": project_input["goal"]},
            )
            assert saved.status_code == 201
            created = client.post("/api/projects", headers=auth, json=project_input)
            assert created.status_code == 201
            project = created.json()
            stepped = client.post(
                "/api/projects/" + project["id"] + "/steps",
                headers=auth,
                json={
                    "revision": project["revision"],
                    "question": project_input["goal"],
                    "completion": "区分原文、样本与方法变化",
                    "key": source_key + ":followup",
                },
            )
            assert stepped.status_code == 201
        assert len(client.get("/api/projects").json()) == 1
        project = client.get("/api/projects/" + project["id"]).json()
        assert len(project["steps"]) == 1
        assert project["steps"][0]["state"] == "queued"
        revised = client.patch(
            "/api/projects/" + project["id"],
            headers=auth,
            json={
                "revision": project["revision"],
                "goal": "用户明确修订目标",
                "job_ids": [jobs[0]],
            },
        )
        assert revised.status_code == 200
        conflict = client.post("/api/projects", headers=auth, json=project_input)
        assert conflict.json()["error_code"] == "PROJECT_SOURCE_KEY_CONFLICT"
        assert client.get("/api/projects/" + project["id"]).json()["job_ids"] == [jobs[0]]
        assert client.post("/api/updates/captures", json={"title": "无同源凭证"}).status_code == 403
        schema = client.get("/api/openapi.json").json()
        assert "/api/updates/captures" in schema["paths"]
        assert "/api/updates/reports/{id}/followup" in schema["paths"]
    with TestClient(create_app(settings, **options), base_url="http://127.0.0.1") as client:
        data = client.get("/api/updates").json()
        assert len(data["captures"]) == 2
        assert len(data["reports"]) == 1
        assert client.get("/api/updates/reports/" + report["id"]).json()["content_changes"] == []
        assert len(client.get("/api/projects").json()) == 1
