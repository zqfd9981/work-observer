"""A research presentation stays attached to its question and remains user-authored."""

import re

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_research_pitch_is_editable_without_changing_investigation_or_using_a_model(tmp_path):
    database = tmp_path / "research-pitch.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(create_app(settings, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code == 201, response.text
            return response.json()

        goal = post("/api/career", {"title": "合成调查", "goal": "解释自己的思考变化"})
        base = "/api/career/" + goal["id"]
        question = post(base + "/questions", {"question": "怎样解释失败输入？"})["questions"][0]
        original = client.get(base).json()
        values = {"title": "失败输入调查讲述", "question_id": question["id"],
                  "text": "只比较过合成输入，真实条件与生产效果尚未验证。"}
        saved = post(base + "/pitches", values)
        pitch = saved["pitches"][0]
        assert pitch["question_id"] == question["id"] and pitch["origin"] == "user"
        changed = client.patch(base + "/pitches/" + pitch["id"], headers=auth,
                               json={**values, "text": "修订讲述：观察范围有限，仍保留未知。"})
        assert changed.status_code == 200
        assert changed.json()["pitches"][0]["id"] == pitch["id"]
        assert changed.json()["pitches"][0]["created_at"] == pitch["created_at"]
        # Later changes to the investigation do not rewrite a saved presentation.
        client.patch(base + "/questions/" + question["id"], headers=auth,
                     json={"question": "重新限定后的调查问题？"})
        reopened = client.get(base).json()
        assert reopened["pitches"][0]["text"] == "修订讲述：观察范围有限，仍保留未知。"
        assert reopened["pitches"][0]["question_id"] == question["id"]
        for key in ("results", "tasks", "stories", "insights", "usage"):
            assert reopened[key] == original[key]
        other = post("/api/career", {"title": "其他目标", "goal": "其他方向"})
        foreign = post("/api/career/" + other["id"] + "/questions", {
            "question": "属于其他目标的问题？",
        })["questions"][0]
        invalid = client.post(base + "/pitches", headers=auth,
                              json={**values, "question_id": foreign["id"]})
        assert invalid.status_code == 422
        assert len(client.get(base).json()["pitches"]) == 1
