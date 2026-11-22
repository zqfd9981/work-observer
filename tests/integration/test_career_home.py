"""Returning home exposes saved inquiry and latest step without running research."""

import re
from copy import deepcopy

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


def test_home_listing_keeps_full_focus_and_latest_step_without_calls(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Opening home must not call a model")

    monkeypatch.setattr(ModelClient, "turn", forbidden)
    database = tmp_path / "home.db"
    upgrade(database)
    with TestClient(create_app(
        Settings(database_path=database, raw_directory=tmp_path / "raw"),
        reports_dir=tmp_path / "reports",
    ), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, payload):
            response = client.post(path, headers=auth, json=payload)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        assert client.get("/api/career").json() == []
        empty = post("/api/career", {"title": "尚未开始的合成目标", "goal": "理解工作"})
        question = "🧪" * 210 + "末尾条件：局部记录不能证明生产权限。"
        active = post("/api/career", {
            "title": "有待继续的合成目标", "goal": "逐步理解责任", "first_question": question,
            "material_text": "合成工作说明：对照记录与交付物。", "material_title": "合成原文",
        })
        base = "/api/career/" + active["id"]
        qid = active["focus_question_id"]
        prepared = post(base + "/prepare", {
            "kind": "ask", "question": "先查清交付物边界。", "question_id": qid,
        })
        task = post(base + "/experiments", {
            "title": "合成实验：条件变化", "task_or_ability": "核对条件",
            "deliverable": "对照记录", "completion_check": "分别记录预期与实际",
            "question_id": qid,
        })["tasks"][-1]
        observation = "合成反例：改变条件后没有产生预期交付物，适用性仍未知。"
        updated = client.patch(base + "/tasks/" + task["id"], headers=auth, json={
            "state": "done", "outcome": observation,
        })
        assert updated.status_code == 200
        planned = post(base + "/experiments", {
            "title": "另一项合成计划", "task_or_ability": "检查输入变化",
            "deliverable": "后续记录", "completion_check": "保留实际失败与未知",
            "question_id": qid,
        })["tasks"][-1]
        note = post(base + "/insights", {
            "previous_view": "以为同名任务会有相同责任。", "observation": "权限尚未披露。",
            "current_view": "需要分别核对交付与验收边界。", "open_question": "实际验收人是谁？",
            "question_id": qid,
        })["insights"][-1]
        before = deepcopy(client.get(base).json())
        listing = client.get("/api/career").json()
        assert listing[0]["id"] == active["id"]
        current = next(row for row in listing if row["id"] == active["id"])
        assert current["focus_question"] == question
        assert current["focus_question_id"] == qid
        latest = current["latest_research"]
        assert latest["step_id"] == prepared["step_id"]
        assert latest["kind"] == "ask" and latest["state"] == "queued"
        assert latest["question_id"] == qid
        assert latest["question"] == "先查清交付物边界。"
        resumes = {row["category"]: row for row in current["resume_items"]}
        assert set(resumes) == {
            "question", "research", "observation", "experiment", "understanding",
        }
        assert resumes["question"]["record_id"] == qid
        assert resumes["question"]["title"] == question
        assert resumes["observation"]["record_id"] == task["id"]
        assert resumes["observation"]["body"] == observation
        assert resumes["experiment"]["record_id"] == planned["id"]
        assert resumes["understanding"]["record_id"] == note["id"]
        assert resumes["research"]["record_id"] == prepared["step_id"]
        untouched = next(row for row in listing if row["id"] == empty["id"])
        assert untouched["resume_items"] == []
        assert untouched["latest_research"] is None
        assert untouched["focus_question"] is None and untouched["focus_question_id"] is None
        assert client.get(base).json() == before
        assert before["usage"]["calls"] == 0
