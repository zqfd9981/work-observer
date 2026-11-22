"""One job requirement drives a scoped experiment and a return to actual observations."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_user_can_design_a_requirement_sample_without_another_model_turn(tmp_path):
    database = tmp_path / "manual-requirement.db"
    upgrade(database)
    model = CareerModel()
    with TestClient(create_app(
        Settings(database_path=database, raw_directory=tmp_path / "raw"),
        model=model, reports_dir=tmp_path / "reports",
    ), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        jobs = [save("/api/import", {
            "title": f"合成手动样本岗位{i}", "company": "合成团队", "data_kind": "synthetic",
            "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
        })["job_id"] for i in range(2)]
        identity = save("/api/career", {
            "title": "合成：自己设计定向工作样本", "goal": "先做可检查的交付", "job_ids": jobs,
        })["id"]
        base = "/api/career/" + identity
        role = run_stage(client, identity, auth, "role")
        requirement = role["requirements"][0]
        key = requirement["key"]
        with_gap = save(base + "/requirement-evidence", {
            "requirement_key": key, "records": [], "relevance": "只有练习计划。",
            "missing": "还缺相同请求的实际输入输出与异常观察。",
        })
        calls = len(model.contexts)
        values = {
            "requirement_key": key, "title": "合成手动接口检查样本",
            "task_or_ability": "接口失败条件的检查", "hypothesis": "重复输入可能重复写入。",
            "deliverable": "两组实际输入输出和检查记录", "completion_check": "逐项比较预期与观察",
            "comparison_rows": [
                {"condition": "单次请求", "input": "固定id一次", "expected": "一次写入"},
                {"condition": "重复请求", "input": "相同id两次", "expected": "尚需实际观察"},
            ],
        }
        saved = save(base + "/experiments", values)
        task = saved["tasks"][-1]
        target = task["target_requirement"]
        assert len(model.contexts) == calls and saved["results"] == with_gap["results"]
        assert target["key"] == key and target["evidence"] == requirement["evidence"]
        assert target["missing"] == "还缺相同请求的实际输入输出与异常观察。"
        assert task["origin"] == "user" and not task.get("source_step_id")
        assert task["state"] == "planned" and not task["outcome"] and not task["artifact"]
        assert all(not row["observed"] for row in task["comparison_rows"])
        assert saved["requirements"][0]["proof"]["records"] == []
        save(base + "/requirement-evidence", {
            "requirement_key": key, "records": [], "missing": "后来改写的缺口，不能改写实验起点。",
        })
        observed = save(base + "/tasks/" + task["id"], {
            "state": "done", "outcome": "合成负面观察：两次写入，原因仍需核实。",
            "artifact_title": "合成接口输入输出",
            "artifact_text": "相同id两次请求，观察到两次写入。",
        }, "patch")
        assert observed["tasks"][-1]["target_requirement"] == target
        follow = save(base + "/experiments", {
            "title": "合成后续边界检查", "task_or_ability": "只改变请求去重条件",
            "deliverable": "对照记录", "completion_check": "同一输入分别观察",
            "previous_task_id": task["id"], "design_change": "仅改变去重条件。",
        })["tasks"][-1]
        assert follow["target_requirement"] == target and not follow.get("source_step_id")
        reflected = run_stage(client, identity, auth, "reflect", task_id=task["id"])
        assert reflected["results"][0]["result"]["status"] == "completed"
        selected = model.contexts[-1]["project_context"]["career_evidence"]["selected_requirement"]
        assert selected == target
        assert reflected["results"][0]["selected_job_ids"] == [target["evidence"][0]["job_id"]]
        before_count = len(reflected["tasks"])
        invalid = client.post(base + "/experiments", headers=auth,
                              json={**values, "requirement_key": "missing"})
        assert invalid.status_code == 422
        assert len(client.get(base).json()["tasks"]) == before_count


def test_requirement_experiment_keeps_selected_material_and_target_through_observation(tmp_path):
    database = tmp_path / "requirement-experiment.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = CareerModel()
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": f"合成定向练习岗位{i}", "company": "合成团队", "data_kind": "synthetic",
            "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
        })["job_id"] for i in range(2)]
        identity = post("/api/career", {
            "title": "合成：从一项要求到一个实验", "goal": "准备可讨论的失败样例",
            "background": "只有本地接口练习，没有生产经验。", "constraints": "使用本地样例。",
            "job_ids": jobs,
        })["id"]
        base = "/api/career/" + identity
        role = run_stage(client, identity, auth, "role")
        requirement = role["requirements"][0]
        key, target_job = requirement["key"], requirement["evidence"][0]["job_id"]
        story = post(base + "/stories", {
            "title": "合成旧经历", "situation": "只做本地检查", "action": "构造超时输入",
            "result": "一次失败观察", "limits": "没有并发或真实业务评测。",
        })["stories"][0]
        # The chosen old story must beat newer unrelated documents within the 20-document round.
        for index in range(21):
            post(base + "/materials", {"title": f"合成无关记录{index}", "text": "只作库存占位。"})
        missing = "还缺同一请求标识的实际输入输出；生产行为仍未知。"
        post(base + "/requirement-evidence", {
            "requirement_key": key, "records": [{"kind": "story", "id": story["id"]}],
            "relevance": "可讨论失败处理的检查方法。", "missing": missing,
        })
        planned = run_stage(client, identity, auth, "plan", requirement_key=key)
        row = planned["results"][0]
        assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
        assert row["requirement_key"] == key and row["selected_job_ids"] == [target_job]
        context = model.contexts[-1]
        assert len(context["fixed_scope"]["jobs"]) == 1
        selected = context["project_context"]["career_evidence"]["selected_requirement"]
        assert selected["key"] == key and selected["missing"] == missing
        assert selected["records"][0]["limits"] == story["limits"]
        assert story["document_id"] in row["document_ids"]
        assert any(item.get("public_document_id") == story["document_id"]
                   for item in row["result"]["evidence"])
        assert len(row["result"]["application_plan"]["actions"]) == 1
        imported = post(base + "/tasks", {"step_id": row["step_id"], "action_indices": [0]})
        task = imported["tasks"][0]
        assert task["target_requirement"] == selected
        assert task["source_step_id"] == row["step_id"] and task["state"] == "planned"
        # Being a targeted plan does not silently select it as proof of personal ability.
        assert imported["requirements"][0]["proof"]["records"][0]["id"] == story["id"]
        response = client.patch(base + "/tasks/" + task["id"], headers=auth, json={
            "state": "done", "outcome": "同一标识出现两次写入。只能确认本地失败，原因仍未知。",
            "artifact_title": "合成负面观察", "artifact_text": "输入id=demo；实际输出两次写入。",
        })
        assert response.status_code == 200, response.text
        done = response.json()["tasks"][0]
        reflected = run_stage(client, identity, auth, "reflect", task_id=task["id"])
        result = reflected["results"][0]
        assert result["result"]["status"] == "completed"
        assert result["selected_job_ids"] == [target_job]
        continued = model.contexts[-1]["project_context"]["career_evidence"]["selected_requirement"]
        assert continued == selected
        assert any(item.get("public_document_id") == done["artifact_document_id"]
                   for item in result["result"]["evidence"])
        follow = post(base + "/experiments", {
            "title": "合成后续对照", "task_or_ability": "比较请求标识条件",
            "deliverable": "两组记录", "completion_check": "核对相同输入的写入次数",
            "previous_task_id": task["id"], "design_change": "只改变标识去重，其他条件不变。",
        })["tasks"][-1]
        assert follow["target_requirement"] == selected
        assert follow["source_step_id"] == row["step_id"]
        refreshed = run_stage(client, identity, auth, "role")
        assert refreshed["requirements"][0]["key"] != key
        assert refreshed["tasks"][0]["target_requirement"]["key"] == key
        assert refreshed["tasks"][0]["target_requirement"]["missing"] == missing
