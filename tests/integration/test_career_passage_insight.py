"""Read a source and save personal understanding without a model-generated discussion."""

import re

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.storage.database import upgrade

TEXT = "合成工作材料🤔\r\n" + "同一工具用于记录与核对，交付对象和验收条件仍需分别说明。" * 38 + (
    "\r\n末尾限定：未说明个人权限，不能从工具名称推断职责相同。"
)


class NoCalls(ModelClient):
    def __init__(self):
        self.last_usage = {}

    async def turn(self, history):
        raise AssertionError("This reading-to-understanding path must not call a model.")


def test_passage_insight_keeps_exact_origin_after_annotation_removal_and_note_edit(tmp_path):
    database = tmp_path / "passage-insight.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")

    def app():
        return create_app(settings, model=NoCalls(), reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]}

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成原文到理解", "goal": "独立阅读并保留出处",
                    "material_title": "合成权限归属原文", "material_text": TEXT})
        base = "/api/career/" + goal["id"]
        question = save(base + "/questions", {"question": "工具相同是否意味着责任相同？",
                        "state": "parked", "conclusion": "暂时保留未知。"})["questions"][0]
        reference = {"public_document_id": goal["materials"][0]["id"],
                     "start": 0, "end": len(TEXT)}
        annotated = save(base + "/questions/" + question["id"] + "/passages", {
            "passage": reference, "relation": "conditions", "user_note": "先核对验收对象。",
        })["questions"][0]["evidence_passages"][0]
        before = client.get(base).json()
        values = {"question_id": question["id"], "previous_view": question["question"],
                  "observation": "从工具名不足以确定责任。", "current_view": "需要核对对象和权限。",
                  "open_question": "真实验收权限仍未知。", "source_passage": reference}
        invalid = client.post(base + "/insights", headers=auth,
                              json={**values, "source_passage": {**reference, "end": len(TEXT)+1}})
        assert invalid.status_code == 422
        assert client.get(base).json() == before
        saved = save(base + "/insights", values)
        note = saved["insights"][-1]
        original = note["source_passage"]
        assert original["quote"] == TEXT and original["start"] == 0
        assert original["title"] == "合成权限归属原文" and not note["source_step_id"]
        assert saved["questions"] == before["questions"] and not saved["results"]
        assert saved["usage"] == before["usage"]
        removed = client.delete(base + "/questions/" + question["id"] + "/passages/"
                                + annotated["id"], headers=auth)
        assert removed.status_code == 200, removed.text
        edited = save(base + "/insights/" + note["id"], {
            **values, "current_view": "工具和职责之间还需说明条件，仍未核实个人权限。",
        }, "patch")["insights"][-1]
        assert edited["source_passage"] == original
        notebook = LearningNotebook(lambda: {"career": {"insights": [edited], "runs": [],
                                    "questions": [question]}, "steps": []}, None)
        assert notebook.search(["权限归属原文"])["matching_count"] == 1
        recalled = notebook.read(note["id"])["note"]
        assert recalled["source_passage"] == original
        assert recalled["source_locators"] == [original]
        assert "evidence_ids" not in recalled["source_passage"]
        hits = client.get(base + "/search", params={"q": "权限归属原文"}).json()
        assert any(row["id"] == note["id"] for row in hits["records"])
        final = client.get(base).json()
        assert final["questions"][0]["state"] == "parked"
        assert final["questions"][0]["conclusion"] == question["conclusion"]
        assert not final["results"] and final["usage"] == before["usage"]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        assert client.get(base).json()["insights"][-1]["source_passage"] == original
