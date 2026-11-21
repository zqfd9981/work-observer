"""Understanding practice checks explanations without inventing personal experience."""

import json
import re

from starlette.testclient import TestClient
from test_career_material_start import MaterialWorkspaceModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade

QUESTION = "为什么重试不一定能消除重复写入，需要区分哪些条件？"
FOLLOWUP = "若正常响应也出现重复，你会怎样区分重试、请求标识和并发这几种解释？"


class UnderstandingModel(MaterialWorkspaceModel):
    async def turn(self, history):
        returned, call = await super().turn(history)
        context = json.loads(history[1]["content"])
        personal = context["project_context"]["career_evidence"]
        if not personal.get("understanding_check"):
            return returned, call
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        selected = personal.get("selected_answer")
        read = [ev for output in outputs for ev in output.get("evidence", [])]
        if (
            call["name"] == "finish_research"
            and selected
            and not any(ev.get("public_document_id") == selected["document_id"] for ev in read)
        ):
            call.update(
                name="read_archived_document",
                arguments=json.dumps(
                    {
                        "document_id": selected["document_id"],
                        "start": 0,
                    }
                ),
            )
        elif call["name"] == "finish_research":
            answer = json.loads(call["arguments"])
            action = context["project_context"]["career_action"]
            if action == "teachback":
                answer["gaps"] = [QUESTION, "哪些观察能推翻你原先的解释，哪些内容还只能说未知？"]
            elif action in {"answer", "followup"}:
                own = next(
                    ev for ev in read if ev.get("public_document_id") == selected["document_id"]
                )
                source = next(ev for ev in read if ev["id"] != own["id"])
                answer["claims"] = [
                    {
                        "category": "task",
                        "basis": "synthesis",
                        "requirement": "unspecified",
                        "text": ("回答需区分重试、请求标识和并发条件；用户明确未运行，"
                                 "不能推成实际工作经验。"),
                        "evidence_ids": [source["id"], own["id"]],
                    }
                ]
                answer["gaps"] = (
                    [FOLLOWUP]
                    if action == "followup"
                    else ["仍需固定请求标识与并发条件作实际对照，概念解释不证明生产能力。"]
                )
            call["arguments"] = json.dumps(answer)
        return returned, call


def test_understanding_answer_feedback_followup_and_experiment_keep_the_same_inquiry(tmp_path):
    database = tmp_path / "understanding.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = UnderstandingModel()
    with TestClient(
        create_app(settings, model=model, reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = post(
            "/api/career",
            {
                "title": "合成理解自测",
                "goal": "检验工作解释与条件边界",
                "background": "仅用本地合成请求练习，没有生产经验。",
                "material_title": "合成工作说明",
                "material_text": "合成工作说明：构造失败请求，交付样例、日志和观察记录；"
                "重试可能再次提交请求，正常响应也可能重复写入，需固定标识比较，未生产验证。",
            },
        )
        identity, base = goal["id"], f"/api/career/{goal['id']}"
        q = post(base + "/questions", {"question": "怎样理解重复写入的解释边界？"})["questions"][0]
        assert (
            client.post(base + "/prepare", headers=auth, json={"kind": "teachback"}).status_code
            == 422
        )
        quiz = run_stage(client, identity, auth, "teachback", question_id=q["id"])["results"][0]
        assert quiz["result"]["status"] == "completed", quiz["result"].get("stop_reason")
        assert quiz["understanding_check"] and quiz["question_id"] == q["id"]
        assert QUESTION in quiz["result"]["gaps"]
        another = post(base + "/questions", {"question": "另一项理解调查？"})["questions"][-1]
        calls = len(model.contexts)
        invalid = client.post(base + "/prepare", headers=auth, json={
            "kind": "answer", "answer": "合成回答。", "source_step_id": quiz["step_id"],
            "question_id": another["id"],
        })
        assert invalid.status_code == 422 and len(model.contexts) == calls
        wrong = "只要有重试就不会重复写入。" * 105 + "末尾限定：我尚未运行，也没有生产经验。"
        assert len(wrong) <= 2500
        feedback = run_stage(
            client,
            identity,
            auth,
            "answer",
            source_step_id=quiz["step_id"],
            question_index=0,
            answer=wrong,
        )["results"][0]
        assert feedback["result"]["status"] == "completed", feedback["result"].get("stop_reason")
        assert feedback["question_id"] == q["id"] and feedback["understanding_check"]
        assert feedback["interview_question"] == QUESTION and feedback["answer"] == wrong
        archived = client.get("/api/public-documents/" + feedback["answer_document_id"]).json()
        assert archived["title"].startswith("理解自测回答") and wrong in archived["text"]
        assert any(
            ev.get("public_document_id") == feedback["answer_document_id"]
            for ev in feedback["result"]["evidence"]
        )
        context = model.contexts[-1]["project_context"]["career_evidence"]
        assert context["understanding_check"] and context["selected_inquiry"]["id"] == q["id"]
        followup = run_stage(
            client, identity, auth, "followup", source_step_id=feedback["step_id"]
        )["results"][0]
        assert followup["result"]["status"] == "completed"
        assert FOLLOWUP in followup["result"]["gaps"] and followup["question_id"] == q["id"]
        assert followup["answer_document_id"] == feedback["answer_document_id"]
        improved = (
            "若正常响应也重复，就不能只归因于超时；还需固定请求标识和并发条件。我仍未运行实验。"
        )
        second = run_stage(
            client,
            identity,
            auth,
            "answer",
            source_step_id=followup["step_id"],
            question_index=0,
            answer=improved,
        )["results"][0]
        assert (
            second["result"]["status"] == "completed" and second["interview_question"] == FOLLOWUP
        )
        repeated = run_stage(
            client,
            identity,
            auth,
            "answer",
            source_step_id=quiz["step_id"],
            question_index=0,
            answer=improved,
        )["results"][0]
        assert repeated["result"]["status"] == "completed" and repeated["question_id"] == q["id"]
        planned = run_stage(client, identity, auth, "plan", source_step_id=repeated["step_id"])[
            "results"
        ][0]
        assert planned["result"]["status"] == "completed", planned["result"].get("stop_reason")
        assert planned["question_id"] == q["id"] and planned["understanding_check"]
        assert (
            model.contexts[-1]["project_context"]["career_evidence"]["selected_answer"][
                "document_id"
            ]
            == repeated["answer_document_id"]
        )
        task = post(base + "/tasks", {"step_id": planned["step_id"]})["tasks"][0]
        assert task["question_id"] == q["id"] and task["state"] == "planned" and not task["outcome"]
        data = client.get(base).json()
        original = next(row for row in data["results"] if row["step_id"] == feedback["step_id"])
        assert (
            original["answer"] == wrong
            and original["answer_document_id"] == feedback["answer_document_id"]
        )
        assert data["questions"][0]["state"] == "open"
