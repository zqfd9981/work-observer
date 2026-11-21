"""Competing explanations stay in one inquiry through a discriminating experiment."""

import json
import re

from starlette.testclient import TestClient
from test_career_material_start import MaterialWorkspaceModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class InquiryChallengeModel(MaterialWorkspaceModel):
    """A local script reads real synthetic archives, including the negative observation."""

    async def turn(self, history):
        outputs, call = await super().turn(history)
        if call["name"] != "finish_research":
            return outputs, call
        context = json.loads(history[1]["content"])
        personal = context["project_context"]["career_evidence"]
        read = [
            item
            for row in history
            if row.get("type") == "function_call_output"
            for item in json.loads(row["output"]).get("evidence", [])
        ]
        needed = [
            row["artifact_document"]["document_id"]
            for row in personal.get("experiments", [])
            if row.get("artifact_document")
        ]
        for document_id in needed:
            if not any(item.get("public_document_id") == document_id for item in read):
                call = {
                    "type": "function_call",
                    "name": "read_archived_document",
                    "arguments": json.dumps({"document_id": document_id, "start": 0}),
                    "call_id": str(len(history)),
                }
                return [call], call
        args = json.loads(call["arguments"])
        refs = list(dict.fromkeys(item["id"] for item in read))
        args["claims"] = [
            {
                "category": "task",
                "basis": "synthesis",
                "requirement": "unspecified",
                "evidence_ids": refs,
                "text": "合成材料只能支持对照条件；现有观察不足以确定重复写入原因。",
            }
        ]
        args["gaps"] = ["固定请求标识后，超时与正常响应是否仍有相同观察？两种解释都可能不充分。"]
        if context["project_context"]["career_action"] == "challenge":
            args["application_plan"] = {
                "background_memory_id": context["application_background"]["memory_id"],
                "actions": [
                    {
                        "title": "固定请求标识的响应对照",
                        "task_or_ability": "区分重复写入解释",
                        "deliverable": "正常与超时两组输入、输出和观察记录",
                        "completion_check": "固定请求标识，比较两种响应；允许没有区分度",
                        "hypothesis": (
                            "若仅超时组重复，才进一步检查响应条件；"
                            "两组相同则保留其他解释。"
                        ),
                        "evidence_ids": refs,
                        "assumptions": ["仅用本地合成输入"],
                    }
                ],
                "open_questions": ["本地观察不证明生产因果。"],
            }
        call["arguments"] = json.dumps(args)
        return [call], call


def test_two_explanations_continue_through_negative_observation_and_revised_understanding(tmp_path):
    database = tmp_path / "inquiry-hypotheses.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = InquiryChallengeModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
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
                "title": "合成：带着竞争解释做验证",
                "goal": "持续核实重复写入原因",
                "background": "只做本地合成练习，没有生产经验。",
                "material_title": "合成工作说明",
                "material_text": "合成说明：对照正常与超时请求，保留输入、输出、标识与观察。",
            },
        )
        base = "/api/career/" + goal["id"]
        pair = {
            "question": "重复写入与响应条件还是请求标识有关？",
            "why_matters": "区分验证方向，不能先认定因果。",
            "hypothesis_a": "超时响应触发重复提交。"
            + "仅限本地条件；" * 50
            + "末尾：尚未核实正常响应。",
            "hypothesis_b": "请求标识变化导致重复写入。",
            "next_evidence": "固定请求标识的正常与超时两组观察。",
        }
        question = post(base + "/questions", pair)["questions"][0]
        qid = question["id"]
        assert not model.contexts
        found = client.get(base + "/search", params={"q": "请求标识变化"}).json()
        assert any(row["id"] == qid and row["kind"] == "question" for row in found["records"])
        compared = run_stage(client, goal["id"], auth, "challenge", question_id=qid)
        comparison = compared["results"][0]
        assert comparison["result"]["status"] == "completed"
        assert comparison["hypothesis_a"] == pair["hypothesis_a"]
        assert comparison["hypothesis_b"] == pair["hypothesis_b"]
        assert comparison["question_id"] == qid and comparison["section"] == "experiments"
        context = model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"]
        assert context["hypothesis_a"] == pair["hypothesis_a"]
        assert context["hypothesis_b"] == pair["hypothesis_b"]
        assert compared["questions"][0]["state"] == "open"
        task = post(base + "/tasks", {"step_id": comparison["step_id"]})["tasks"][0]
        assert task["question_id"] == qid and task["hypothesis"]
        negative = "合成观察：固定标识后两组仍重复；未能区分解释，也不证明因果。"
        updated = client.patch(
            base + "/tasks/" + task["id"],
            headers=auth,
            json={"state": "done", "outcome": negative, "artifact_text": negative},
        )
        assert updated.status_code == 200, updated.text
        artifact = updated.json()["tasks"][0]["artifact_document_id"]
        reflected = run_stage(client, goal["id"], auth, "reflect", task_id=task["id"])
        reflection = reflected["results"][0]
        assert reflection["question_id"] == qid
        assert any(
            item.get("public_document_id") == artifact for item in reflection["result"]["evidence"]
        )
        note = post(
            base + "/insights",
            {
                "question_id": qid,
                "task_id": task["id"],
                "source_step_id": reflection["step_id"],
                "previous_view": "原以为对照响应就能找出原因。",
                "observation": negative,
                "current_view": "当前对照没有区分度，两种解释都仍需核实。",
                "open_question": "还需要哪些受控条件？",
            },
        )["insights"][0]
        # Editing the saved alternatives does not rewrite what was compared earlier.
        revised_pair = {**pair, "hypothesis_b": "还可能存在未控制的并发条件。"}
        client.patch(base + "/questions/" + qid, headers=auth, json=revised_pair)
        asked = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=qid,
            task_id=task["id"],
            source_step_id=comparison["step_id"],
            question="带着负面观察，下一步该区分什么？",
        )
        personal = model.contexts[-1]["project_context"]["career_evidence"]
        assert personal["selected_inquiry"]["hypothesis_b"] == revised_pair["hypothesis_b"]
        old = next(row for row in asked["results"] if row["step_id"] == comparison["step_id"])
        assert old["hypothesis_b"] == pair["hypothesis_b"]
        assert any(
            row["id"] == note["id"]
            for row in asked["results"][0]["result"]["career_learning_context"]["notes"]
        )
        assert asked["questions"][0]["state"] == "open"
        # Another inquiry's experiment must not be silently presented as this one's observation.
        other = post(base + "/questions", {"question": "另一个调查问题"})["questions"][-1]
        rejected = client.post(
            base + "/prepare",
            headers=auth,
            json={
                "kind": "challenge",
                "question_id": other["id"],
                "task_id": task["id"],
                "hypothesis_a": "A",
                "hypothesis_b": "B",
            },
        )
        assert rejected.status_code == 422
        inferred = run_stage(client, goal["id"], auth, "challenge", insight_id=note["id"])
        assert inferred["results"][0]["question_id"] == qid
        assert inferred["results"][0]["task_id"] == task["id"]
        assert inferred["results"][0]["hypothesis_b"] == revised_pair["hypothesis_b"]
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()
        assert reopened["questions"][0]["hypothesis_a"] == pair["hypothesis_a"]
        assert reopened["questions"][0]["hypothesis_b"] == revised_pair["hypothesis_b"]
        assert reopened["tasks"][0]["outcome"] == negative
        assert reopened["insights"][0]["question_id"] == qid
