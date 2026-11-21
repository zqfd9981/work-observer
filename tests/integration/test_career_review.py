"""Browse saved understandings across goals without researching or changing their use."""

import re
from copy import deepcopy

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_global_review_keeps_full_notes_inquiry_links_scope_and_paging(tmp_path):
    database = tmp_path / "review.db"
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

        goals = [post("/api/career", {"title": f"合成回顾目标{index}", "goal": "积累有条件的理解"})
                 for index in range(2)]
        base = "/api/career/" + goals[0]["id"]
        question = post(base + "/questions", {"question": "合成父问题：哪些条件影响责任解释？"})[
            "questions"][0]
        old = post(base + "/insights", {
            "previous_view": "原先按工具名称猜职责。", "observation": "一次局部观察。",
            "current_view": "旧认识需要重新核实。", "open_question": "旧未知仍保留？",
            "question_id": question["id"],
        })["insights"][-1]
        full = "<原话>" + "适用条件与反例必须分别保留。" * 80 + "末尾条件：生产验收权未知。"
        revised = post(base + "/insights", {
            "previous_view": old["current_view"], "observation": "用户记录：重新对照条件。",
            "current_view": full, "open_question": "怎样解释尚未运行的反例？",
            "replaces_insight_id": old["id"],
        })["insights"][-1]
        for index in range(12):
            post(base + "/insights", {"previous_view": "原问题。", "observation": "虚构记录。",
                 "current_view": f"合成其他理解{index}。"})
        other_base = "/api/career/" + goals[1]["id"]
        independent = post(other_base + "/insights", {
            "previous_view": "不同工作线。", "observation": "另一次观察。",
            "current_view": "独立的当前理解。", "open_question": "尚需核对哪个来源？",
        })["insights"][-1]
        parked = post(other_base + "/insights", {
            "previous_view": "另一份原想法。", "observation": "保留原始记录。",
            "current_view": "显式搁置的独立理解。",
        })["insights"][-1]
        post(other_base + "/insights/" + parked["id"] + "/use", {"use_for_research": False})
        before = [deepcopy(client.get("/api/career/" + goal["id"]).json()) for goal in goals]

        def review(**params):
            response = client.get("/api/career/review", params=params)
            assert response.status_code == 200, response.text
            return response.json()

        first = review()
        assert first["total_count"] == 14 and len(first["notes"]) == 12
        assert first["next_offset"] == 12
        second = review(offset=12)
        assert len(second["notes"]) == 2 and second["next_offset"] is None
        selected = first["notes"] + second["notes"]
        assert len({(row["project_id"], row["id"]) for row in selected}) == 14
        assert all(row["use_for_research"] for row in selected)
        assert independent["id"] in {row["id"] for row in selected}
        assert {row["id"] for row in first["goals"]} == {goal["id"] for goal in goals}
        unresolved = review(unknown=True)
        assert {row["id"] for row in unresolved["notes"]} == {revised["id"], independent["id"]}
        assert next(row for row in unresolved["notes"] if row["id"] == revised["id"])[
            "current_view"] == full
        scoped = review(goal_id=goals[0]["id"], state="all")
        assert scoped["total_count"] == 14
        assert all(row["project_id"] == goals[0]["id"] for row in scoped["notes"])
        shelved = review(state="parked")
        assert {row["id"] for row in shelved["notes"]} == {old["id"], parked["id"]}
        assert next(row for row in shelved["notes"] if row["id"] == old["id"])[
            "successor_ids"] == [revised["id"]]
        linked = review(q="合成父问题", state="all")
        assert {row["id"] for row in linked["notes"]} == {old["id"], revised["id"]}
        assert all(row["inquiry_links"][0]["question_id"] == question["id"]
                   for row in linked["notes"])
        assert not review(goal_id="f" * 32)["notes"]
        for params in [{"state": "invalid"}, {"offset": -1}, {"q": "字" * 201},
                       {"goal_id": "not-a-goal"}]:
            assert client.get("/api/career/review", params=params).status_code == 422
        for expected in before:
            after = client.get("/api/career/" + expected["id"]).json()
            assert after["insights"] == expected["insights"]
            assert after["questions"] == expected["questions"]
            assert after["results"] == expected["results"] == []
            assert after["usage"]["calls"] == expected["usage"]["calls"] == 0
