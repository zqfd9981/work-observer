"""Older relevant understanding can re-enter research without becoming new evidence."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.learning import recall_learning_notes
from work_observer.storage.database import upgrade


def test_old_related_understanding_is_recalled_and_the_sent_record_survives_edits(tmp_path):
    database = tmp_path / "recall.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = CareerModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成长期认识岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
            },
        ).json()["job_id"]
        identity = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成持续学习",
                "goal": "用原文理解工作",
                "background": "本地虚构练习。",
                "job_ids": [job],
            },
        ).json()["id"]
        base = f"/api/career/{identity}"
        old_data = {
            "previous_view": "重试次数多就能避免重复写入。",
            "observation": "合成观察：同一个幂等键在并发重复提交中仍出现两条记录。",
            "current_view": "幂等键与并发重复提交需要一起检查，局部记录尚不能证明生产有效。",
            "open_question": "并发重复提交时，幂等键是否被同一事务约束？",
        }
        response = client.post(base + "/insights", headers=auth, json=old_data)
        old_id = response.json()["insights"][0]["id"]
        for topic in ("版式配色", "校园课程", "文档目录", "城市交通"):
            assert (
                client.post(
                    base + "/insights",
                    headers=auth,
                    json={
                        "previous_view": topic + "的旧理解",
                        "observation": "合成观察：" + topic,
                        "current_view": topic + "的当前理解",
                        "open_question": "",
                    },
                ).status_code
                == 201
            )
        assert not model.contexts
        data = run_stage(client, identity, auth, "ask", question="幂等键能避免并发重复提交吗？")
        first = data["results"][0]
        personal = model.contexts[-1]["project_context"]["career_evidence"]
        assert personal["learning_notes"][0]["id"] == old_id
        assert len(personal["learning_notes"]) == 1
        assert personal["learning_recall"]["omitted_count"] == 4
        assert personal["learning_recall"]["selections"][0]["reason"] == "keyword"
        snapshot = first["result"]["career_learning_context"]
        assert snapshot["notes"] == personal["learning_notes"]
        assert snapshot["notes"][0]["current_user_view"] == old_data["current_view"]
        assert not any(row.get("id") == old_id for row in first["result"]["evidence"])

        calls = len(model.contexts)
        edited_data = {**old_data, "current_view": "编辑后：仍要核对事务边界，不泛化到生产。"}
        assert (
            client.patch(base + "/insights/" + old_id, headers=auth, json=edited_data).status_code
            == 200
        )
        assert (
            client.post(
                base + "/insights/" + old_id + "/use",
                headers=auth,
                json={"use_for_research": False},
            ).status_code
            == 200
        )
        assert len(model.contexts) == calls
        next_data = run_stage(
            client, identity, auth, "ask", question="幂等键能避免并发重复提交吗？"
        )
        next_context = model.contexts[-1]["project_context"]["career_evidence"]
        assert old_id not in {row["id"] for row in next_context["learning_notes"]}
        historical = next(row for row in next_data["results"] if row["step_id"] == first["step_id"])
        assert historical["result"]["career_learning_context"] == snapshot
        selected = run_stage(
            client, identity, auth, "ask", question="重查这条已搁置理解。", insight_id=old_id
        )
        explicit = selected["results"][0]["result"]["career_learning_context"]["selected_note"]
        assert explicit["current_user_view"] == edited_data["current_view"]
        assert explicit["use_for_research"] is False
        role = run_stage(client, identity, auth, "role")
        assert "learning_notes" not in model.contexts[-1]["project_context"]["career_evidence"]
        assert "career_learning_context" not in role["results"][0]["result"]

    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        historical = next(
            row for row in client.get(base).json()["results"] if row["step_id"] == first["step_id"]
        )
        assert historical["result"]["career_learning_context"] == snapshot


def test_recall_prefers_explicit_problem_links_and_never_restores_shelved_notes():
    def note(identity, **extra):
        return {
            "id": identity,
            "created_at": identity,
            "current_view": "不同主题",
            "previous_view": "",
            "observation": "",
            "open_question": "",
            **extra,
        }

    career = {
        "questions": [{"id": "q", "question": "核对迁移条件"}],
        "tasks": [{"id": "task", "question_id": "q", "title": "局部对照"}],
        "runs": [
            {"step_id": "source", "question_id": "q"},
            {"step_id": "now", "user_question": "词面与原笔记不同"},
        ],
        "insights": [
            note("a", source_step_id="source"),
            note("b", task_id="task"),
            *[note(str(i), current_view="词面与原笔记不同") for i in range(4, 9)],
            note("z", task_id="task", use_for_research=False),
        ],
    }
    chosen, recall = recall_learning_notes(career, {"id": "now", "career_question_id": "q"}, "")
    assert {row["id"] for row in chosen[:2]} == {"a", "b"}
    assert all(row["reason"] == "same_inquiry_or_experiment" for row in recall["selections"][:2])
    assert "z" not in {row["id"] for row in chosen}
    assert career["insights"][-1]["use_for_research"] is False


def test_recheck_recalls_a_successor_and_specific_questions_do_not_fill_unrelated_notes():
    notes = [
        {
            "id": key,
            "created_at": key,
            "current_view": text,
            "previous_view": "",
            "observation": "",
            "open_question": "",
        }
        for key, text in (("a", "alpha"), ("b", "beta"), ("c", "gamma"), ("d", "delta"))
    ]
    notes[0]["use_for_research"] = False
    notes[1]["replaces_insight_id"] = "a"
    career = {"insights": notes, "runs": [{"step_id": "now", "user_question": "复核旧理解"}]}
    step = {"id": "now", "career_insight_id": "a"}
    chosen, recalled = recall_learning_notes(career, step, "")
    assert [row["id"] for row in chosen] == ["b"]
    assert recalled["selections"][0]["reason"] == "belief_revision"
    assert recalled["eligible_count"] == 3 and recalled["omitted_count"] == 2
    unrelated, _ = recall_learning_notes(career, {"id": "now"}, "")
    assert unrelated == []
    recent, _ = recall_learning_notes(career, {"id": "general"}, "")
    assert [row["id"] for row in recent] == ["d", "c", "b"]
    career["runs"].extend(
        [
            {"step_id": "origin", "user_question": "beta"},
            {"step_id": "reply", "user_question": "请再说明", "source_step_id": "origin"},
        ]
    )
    continued, _ = recall_learning_notes(career, {"id": "reply"}, "")
    assert [row["id"] for row in continued] == ["b"]
