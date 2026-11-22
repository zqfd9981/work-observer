"""Start with two to six explicit JDs without calling a model or broadening research."""

import re

import pytest
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class NoModel:
    async def turn(self, history):
        raise AssertionError("Saving a comparison must not call a provider")


@pytest.mark.parametrize("count", [2, 6])
def test_first_inquiry_keeps_its_explicit_jobs_after_reopening(tmp_path, count):
    database = tmp_path / "comparison-start.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")

    def app():
        return create_app(settings, model=NoModel(), reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        jobs = []
        for index in range(count + 1):
            response = client.post("/api/import", headers=auth, json={
                "title": f"合成岗位{index}", "company": "合成团队", "data_kind": "synthetic",
                "description": f"合成原文{index}：交付物与任务条件待分别核对。",
            })
            assert response.status_code == 201, response.text
            jobs.append(response.json()["job_id"])
        payload = {"title": "合成岗位对照", "goal": "理解交付物与责任差异",
                   "first_question": "两份岗位分别做什么？", "job_ids": jobs[:count]}
        before = client.get("/api/career").json()
        for bad in [
            {"first_question_job_ids": [jobs[count]]},
            {"first_question_job_ids": [jobs[0], jobs[0]]},
            {"first_question_job_ids": jobs[:count], "first_question": ""},
        ]:
            response = client.post("/api/career", headers=auth, json={**payload, **bad})
            assert response.status_code == 422, response.text
            assert client.get("/api/career").json() == before
        response = client.post("/api/career", headers=auth, json={
            **payload, "first_question_job_ids": jobs[:count],
        })
        assert response.status_code == 201, response.text
        goal = response.json()
        identity = goal["id"]
        question = goal["questions"][0]
        assert question["selected_job_ids"] == jobs[:count]
        assert goal["focus_question_id"] == question["id"]
        assert not goal["results"] and goal["usage"]["calls"] == 0
        response = client.patch("/api/career/" + identity, headers=auth, json={
            "title": payload["title"], "goal": payload["goal"], "job_ids": jobs[:6],
        })
        assert response.status_code == 200, response.text
        assert response.json()["questions"][0]["selected_job_ids"] == jobs[:count]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        base = "/api/career/" + identity
        restored = client.get(base).json()
        assert len(restored["jobs"]) == min(count + 1, 6)
        assert restored["questions"][0]["selected_job_ids"] == jobs[:count]
        prepared = client.post(base + "/prepare", headers=auth, json={
            "kind": "ask", "question_id": question["id"], "question": "按这两个岗位比较。",
        })
        assert prepared.status_code == 201, prepared.text
        saved = client.get(base).json()
        assert saved["results"][0]["selected_job_ids"] == jobs[:count]
        assert saved["usage"]["calls"] == 0
