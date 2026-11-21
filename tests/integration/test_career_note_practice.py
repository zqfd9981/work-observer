"""Practice a saved understanding without requiring an inquiry or inventing experience."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_question_materials import QuestionMaterialModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

QUESTION = "如果正常响应仍重复写入，怎样区分重试与并发条件？"
FOLLOWUP = "若固定请求编号后仍重复，你还需要哪些观察才能缩窄解释？"
NOTE_END = "末尾限定：局部观察不证明生产恢复能力，实际权限未知。"
NOTE_VIEW = "合成认识自测：重试、请求编号和并发条件需要分开解释。" * 44 + NOTE_END


class NotePracticeModel(ModelClient):
    def __init__(self):
        self.initial = QuestionMaterialModel()
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        if not personal["understanding_check"]:
            self.initial.tools = self.tools
            return await self.initial.turn(history)
        note = personal["selected_learning_note"]
        assert note["current_user_view"] == NOTE_VIEW
        assert not note["use_for_research"] and personal["selected_inquiry"] is None
        assert not personal["selected_story"] and not personal["selected_experiment_id"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        action = context["project_context"]["career_action"]
        if not outputs:
            name, args = "read_learning_note", {"note_id": note["id"]}
        elif len(outputs) == 1:
            record = outputs[0]["note"]
            assert record["current_user_view"].endswith(NOTE_END)
            source = record["source_locators"][0]["public_document_id"]
            reads = [{"document_id": source, "start": 0}]
            if personal["selected_answer"]:
                reads.append({
                    "document_id": personal["selected_answer"]["document_id"], "start": 0,
                })
            name, args = "read_archived_documents", {"reads": reads}
        else:
            evidence = outputs[1]["evidence"]
            answer_id = (personal["selected_answer"] or {}).get("document_id")
            if answer_id:
                own = "".join(row["quote"] for row in evidence
                              if row.get("public_document_id") == answer_id)
                assert "末尾自述：尚未运行，也没有生产经验。" in own
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "synthesis",
                            "requirement": "unspecified", "text": (
                                "合成原文提供局部请求记录，生产权限仍未知。"
                                if action == "teachback" else
                                "合成反馈：回答把重试当成充分条件；需要区分请求编号、并发与反例，"
                                "用户说明尚未运行，不能解释成实际生产经验。"
                            ), "evidence_ids": [row["id"] for row in evidence]}],
                "gaps": [QUESTION] if action == "teachback" else [FOLLOWUP],
            }
            if action == "plan":
                assert not context["application_background"]["background"]
                args["application_plan"] = {
                    "background_memory_id": context["application_background"]["memory_id"],
                    "actions": [{
                        "title": "合成：固定请求编号再观察重复写入",
                        "task_or_ability": "比较解释成立的条件", "deliverable": "两组局部观察记录",
                        "hypothesis": "先固定编号才能区分部分解释，尚未实际运行。",
                        "completion_check": "记录正常和超时输入，保留反例与未知。",
                        "evidence_ids": [row["id"] for row in evidence],
                        "assumptions": ["只使用虚构局部输入。"],
                    }], "open_questions": ["局部结果仍不能证明生产能力。"],
                }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_note_practice_feedback_followup_and_revision_preserve_the_chosen_understanding(tmp_path):
    database = tmp_path / "note-practice.db"
    upgrade(database)
    model = NotePracticeModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = post("/api/career", {
            "title": "合成独立认识自测", "goal": "检验解释能否经得住条件变化",
            "material_title": "合成认识自测原文",
            "material_text": "虚构工作记录：重试可能再次提交请求，正常响应也可能重复写入。"
                             "需要分别记录请求编号和并发条件；生产权限未说明。",
        })
        identity, raw = goal["id"], goal["materials"][0]["id"]
        base = "/api/career/" + identity
        source = run_stage(client, identity, auth, "ask", question="记录局部解释的依据。",
                           material_id=raw)["results"][0]
        assert source["result"]["status"] == "completed"
        task = post(base + "/experiments", {
            "title": "合成旧观察练习", "task_or_ability": "比较局部条件",
            "deliverable": "观察记录", "completion_check": "保留反例与未知。",
        })["tasks"][-1]
        observed = client.patch(base + "/tasks/" + task["id"], headers=auth, json={
            "state": "done", "outcome": "虚构旧记录：出现重复，生产环境未运行。",
        })
        assert observed.status_code == 200, observed.text
        note = post(base + "/insights", {
            "previous_view": "原先以为有重试就会恢复。", "observation": "阅读虚构局部工作记录。",
            "current_view": NOTE_VIEW, "open_question": "哪些反例能检验解释？",
            "source_step_id": source["step_id"], "source_claim_index": 0, "task_id": task["id"],
        })["insights"][-1]
        post(base + "/insights/" + note["id"] + "/use", {"use_for_research": False})
        # The note's attached raw source must remain readable beyond the opening previews.
        for index in range(21):
            post(base + "/materials", {"title": f"合成后续背景{index}", "text": "其他说明。"})
        before = deepcopy(client.get(base).json())
        assert not before["questions"] and not before["stories"]
        quiz = run_stage(client, identity, auth, "teachback", insight_id=note["id"])["results"][0]
        assert quiz["result"]["status"] == "completed", quiz["result"].get("stop_reason")
        assert quiz["understanding_check"] and quiz["insight_id"] == note["id"]
        assert quiz["question_id"] is None and QUESTION in quiz["result"]["gaps"]
        assert quiz["result"]["career_learning_context"]["selected_note"]["current_user_view"] == (
            NOTE_VIEW
        )
        assert {row["public_document_id"] for row in quiz["result"]["evidence"]} == {raw}
        other = post(base + "/insights", {
            "previous_view": "另一个问题。", "observation": "另一份观察。",
            "current_view": "另一条认识。", "open_question": "待核对？",
        })["insights"][-1]
        calls = len(model.contexts)
        invalid = client.post(base + "/prepare", headers=auth, json={
            "kind": "answer", "source_step_id": quiz["step_id"], "answer": "不能混入其他认识。",
            "insight_id": other["id"],
        })
        assert invalid.status_code == 422 and len(model.contexts) == calls
        answer = ("合成回答：只要有重试就不会重复写入。" * 90
                  + "末尾自述：尚未运行，也没有生产经验。")
        feedback = run_stage(client, identity, auth, "answer", source_step_id=quiz["step_id"],
                             question_index=0, answer=answer)["results"][0]
        assert feedback["result"]["status"] == "completed", json.dumps({
            key: feedback["result"].get(key) for key in ("stop_reason", "trace", "model_calls")
        }, ensure_ascii=False)
        assert feedback["understanding_check"] and feedback["insight_id"] == note["id"]
        assert feedback["answer"] == answer and feedback["interview_question"] == QUESTION
        assert {row["public_document_id"] for row in feedback["result"]["evidence"]} == {
            raw, feedback["answer_document_id"],
        }
        followup = run_stage(
            client, identity, auth, "followup", source_step_id=feedback["step_id"],
        )["results"][0]
        assert followup["result"]["status"] == "completed" and FOLLOWUP in (
            followup["result"]["gaps"]
        )
        assert followup["insight_id"] == note["id"] and followup["question_id"] is None
        assert followup["answer_document_id"] == feedback["answer_document_id"]
        planned = run_stage(client, identity, auth, "plan", source_step_id=feedback["step_id"])[
            "results"][0]
        assert planned["result"]["status"] == "completed", planned["result"].get("stop_reason")
        assert planned["insight_id"] == note["id"] and planned["understanding_check"]
        after = client.get(base).json()
        retained = next(row for row in after["insights"] if row["id"] == note["id"])
        assert retained == before["insights"][0] and not retained["use_for_research"]
        assert after["questions"] == before["questions"] and not after["stories"]
        assert after["materials"] == before["materials"]
        assert after["tasks"] == before["tasks"]
        replacement = post(base + "/insights", {
            "previous_view": NOTE_VIEW, "observation": "自测暴露了把重试当作充分条件的问题。",
            "current_view": "需要分别控制请求编号与并发，不能由局部解释推出生产经验。",
            "open_question": "尚未运行对照，真实分工仍未知。", "replaces_insight_id": note["id"],
            "source_step_id": feedback["step_id"],
        })["insights"][-1]
        assert replacement["replaces_insight_id"] == note["id"]
        retained_quiz = next(row for row in client.get(base).json()["results"]
                             if row["step_id"] == quiz["step_id"])
        assert retained_quiz["result"]["career_learning_context"]["selected_note"] == (
            quiz["result"]["career_learning_context"]["selected_note"]
        )
