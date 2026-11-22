import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace
from test_requirement_interview import RequirementInterviewModel

from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore


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
        original_run = deepcopy(task["context_run"])
        assert original_run["cases"] == experiment["cases"]
        assert "artifact_text" not in original_run and "target_requirement" not in original_run
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
        edited = client.patch(base + "/tasks/" + task["id"], headers=auth, json={
            "state": "done", "outcome": "后来补写的总结，不替换本机原始计算。",
            "hypothesis": "后来修改的预期。",
        })
        assert edited.status_code == 200, edited.text
        assert edited.json()["tasks"][-1]["context_run"] == original_run
        changed = deepcopy(values)
        changed.pop("question_id")
        changed["cases"][0]["cloud"][0]["value"] = "查充电站"
        changed.update(previous_task_id=task["id"], design_change="只把m1两端内容改成相同。")
        calls = len(model.contexts)
        next_preview = post(base + "/experiments/context", changed)
        child_saved = post(base + "/experiments/context", {**changed, "save": True})
        child = child_saved["career"]["tasks"][-1]
        assert next_preview["experiment"] == child_saved["experiment"]
        assert len(model.contexts) == calls
        assert child["previous_task_id"] == task["id"] and child["question_id"] == inquiry["id"]
        assert child["target_requirement"] == task["target_requirement"]
        assert child["context_run"]["cases"][0]["conflicting_keys"] == []
        assert child["context_run"]["cases"][0]["folded_copies"] == 2
        assert "context_run" not in child["context_run"]
        parent = next(row for row in child_saved["career"]["tasks"] if row["id"] == task["id"])
        assert parent["context_run"] == original_run
        note = post(base + "/insights", {
            "task_id": child["id"], "question_id": inquiry["id"],
            "previous_view": "以为冲突消失就说明同步处理正确。",
            "observation": "只把构造输入改为相同内容后，冲突没有再出现。",
            "current_view": "结果只说明所给输入下的行为，还需另查真实同步条件。",
        })["insights"][-1]
        project = client.get("/api/projects/" + goal["id"]).json()
        store = ResearchStore(tmp_path / "checkpoints.db",
                              namespace=str((tmp_path / "adaptive.db").resolve()))
        try:
            remembered = LearningNotebook(lambda: project, store).read(note["id"])["note"]
            assert "context_run" not in remembered["linked_experiment"]
            assert remembered["linked_experiment"]["artifact_document_id"] == (
                child["artifact_document_id"]
            )
        finally:
            store.close()
        wrong_origin = client.post(base + "/experiments/context", headers=auth, json={
            **changed, "requirement_key": another["key"], "save": True,
        })
        assert wrong_origin.status_code == 422 and "原岗位工作" in wrong_origin.text
        invalid = client.post(base + "/experiments/context", headers=auth,
                              json={**values, "requirement_key": "missing", "save": True})
        assert invalid.status_code == 422 and len(client.get(base).json()["tasks"]) == 2
        oversized = {"cases": [{"name": str(i), "edge": [
            {"key": str(j) + "k" * 55, "value": "\\" * 500} for j in range(8)
        ], "cloud": []} for i in range(4)], "save": True}
        too_long = client.post(base + "/experiments/context", headers=auth, json=oversized)
        assert too_long.status_code == 422 and "运行记录过长" in too_long.text
        assert len(client.get(base).json()["tasks"]) == 2
