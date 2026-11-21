"""The agent can investigate personal understanding beyond its initial recalled notes."""

import json
import re

import pytest
from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.storage.database import upgrade


class NotebookModel(ModelClient):
    """No provider requests: follow local tool results, including the second search page."""

    def __init__(self):
        self.tools, self.contexts, self.toolsets = [], [], []
        self.last_usage = {}
        self.cite_note = False
        self.skip_query = False

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.toolsets.append({row["name"] for row in self.tools})
        if context["project_context"]["career_action"] != "ask":
            return await CareerModel.turn(self, history)
        self.contexts.append(context)
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        stage = len(outputs) + int(self.skip_query)
        if stage == 0:
            name, arguments = "query_jobs", {}
        elif stage == 1:
            name, arguments = "search_learning_notes", {"terms": ["并发"], "offset": 0}
        elif stage == 2:
            assert outputs[-1]["next_offset"] == 6
            name, arguments = "search_learning_notes", {"terms": ["并发"], "offset": 6}
        elif stage == 3:
            old = next(row for row in outputs[-1]["notes"] if not row["use_for_research"])
            assert old["preview_is_partial"]
            self.read_id = old["id"]
            name, arguments = "read_learning_note", {"note_id": old["id"]}
        elif stage == 4:
            self.read_note = outputs[-1]["note"]
            assert self.read_note["current_user_view"].endswith("末尾限定：并发仍未控制。")
            assert self.read_note["open_question"] == "不能把局部观察外推到生产。"
            assert "evidence" not in outputs[-1]
            name, arguments = (
                "read_job",
                {"job_id": context["fixed_scope"]["jobs"][0]["id"], "start": None},
            )
        else:
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "原文说明负责失败样例验证。",
                            "evidence_ids": [
                                self.read_id
                                if self.cite_note
                                else outputs[-1]["evidence"][0]["citation_key"]
                            ],
                        }
                    ],
                    "gaps": ["用户旧认识仍是个人理解，局部观察尚不能证明生产有效。"],
                    "application_plan": None,
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": str(len(history)),
        }
        return [call], call


def test_agent_pages_and_reads_old_understanding_then_returns_to_original_sources(tmp_path):
    database = tmp_path / "notebook.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = NotebookModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成认识查阅岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
            },
        ).json()["job_id"]
        identity = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成自主查阅",
                "goal": "核对认识变化的依据",
                "background": "本地虚构练习。",
                "job_ids": [job],
            },
        ).json()["id"]
        base = f"/api/career/{identity}"

        def save(current, parent=None, unknown=""):
            response = client.post(
                base + "/insights",
                headers=auth,
                json={
                    "previous_view": "合成旧看法。",
                    "observation": "本地虚构观察。",
                    "current_view": current,
                    "open_question": unknown,
                    "replaces_insight_id": parent,
                },
            )
            assert response.status_code == 201, response.text
            return response.json()["insights"][-1]

        first = save("只看运行日志就能判断原因。")
        middle = save(
            "合成边界说明。" * 120 + "末尾限定：并发仍未控制。",
            first["id"],
            "不能把局部观察外推到生产。",
        )
        current = save("并发与请求标识都需要对照检查，原因仍未知。", middle["id"])
        for index in range(7):
            save(f"并发相关的另一条合成认识{index}，不是同一认识的修正。")
        notes_before = client.get(base).json()["insights"]
        result = run_stage(
            client, identity, auth, "ask", question="重新检验这条旧认识。", insight_id=first["id"]
        )["results"][0]
        answer = result["result"]
        assert answer["status"] == "completed", answer.get("stop_reason")
        assert answer["model_calls"] == 6
        saved = answer["career_learning_context"]
        assert middle["id"] not in {row["id"] for row in saved["notes"]}
        assert current["id"] in {row["id"] for row in saved["notes"]}
        assert saved["selected_note"]["id"] == first["id"]
        assert [row["offset"] for row in saved["searches"]] == [0, 6]
        assert saved["read_notes"][0]["id"] == middle["id"]
        assert saved["read_notes"][0] == model.read_note
        assert not saved["read_notes"][0]["use_for_research"]
        assert all(row.get("job_id") == job for row in answer["evidence"])
        assert model.read_id not in answer["claims"][0]["evidence_ids"]
        assert {"search_learning_notes", "read_learning_note"} <= model.toolsets[-1]
        assert client.get(base).json()["insights"] == notes_before
        run_stage(client, identity, auth, "role")
        assert not {"search_learning_notes", "read_learning_note"} & model.toolsets[-1]
        assert "learning_notes" not in model.contexts[-1]["project_context"]["career_evidence"]
        model.skip_query = True
        direct = run_stage(
            client, identity, auth, "ask", question="再查旧理解的依据。", insight_id=first["id"]
        )["results"][0]["result"]
        assert direct["status"] == "completed" and direct["model_calls"] == 5
        assert direct["trace"][0]["tool"] == "search_learning_notes"
        model.skip_query = False
        model.cite_note = True
        rejected = run_stage(
            client, identity, auth, "ask", question="重查旧认识的依据。", insight_id=first["id"]
        )["results"][0]["result"]
        assert rejected["status"] != "completed"
        assert not rejected["claims"]
        assert all(row.get("job_id") == job for row in rejected["evidence"])
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        old = next(
            row for row in client.get(base).json()["results"] if row["step_id"] == result["step_id"]
        )
        assert old["result"]["career_learning_context"]["read_notes"][0] == model.read_note


def test_notebook_only_opens_selected_history_and_current_goal_records():
    def note(identity, active, parent=None):
        return {
            "id": identity,
            "current_view": "完整理解及限定。",
            "created_at": identity,
            "previous_view": "原先理解。",
            "observation": "自述观察。",
            "open_question": "仍未知。",
            "use_for_research": active,
            "replaces_insight_id": parent,
        }

    notes = [note("old", False), note("current", True, "old"), note("shelved", False)]
    project = {"career": {"insights": notes}, "steps": []}
    ordinary = LearningNotebook(lambda: project, None)
    assert [row["id"] for row in ordinary.search([])["notes"]] == ["current"]
    for identity in ("old", "shelved", "another-goal-id"):
        with pytest.raises(ProbeError, match="LEARNING_NOTE_NOT_AVAILABLE"):
            ordinary.read(identity)
    focused = LearningNotebook(lambda: project, None, "current")
    assert {row["id"] for row in focused.search([])["notes"]} == {"current", "old"}
    assert focused.read("old")["note"]["open_question"] == "仍未知。"
    assert notes[0]["use_for_research"] is False
