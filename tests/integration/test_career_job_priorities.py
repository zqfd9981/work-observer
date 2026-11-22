"""User priorities guide a bounded inquiry without becoming recruitment facts."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

PURPOSE = (
    "用户提供的调查目的与取舍，不是招聘事实或能力认证。\n"
    "想参与的具体工作：合成偏好，想兼顾用户问题和持续编码🤔。\n"
    "个人经历自述（未独立核实）：构造案例中做过接口原型，未参与生产验收。\n"
    "这次最在意的条件：真实工作对象与交付反馈，不按岗位名称判断。"
)
UNKNOWN = "日常任务比例和验收权限需要向团队核实。"


class JobPriorityModel(ModelClient):
    def __init__(self):
        self.last_usage, self.contexts = {}, []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        inquiry = context["project_context"]["career_evidence"]["selected_inquiry"]
        assert inquiry["why_matters"] == PURPOSE and inquiry["next_evidence"] == UNKNOWN
        assert inquiry["state"] == "open" and not inquiry["conclusion"]
        jobs = context["fixed_scope"]["jobs"]
        assert len(jobs) == 2 and {row["id"] for row in jobs} == set(inquiry["selected_job_ids"])
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = "read_jobs", {"reads": [{"job_id": row["id"], "start": 0} for row in jobs]}
        else:
            evidence = outputs[-1]["evidence"]
            assert {row["job_id"] for row in evidence} == set(inquiry["selected_job_ids"])
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "inference",
                            "requirement": "unspecified",
                            "text": "两份资料描述不同工作对象与交付。"
                            "用户在意的日常任务比例和个人验收权限未明确，仍需面试核实；"
                            "现有自述不证明已经能够承担实际业务责任。",
                            "evidence_ids": [row["id"] for row in evidence],
                        }
                    ],
                    "gaps": ["实际分工、反馈方式与个人权限尚未明确。"],
                },
            )
            project = context["project_context"]
            if project.get("previous_findings") or project.get("historical_reply"):
                args["revisions"] = []
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_priorities_remain_user_context_with_the_exact_original_scope_and_snapshot(tmp_path):
    database = tmp_path / "job-priorities.db"
    upgrade(database)
    model = JobPriorityModel()
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model,
            reports_dir=tmp_path / "reports",
        ),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        jobs = [
            save(
                "/api/import",
                {
                    "title": "合成偏好岗位" + str(index),
                    "company": "合成团队",
                    "data_kind": "synthetic",
                    "description": "合成原文：对象"
                    + str(index)
                    + "需要原型检查与交付反馈；日常任务比例和个人验收权限未明确。",
                },
            )["job_id"]
            for index in range(3)
        ]
        goal = save(
            "/api/career",
            {
                "title": "合成个人取舍调查",
                "goal": "按具体工作准备",
                "background": "整个目标原有的合成背景，仍应保持。",
                "job_ids": jobs,
            },
        )
        base = "/api/career/" + goal["id"]
        values = {
            "question": "工作差异与我的准备方向有什么关系？",
            "why_matters": PURPOSE,
            "next_evidence": UNKNOWN,
            "selected_job_ids": jobs[:2],
        }
        with_question = save(base + "/questions", values)
        question = with_question["questions"][-1]
        assert with_question["profile"] == goal["profile"]
        assert not model.contexts and not with_question["results"]
        studied = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=question["id"],
            question=question["question"],
        )
        result = studied["results"][0]["result"]
        assert result["status"] == "completed", result["stop_reason"]
        snapshot = result["career_learning_context"]["inquiry_at_start"]
        assert snapshot["why_matters"] == PURPOSE and snapshot["selected_job_ids"] == jobs[:2]
        changed = save(
            base + "/questions/" + question["id"],
            {**values, "why_matters": "后来重新考虑的个人取舍。"},
            "patch",
        )
        assert changed["profile"] == goal["profile"]
        assert (
            changed["results"][0]["result"]["career_learning_context"]["inquiry_at_start"]
            == snapshot
        )
