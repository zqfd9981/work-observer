"""A rephrased inquiry keeps its original unknown and explicit user conclusion across sessions."""

import re

from starlette.testclient import TestClient
from test_career_question_materials import QuestionMaterialModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_gap_inquiry_rephrasing_and_user_explanation_survive_reopening(tmp_path):
    database = tmp_path / "gap-followup.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = QuestionMaterialModel()

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, payload):
            response = client.post(path, headers=auth, json=payload)
            assert response.status_code == 201, response.text
            return response.json()

        goal = post("/api/career", {"title": "合成：未知逐步形成解释", "goal": "核对记录及其条件"})
        identity = goal["id"]
        base = "/api/career/" + identity
        materials = post(base + "/materials", {"title": "合成局部记录",
                         "text": "只记录一个条件下的输出。"})
        document = materials["added_material_id"]
        parent = post(base + "/questions", {"question": "合成：这项工作交付什么？",
                      "state": "open", "material_ids": [document]})["questions"][0]
        source = run_stage(client, identity, auth, "ask", question_id=parent["id"],
                           question=parent["question"])["results"][0]
        original_gap = source["result"]["review"]["next_questions"][0]
        gap_index = source["result"]["gaps"].index(original_gap)
        child_data = {"question": "合成：改写后的具体调查问题？", "state": "open",
                      "source_step_id": source["step_id"], "source_gap_index": gap_index,
                      "parent_question_id": parent["id"], "material_ids": [document]}
        child = post(base + "/questions", child_data)["questions"][-1]
        assert child["source_gap_index"] == gap_index
        assert child["question"] != original_gap and not child["conclusion"]
        assert len(model.contexts) == 2
        unchanged = client.get(base).json()
        for bad in (len(source["result"]["gaps"]), -1, 0.5, True):
            response = client.post(base + "/questions", headers=auth, json={
                **child_data, "source_gap_index": bad,
            })
            assert response.status_code == 422, response.text
            assert client.get(base).json() == unchanged

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        reread = run_stage(client, identity, auth, "ask", question_id=child["id"],
                           question="合成：核对这个未知涉及的条件。")["results"][0]
        inquiry = model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"]
        assert inquiry["origin_unknown"]["text"] == original_gap
        assert inquiry["origin_unknown"]["step_id"] == source["step_id"]
        assert inquiry["question"] == child_data["question"]
        assert reread["result"]["status"] == "completed"
        data = {**child_data, "question": "合成：再次修改调查标题？", "state": "answered",
                "conclusion": "用户解释：只在已记录的条件下观察到输出，其他条件仍未知。",
                "conclusion_step_id": reread["step_id"], "next_evidence": "还需改变条件的观察。"}
        # Omitting the origin index from an ordinary edit preserves its exact association.
        data.pop("source_gap_index")
        response = client.patch(base + "/questions/" + child["id"], headers=auth, json=data)
        assert response.status_code == 200, response.text
        saved = response.json()["questions"][-1]
        assert saved["source_gap_index"] == gap_index and saved["conclusion"] == data["conclusion"]
        assert response.json()["results"][-1] == source
        assert response.json()["questions"][0] == parent

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        saved = client.get(base).json()["questions"][-1]
        assert saved["source_gap_index"] == gap_index
        assert saved["state"] == "answered" and saved["conclusion_step_id"] == reread["step_id"]
        assert saved["next_evidence"] == data["next_evidence"]
        assert len(model.contexts) == 4
