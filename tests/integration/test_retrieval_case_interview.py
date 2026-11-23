"""One saved evaluation case remains the subject of questions, feedback and comparison."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace
from test_requirement_interview import RequirementInterviewModel

from work_observer.research.agent import ModelClient

QUESTION = "你怎样解释这条样例的实际返回，哪些条件仍未验证？"


class CaseInterviewModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        if context["project_context"]["career_action"] == "role":
            return await RequirementInterviewModel.turn(self, history)
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        selected = personal["selected_retrieval_case"]
        assert selected["input"] == self.case
        assert selected["name"] == self.case["name"]
        assert personal["selected_requirement"] == self.target
        assert personal["retrieval_review"]["task_id"] == self.parent["id"]
        assert {row["id"] for row in context["fixed_scope"]["jobs"]} == set(self.jobs[:2])
        documents = {self.parent["artifact_document_id"]}
        if answer := personal.get("selected_answer"):
            documents.add(answer["document_id"])
        for answer in personal.get("selected_answer_comparison", []):
            assert answer["retrieval_case_then"]["input"] == self.case
            documents.add(answer["answer_document_id"])
        assert set(context["fixed_scope"]["archived_public_ids"]) == documents
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, values = "read_archived_documents", {
                "reads": [{"document_id": key, "start": 0} for key in sorted(documents)],
            }
        elif len(outputs) == 1:
            name, values = "read_job", {"job_id": self.read_job, "start": 0}
        else:
            evidence = outputs[-1]["evidence"][0]
            claims = [{"category": "task", "basis": "direct", "requirement": "unspecified",
                       "text": evidence["quote"], "evidence_ids": [evidence["citation_key"]]}]
            if answer := personal.get("selected_answer"):
                own = next(row for row in outputs[0]["evidence"]
                           if row.get("public_document_id") == answer["document_id"])
                claims.append({"category": "responsibility", "basis": "direct",
                               "requirement": "unspecified", "text": own["quote"],
                               "evidence_ids": [own["citation_key"]]})
            name, values = "finish_research", {"claims": claims, "gaps": [QUESTION]}
            schema = next(tool for tool in self.tools if tool["name"] == name)["parameters"]
            for key, value in (("application_plan", None), ("revisions", [])):
                if key in schema["properties"]:
                    values[key] = value
        call = {"type": "function_call", "name": name, "arguments": json.dumps(values),
                "call_id": str(len(history))}
        return [call], call


def test_case_interview_keeps_exact_case_through_answers_followup_and_comparison(tmp_path):
    model = CaseInterviewModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": "合成样例面试岗位" + str(i), "company": "合成团队" + str(i),
            "description": text, "data_kind": "synthetic",
        })["job_id"] for i, text in enumerate([
            "职责：建设检索评估集，核对失败样例。", "可选方向：端云上下文与记忆管理。",
            "未选的其他支付业务工作。",
        ])]
        goal = post("/api/career", {
            "title": "合成单条评估样例面试", "goal": "解释实际观察与未知", "job_ids": jobs,
            "material_title": "未选入资料", "material_text": "另一条工作线的笔记。",
        })
        base = "/api/career/" + goal["id"]

        def run(values):
            step = post(base + "/prepare", values)
            post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
            return row

        model.selected_job = jobs[0]
        run({"kind": "role"})
        point = client.get(base).json()["requirements"][0]
        values = {"job_ids": jobs[:2], "requirement_key": point["key"], "cases": [
            {"name": "评估:职责与标签", "question": "哪份原文要求建设评估集？",
             "label_reason": "第一份职责明示评估集与失败样例，标签仍是用户判断。",
             "baseline": {"terms": ["查无表达"]}, "candidate": {"terms": ["评估集"]},
             "expected_job_ids": jobs[:1]},
            {"name": "记忆:可选方向", "question": "哪些工作涉及端云上下文？",
             "label_reason": "第二份写在可选方向中，不能当作所有岗位的硬要求。",
             "baseline": {"terms": ["聊天"]}, "candidate": {"terms": ["端云"]},
             "expected_job_ids": jobs[1:2]},
        ]}
        saved = post(base + "/experiments/retrieval-suite", {**values, "save": True})
        model.parent, model.jobs = saved["career"]["tasks"][-1], jobs
        model.target = model.parent["target_requirement"]
        cases = saved["experiment"]["input"]["cases"]
        model.case, model.read_job = cases[0], jobs[0]
        model.selected_job = jobs[2]
        run({"kind": "role"})
        assert client.get(base).json()["requirements"][0]["key"] != model.target["key"]
        root = run({"kind": "interview", "task_id": model.parent["id"],
                    "retrieval_case_name": cases[0]["name"]})
        frozen = deepcopy(root["result"]["career_learning_context"]["retrieval_case"])
        changed = deepcopy(saved["experiment"]["input"])
        changed["cases"][0]["candidate"] = {"terms": ["端云"]}
        post(base + "/experiments/retrieval-suite", {
            **changed, "previous_task_id": model.parent["id"], "save": True,
        })
        answers = []
        for text in ("只看到改写后返回第一份原文，未验证语义效果。",
                     "原标签仍需核对；片段上限、查询表达与业务验收还不能等同。"):
            answers.append(run({"kind": "answer", "source_step_id": root["step_id"],
                                "question_index": 0, "answer": text}))
        followup = run({"kind": "followup", "source_step_id": answers[0]["step_id"]})
        followed = run({"kind": "answer", "source_step_id": followup["step_id"],
                        "question_index": 0, "answer": "还需要固定标签与资料做另一组对照。"})
        for row in [*answers, followup, followed]:
            assert row["retrieval_case_name"] == cases[0]["name"]
            assert row["result"]["career_learning_context"]["retrieval_case"] == frozen
        compared = run({"kind": "ask", "task_id": model.parent["id"],
                        "comparison_step_ids": [row["step_id"] for row in answers],
                        "question": "比较两次解释，指出仍不能确定的条件。"})
        assert compared["result"]["career_learning_context"]["retrieval_case"] == frozen
        model.case, model.read_job = cases[1], jobs[1]
        other = run({"kind": "interview", "task_id": model.parent["id"],
                     "retrieval_case_name": cases[1]["name"]})
        other_answer = run({"kind": "answer", "source_step_id": other["step_id"],
                            "question_index": 0, "answer": "这是另一条样例的观察，不合并为同题。"})
        assert other_answer["interview_question"] == answers[0]["interview_question"]
        rejected = client.post(base + "/prepare", headers=auth, json={
            "kind": "ask", "task_id": model.parent["id"], "question": "对照这两次回答。",
            "comparison_step_ids": [answers[0]["step_id"], other_answer["step_id"]],
        })
        assert rejected.status_code == 422 and "同一道题" in rejected.text
        final = client.get(base).json()
        assert next(row for row in final["results"] if row["step_id"] == root["step_id"])[
            "result"
        ]["career_learning_context"]["retrieval_case"] == frozen
