"""Correct a work note and revisit the old reasoning without losing inquiry defaults."""

import re

from starlette.testclient import TestClient
from test_career_question_materials import QuestionMaterialModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_corrected_original_updates_future_inquiry_focus_but_keeps_old_reasoning(tmp_path):
    database = tmp_path / "corrected-inquiry.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = QuestionMaterialModel()
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        original = "合成工作说明：构造失败请求并交付记录；后续责任未知。"
        goal = post("/api/career", {"title": "合成：更正资料后继续原调查", "goal": "核对原判断",
                    "material_title": "合成原说明", "material_text": original})
        identity, old = goal["id"], goal["materials"][0]["id"]
        base = "/api/career/" + identity
        reference = post(base + "/materials", {"title": "合成配套条件", "text":
                         "合成配套说明：局部观察不代表生产验收，具体权限仍需核实。"})[
                             "materials"][-1]["id"]
        conclusion = "只记录过局部交付，实际复核责任仍未知。"
        question = post(base + "/questions", {
            "question": "交付之后谁复核，原先的判断是否需要缩窄？", "state": "answered",
            "conclusion": conclusion, "material_ids": [old, reference],
            "source_passage": {"public_document_id": old, "start": 0, "end": len(original)},
        })["questions"][0]
        other = post("/api/career", {"title": "合成另一目标", "goal": "保留独立的选择"})
        other_base = "/api/career/" + other["id"]
        post(other_base + "/materials/attach", {"document_id": old})
        other_question = post(other_base + "/questions", {
            "question": "另一目标仍从原来的记录出发。", "material_ids": [old],
        })["questions"][0]
        first = run_stage(client, identity, auth, "ask", question_id=question["id"],
                          material_id=old, question="先核对这份原说明。")["results"][0]
        assert first["result"]["status"] == "completed", first["result"].get("stop_reason")
        before = client.get("/api/public-documents/" + old).json()
        corrected = "合成工作说明：构造失败请求，交付记录后由负责人复核；生产权限未知。"
        updated = post(base + "/materials/" + old + "/revisions", {
            "title": "合成更正后的说明", "text": corrected, "source_name": "虚构记录，待核实",
        })
        new = updated["updated_material_id"]
        saved = updated["questions"][0]
        historical_source = next(row for row in updated["results"]
                                 if row["step_id"] == first["step_id"])
        assert not historical_source["current"]
        assert saved["material_ids"] == [new, reference]
        assert saved["conclusion"] == conclusion and saved["state"] == "answered"
        assert saved["source_passage"] == question["source_passage"]
        assert client.get(other_base).json()["questions"][0] == other_question
        assert client.get(other_base).json()["document_ids"] == [old]
        rechecked = run_stage(client, identity, auth, "ask", source_step_id=first["step_id"],
                              question_id=question["id"], question="对照旧解释，补充后怎样理解？")[
                                  "results"][0]
        assert rechecked["result"]["status"] == "completed", rechecked["result"].get("stop_reason")
        assert rechecked["material_ids"] == [new, reference]
        assert {row["public_document_id"] for row in rechecked["result"]["evidence"]} == {
            new, reference,
        }
        assert old not in rechecked["document_ids"]
        context = model.contexts[-1]["project_context"]["career_evidence"]
        continued = context["continued_discussion"]
        assert continued["step_id"] == first["step_id"]
        assert continued["claim_details_to_recheck"][0]["text"] == first["result"]["claims"][0][
            "text"]
        assert all("evidence_ids" not in row for row in continued["claim_details_to_recheck"])
        assert continued["source_references_to_reread"][0]["public_document_id"] == old
        assert "不是新证据" in continued["notice"]
        retained = client.get("/api/public-documents/" + old).json()
        assert retained["text"] == original and retained["sha256"] == before["sha256"]
        assert retained["evidence"] == before["evidence"]
        final = client.get(base).json()
        historical = next(row for row in final["results"] if row["step_id"] == first["step_id"])
        assert historical["material_id"] == old
        assert historical["result"]["claims"] == first["result"]["claims"]
        assert historical["result"]["evidence"] == first["result"]["evidence"]
        assert final["questions"][0]["conclusion"] == conclusion
