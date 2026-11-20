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
    assert running.json()["max_steps"] == 1
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
                "resume_title": "合成简历.txt",
                "resume_text": "合成简历：参与Python接口练习。没有真实业务效果数据。",
                "job_ids": [job],
            },
            headers=auth,
        )
        assert created.status_code == 201, created.text
        identity = created.json()["id"]
        assert not model.contexts  # Saving a goal never starts a model request.
        first_resume = created.json()["resume"]["document_id"]
        resume_text = client.get("/api/public-documents/" + first_resume).json()["text"]
        replacement = client.patch(
            f"/api/career/{identity}/resume",
            json={"title": "合成简历更正.txt", "text": "更正：仅完成本地接口练习，尚未验证去重。"},
            headers=auth,
        )
        assert replacement.status_code == 200, replacement.text
        assert replacement.json()["resume"]["document_id"] != first_resume
        assert client.get("/api/public-documents/" + first_resume).json()["text"] == resume_text
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
        original_document_id = saved["stories"][0]["document_id"]
        story_id = saved["stories"][0]["id"]
        story["result"] = "更正：只保存了本地失败记录，没有业务效果数据"
        edited = client.patch(
            f"/api/career/{identity}/stories/{story_id}", json=story, headers=auth
        )
        assert edited.status_code == 200, edited.text
        saved_story = edited.json()["stories"][0]
        assert saved_story["id"] == story_id and saved_story["document_id"] != original_document_id
        assert (
            client.get("/api/public-documents/" + original_document_id).json()["text"]
            == doc["text"]
        )
        current_scope = client.get(f"/api/projects/{identity}").json()["public_document_ids"]
        assert (
            saved_story["document_id"] in current_scope
            and original_document_id not in current_scope
        )
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
        assert personal["resume"]["document_id"] == replacement.json()["resume"]["document_id"]
        calls_before_note = len(model.contexts)
        insight = {
            "previous_view": "重试会自动消除写入问题",
            "observation": "本地仍有重复写入",
            "current_view": "目前只证明运行了失败样例，尚未证明重复写入已解决",
            "open_question": "下一步如何设计去重对照实验？",
            "task_id": task["id"],
        }
        learned = client.post(f"/api/career/{identity}/insights", json=insight, headers=auth)
        assert learned.status_code == 201, learned.text
        assert learned.json()["insights"][0]["origin"] == "user"
        assert len(model.contexts) == calls_before_note
        interview = run_stage(client, identity, auth, "interview")
        assert (
            model.contexts[-1]["project_context"]["career_evidence"]["learning_notes"][0][
                "current_user_view"
            ]
            == insight["current_view"]
        )
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
        temporary = client.post(
            f"/api/career/{identity}/stories",
            json={**story, "title": "不再使用的合成补充"},
            headers=auth,
        ).json()["stories"][-1]
        removed = client.delete(f"/api/career/{identity}/stories/{temporary['id']}", headers=auth)
        assert removed.status_code == 200 and len(removed.json()["stories"]) == 1
        assert client.get("/api/public-documents/" + temporary["document_id"]).status_code == 200
        calls_before_manual = len(model.contexts)
        manual = client.post(
            f"/api/career/{identity}/experiments",
            json={
                "title": "自选合成对照实验",
                "task_or_ability": "排查重复写入",
                "hypothesis": "只有超时场景会重复写入",
                "deliverable": "正常与超时两组本地运行记录",
                "completion_check": "对照两组的请求标识和写入次数",
            },
            headers=auth,
        )
        assert manual.status_code == 201, manual.text
        manual_task = manual.json()["tasks"][-1]
        assert manual_task["origin"] == "user" and manual_task["evidence_ids"] == []
        assert len(model.contexts) == calls_before_manual
        client.patch(
            f"/api/career/{identity}/tasks/{manual_task['id']}",
            json={
                "state": "done",
                "hypothesis": manual_task["hypothesis"],
                "outcome": "两组都观察到了重复写入，原先解释仍需调整",
                "artifact": "本地合成对照记录",
            },
            headers=auth,
        )
        run_stage(client, identity, auth, "reflect", task_id=manual_task["id"])
        manual_context = model.contexts[-1]["project_context"]["career_evidence"]
        assert manual_context["experiments"][0]["title"] == manual_task["title"]
        assert manual_context["experiments"][0]["origin"] == "user"
        calls_before_goal_edit = len(model.contexts)
        before_edit = client.get(f"/api/career/{identity}").json()
        another_job = client.post(
            "/api/import",
            json={
                "title": "合成平台目标岗位",
                "company": "合成团队",
                "description": "负责平台任务编排与接口验证。",
                "external_id": "career-new-target",
                "data_kind": "synthetic",
            },
            headers=auth,
        ).json()["job_id"]
        goal_edit = client.patch(
            f"/api/career/{identity}",
            json={
                "title": "调整后的合成求职目标",
                "goal": "转向理解平台工作与个人分工",
                "background": "更正：只有本地接口练习经历",
                "constraints": "仅使用合成记录",
                "job_ids": [another_job],
            },
            headers=auth,
        )
        assert goal_edit.status_code == 200, goal_edit.text
        changed = goal_edit.json()
        assert changed["title"] == "调整后的合成求职目标"
        assert changed["profile"]["background"] == "更正：只有本地接口练习经历"
        assert (
            len(changed["stories"]) == 1
            and len(changed["tasks"]) == 2
            and len(changed["insights"]) == 1
        )
        assert (
            changed["usage"] == before_edit["usage"] and changed["budget"] == before_edit["budget"]
        )
        assert changed["requirements"] == [] and all(
            not row["current"] for row in changed["results"]
        )
        assert len(model.contexts) == calls_before_goal_edit
        old_interview = client.post(
            f"/api/career/{identity}/prepare",
            json={"kind": "answer", "answer": "旧问题的回答"},
            headers=auth,
        )
        assert old_interview.status_code == 422
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        data = client.get(f"/api/career/{identity}").json()
        assert len(data["stories"]) == 1 and len(data["tasks"]) == 2
        assert data["tasks"][0]["state"] == "done"
        assert data["insights"][0]["current_view"] == insight["current_view"]
        assert data["title"] == "调整后的合成求职目标"
        assert client.get("/api/career").json()[0]["done_count"] == 2
