"""A parent inquiry discovers rephrased child notes by their relationship, then rereads sources."""

import json
import re

from starlette.testclient import TestClient
from test_career_question_materials import QuestionMaterialModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class ChildRecallModel(QuestionMaterialModel):
    def __init__(self):
        super().__init__()
        self.recall = False
        self.calls = []

    async def turn(self, history):
        if not self.recall:
            return await super().turn(history)
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        parent = context["project_context"]["career_evidence"]["selected_inquiry"]
        assert {row["id"] for row in parent["child_inquiries"]} == self.direct_ids
        child = next(row for row in parent["child_inquiries"] if row["id"] == self.child_id)
        assert child["has_user_conclusion"] and "conclusion" not in child
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_inquiry", {"question_id": child["id"]}
        elif len(outputs) == 1:
            note = outputs[0]["inquiry"]
            assert note["conclusion"] == self.full_conclusion
            assert note["origin_unknown"]["text"] == self.original_gap
            assert note["parent_question_id"] == parent["id"]
            assert [row["id"] for row in note["child_inquiries"]] == [self.grandchild_id]
            assert note["conclusion_step_id"] == self.child_study_id
            assert "evidence" not in outputs[0]
            name, args = "read_archived_document", {"document_id": note["material_ids"][0],
                                                     "start": 0}
        else:
            evidence = outputs[-1]["evidence"]
            assert all(row["public_document_id"] == self.document_id for row in evidence)
            name, args = "finish_research", {
                "claims": [{"text": "原记录只支持局部样例交付，其他条件尚不能判断。",
                            "category": "deliverable", "basis": "synthesis",
                            "requirement": "unspecified",
                            "evidence_ids": [row["id"] for row in evidence]}],
                "gaps": ["子调查的用户解释仍有条件限制，不证明生产环境成立。"],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        self.calls.append(name)
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_parent_research_recalls_complete_child_understanding_after_reopening(tmp_path):
    database = tmp_path / "child-recall.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = ChildRecallModel()

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成：子调查回到原问题",
                    "goal": "理解工作交付的条件"})
        identity = goal["id"]
        base = "/api/career/" + identity
        document = save(base + "/materials", {"title": "合成样例交付记录",
                        "text": "交付一个局部验证样例，只在记录的输入条件下观察到输出。"})
        model.document_id = document["added_material_id"]
        parent = save(base + "/questions", {"question": "合成：这类工作怎样产生交付？",
                      "state": "open", "material_ids": [model.document_id]})["questions"][0]
        original = run_stage(client, identity, auth, "ask", question_id=parent["id"],
                             question=parent["question"])["results"][0]
        model.original_gap = original["result"]["review"]["next_questions"][0]
        gap_index = original["result"]["gaps"].index(model.original_gap)
        child_data = {"question": "合成：改写为仅讨论一个输入条件？", "state": "open",
                      "parent_question_id": parent["id"], "source_step_id": original["step_id"],
                      "source_gap_index": gap_index, "material_ids": [model.document_id]}
        child = save(base + "/questions", child_data)["questions"][-1]
        model.child_id = child["id"]
        child_study = run_stage(client, identity, auth, "ask", question_id=child["id"],
                                question=child["question"])["results"][0]
        model.child_study_id = child_study["step_id"]
        model.full_conclusion = "仅保留局部观察及其条件。" * 110 + "末尾限定：生产环境仍未知。"
        save(base + "/questions/" + child["id"], {
            **child_data, "state": "answered", "conclusion": model.full_conclusion,
            "next_evidence": "补其他条件下的实际观察。",
            "conclusion_step_id": child_study["step_id"],
        }, "patch")
        other_children = [save(base + "/questions", {
            "question": "合成：另一个明确关联的" + state + "问题？", "state": state,
            "parent_question_id": parent["id"],
        })["questions"][-1] for state in ("open", "parked")]
        grandchild = save(base + "/questions", {"question": "合成：更深一层的问题？",
                          "state": "open", "parent_question_id": child["id"]})["questions"][-1]
        model.grandchild_id = grandchild["id"]
        save(base + "/questions", {"question": parent["question"], "state": "open"})
        model.direct_ids = {child["id"], *(row["id"] for row in other_children)}
        before = client.get(base).json()

    model.recall = True
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        data = run_stage(client, identity, auth, "ask", question_id=parent["id"],
                         question="合成：重新研究原问题，已有调查提供了什么、还缺什么？")
        current = data["results"][0]
        assert current["result"]["status"] == "completed", (current["result"], model.calls)
        assert model.calls == ["read_inquiry", "read_archived_document", "finish_research"]
        recalled = current["result"]["career_learning_context"]["read_inquiries"][0]
        assert recalled["id"] == child["id"] and recalled["conclusion"] == model.full_conclusion
        assert recalled["origin_unknown"]["text"] == model.original_gap
        assert current["result"]["evidence"][0]["public_document_id"] == model.document_id
        assert data["questions"] == before["questions"]
        assert data["results"][1:] == before["results"]
