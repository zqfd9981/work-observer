"""Explicit excerpt comparisons keep the chosen annotations and reread their originals."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

TEXTS = ["合成配置说明🤔\r\n已有能力只需配置并核对参数；本场景不涉及接口集成。",
         "合成集成说明🤔\r\n复杂集成需要开发适配接口与测试；验收权限仍未知。"]
TARGET = "已有能力配置可能无需开发接口。" + "只限既有能力场景，复杂集成尚未知；" * 25
NOTE = "先核对各自业务对象和适用条件🤔。" * 28 + "末尾：同一归档的摘录不能当作独立来源。"


class PassageComparisonModel(ModelClient):
    def __init__(self):
        self.last_usage, self.inputs = {}, []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        inquiry = context["project_context"]["career_evidence"]["selected_inquiry"]
        selected = inquiry["selected_passages"]
        assert len(selected) == 2 and not inquiry["missing_selected_passage_ids"]
        assert inquiry["evidence_passages"] == selected
        assert inquiry["other_evidence_passage_count"] == 1
        assert selected[0]["target_view"] == TARGET and selected[0]["user_note"] == NOTE
        assert selected[0]["start"] == 0 and selected[0]["quote"] == TEXTS[0]
        assert selected[1]["quote"] == TEXTS[1]
        self.inputs.append(inquiry)
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_archived_documents", {"reads": [
                {"document_id": row["public_document_id"], "start": row["start"]}
                for row in selected
            ]}
        else:
            assert {row["quote"] for row in outputs[0]["evidence"]} == set(TEXTS)
            name, args = "finish_research", {"claims": [{
                "category": "task", "basis": "inference", "requirement": "unspecified",
                "text": "两份合成说明的工作场景不同；是否冲突须先核对条件，不能按标注条数决定。",
                "evidence_ids": [row["id"] for row in outputs[0]["evidence"]],
            }], "gaps": ["实际业务对象、分工与验收仍需核实。"]}
            if (context["project_context"].get("previous_findings")
                    or context["project_context"].get("historical_reply")):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_selected_passages_are_scoped_snapshotted_and_reread_without_annotation_changes(tmp_path):
    database = tmp_path / "passage-comparison.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = PassageComparisonModel()
    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]}
        def save(path, payload, method="post"):
            response = getattr(client, method)(path, headers=auth, json=payload)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成摘录并排核对", "goal": "核对解释所据的条件",
                    "material_title": "合成摘录对照配置", "material_text": TEXTS[0]})
        identity, base = goal["id"], "/api/career/" + goal["id"]
        documents = [goal["materials"][0]["id"]]
        data = save(base + "/materials", {"title": "合成摘录对照集成", "text": TEXTS[1]})
        documents.append(next(row["id"] for row in data["materials"]
                              if row["id"] not in documents))
        question = save(base + "/questions", {"question": "配置与开发的两段说法是否冲突？",
                        "hypothesis_a": TARGET, "hypothesis_b": "可能是不同场景下的不同工作。",
                        "state": "answered", "conclusion": "先保留条件差异，尚未证明实际分工。"}
                        )["questions"][-1]
        qpath = base + "/questions/" + question["id"]
        selected = []
        for index in range(3):
            source = index % 2
            data = save(qpath + "/passages", {
                "passage": {"public_document_id": documents[source], "start": 0,
                            "end": len(TEXTS[source])},
                "relation": "supports" if index == 0 else "conditions",
                "target_view": TARGET if index == 0 else "可能是不同场景下的不同工作。",
                "user_note": NOTE if index == 0 else "保留原文中的场景差别。",
            })
            if index < 2:
                selected.append(data["questions"][0]["evidence_passages"][-1])
        foreign = save(base + "/questions", {"question": "同一目标的另一个问题"}
                       )["questions"][-1]
        foreign_path = base + "/questions/" + foreign["id"]
        data = save(foreign_path + "/passages", {
            "passage": {"public_document_id": documents[0], "start": 0,
                        "end": len(TEXTS[0])}, "relation": "unclassified",
        })
        foreign_id = data["questions"][-1]["evidence_passages"][-1]["id"]
        ids = [row["id"] for row in selected]
        before = client.get(base).json()
        for invalid in [[ids[0]], [ids[0], ids[0]], [ids[0], foreign_id]]:
            response = client.post(base + "/prepare", headers=auth, json={
                "kind": "ask", "question": "只核对本次选择", "question_id": question["id"],
                "passage_ids": invalid,
            })
            assert response.status_code == 422, response.text
        assert client.get(base).json() == before and not model.inputs
        studied = run_stage(client, identity, auth, "ask", question_id=question["id"],
                            passage_ids=ids, material_ids=documents,
                            question="合成摘录对照：核对所选两段，不预设冲突。")
        row = studied["results"][0]
        assert row["result"]["status"] == "completed", row["result"]["stop_reason"]
        assert row["passage_ids"] == ids and row["result"]["model_calls"] == 2
        snapshot = row["result"]["career_learning_context"]["passage_comparison"]
        assert snapshot == {"question_id": question["id"], "passage_ids": ids,
                            "passages": selected, "missing_ids": []}
        assert studied["questions"] == before["questions"]
        assert {ev["public_document_id"] for ev in row["result"]["evidence"]} == set(documents)
        calls = len(model.inputs)
        save(qpath + "/passages/" + ids[0], {
            "relation": "challenges", "target_view": "后来改写的解释",
             "user_note": "这是后来的标注，不改写旧研究输入。"}, "patch")
        removed = client.delete(qpath + "/passages/" + ids[1], headers=auth)
        assert removed.status_code == 200, removed.text
        retained = next(item for item in client.get(base).json()["results"]
                        if item["step_id"] == row["step_id"])
        assert retained["result"]["career_learning_context"]["passage_comparison"] == snapshot
        assert len(model.inputs) == calls
        invalid = client.post(base + "/prepare", headers=auth, json={
            "kind": "ask", "question_id": question["id"], "passage_ids": ids,
            "question": "不恢复已经移除的摘录。",
        })
        assert invalid.status_code == 422
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        reopened = next(item for item in client.get(base).json()["results"]
                        if item["step_id"] == row["step_id"])
        assert reopened["result"]["career_learning_context"]["passage_comparison"] == snapshot
