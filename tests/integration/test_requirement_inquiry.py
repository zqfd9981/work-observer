"""A plain question about one JD work point becomes a scoped, continuing investigation."""

import json
import re

from starlette.testclient import TestClient
from test_adaptive_investigation import ScriptedPlanner, brief, settled, task, workspace
from test_requirement_interview import RequirementInterviewModel


class RequirementInquiryModel(ScriptedPlanner):
    def __init__(self):
        super().__init__(brief([
            task(terms=["评估集"], retry=["失败样本"], question="这项工作交付什么？"),
            task(intent="practice", terms=["评估集"], retry=["失败样本"],
                 question="先做什么小样本来理解这项任务？"),
        ]), produce_plan=True)

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        if context["project_context"]["career_action"] == "role":
            return await RequirementInterviewModel.turn(self, history)
        personal = context["project_context"]["career_evidence"]
        assert {row["id"] for row in context["fixed_scope"]["jobs"]} == {self.selected_job}
        assert context["fixed_scope"]["archived_public_ids"] == []
        assert not personal["stories"] and not personal["experiments"]
        assert personal["selected_requirement"] == self.target
        assert personal["selected_inquiry"]["target_requirement"] == self.target
        returned, call = await super().turn(history)
        if call["name"] == "finish_research":
            values = json.loads(call["arguments"])
            for claim in values["claims"]:
                claim["text"] = "负责评估集核对与失败样本记录。"
            call["arguments"] = json.dumps(values)
        return returned, call


def test_plain_requirement_question_keeps_jd_scope_through_planning_and_child_inquiry(tmp_path):
    model = RequirementInquiryModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": "合成要求调查岗位" + str(i), "company": "合成团队" + str(i),
            "description": text, "data_kind": "synthetic",
        })["job_id"] for i, text in enumerate([
            "职责：负责评估集核对与失败样本记录。", "职责：维护端云同步和上下文。",
            "其他工作：维护支付接口。",
        ])]
        goal = post("/api/career", {
            "title": "合成要求到自然提问", "goal": "先理解实际任务，再做可检查的练习",
            "job_ids": jobs, "material_title": "不应混入的支付笔记", "material_text": "支付日志。",
        })
        base = "/api/career/" + goal["id"]
        model.selected_job = jobs[0]

        def run(values):
            step = post(base + "/prepare", values)
            post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
            return row

        run({"kind": "role"})
        requirement = client.get(base).json()["requirements"][0]
        question_text = "评估集这活具体要交付什么？我没做过，先做什么小样本来理解？"
        calls = len(model.contexts)
        question = post(base + "/questions", {
            "requirement_key": requirement["key"], "question": question_text,
        })["questions"][-1]
        assert len(model.contexts) == calls
        assert question["selected_job_ids"] == jobs[:1] and question["material_ids"] == []
        model.target = question["target_requirement"]
        assert model.target["key"] == requirement["key"]
        assert model.target["requirement"] == "unspecified" and model.target["basis"] == "direct"
        post(base + "/stories", {"title": "另一项目的经历", "situation": "支付接口",
                                "action": "只做了本地检查", "result": "尚无业务效果证据"})

        # Later role work must not replace the saved question's original selection.
        model.selected_job = jobs[1]
        run({"kind": "role"})
        model.selected_job = jobs[0]
        answered = run({"kind": "ask", "question_id": question["id"], "question": question_text,
                        "adaptive": True, "selected_job_ids": []})
        assert answered["requirement_key"] == requirement["key"]
        assert answered["result"]["career_learning_context"]["requirement"] == model.target
        investigation = answered["result"]["investigation"]
        assert [row["intent"] for row in investigation["tasks"]] == ["understand", "practice"]
        assert len(answered["result"]["application_plan"]["actions"]) == 1
        generated = post(base + "/tasks", {"step_id": answered["step_id"]})["tasks"][-1]
        assert generated["target_requirement"] == model.target and generated["state"] == "planned"
        assert not generated["outcome"] and generated["question_id"] == question["id"]
        child = post(base + "/questions", {
            "parent_question_id": question["id"], "source_step_id": answered["step_id"],
            "question": "怎样记录失败样本和标注分歧？",
        })["questions"][-1]
        assert child["target_requirement"] == model.target
        assert child["selected_job_ids"] == jobs[:1]
        run({"kind": "ask", "question_id": child["id"], "question": child["question"],
             "adaptive": True})
        updated = client.patch(base + "/questions/" + question["id"], headers=auth,
                               json={"question": "我想进一步问清评估集的输入与交付。"})
        assert updated.status_code == 200, updated.text
        retained = next(row for row in updated.json()["questions"] if row["id"] == question["id"])
        assert retained["target_requirement"] == model.target
        rejected = client.post(base + "/questions", headers=auth,
                               json={"question": "无效要求", "requirement_key": "missing"})
        assert rejected.status_code == 422
        transfer = post(base + "/prepare", {
            "kind": "ask", "question_id": question["id"], "question": "能迁移到上下文工作吗？",
            "inherit_focus": False, "selected_job_ids": jobs[1:2],
        })
        project = client.get("/api/projects/" + goal["id"]).json()
        step = next(row for row in project["steps"] if row["id"] == transfer["step_id"])
        assert step["job_ids"] == jobs[1:2] and not step.get("career_requirement")
