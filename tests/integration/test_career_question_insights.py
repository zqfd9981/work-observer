"""A reviewed inquiry conclusion becomes an editable, retrievable personal understanding."""

import re

from starlette.testclient import TestClient
from test_career_material_start import MaterialWorkspaceModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.learning import LearningNotebook
from work_observer.research.projects import ProjectService
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


def test_question_link_recalls_personal_understanding_and_preserves_revisions(tmp_path):
    database = tmp_path / "question-insights.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MaterialWorkspaceModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = post("/api/career", {
            "title": "合成：把调查结论留给后续学习", "goal": "持续核对自己的理解",
            "material_title": "合成工作说明", "material_text": "合成说明：构造失败请求，交付日志。",
        })
        identity, base = goal["id"], f"/api/career/{goal['id']}"
        question = post(base + "/questions", {"question": "如何说明响应行为？"})["questions"][0]
        result = run_stage(client, identity, auth, "ask", question=question["question"],
                           question_id=question["id"])["results"][0]
        personal = "这批资料只涉及局部样例，尚不代表已完成业务实践。"
        noted = client.patch(base + "/questions/" + question["id"], headers=auth, json={
            "question": question["question"], "state": "answered", "conclusion": personal,
            "conclusion_step_id": result["step_id"],
        })
        assert noted.status_code == 200, noted.text
        calls = len(model.contexts)
        note_data = {"question_id": question["id"], "source_step_id": result["step_id"],
                     "previous_view": question["question"],
                     "observation": "仅核对了用户提供的说明。",
                     "current_view": personal, "open_question": "还需要实际对照记录。"}
        invalid = client.post(base + "/insights", headers=auth,
                              json={**note_data, "question_id": "f" * 32})
        assert invalid.status_code == 422
        note = post(base + "/insights", note_data)["insights"][0]
        assert note["question_id"] == question["id"] and len(model.contexts) == calls
        assert note.get("source_claim_index") is None
        run_stage(client, identity, auth, "ask", question="换一个角度继续核实。",
                  question_id=question["id"])
        recall = model.contexts[-1]["project_context"]["career_evidence"]
        assert recall["learning_recall"]["selections"][0]["reason"] == "same_inquiry_or_experiment"
        recalled = recall["learning_notes"][0]
        assert recalled["current_user_view"] == personal
        assert recalled["question_id"] == question["id"]
        assert recalled["inquiry_question"] == question["question"]
        assert recalled["source_discussion"]["claims_to_recheck"]
        assert recalled["source_locators"][0]["public_document_id"] == goal["materials"][0]["id"]
        snapshot = client.get(base).json()["results"][0]["result"]["career_learning_context"]
        calls = len(model.contexts)
        replacement = post(base + "/insights", {
            **note_data, "replaces_insight_id": note["id"],
            "current_view": "需要分别检查正常与失败输入；生产条件仍未知。",
        })["insights"][-1]
        notes = client.get(base).json()["insights"]
        assert not notes[0]["use_for_research"] and notes[0]["current_view"] == personal
        assert replacement["question_id"] == question["id"] and len(model.contexts) == calls
        run_stage(client, identity, auth, "ask", question="继续看这条调查。",
                  question_id=question["id"])
        recall = model.contexts[-1]["project_context"]["career_evidence"]
        assert [row["id"] for row in recall["learning_notes"]] == [replacement["id"]]
        rechecked = run_stage(client, identity, auth, "ask", question="回查所选认识的边界。",
                              insight_id=note["id"])
        assert rechecked["results"][0]["question_id"] == question["id"]
        assert not rechecked["insights"][0]["use_for_research"]

        historical = next(row for row in client.get(base).json()["results"]
                          if row["result"].get("career_learning_context") == snapshot)
        assert historical["result"]["career_learning_context"]["notes"][0][
            "current_user_view"
        ] == personal
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()
        assert reopened["insights"] == notes
        assert reopened["questions"][0]["conclusion"] == personal
    # The same notebook tools can read the explicitly chosen old family after reopening.
    store = ResearchStore(tmp_path / "checkpoints.db", str(database.resolve()))
    projects = ProjectService(store)
    notebook = LearningNotebook(lambda: projects.get(identity), store, note["id"])
    assert notebook.read(note["id"])["note"]["current_user_view"] == personal
    store.close()
