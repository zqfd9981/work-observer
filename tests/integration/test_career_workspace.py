"""The job-seeker journey using synthetic sources and a local model substitute."""

import json
import re
import time

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class CareerModel:
    def __init__(self):
        self.contexts = []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, arguments = "read_job", {"job_id": context["fixed_scope"]["jobs"][0]["id"]}
        else:
            evidence = outputs[0]["evidence"][0]["id"]
            question = context["question"]
            arguments = {
                "claims": [
                    {
                        "category": "ability",
                        "basis": "direct",
                        "requirement": "required",
                        "text": "合成岗位要求Python接口开发与测试能力。",
                        "evidence_ids": [evidence],
                    }
                ],
                "gaps": [],
                "application_plan": None,
            }
            project_context = context.get("project_context") or {}
            if project_context.get("previous_findings") or project_context.get("historical_reply"):
                arguments["revisions"] = []
            if "工作样本实验" in question:
                arguments["application_plan"] = {
                    "background_memory_id": context["application_background"]["memory_id"],
                    "actions": [
                        {
                            "title": "合成接口失败样例实验",
                            "task_or_ability": "接口测试",
                            "deliverable": "接口、失败样例与测试记录",
                            "completion_check": "重现超时与重试结果",
                            "evidence_ids": [evidence],
                            "assumptions": ["使用本地合成数据"],
                        }
                    ],
                    "open_questions": ["真实业务验收边界待核实"],
                }
            if "设计一次证据驱动的模拟面试" in question:
                arguments["gaps"] = [
                    "请结合亲自完成的接口项目，说明如何验证失败重试，哪一步有结果记录？"
                ]
            name = "finish_research"
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": str(len(history)),
        }
        return [call], call


def run_stage(client, identity, auth, kind, **extra):
    prepared = client.post(
        f"/api/career/{identity}/prepare", json={"kind": kind, **extra}, headers=auth
    )
    assert prepared.status_code == 201, prepared.text
    step = prepared.json()["step_id"]
    running = client.post(f"/api/projects/{identity}/run", json={"step_id": step}, headers=auth)
    assert running.status_code == 202, running.text
    for _ in range(200):
        data = client.get(f"/api/career/{identity}").json()
        if not data["running"] and data["results"][0]["result"]:
            return data
        time.sleep(0.01)
    raise AssertionError("Synthetic research did not finish")


def test_target_evidence_experiment_and_interview_survive_reopen(tmp_path):
    database = tmp_path / "career.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = CareerModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        html = client.get("/").text
        assert 'id="page-career"' in html and "/assets/career.js" in html
        assert client.get("/assets/career.js").status_code == 200
        token = re.search(r'name="wo-token" content="([^"]+)"', html)[1]
        auth = {"X-WO-Token": token}
        job = client.post(
            "/api/import",
            json={
                "title": "合成接口岗位",
                "company": "合成团队",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
                "external_id": "career-test",
                "data_kind": "synthetic",
            },
            headers=auth,
        ).json()["job_id"]
        created = client.post(
            "/api/career",
            json={
                "title": "合成转型目标",
                "goal": "理解接口工作并形成作品",
                "background": "亲自做过合成接口练习",
                "constraints": "本地合成数据",
                "job_ids": [job],
            },
            headers=auth,
        )
        assert created.status_code == 201, created.text
        identity = created.json()["id"]
        assert not model.contexts  # Saving a goal never starts a model request.
        role = run_stage(client, identity, auth, "role")
        requirement = role["requirements"][0]
        assert requirement["requirement"] == "required" and requirement["evidence"][0]["quote"]
        story = {
            "title": "合成项目经历",
            "situation": "验证失败重试",
            "action": "亲自编写超时样例",
            "result": "保存了测试记录",
            "limits": "未在生产环境执行",
            "requirement_key": requirement["key"],
        }
        saved = client.post(f"/api/career/{identity}/stories", json=story, headers=auth).json()
        assert saved["stories"][0]["action"] == story["action"]
        doc = client.get("/api/public-documents/" + saved["stories"][0]["document_id"]).json()
        assert "用户自述" in doc["text"] and story["limits"] in doc["text"]
        plan = run_stage(client, identity, auth, "plan")
        step = plan["results"][0]["step_id"]
        tasks = client.post(
            f"/api/career/{identity}/tasks", json={"step_id": step}, headers=auth
        ).json()
        repeated = client.post(
            f"/api/career/{identity}/tasks", json={"step_id": step}, headers=auth
        ).json()
        assert len(tasks["tasks"]) == len(repeated["tasks"]) == 1
        task = tasks["tasks"][0]
        updated = client.patch(
            f"/api/career/{identity}/tasks/{task['id']}",
            json={
                "state": "done",
                "hypothesis": "重试会避免写入失败",
                "outcome": "重试仍有重复写入，假设尚未验证",
                "artifact": "本地测试记录",
            },
            headers=auth,
        ).json()
        assert updated["tasks"][0]["outcome"].startswith("重试仍有")
        reflected = run_stage(client, identity, auth, "reflect", task_id=task["id"])
        assert reflected["results"][0]["kind"] == "reflect"
        personal = model.contexts[-1]["project_context"]["career_evidence"]
        assert model.contexts[-1]["project_context"]["previous_findings"] == []
        assert personal["stories"][0]["personal_action"] == story["action"]
        assert personal["experiments"][0]["reported_observation"].startswith("重试仍有")
        assert personal["experiments"][0]["prior_expectation"] == "重试会避免写入失败"
        assert personal["selected_experiment_id"] == task["id"]
        interview = run_stage(client, identity, auth, "interview")
        question = interview["results"][0]["result"]["gaps"][-1]
        feedback = run_stage(
            client,
            identity,
            auth,
            "answer",
            answer="我只在本地做了超时样例，未完成去重验证。",
            question_index=0,
        )
        assert feedback["results"][0]["kind"] == "answer"
        assert question in model.contexts[-1]["question"]
        assert "未完成去重验证" in model.contexts[-1]["question"]
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        data = client.get(f"/api/career/{identity}").json()
        assert len(data["stories"]) == len(data["tasks"]) == 1
        assert data["tasks"][0]["state"] == "done"
        assert client.get("/api/career").json()[0]["done_count"] == 1
