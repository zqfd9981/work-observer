"""A note about a context exercise stays tied to that exercise during practice."""

import json
import re
from copy import deepcopy

import pytest
from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace
from test_requirement_interview import RequirementInterviewModel


class ContextUnderstandingModel(RequirementInterviewModel):
    async def turn(self, history):
        context = json.loads(history[1]["content"])
        if context["project_context"]["career_action"] != "role":
            personal = context["project_context"]["career_evidence"]
            note = personal["selected_learning_note"]
            assert note["current_user_view"] == self.view
            assert note["open_question"] == self.unknown
            assert note["use_for_research"] == self.expected_selected
            assert note["linked_experiment"]["id"] == self.parent["id"]
            assert "context_run" not in note["linked_experiment"]
            documents = set(context["fixed_scope"]["archived_public_ids"])
            assert self.parent["artifact_document_id"] in documents
            assert self.child["artifact_document_id"] not in documents
        return await super().turn(history)


@pytest.mark.parametrize("with_inquiry", [False, True])
def test_context_note_practice_keeps_original_log_and_jd_instead_of_latest_run(
    tmp_path, with_inquiry,
):
    model = ContextUnderstandingModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": "合成上下文自测岗位" + str(i), "company": "合成团队" + str(i),
            "description": text, "data_kind": "synthetic",
        })["job_id"] for i, text in enumerate([
            "可选专攻方向之一：上下文工程与记忆，负责端云同步上下文管理。",
            "另一工作：维护检索评估集。",
        ])]
        goal = post("/api/career", {
            "title": "合成上下文观察到理解自测", "goal": "解释冲突、输入条件与仍未验证的边界",
            "job_ids": jobs, "material_title": "无关资料", "material_text": "另一项目的笔记。",
        })
        base = "/api/career/" + goal["id"]
        model.selected_job, model.records = jobs[0], []
        model.unrelated_document = goal["materials"][0]["id"]

        def run(values):
            step = post(base + "/prepare", values)
            post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
            return row

        run({"kind": "role"})
        point = client.get(base).json()["requirements"][0]
        question_id = None
        if with_inquiry:
            question_id = post(base + "/questions", {
                "requirement_key": point["key"], "question": "同编号冲突应该怎样核对？",
            })["questions"][-1]["id"]
        cases = [{"name": "同编号不同内容", "edge": [{"key": "m1", "value": "查充电站"}],
                  "cloud": [{"key": "m1", "value": "查停车场"}]}]
        parent = post(base + "/experiments/context", {
            "cases": cases, "requirement_key": point["key"], "question_id": question_id,
            "hypothesis": "还不能选择哪端更新。", "save": True,
        })["career"]["tasks"][-1]
        changed = deepcopy(cases)
        changed[0]["cloud"][0]["value"] = "查充电站"
        child = post(base + "/experiments/context", {
            "cases": changed, "previous_task_id": parent["id"],
            "design_change": "仅把一端内容改成相同。", "save": True,
        })["career"]["tasks"][-1]
        values = {
            "task_id": parent["id"], "question_id": question_id,
            "previous_view": "同编号就可以选择一端覆盖。",
            "observation": "原样例保留了两端不同的内容，没有决定哪份更新。",
            "current_view": (
                "同编号内容不同应保留冲突；单端缺少不能直接判为删除，还缺时序与处理依据。" * 32
                + "末尾限定：未验证真实网络和同步恢复。"
            ),
            "open_question": "需要什么观察才能判断权威来源，仍需核对真实协议条件。" * 20
            + "末尾未知：断连和删除传播尚未实验。",
        }
        assert 1000 < len(values["current_view"]) <= 1500
        note = post(base + "/insights", values)["insights"][-1]
        post(base + "/insights/" + note["id"] + "/use", {"use_for_research": False})
        model.parent, model.child = parent, child
        model.view, model.unknown = values["current_view"], values["open_question"]
        model.expected_selected = False
        model.selected_job = jobs[1]
        run({"kind": "role"})
        model.selected_job = jobs[0]
        quiz = run({"kind": "teachback", "insight_id": note["id"]})
        assert quiz["task_id"] is None and quiz["understanding_check"]
        assert quiz["requirement_key"] == point["key"]
        assert quiz["result"]["scope"]["archived_public_ids"] == [parent["artifact_document_id"]]
        before = deepcopy(quiz["result"]["career_learning_context"])
        answer = run({"kind": "answer", "source_step_id": quiz["step_id"],
                      "answer": "这些输入只暴露冲突，不能说明哪端更新，也未验证真实同步。"})
        followup = run({"kind": "followup", "source_step_id": answer["step_id"]})
        run({"kind": "answer", "source_step_id": followup["step_id"],
             "answer": "缺失不等于删除；还需要明确协议与可观察的时序依据。"})
        rechecked = run({"kind": "ask", "insight_id": note["id"],
                         "question": "对照原样例核对这份认识，哪些条件仍然未知？"})
        assert rechecked["requirement_key"] == point["key"]
        revision = post(base + "/insights", {
            **values, "source_step_id": rechecked["step_id"], "replaces_insight_id": note["id"],
            "previous_view": values["current_view"],
            "current_view": "原样例只展示同编号冲突；还需要明确权威来源、时序和协议条件。",
            "open_question": "仍未验证断连、删除传播与实际同步恢复。",
        })["insights"][-1]
        model.view, model.unknown = revision["current_view"], revision["open_question"]
        model.expected_selected = True
        revised_quiz = run({"kind": "teachback", "insight_id": revision["id"]})
        assert revised_quiz["requirement_key"] == point["key"]
        assert revised_quiz["result"]["scope"]["archived_public_ids"] == [
            parent["artifact_document_id"],
        ]
        current = client.get(base).json()
        assert not next(row for row in current["insights"] if row["id"] == note["id"])[
            "use_for_research"
        ]
        old = next(row for row in current["results"] if row["step_id"] == quiz["step_id"])
        assert old["result"]["career_learning_context"] == before
        transfer = post(base + "/prepare", {
            "kind": "ask", "insight_id": note["id"], "question": "能用于另一份岗位的检索工作吗？",
            "inherit_focus": False, "selected_job_ids": jobs[1:2],
        })
        project = client.get("/api/projects/" + goal["id"]).json()
        step = next(row for row in project["steps"] if row["id"] == transfer["step_id"])
        assert step["job_ids"] == jobs[1:2] and not step.get("career_requirement")
