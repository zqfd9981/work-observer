"""One archived JD task remains the focus without inventing personal experience."""

import json
import re

from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace

from work_observer.research.agent import ModelClient


class RequirementInterviewModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}
        self.story_documents = []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        scope = context["fixed_scope"]
        personal = context["project_context"]["career_evidence"]
        role = context["project_context"]["career_action"] == "role"
        if not role:
            assert {row["id"] for row in scope["jobs"]} == {self.selected_job}
            assert [row["document_id"] for row in personal["stories"]] == self.story_documents
            assert not personal["experiments"]
            assert personal["selected_requirement"]["requirement"] == "unspecified"
            assert personal["selected_requirement"]["records"] == self.records
            assert self.unrelated_document not in scope["archived_public_ids"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        documents = scope["archived_public_ids"] if not role else []
        if not outputs and documents:
            name, args = "read_archived_documents", {
                "reads": [{"document_id": key, "start": 0} for key in documents],
            }
        elif not outputs or len(outputs) == 1 and documents:
            name, args = "read_job", {"job_id": self.selected_job, "start": 0}
        else:
            evidence = outputs[-1]["evidence"][0]
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "direct", "requirement": "unspecified",
                            "text": evidence["quote"], "evidence_ids": [evidence["citation_key"]]}],
                "gaps": ["你会如何解释这项工作的输入、输出与验证方法？"],
            }
            schema = next(tool for tool in self.tools if tool["name"] == name)["parameters"]
            for key, value in (("application_plan", None), ("revisions", [])):
                if key in schema["properties"]:
                    args[key] = value
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_requirement_questions_answers_followups_and_comparisons_keep_exact_work(tmp_path):
    model = RequirementInterviewModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": "合成岗位工作" + str(i), "company": "合成团队" + str(i),
            "description": text, "data_kind": "synthetic",
        })["job_id"] for i, text in enumerate([
            "职责：建设检索评估集，核对失败样本。", "职责：维护端云同步和上下文。",
            "其他岗位：维护支付接口。",
        ])]
        goal = post("/api/career", {
            "title": "合成岗位工作面试", "goal": "解释具体任务和仍然未知的验证条件",
            "job_ids": jobs, "material_title": "无关资料", "material_text": "其他项目笔记。",
        })
        base = "/api/career/" + goal["id"]
        model.unrelated_document = goal["materials"][0]["id"]
        post(base + "/stories", {"title": "不应自动带入的经历", "situation": "支付接口",
                                "action": "构造本地样例", "result": "尚未验证业务效果"})
        planned = post(base + "/experiments", {
            "title": "尚未执行的检索练习", "task_or_ability": "核对失败样例",
            "deliverable": "对照记录", "completion_check": "逐例检查来源",
        })["tasks"][-1]

        def run(data):
            step = post(base + "/prepare", data)
            post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
            return row

        model.selected_job, model.records = jobs[0], []
        run({"kind": "role"})
        requirement = client.get(base).json()["requirements"][0]
        key = requirement["key"]
        initial = run({"kind": "interview", "requirement_key": key, "selected_job_ids": []})
        frozen = initial["result"]["career_learning_context"]["requirement"]
        assert initial["requirement_key"] == key
        assert frozen["text"] == requirement["text"] and frozen["basis"] == "direct"
        assert frozen["evidence"] == requirement["evidence"] and frozen["records"] == []
        assert initial["result"]["scope"]["archived_public_ids"] == []
        first = run({"kind": "answer", "source_step_id": initial["step_id"],
                     "answer": "我没有做过，先解释输入输出，验证条件还不清楚。"})
        followup = run({"kind": "followup", "source_step_id": first["step_id"]})
        followup_answer = run({"kind": "answer", "source_step_id": followup["step_id"],
                               "answer": "我仍然缺少标注规范，只能提出核对计划。"})
        repeated = run({"kind": "answer", "source_step_id": initial["step_id"],
                        "answer": "我会把来源召回和回答质量分开记录，实际效果仍未知。"})
        compared = run({"kind": "ask", "section": "interview", "inherit_focus": False,
                        "comparison_step_ids": [first["step_id"], repeated["step_id"]],
                        "question": "两次原回答的理由和未知有什么变化？"})
        for row in (first, followup, followup_answer, repeated, compared):
            assert row["requirement_key"] == key
            assert row["result"]["career_learning_context"]["requirement"] == frozen
        assert first["answer_document_id"] in followup["result"]["scope"]["archived_public_ids"]
        pair = compared["result"]["career_learning_context"]["answer_comparison"]
        assert [row["requirement_then"] for row in pair] == [frozen, frozen]

        # A second work point can ask the same words; that does not make the answers a pair.
        model.selected_job = jobs[1]
        run({"kind": "role"})
        other = client.get(base).json()["requirements"][0]
        questions = run({"kind": "interview", "requirement_key": other["key"]})
        other_answer = run({"kind": "answer", "source_step_id": questions["step_id"],
                            "answer": "我只了解上下文管理的概念，尚未实际实现。"})
        bad = client.post(base + "/prepare", headers=auth, json={
            "kind": "ask", "question": "对照这两次回答",
            "comparison_step_ids": [first["step_id"], other_answer["step_id"]],
        })
        assert bad.status_code == 422 and "同一项岗位工作" in bad.text

        selected = post(base + "/requirement-evidence", {
            "requirement_key": other["key"], "records": [{"kind": "task", "id": planned["id"]}],
            "missing": "只有计划，尚未执行。",
        })["requirements"][0]
        model.records = selected["proof"]["records"]
        with_plan = run({"kind": "interview", "requirement_key": other["key"]})
        snapshot = with_plan["result"]["career_learning_context"]["requirement"]
        assert snapshot["records"][0]["state"] == "planned"
        assert snapshot["missing"] == "只有计划，尚未执行。"
        assert questions["result"]["career_learning_context"]["requirement"]["records"] == []

        chosen_story = post(base + "/stories", {
            "title": "明确选入的本地检查", "situation": "只在个人练习中核对上下文",
            "action": "我记录了输入输出，没有参与端云同步工程。",
            "result": "尚不能证明业务效果。", "limits": "未实施生产同步。",
        })["stories"][-1]
        selected = post(base + "/requirement-evidence", {
            "requirement_key": other["key"], "records": [
                {"kind": "story", "id": chosen_story["id"]},
                {"kind": "task", "id": planned["id"]},
            ], "missing": "只有本地自述与计划，未做生产同步。",
        })["requirements"][0]
        model.records = selected["proof"]["records"]
        model.story_documents = [chosen_story["document_id"]]
        with_story = run({"kind": "interview", "requirement_key": other["key"]})
        assert with_story["result"]["scope"]["archived_public_ids"] == [chosen_story["document_id"]]
        assert with_plan["result"]["career_learning_context"]["requirement"] == snapshot
