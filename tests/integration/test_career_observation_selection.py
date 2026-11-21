"""Select exact acquisition records without replacing an earlier investigation with latest JDs."""

import re

from starlette.testclient import TestClient
from test_career_job_changes import JobChangesModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_select_historical_observations_then_study_the_chosen_pair(tmp_path):
    database = tmp_path / "observation-selection.db"
    upgrade(database)
    model = JobChangesModel()
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model,
            reports_dir=tmp_path / "reports",
        ),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        def import_body(text):
            return post(
                "/api/import",
                {
                    "title": "合成变化观察自选基线",
                    "company": "合成团队",
                    "external_id": "selected-records",
                    "description": text,
                    "data_kind": "synthetic",
                },
            )["job_id"]

        original_text = "负责接口验证。交付本地样例；实际分工未知。"
        job = import_body(original_text)
        for text in (
            "商科背景更佳。负责业务复盘，实际验收权仍未知。",
            original_text,
            "后来取得的原文只描述工具运维；不替换选定的早期对照。",
        ):
            assert import_body(text) == job
        path = "/api/jobs/" + job + "/compare-history"
        default = client.get(path).json()
        observations = default["observations"]
        assert len(observations) == 4
        assert observations[0]["snapshot_id"] == observations[2]["snapshot_id"]
        assert default["before"]["observation_id"] == observations[2]["observation_id"]
        assert default["after"]["observation_id"] == observations[3]["observation_id"]
        history_before = client.get("/api/jobs/" + job + "/history").json()

        def compare(left, right):
            return client.get(
                path,
                params={
                    "before_observation_id": left["observation_id"],
                    "after_observation_id": right["observation_id"],
                },
            )

        selected_response = compare(observations[0], observations[1])
        assert selected_response.status_code == 200
        selected = selected_response.json()
        assert selected["before"] == observations[0] and selected["after"] == observations[1]
        unchanged = compare(observations[0], observations[2]).json()
        assert unchanged["status"] == "compared" and unchanged["changes"] == []
        assert unchanged["description_diff"] == ""
        assert {row["observation_id"] for row in unchanged["evidence"]} == {
            observations[0]["observation_id"],
            observations[2]["observation_id"],
        }
        assert all(row["quote"] == original_text for row in unchanged["evidence"])
        assert (
            compare(observations[1], observations[0]).json()["error_code"]
            == "HISTORY_VERSION_ORDER_INVALID"
        )
        assert (
            compare(observations[0], observations[0]).json()["error_code"]
            == "HISTORY_VERSION_ORDER_INVALID"
        )
        other = post(
            "/api/import",
            {
                "title": "合成其他岗位",
                "company": "另一合成团队",
                "description": "不在这次原文对照中。",
                "data_kind": "synthetic",
            },
        )["job_id"]
        foreign = client.get("/api/jobs/" + other + "/compare-history").json()["observations"][0]
        denied = compare(observations[0], foreign)
        assert (
            denied.status_code == 404
            and denied.json()["error_code"] == "HISTORY_OBSERVATION_NOT_FOUND"
        )
        assert client.get(path, params={"before_observation_id": "not-an-id"}).status_code == 422
        assert client.get("/api/jobs/" + job + "/history").json() == history_before

        identity = post(
            "/api/career",
            {
                "title": "合成：按观察起点研究变化",
                "goal": "对照选定的两次原文，而非最新两次",
                "job_ids": [job, other],
            },
        )["id"]
        base = "/api/career/" + identity
        before, after = selected["before"], selected["after"]
        older = next(
            row for row in selected["evidence"] if row["observation_id"] == before["observation_id"]
        )
        newer = next(
            row for row in selected["evidence"] if row["observation_id"] == after["observation_id"]
        )

        def passage(row):
            return {key: row[key] for key in ("document_id", "snapshot_id", "start", "end")}

        question = post(
            base + "/questions",
            {
                "question": "这两次取得之间，工作与资格条件究竟如何变化？",
                "state": "open",
                "selected_job_ids": [job],
                "source_passage": passage(older),
                "next_evidence": f"按来源截止 {before['read_as_of']} "
                f"与截止 {after['read_as_of']} 分别回读。",
            },
        )["questions"][-1]
        post(
            base + "/questions/" + question["id"] + "/passages",
            {
                "passage": passage(newer),
                "user_note": "所选的较晚原文，仍需核对变化含义。",
            },
        )
        saved = client.get(base).json()["questions"][0]
        assert import_body("第五次取得只写日志维护，不得替换先前的变化问题。") == job
        studied = run_stage(
            client, identity, auth, "ask", question_id=question["id"], question=question["question"]
        )
        result = studied["results"][0]["result"]
        assert result["status"] == "completed" and result["model_calls"] == 3
        assert {row["snapshot_id"] for row in result["evidence"]} == {
            before["snapshot_id"],
            after["snapshot_id"],
        }
        assert result["claims"][1]["requirement"] == "preferred"
        assert studied["questions"][0] == saved
        assert compare(observations[0], observations[1]).json()["before"] == before
