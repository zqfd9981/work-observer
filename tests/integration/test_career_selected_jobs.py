"""A chosen job pair stays the scope of its inquiry without changing the workspace."""

import re

from starlette.testclient import TestClient
from test_career_multi_job_reading import MultiJobModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_selected_pair_continues_and_survives_saved_question_and_reopen(tmp_path):
    database = tmp_path / "selected-jobs.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MultiJobModel(batch=True)

    def open_app():
        return TestClient(
            create_app(settings, model=model, reports_dir=tmp_path / "reports"),
            base_url="http://127.0.0.1",
        )

    with open_app() as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        jobs = [
            post("/api/import", {
                "title": f"合成六岗限定{i}", "company": "合成团队", "data_kind": "synthetic",
                "description": f"负责第{i}类接口验证。交付样例与观察；验收标准未知。",
            })["job_id"]
            for i in range(6)
        ]
        identity = post("/api/career", {
            "title": "合成：六岗中只比较两岗", "goal": "比较各自任务", "job_ids": jobs,
        })["id"]
        base = "/api/career/" + identity

        def study(expected, **values):
            values.setdefault("question", "分别核对两岗任务与未知。")
            data = run_stage(client, identity, auth, "ask", **values)
            row = data["results"][0]
            assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
            assert {item["job_id"] for item in row["result"]["evidence"]} == set(expected)
            assert {item["id"] for item in row["result"]["scope"]["jobs"]} == set(expected)
            assert len(row["result"]["claims"]) == len(expected)
            frozen_jobs = model.contexts[-1]["fixed_scope"]["jobs"]
            assert {item["id"] for item in frozen_jobs} == set(expected)
            assert {item["id"] for item in data["jobs"]} == set(jobs)
            step = next(item for item in client.get("/api/projects/" + identity).json()["steps"]
                        if item["id"] == row["step_id"])
            assert step["job_ids"] == expected
            return row

        # Names in the question do not themselves restrict the readable job pool.
        study(jobs, question="只比较合成六岗限定4和合成六岗限定1的任务。")
        pair = [jobs[4], jobs[1]]
        selected = study(pair, question="比较这两岗的任务。", selected_job_ids=pair)
        assert selected["selected_job_ids"] == pair
        followed = study(pair, question="分别还有哪些未知？", source_step_id=selected["step_id"])
        assert followed["selected_job_ids"] == pair
        question = post(base + "/questions", {
            "question": "两岗任务的差异与限制是什么？", "source_step_id": selected["step_id"],
        })["questions"][0]
        assert question["selected_job_ids"] == pair
        study(pair, question_id=question["id"])
        response = client.patch(base + "/questions/" + question["id"], headers=auth, json={
            "question": question["question"],
            "hypothesis_a": "任务不同", "hypothesis_b": "表述不同",
        })
        assert response.status_code == 200, response.text
        assert response.json()["questions"][0]["selected_job_ids"] == pair
        # A deliberate one-round expansion does not edit the saved question or targets.
        expanded = study(jobs, question_id=question["id"], selected_job_ids=[])
        assert expanded["selected_job_ids"] == []
        assert client.get(base).json()["questions"][0]["selected_job_ids"] == pair
        study(pair, question_id=question["id"])
        turns = len(model.contexts)
        for invalid in ([jobs[0], jobs[0]], ["f" * 32]):
            response = client.post(base + "/prepare", headers=auth, json={
                "kind": "ask", "question": "比较任务", "selected_job_ids": invalid,
            })
            assert response.status_code == 422, response.text
        assert len(model.contexts) == turns

    with open_app() as client:
        reopened = client.get(base).json()
        assert {row["id"] for row in reopened["jobs"]} == set(jobs)
        assert reopened["questions"][0]["selected_job_ids"] == pair
        saved = next(row for row in reopened["results"] if row["step_id"] == selected["step_id"])
        assert saved == selected
