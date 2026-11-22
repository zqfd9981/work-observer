import re

from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace
from test_requirement_interview import RequirementInterviewModel


def test_jd_context_experiment_saves_actual_output_then_becomes_interview_material(tmp_path):
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
            "title": "合成上下文岗位" + str(i), "company": "合成团队" + str(i),
            "description": text, "data_kind": "synthetic",
        })["job_id"] for i, text in enumerate([
            "可选专攻方向之一：上下文工程与记忆，负责端云同步上下文管理。",
            "其他工作：评估检索结果。",
        ])]
        goal = post("/api/career", {
            "title": "合成端云上下文理解", "goal": "先构造样例检查合并行为和仍未知的条件",
            "job_ids": jobs, "material_title": "不应混入的资料", "material_text": "其他任务笔记。",
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
        inquiry = post(base + "/questions", {
            "requirement_key": point["key"], "question": "只存聊天是否就能做好上下文同步？",
        })["questions"][-1]
        values = {"question_id": inquiry["id"], "hypothesis": "先检查同编号冲突会怎样。",
                  "cases": [{"name": "冲突与副本", "edge": [
                      {"key": "m1", "value": "查充电站"}, {"key": "m2", "value": "相同内容"}],
                      "cloud": [{"key": "m1", "value": "查停车场"},
                                {"key": "m2", "value": "相同内容"}]}]}
        calls = len(model.contexts)
        preview = post(base + "/experiments/context", values)
        assert not client.get(base).json()["tasks"] and len(model.contexts) == calls
        saved = post(base + "/experiments/context", {**values, "save": True})
        experiment = saved["experiment"]
        task = saved["career"]["tasks"][-1]
        assert experiment == preview["experiment"] and len(model.contexts) == calls
        assert task["target_requirement"] == inquiry["target_requirement"]
        assert task["state"] == "done" and task["local_experiment"] == "context_merge"
        assert experiment["cases"][0]["folded_copies"] == 1
        assert experiment["cases"][0]["conflicting_keys"] == ["m1"]
        log = client.get("/api/public-documents/" + task["artifact_document_id"]).json()["text"]
        assert "查充电站" in log and "查停车场" in log and "冲突内容全部保留待核对" in log
        assert "可选专攻方向之一" in log
        assert values["hypothesis"] in log
        model.selected_job = jobs[1]
        run({"kind": "role"})
        another = client.get(base).json()["requirements"][0]
        mismatched = client.post(base + "/experiments/context", headers=auth, json={
            **values, "requirement_key": another["key"], "save": True,
        })
        assert mismatched.status_code == 422 and "沿用" in mismatched.text
        model.selected_job = jobs[0]
        for kind in ("reflect", "interview"):
            row = run({"kind": kind, "task_id": task["id"]})
            assert row["result"]["career_learning_context"]["requirement"] == (
                inquiry["target_requirement"]
            )
            assert row["result"]["scope"]["archived_public_ids"] == [task["artifact_document_id"]]
        invalid = client.post(base + "/experiments/context", headers=auth,
                              json={**values, "requirement_key": "missing", "save": True})
        assert invalid.status_code == 422 and len(client.get(base).json()["tasks"]) == 1
        oversized = {"cases": [{"name": str(i), "edge": [
            {"key": str(j) + "k" * 55, "value": "\\" * 500} for j in range(8)
        ], "cloud": []} for i in range(4)], "save": True}
        too_long = client.post(base + "/experiments/context", headers=auth, json=oversized)
        assert too_long.status_code == 422 and "运行记录过长" in too_long.text
        assert len(client.get(base).json()["tasks"]) == 1
