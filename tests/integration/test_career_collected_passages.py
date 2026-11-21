"""Bring a counterexample back to an existing inquiry without treating its label as truth."""

import json
import re

from starlette.testclient import TestClient
from test_career_source_passage import PassageModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class CollectedPassageModel(PassageModel):
    """The local substitute re-reads both actual synthetic archives before comparing them."""

    async def turn(self, history):
        outputs, call = await super().turn(history)
        if call["name"] != "finish_research":
            return outputs, call
        context = json.loads(history[1]["content"])
        inquiry = context["project_context"]["career_evidence"].get("selected_inquiry") or {}
        evidence = [
            item
            for row in history
            if row.get("type") == "function_call_output"
            for item in json.loads(row["output"]).get("evidence", [])
        ]
        allowed = {row["id"] for row in context["fixed_scope"]["public_document_titles"]}
        for passage in inquiry.get("evidence_passages", []):
            document = passage.get("public_document_id")
            if document in allowed and not any(
                item.get("public_document_id") == document for item in evidence
            ):
                call = {
                    "type": "function_call",
                    "name": "read_archived_document",
                    "arguments": json.dumps({"document_id": document, "start": 0}),
                    "call_id": str(len(history)),
                }
                return [call], call
        args = json.loads(call["arguments"])
        args["claims"] = [
            {
                "category": "task",
                "basis": "synthesis",
                "requirement": "unspecified",
                "text": "合成资料需要区分配置和开发条件；用户的挑战标注尚不能直接证明矛盾。",
                "evidence_ids": list(dict.fromkeys(item["id"] for item in evidence)),
            }
        ]
        args["gaps"] = ["还需要核实实际交付条件与验收责任，现有资料不能证明个人胜任。"]
        call["arguments"] = json.dumps(args)
        return [call], call


def test_collected_counterexample_can_be_rechecked_relabelled_and_removed_without_rewriting_history(
    tmp_path,
):
    database = tmp_path / "collected-passages.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = CollectedPassageModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def request(path, data, method="post"):
            response = getattr(client, method)(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        first_text = "合成工作说明：配置现有流程不要求编写代码，但复杂集成责任尚未说明。"
        goal = request(
            "/api/career",
            {
                "title": "合成：带回反例核实条件",
                "goal": "理解配置与开发的工作边界",
                "material_title": "合成工作说明配置",
                "material_text": first_text,
            },
        )
        base = "/api/career/" + goal["id"]
        origin = goal["materials"][0]["id"]
        qdata = {
            "question": "配置和集成开发是否有不同交付条件？",
            "conclusion": "配置可能只涉及已有能力，复杂场景仍未知。",
            "state": "answered",
        }
        question = request(
            base + "/questions",
            {
                **qdata,
                "source_passage": {
                    "public_document_id": origin,
                    "start": 0,
                    "end": len(first_text),
                },
            },
        )["questions"][0]
        qid = question["id"]
        before = run_stage(
            client, goal["id"], auth, "ask", question_id=qid, question="先核实配置说明中的边界。"
        )
        old = before["results"][0]
        second_text = "合成接口说明：复杂集成需要实现适配接口和测试；不能泛化为所有配置工作。"
        document = request(base + "/materials", {"title": "合成集成说明", "text": second_text})[
            "materials"
        ][-1]["id"]
        calls = len(model.contexts)
        note = "可能挑战原解释；" * 65 + "末尾限定：先核对是否来自不同工作条件。"
        saved = request(
            base + "/questions/" + qid + "/passages",
            {
                "passage": {"public_document_id": document, "start": 0, "end": len(second_text)},
                "relation": "challenges",
                "user_note": note,
            },
        )
        collected = saved["questions"][0]["evidence_passages"][0]
        assert len(model.contexts) == calls
        assert collected["quote"] == second_text and collected["user_note"] == note
        assert saved["questions"][0]["state"] == "answered"
        assert saved["questions"][0]["conclusion"] == qdata["conclusion"]
        assert saved["results"][0] == old
        found = client.get(base + "/search", params={"q": "复杂集成需要实现适配接口"}).json()
        assert any(row["kind"] == "question" and row["id"] == qid for row in found["records"])
        checked = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=qid,
            question="这段反例是否真的挑战原解释，还是适用条件不同？",
        )
        result = checked["results"][0]
        assert {origin, document} <= {
            row.get("public_document_id") for row in result["result"]["evidence"]
        }
        context = model.contexts[-1]
        selected = context["project_context"]["career_evidence"]["selected_inquiry"]
        assert selected["evidence_passages"][0]["user_note"] == note
        assert selected["evidence_passages"][0]["relation"] == "challenges"
        changed = request(
            base + "/questions/" + qid + "/passages/" + collected["id"],
            {
                "relation": "conditions",
                "user_note": "重新核对后，可能只是不同条件；仍待确认。",
            },
            "patch",
        )
        assert len(model.contexts) > calls
        assert changed["questions"][0]["evidence_passages"][0]["quote"] == second_text
        assert changed["questions"][0]["evidence_passages"][0]["id"] == collected["id"]
        assert (
            context["project_context"]["career_evidence"]["selected_inquiry"]["evidence_passages"][
                0
            ]["relation"]
            == "challenges"
        )
        changed_question = request(base + "/questions/" + qid, qdata, "patch")
        assert (
            changed_question["questions"][0]["evidence_passages"]
            == changed["questions"][0]["evidence_passages"]
        )
        removed = client.delete(base + "/materials/" + document, headers=auth)
        assert removed.status_code == 200
        rechecked = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=qid,
            question="原资料移出后，哪些线索已无法重核？",
        )
        assert document not in {
            row["id"] for row in model.contexts[-1]["fixed_scope"]["public_document_titles"]
        }
        assert document not in rechecked["document_ids"]
        assert rechecked["questions"][0]["evidence_passages"][0]["quote"] == second_text
        other = request("/api/career", {"title": "另一个合成目标", "goal": "另一方向"})
        invalid = client.post(
            f"/api/career/{other['id']}/questions/{qid}/passages",
            headers=auth,
            json={"passage": {"public_document_id": origin, "start": 0, "end": 1}},
        )
        assert invalid.status_code == 422
        deleted = client.delete(
            base + "/questions/" + qid + "/passages/" + collected["id"], headers=auth
        )
        assert deleted.status_code == 200
        final = deleted.json()
        assert final["questions"][0]["evidence_passages"] == []
        historical = next(row for row in final["results"] if row["step_id"] == result["step_id"])
        assert historical["result"] == result["result"]
        assert client.get("/api/public-documents/" + document).json()["text"] == second_text
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()
        assert reopened["questions"][0]["source_passage"]["quote"] == first_text
        assert reopened["questions"][0]["conclusion"] == qdata["conclusion"]
