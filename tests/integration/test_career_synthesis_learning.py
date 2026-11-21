"""A saved synthesis remains useful across sessions, revisions and explicit scope changes."""

import json
import re

from starlette.testclient import TestClient
from test_career_inquiry_synthesis import InquirySynthesisModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class SynthesisLearningModel(InquirySynthesisModel):
    def __init__(self):
        super().__init__()
        self.expected_note_id = None
        self.read_notes = []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        personal = context["project_context"]["career_evidence"]
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not self.expected_note_id or not personal.get("selected_inquiry"):
            messages, call = await super().turn(history)
            if call["name"] == "finish_research" and personal.get("synthesis_inquiries"):
                args = json.loads(call["arguments"])
                evidence = [row for output in outputs for row in output.get("evidence", [])]
                preferred_job = context["fixed_scope"]["jobs"][-1]["id"]
                args["claims"].append(
                    {
                        "category": "ability",
                        "basis": "direct",
                        "requirement": "preferred",
                        "text": "原岗位写明商科背景更佳，属于加分条件。",
                        "evidence_ids": [
                            row["id"] for row in evidence if row.get("job_id") == preferred_job
                        ],
                    }
                )
                call["arguments"] = json.dumps(args)
            return messages, call
        self.contexts.append(context)
        selected = [*personal["learning_notes"], personal.get("selected_learning_note") or {}]
        assert any(row.get("id") == self.expected_note_id for row in selected)
        evidence = [row for output in outputs for row in output.get("evidence", [])]
        scope = context["fixed_scope"]
        documents = [
            row
            for row in scope.get("public_document_titles", [])
            if row["title"].startswith("合成综合原资料")
        ]
        if not outputs:
            name, args = "read_learning_note", {"note_id": self.expected_note_id}
        elif not evidence:
            assert outputs[0]["note"]["id"] == self.expected_note_id
            self.read_notes.append(outputs[0]["note"])
            name, args = "read_job", {"job_id": scope["jobs"][0]["id"], "start": 0}
        elif documents and not any(row.get("public_document_id") for row in evidence):
            if len(documents) == 1:
                name, args = (
                    "read_archived_document",
                    {"document_id": documents[0]["id"], "start": 0},
                )
            else:
                name, args = (
                    "read_archived_documents",
                    {
                        "reads": [{"document_id": row["id"], "start": 0} for row in documents],
                    },
                )
        else:
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "synthesis",
                            "requirement": "unspecified",
                            "text": "合成复核：只按当前原文与局部记录解释任务，"
                            "实际生产验收分工仍未知。",
                            "evidence_ids": [row["id"] for row in evidence],
                        }
                    ],
                    "gaps": ["个人理解仍需按当前问题的适用条件核对。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_synthesis_understanding_is_recalled_then_revised_scoped_and_shelved(tmp_path):
    model = SynthesisLearningModel()
    settings = Settings(database_path=tmp_path / "app.db", raw_directory=tmp_path / "raw")
    upgrade(settings.database_path)
    kwargs = {
        "model": model,
        "reports_dir": tmp_path / "reports",
        "checkpoint_path": tmp_path / "research.db",
    }

    def open_client():
        return TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1")

    def authorization(client):
        return {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

    def post(path, values):
        response = client.post(path, headers=auth, json=values)
        assert response.status_code in {200, 201}, response.text
        return response.json()

    with open_client() as client:
        auth = authorization(client)
        jobs = [
            post(
                "/api/import",
                {
                    "title": "合成综合学习岗位" + str(index),
                    "company": "合成团队",
                    "data_kind": "synthetic",
                    "description": text,
                },
            )["job_id"]
            for index, text in enumerate(
                [
                    "负责工具接口接入和失败记录；生产验收权未说明。",
                    "参与业务验证，商科背景更佳。",
                ]
            )
        ]
        identity = post(
            "/api/career",
            {
                "title": "合成：整体认识用于后续调查",
                "goal": "理解工作关系并按新观察修正",
                "job_ids": jobs,
            },
        )["id"]
        base = "/api/career/" + identity
        questions, documents = [], []
        for index, title in enumerate(("接口检查与验收是否不同？", "商科更佳说明什么？")):
            question = post(
                base + "/questions",
                {
                    "question": title,
                    "state": "open",
                    "selected_job_ids": [jobs[index]],
                },
            )["questions"][-1]
            questions.append(question)
            material = post(
                base + "/materials",
                {
                    "title": "合成综合原资料学习" + str(index),
                    "text": "合成工作记录：接口输入输出与最终业务验收不同；商业理解仅为加分条件。",
                },
            )["materials"][-1]
            documents.append(material["id"])
            first = run_stage(
                client,
                identity,
                auth,
                "ask",
                question_id=question["id"],
                question=title,
                material_id=material["id"],
            )["results"][0]
            assert first["result"]["status"] == "completed"
        combined = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="综合两项调查的关系与未知。",
            synthesis_question_ids=[row["id"] for row in questions],
        )["results"][0]
        assert combined["result"]["status"] == "completed"
        assert len(combined["result"]["claims"]) == 2
        original = {
            "previous_view": "Before.",
            "observation": "A local run failed.",
            "current_view": "Only local conditions. " * 52
            + "FINAL LIMIT: no production authority.",
            "open_question": "What is still unknown?",
            "source_step_id": combined["step_id"],
            "source_claim_index": None,
        }
        note = post(base + "/insights", original)["insights"][-1]
        model.expected_note_id = note["id"]
        for index in range(21):
            post(
                base + "/materials",
                {"title": "其他合成工作资料" + str(index), "text": "无关记录。"},
            )
        for _index in range(3):
            post(
                base + "/insights",
                {
                    "previous_view": "无关的词面相似记录",
                    "observation": "只用作检索干扰。",
                    "current_view": "接口检查与验收是否不同？商科更佳说明什么？" * 10,
                    "open_question": "关键词命中不表示它关联本次调查。",
                },
            )
        checked = run_stage(
            client,
            identity,
            auth,
            "ask",
            question_id=questions[0]["id"],
            question="继续查证接口边界。",
        )["results"][0]
        assert checked["result"]["status"] == "completed" and checked["result"]["model_calls"] == 4
        personal = model.contexts[-1]["project_context"]["career_evidence"]
        assert personal["learning_notes"][0]["id"] == note["id"]
        assert (
            personal["learning_recall"]["selections"][0]["reason"] == "same_inquiry_or_experiment"
        )
        full = model.read_notes[-1]
        assert full["current_user_view"] == original["current_view"]
        assert {link["question_id"] for link in full["inquiry_links"]} == {
            row["id"] for row in questions
        }
        assert len(full["source_discussion"]["claims_to_recheck"]) == 2
        assert full["source_scope"] == combined["result"]["scope"]
        assert full["source_discussion"]["claims_to_recheck"][1]["requirement"] == "preferred"
        assert set(documents) <= set(checked["document_ids"])
        assert all(note["id"] not in claim["evidence_ids"] for claim in checked["result"]["claims"])

    with open_client() as client:
        auth = authorization(client)
        checked = run_stage(
            client,
            identity,
            auth,
            "ask",
            question_id=questions[1]["id"],
            question="重新打开后，继续核对这个问题。",
        )["results"][0]
        assert checked["result"]["status"] == "completed"
        assert model.read_notes[-1]["current_user_view"] == original["current_view"]
        revised = {
            "previous_view": original["current_view"],
            "observation": "Another local failure.",
            "current_view": "A narrower interpretation. " * 42
            + "FINAL REVISION: scope remains limited.",
            "open_question": "Which conditions transfer?",
            "replaces_insight_id": note["id"],
        }
        replacement = post(base + "/insights", revised)["insights"][-1]
        assert not next(
            row for row in client.get(base).json()["insights"] if row["id"] == note["id"]
        )["use_for_research"]
        model.expected_note_id = replacement["id"]
        checked = run_stage(
            client,
            identity,
            auth,
            "ask",
            question_id=questions[1]["id"],
            question="用新的认识回查原问题。",
        )["results"][0]
        assert checked["result"]["status"] == "completed"
        full = model.read_notes[-1]
        assert full["current_user_view"] == revised["current_view"]
        assert all(link["inherited"] for link in full["inquiry_links"])
        assert set(documents) <= set(checked["document_ids"])
        narrowed = {**revised, "question_id": questions[0]["id"]}
        response = client.patch(
            base + "/insights/" + replacement["id"], headers=auth, json=narrowed
        )
        assert response.status_code == 200, response.text
        model.expected_note_id = None
        run_stage(
            client,
            identity,
            auth,
            "ask",
            question_id=questions[1]["id"],
            question="单独核对商科条件。",
        )
        selected = model.contexts[-1]["project_context"]["career_evidence"]["learning_notes"]
        assert not any(row["id"] in {note["id"], replacement["id"]} for row in selected)
        model.expected_note_id = replacement["id"]
        checked = run_stage(
            client,
            identity,
            auth,
            "ask",
            question_id=questions[0]["id"],
            question="只在接口问题范围内核对。",
        )["results"][0]
        assert checked["result"]["status"] == "completed"
        assert [link["question_id"] for link in model.read_notes[-1]["inquiry_links"]] == [
            questions[0]["id"]
        ]
        post(base + "/insights/" + replacement["id"] + "/use", {"use_for_research": False})

    with open_client() as client:
        auth = authorization(client)
        model.expected_note_id = None
        run_stage(
            client,
            identity,
            auth,
            "ask",
            question_id=questions[0]["id"],
            question="继续核对接口问题。",
        )
        selected = model.contexts[-1]["project_context"]["career_evidence"]["learning_notes"]
        assert not any(row["id"] in {note["id"], replacement["id"]} for row in selected)
        model.expected_note_id = replacement["id"]
        checked = run_stage(
            client,
            identity,
            auth,
            "ask",
            insight_id=replacement["id"],
            question="明确重查这份已搁置认识。",
        )["results"][0]
        assert checked["result"]["status"] == "completed"
        assert not model.read_notes[-1]["use_for_research"]
        data = client.get(base).json()
        assert not next(row for row in data["insights"] if row["id"] == replacement["id"])[
            "use_for_research"
        ]
        assert data["questions"] == questions
