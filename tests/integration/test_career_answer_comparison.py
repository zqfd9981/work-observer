"""Full answer comparisons use old feedback as context and reread source material."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_note_practice import NOTE_VIEW, QUESTION, NotePracticeModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade

FIRST_ANSWER = "合成原回答：重试就能防止重复。" * 65 + "末尾自述：尚未运行，也没有生产经验。"
SECOND_ANSWER = "合成重答：请求编号、业务动作和并发条件需要分别核对。" * 60 + (
    "末尾自述：尚未运行，也没有生产经验。"
)


class AnswerComparisonModel(NotePracticeModel):
    async def turn(self, history):
        context = json.loads(history[1]["content"])
        personal = context["project_context"]["career_evidence"]
        pair = personal.get("selected_answer_comparison", [])
        if not pair:
            return await super().turn(history)
        self.contexts.append(context)
        assert [row["user_answer"] for row in pair] == [FIRST_ANSWER, SECOND_ANSWER]
        assert all(row["interview_question"] == QUESTION for row in pair)
        assert all(row["claim_details_to_recheck"] and row["unresolved_then"] for row in pair)
        assert all("evidence_ids" not in claim for row in pair
                   for claim in row["claim_details_to_recheck"])
        assert personal["understanding_check"] and personal["selected_inquiry"] is None
        assert not personal["selected_map_comparison"] and not personal["selected_experiment_id"]
        assert not context.get("application_background", {}).get("background")
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            source = next(
                row["public_document_id"] for row in pair[0]["source_references_to_reread"]
                if row.get("evidence_kind") == "work_material"
            )
            name, args = "read_archived_document", {"document_id": source, "start": 0}
        else:
            name, args = "finish_research", {
                "claims": [{
                    "category": "task", "basis": "synthesis", "requirement": "unspecified",
                    "text": "合成对照：后次回答区分了更多条件，但原文只描述局部记录，"
                            "仍不能确定实际协议或证明生产经验。",
                    "evidence_ids": [row["id"] for row in outputs[0]["evidence"]],
                }],
                "gaps": ["怎样构造一个请求编号改变、业务动作不变的反例？"],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_answer_pair_without_inquiry_retains_full_originals_and_independent_raw_evidence(tmp_path):
    database = tmp_path / "answer-comparison.db"
    upgrade(database)
    model = AnswerComparisonModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = post("/api/career", {
            "title": "合成回答前后对照", "goal": "区分表述变化与有依据的理解",
            "material_title": "合成认识自测原文",
            "material_text": "虚构工作记录：重试可能再次提交请求，正常响应也可能重复写入。"
                             "需要分别记录请求编号和并发条件；生产权限未说明。",
        })
        identity, raw = goal["id"], goal["materials"][0]["id"]
        base = "/api/career/" + identity
        source = run_stage(client, identity, auth, "ask", question="先读局部资料。")["results"][0]
        note = post(base + "/insights", {
            "previous_view": "有重试就不会重复。", "observation": "虚构工作记录。",
            "current_view": NOTE_VIEW, "source_step_id": source["step_id"],
            "open_question": "条件改变时还成立吗？",
        })["insights"][-1]
        post(base + "/insights/" + note["id"] + "/use", {"use_for_research": False})
        quiz = run_stage(client, identity, auth, "teachback", insight_id=note["id"])["results"][0]
        answers = [run_stage(client, identity, auth, "answer", source_step_id=quiz["step_id"],
                             answer=text, question_index=0)["results"][0]
                   for text in [FIRST_ANSWER, SECOND_ANSWER]]
        assert all(row["result"]["status"] == "completed" for row in answers)
        before = deepcopy(client.get(base).json())
        other = post(base + "/insights", {
            "previous_view": "另一个问题。", "observation": "其他虚构观察。",
            "current_view": "其他认识。",
        })["insights"][-1]
        payload = {"kind": "ask", "section": "interview",
                   "question": "对照原回答，别把新旧当正确性。",
                   "comparison_step_ids": [row["step_id"] for row in answers],
                   "insight_id": note["id"], "inherit_focus": False}
        calls = len(model.contexts)
        invalid = client.post(base + "/prepare", headers=auth,
                              json={**payload, "insight_id": other["id"]})
        assert invalid.status_code == 422 and len(model.contexts) == calls
        compared = run_stage(client, identity, auth, **payload)["results"][0]
        assert compared["result"]["status"] == "completed", compared["result"].get("stop_reason")
        saved_pair = compared["result"]["career_learning_context"]["answer_comparison"]
        assert [row["user_answer"] for row in saved_pair] == [FIRST_ANSWER, SECOND_ANSWER]
        assert compared["understanding_check"] and compared["insight_id"] == note["id"]
        assert compared["question_id"] is None and compared["comparison_step_ids"] == (
            payload["comparison_step_ids"]
        )
        assert {row["public_document_id"] for row in compared["result"]["evidence"]} == {raw}
        assert any(row["tool"] == "read_archived_document" for row in compared["result"]["trace"])
        after = client.get(base).json()
        assert after["questions"] == before["questions"] and not after["stories"]
        assert after["materials"] == before["materials"] and not after["tasks"]
        assert after["insights"][0] == before["insights"][0]
        assert [row for row in after["results"] if row["step_id"] in
                {item["step_id"] for item in before["results"]}] == before["results"]
        next_answer = run_stage(
            client, identity, auth, "answer", source_step_id=compared["step_id"],
            answer="合成回答：构造请求编号变化、业务动作不变的输入。"
                   "末尾自述：尚未运行，也没有生产经验。", question_index=0,
        )["results"][0]
        assert next_answer["result"]["status"] == "completed"
        assert next_answer["interview_question"] == "怎样构造一个请求编号改变、业务动作不变的反例？"
        assert next_answer["understanding_check"] and next_answer["insight_id"] == note["id"]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        restored = next(row for row in client.get(base).json()["results"]
                        if row["step_id"] == compared["step_id"])
        assert restored["result"]["career_learning_context"]["answer_comparison"] == saved_pair
