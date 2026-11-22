"""Scripted local interview checks: question origins are positions, never guessed semantics."""

import json
import re

import pytest
from starlette.testclient import TestClient
from test_adaptive_investigation import ScriptedPlanner, brief, settled, task, workspace
from test_adaptive_investigation import prepare as prepare_default

from work_observer.research.agent import ModelClient


def test_no_matching_jobs_remain_an_empty_scope_when_answering(tmp_path):
    plan = brief([task("interview")])
    plan["constraints"] = [{"field": "city", "value": "上海", "source_text": "只看上海"}]
    with TestClient(workspace(tmp_path, ScriptedPlanner(plan)),
                    base_url="http://127.0.0.1") as client:
        auth, goal, base, root, jobs = prepare_default(
            client, "只看上海，如何解释这项工作？", ["北京", "北京"],
        )
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": root})
        source = settled(client, base)["results"][0]["result"]
        assert source["status"] == "completed", source
        assert source["investigation"]["effective_scope"]["job_ids"] == []
        prepared = client.post(base + "/prepare", headers=auth, json={
            "kind": "answer", "source_step_id": root, "question_index": 0,
            "answer": "当前没有上海岗位依据，保留未知。",
        })
        assert prepared.status_code == 201, prepared.text
        project = client.get("/api/projects/" + goal).json()
        step = next(row for row in project["steps"] if row["id"] == prepared.json()["step_id"])
        assert step["job_ids"] == [] and project["job_ids"] == jobs


class InterviewFlowModel(ModelClient):
    def __init__(self):
        self.planner = ScriptedPlanner(brief([
            task("interview", terms=["重排"], question="如何解释知识库检索工作？"),
            task("interview", terms=["端云同步"], question="如何解释端云记忆同步工作？"),
        ]))
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if any(tool["name"] == "plan_investigation" for tool in self.tools):
            self.planner.tools = self.tools
            calls, raw = await self.planner.turn(history)
            call = calls[0]
            if call["name"] == "finish_research":
                arguments = json.loads(call["arguments"])
                evidence = next(row["evidence"] for row in outputs if row.get("engine"))
                arguments["claims"] = [{"category": "task", "basis": "direct",
                                        "requirement": "unspecified", "text": row["quote"],
                                        "evidence_ids": [row["citation_key"]]} for row in evidence]
                for i, outcome in enumerate(arguments["task_outcomes"]):
                    outcome["claim_indices"] = [n for n, row in enumerate(evidence)
                                                if row["job_id"] == self.jobs[i]]
                    # Same question wording in two tasks must retain different origins.
                    outcome["questions"] = ["你会如何构造失败输入并说明验证边界？"]
                call["arguments"] = json.dumps(arguments)
            return calls, raw

        personal = context["project_context"]["career_evidence"]
        selected = personal["selected_interview_task"]
        assert selected["task_index"] == 1 and selected["available"]
        assert selected["task"]["question"] == "如何解释端云记忆同步工作？"
        assert {row["job_id"] for row in selected["source_references_to_reread"]} == {self.jobs[1]}
        assert all("quote" not in row for row in selected["source_references_to_reread"])
        assert {row["id"] for row in context["fixed_scope"]["jobs"]} == set(self.jobs[:2])
        if not outputs:
            name, arguments = "read_archived_document", {
                "document_id": personal["selected_answer"]["document_id"], "start": 0,
            }
        elif len(outputs) == 1:
            name, arguments = "read_job", {"job_id": self.jobs[1], "start": 0}
        else:
            answer = outputs[0]["evidence"][0]
            name, arguments = "finish_research", {
                "claims": [{"category": "task", "basis": "direct", "requirement": "unspecified",
                            "text": "用户自述只完成本地构造输入，尚未验证真实端云同步。",
                            "evidence_ids": [answer["citation_key"]]}],
                "gaps": ["构造输入改变了什么条件，哪些端云行为尚未验证？"],
            }
            finish = next(tool for tool in self.tools if tool["name"] == name)["parameters"]
            if "revisions" in finish["properties"]:
                arguments["revisions"] = []
            if "application_plan" in finish["properties"]:
                arguments["application_plan"] = None
        call = {"type": "function_call", "name": name,
                "arguments": json.dumps(arguments), "call_id": str(len(history))}
        return [call], call


@pytest.mark.parametrize("selection", ["explicit", "city"])
def test_question_feedback_and_followup_keep_origin_and_scope(tmp_path, selection):
    model = InterviewFlowModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        jobs = [client.post("/api/import", headers=auth, json={
            "title": "合成工作方向" + str(i), "company": "合成公司" + str(i),
            "description": text, "city": "上海" if i < 2 else "北京", "data_kind": "synthetic",
        }).json()["job_id"] for i, text in enumerate([
            "负责知识库检索与重排，构建评估集。", "负责记忆存储与端云同步上下文管理。",
            "负责另一工作区方向的端云同步。",
        ])]
        model.jobs = jobs
        for i, item in enumerate(model.planner.plan["tasks"]):
            item["source_job_ids"] = [jobs[i]]
        if selection == "city":
            model.planner.plan["constraints"] = [
                {"field": "city", "value": "上海", "source_text": "只看上海"},
            ]
        goal = client.post("/api/career", headers=auth, json={
            "title": "合成复合面试", "goal": "分清两条工作线", "job_ids": jobs,
        }).json()["id"]
        base = f"/api/career/{goal}"

        def prepare(values):
            response = client.post(base + "/prepare", headers=auth, json=values)
            assert response.status_code == 201, response.text
            return response.json()["step_id"]

        def run(step):
            response = client.post(
                f"/api/projects/{goal}/run", headers=auth, json={"step_id": step},
            )
            assert response.status_code == 202, response.text
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row
            return row

        root = prepare({"kind": "ask", "adaptive": True,
                        "question": "只看上海，分别就两种工作准备面试题。",
                        **({"selected_job_ids": jobs[:2]} if selection == "explicit" else {})})
        run(root)
        answer = prepare({"kind": "answer", "source_step_id": root, "question_index": 1,
                          "answer": "我只完成本地构造输入，尚未验证真实端云同步。"})
        feedback = run(answer)
        origin = feedback["interview_origin"]
        assert origin == {"step_id": root, "task_index": 1, "question_index": 1,
                          "task_question": "如何解释端云记忆同步工作？"}
        followup = run(prepare({"kind": "followup", "source_step_id": answer}))
        assert followup["interview_origin"] == origin
        reanswer = prepare({"kind": "answer", "source_step_id": followup["step_id"],
                            "question_index": 0,
                            "answer": "我只完成本地构造输入，尚未验证真实端云同步。"})
        pending = client.get(base).json()["results"][0]
        assert pending["interview_origin"] == origin
        assert set(pending["selected_job_ids"]) == set(jobs[:2])
        project = client.get("/api/projects/" + goal).json()
        for identity in (answer, followup["step_id"], reanswer):
            step = next(row for row in project["steps"] if row["id"] == identity)
            assert set(step["job_ids"]) == set(jobs[:2])
        assert project["job_ids"] == jobs  # The surrounding workspace is not edited.
