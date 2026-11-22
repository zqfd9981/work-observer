"""Answer an existing inquiry without generating a separate model question first."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

QUESTION = "同一个工具出现在不同工作中，能说明交付与责任相同吗？"
MATERIAL = "合成工作说明：同一工具用于核对账本与记录执行过程，交付对象不同。个人验收权仍未知。"
ANSWER = ("我的理解🤔：工具相同还不能证明交付和责任相同；需要核对业务对象与条件。" * 34
          + "末尾限定：我没有参与真实业务，个人验收权限与实际验证仍未知。")
REVISED = "我先区分任务、交付对象和验收权限，再核对同一工具在各场景中的用途。仍需原文与反例。"


class InquiryAnswerModel(ModelClient):
    def __init__(self):
        self.last_usage, self.contexts = {}, []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        pair = personal.get("selected_answer_comparison", [])
        assert context["project_context"]["career_action"] == ("ask" if pair else "answer")
        assert personal["understanding_check"] and personal["selected_inquiry"]
        assert not personal.get("selected_story") and not personal.get("selected_learning_note")
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if pair:
            assert [row["user_answer"] for row in pair] == [ANSWER, REVISED]
            assert all(row["interview_question"] == QUESTION for row in pair)
            assert all(row["claim_details_to_recheck"] for row in pair)
        if not outputs:
            name, args = "read_archived_documents", {"reads": [
                *([] if pair else [
                    {"document_id": personal["selected_answer"]["document_id"], "start": 0},
                ]),
                *[{"document_id": row["document_id"], "start": 0}
                  for row in personal["selected_materials"]],
            ]}
        else:
            evidence = outputs[0]["evidence"]
            if not pair:
                answer = "".join(row["quote"] for row in sorted(
                    (row for row in evidence if row["public_document_id"]
                     == personal["selected_answer"]["document_id"]), key=lambda row: row["start"]))
                assert ANSWER in answer or REVISED in answer
                assert "理解自测问题：" in answer and "用户回答：" in answer
            assert any(MATERIAL in row["quote"] for row in evidence)
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "inference", "requirement": "unspecified",
                            "text": ("这份回答区分了共用工具与交付责任；"
                                     "具体业务对象和权限仍需原文核实。"),
                            "evidence_ids": [row["id"] for row in evidence]}],
                "gaps": ["若业务对象改变，需要补哪些交付和验收证据？"],
            }
            project = context["project_context"]
            if project.get("previous_findings") or project.get("historical_reply"):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_direct_inquiry_answers_keep_their_original_question_and_independent_feedback(tmp_path):
    database = tmp_path / "inquiry-answer.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = InquiryAnswerModel()
    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]}
        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成直接作答", "goal": "用自己的话解释工作",
                    "material_title": "合成直接作答工作原文", "material_text": MATERIAL})
        identity, base = goal["id"], "/api/career/" + goal["id"]
        values = {"question": QUESTION, "material_ids": [goal["materials"][0]["id"]],
                  "state": "parked", "conclusion": "个人旧理解，尚未重新核实。"}
        q = save(base + "/questions", values)["questions"][0]
        before = client.get(base).json()
        for invalid in [{"kind": "ask", "question_id": q["id"]},
                        {"kind": "answer"}, {"kind": "answer", "question_id": q["id"],
                                              "question": "与当前题目不同的旧草稿"}]:
            response = client.post(base + "/prepare", headers=auth,
                                   json={"inquiry_answer": True, "answer": ANSWER, **invalid})
            assert response.status_code == 422, response.text
        assert client.get(base).json() == before and not model.contexts
        first = run_stage(client, identity, auth, "answer", inquiry_answer=True,
                          question_id=q["id"], question=QUESTION, answer=ANSWER)["results"][0]
        assert first["result"]["status"] == "completed", first["result"]["stop_reason"]
        assert first["inquiry_answer"] and first["understanding_check"]
        assert first["source_step_id"] is None and first["interview_question"] == QUESTION
        assert first["answer"] == ANSWER and first["result"]["model_calls"] == 2
        assert first["material_ids"] == values["material_ids"]
        assert client.get(base).json()["questions"] == before["questions"]
        second = run_stage(client, identity, auth, "answer", inquiry_answer=True,
                           question_id=q["id"], question=QUESTION, answer=REVISED)["results"][0]
        assert second["result"]["status"] == "completed"
        assert first["step_id"] != second["step_id"]
        before_comparison = client.get(base).json()
        comparison = run_stage(
            client, identity, auth, "ask", question="对照两次完整原回答，重读工作原文。",
            question_id=q["id"], comparison_step_ids=[first["step_id"], second["step_id"]],
            inherit_focus=False,
        )["results"][0]
        assert comparison["result"]["status"] == "completed", comparison["result"]["stop_reason"]
        snapshot = comparison["result"]["career_learning_context"]["answer_comparison"]
        assert [row["user_answer"] for row in snapshot] == [ANSWER, REVISED]
        assert all(row["interview_question"] == QUESTION for row in snapshot)
        assert client.get(base).json()["questions"] == before_comparison["questions"]
        assert all(row["public_document_id"] == values["material_ids"][0]
                   for row in comparison["result"]["evidence"])
        new_question = "业务对象变化时，需要怎样核对交付与责任的迁移条件？"
        save(base + "/questions/" + q["id"], {**values, "question": new_question}, "patch")
        third = run_stage(client, identity, auth, "answer", inquiry_answer=True,
                          question_id=q["id"], question=new_question, answer=REVISED)["results"][0]
        assert third["result"]["status"] == "completed"
        assert third["interview_question"] == new_question
        retained = client.get(base).json()
        assert len(retained["results"]) == 4
        assert sum(row["kind"] == "answer" for row in retained["results"]) == 3
        old = next(row for row in retained["results"] if row["step_id"] == first["step_id"])
        assert old["answer"] == ANSWER and old["interview_question"] == QUESTION
        assert old["result"]["evidence"] == first["result"]["evidence"]
        assert retained["questions"][0]["state"] == "parked"
        assert retained["questions"][0]["conclusion"] == values["conclusion"]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()
        assert len(reopened["results"]) == 4
        assert next(row for row in reopened["results"] if row["step_id"] == comparison["step_id"])[
            "result"]["career_learning_context"]["answer_comparison"] == snapshot
        assert next(row for row in reopened["results"] if row["step_id"] == first["step_id"])[
            "interview_question"] == QUESTION
