"""A six-JD comparison can finish within the existing six-call research round."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class MultiJobModel(ModelClient):
    def __init__(self, *, batch):
        self.batch = batch
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        evidence = [item for output in outputs for item in output.get("evidence", [])]
        jobs = context["fixed_scope"]["jobs"]
        unread = [
            job["id"]
            for job in jobs
            if not any(item.get("job_id") == job["id"] for item in evidence)
        ]
        if unread:
            if self.batch:
                assert "read_jobs" in {tool["name"] for tool in self.tools}
                name, arguments = (
                    "read_jobs",
                    {"reads": [{"job_id": identity, "start": 0} for identity in unread]},
                )
            else:
                name, arguments = "read_job", {"job_id": unread[0], "start": 0}
        elif story := context["project_context"]["career_evidence"].get("selected_story"):
            if not any(item.get("public_document_id") == story["document_id"] for item in evidence):
                name, arguments = (
                    "read_archived_document",
                    {
                        "document_id": story["document_id"],
                        "start": 0,
                    },
                )
            else:
                name, arguments = self.answer(evidence)
        else:
            name, arguments = self.answer(evidence)
        if name == "finish_research" and context["project_context"]["career_action"] == "map":
            arguments["work_map"] = {
                "version": "work-map-v3-work-relations",
                "scope_note": "只演示六份合成资料的读取，不代表真实模型研究效果。",
                "work_types": [
                    {
                        "name": "合成接口验证任务",
                        "problem": "区分各份正文的验证任务。",
                        "tasks": "按原文核对输入与输出。",
                        "deliverables": "样例与观察记录。",
                        "claim_indices": list(range(len(arguments["claims"]))),
                        "basis": "inference",
                        "boundary": "验收责任和个人能力仍未知。",
                        "next_check": "核对实际分工。",
                    }
                ],
                "work_relations": [],
                "comparisons": [],
                "unknowns": ["未说明真实验收标准。"],
            }
            arguments["revisions"] = []
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": str(len(history)),
        }
        return [call], call

    @staticmethod
    def answer(evidence):
        return "finish_research", {
            "claims": [
                {
                    "category": "task",
                    "basis": "direct",
                    "requirement": "unspecified",
                    "text": item["quote"].split("。")[0] + "。",
                    "evidence_ids": [item["id"]],
                }
                for item in evidence
                if item.get("job_id")
            ],
            "gaps": ["六份合成资料的实际验收标准和个人能力仍未知。"],
        }


class BatchContinuationModel(ModelClient):
    def __init__(self):
        self.last_usage = {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, arguments = (
                "read_jobs",
                {
                    "reads": [
                        {"job_id": job["id"], "start": 0} for job in context["fixed_scope"]["jobs"]
                    ]
                },
            )
        elif len(outputs) == 1:
            first = outputs[0]
            window = next(row for row in first["windows"] if row["has_more"])
            self.long_job = window["job_id"]
            assert not any("商科背景更佳" in item["quote"] for item in first["evidence"])
            name, arguments = "read_job", {"job_id": self.long_job, "start": window["next_start"]}
        else:
            guide = outputs[-1]["reading_guide"]
            source = next(row for row in guide["sources"] if row["job_id"] == self.long_job)
            assert source["coverage"]["fully_read"]
            item = next(item for item in outputs[-1]["evidence"] if "商科背景更佳" in item["quote"])
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "ability",
                            "basis": "direct",
                            "requirement": "preferred",
                            "text": "合成长JD写商科背景更佳，属于加分条件。",
                            "evidence_ids": [item["id"]],
                        }
                    ],
                    "gaps": ["不能从这一条件推断实际验收权。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": str(len(history)),
        }
        return [call], call


def test_compare_six_jobs_and_one_selected_story_without_increasing_the_call_limit(tmp_path):
    database = tmp_path / "six-jobs.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MultiJobModel(batch=False)
    with TestClient(
        create_app(settings, model=model, reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        jobs = [
            post(
                "/api/import",
                {
                    "title": f"合成六岗对照{i}",
                    "company": "合成团队",
                    "description": f"负责第{i}类接口验证。交付样例与观察；验收标准未知。",
                    "data_kind": "synthetic",
                },
            )["job_id"]
            for i in range(6)
        ]
        original = {
            identity: client.get("/api/jobs/" + identity).json()["current"]["description_text"]
            for identity in jobs
        }
        goal = post(
            "/api/career",
            {"title": "合成：六个岗位一次对照", "goal": "比较各自实际任务", "job_ids": jobs},
        )
        identity = goal["id"]
        base = "/api/career/" + identity
        # Reproduce the actual stop: six separate reads leave no turn to form an answer.
        sequential = run_stage(client, identity, auth, "ask", question="比较所选六份JD的任务。")
        stopped = sequential["results"][0]
        assert stopped["result"]["status"] == "incomplete"
        assert stopped["result"]["stop_reason"] == "model_call_limit"
        assert stopped["result"]["model_calls"] == 6
        response = client.delete(base + "/steps/" + stopped["step_id"], headers=auth)
        assert response.status_code == 200
        model.batch = True
        compared = run_stage(client, identity, auth, "ask", question="比较所选六份JD的任务。")
        result = compared["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert result["model_calls"] == 2 and len(result["claims"]) == 6
        assert {item["job_id"] for item in result["evidence"]} == set(jobs)
        assert result["trace"][0]["tool"] == "read_jobs"
        story = post(
            base + "/stories",
            {
                "title": "虚构本地练习",
                "situation": "只做合成接口。",
                "action": "构造输入并记录输出。",
                "result": "有本地观察，未独立核实。",
                "limits": "无生产经验。",
            },
        )["stories"][0]
        personal = run_stage(
            client, identity, auth, "ask", question="结合这份经历对照六份JD。", story_id=story["id"]
        )["results"][0]["result"]
        assert personal["status"] == "completed"
        assert personal["model_calls"] == 3
        assert any(
            item.get("public_document_id") == story["document_id"] for item in personal["evidence"]
        )
        mapped = run_stage(client, identity, auth, "map")["results"][0]["result"]
        assert mapped["status"] == "completed" and mapped["model_calls"] == 2
        assert mapped["work_map"]["work_types"][0]["claim_indices"] == list(range(6))
        assert all(
            client.get("/api/jobs/" + key).json()["current"]["description_text"] == text
            for key, text in original.items()
        )


def test_batch_beginnings_can_continue_to_a_late_qualification_without_changing_its_strength(
    tmp_path,
):
    database = tmp_path / "batch-continuation.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = BatchContinuationModel()
    with TestClient(
        create_app(settings, model=model, reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        long_text = "负责接口开发。" + "背景说明。" * 1500 + "商科背景更佳。生产能力未说明。"
        jobs = [
            client.post(
                "/api/import",
                headers=auth,
                json={
                    "title": title,
                    "company": "合成团队",
                    "data_kind": "synthetic",
                    "description": text,
                },
            ).json()["job_id"]
            for title, text in (("合成长JD", long_text), ("合成短JD", "负责接口验证。"))
        ]
        goal = client.post(
            "/api/career",
            headers=auth,
            json={"title": "合成：并排读取后补读限定", "goal": "核对资格性质", "job_ids": jobs},
        ).json()
        result = run_stage(
            client, goal["id"], auth, "ask", question="两份JD如何说明教育背景条件？"
        )["results"][0]["result"]
        assert result["status"] == "completed" and result["model_calls"] == 3
        assert result["claims"][0]["requirement"] == "preferred"
        assert [entry["tool"] for entry in result["trace"]] == [
            "read_jobs",
            "read_job",
            "finish_research",
        ]
        assert client.get("/api/jobs/" + jobs[0]).json()["current"]["description_text"] == long_text
