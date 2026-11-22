"""One compound question can lead to a user-authored note and an unrun test plan."""

import json
from copy import deepcopy

from starlette.testclient import TestClient
from test_adaptive_investigation import ScriptedPlanner, brief, prepare, settled, task, workspace

from work_observer.research.learning import LearningNotebook, learning_record
from work_observer.research.store import ResearchStore


def test_two_practice_requests_keep_their_own_actions_citations_and_saved_origins(tmp_path):
    class TwoPracticePlanner(ScriptedPlanner):
        async def turn(self, history):
            response, raw = await super().turn(history)
            call = response[0]
            if call["name"] == "finish_research":
                arguments = json.loads(call["arguments"])
                plan = arguments["application_plan"]
                evidence = next(json.loads(row["output"])["evidence"] for row in history
                                if row.get("type") == "function_call_output"
                                and json.loads(row["output"]).get("engine") == "langgraph")
                by_job = {row["job_id"]: row["citation_key"] for row in evidence}
                first = deepcopy(plan["actions"][0])
                second = deepcopy(first)
                # Deliberately reverse action order to prove bindings do not rely on position.
                first.update(title="合成重复请求对照", evidence_ids=[by_job[self.jobs[1]]])
                second.update(title="合成失败输入对照", evidence_ids=[by_job[self.jobs[0]]])
                plan["actions"] = [first, second]
                for i, outcome in enumerate(arguments["task_outcomes"]):
                    outcome.update(action_indices=[1 - i], claim_indices=[])
                call["arguments"] = json.dumps(arguments)
            return response, raw

    model = TwoPracticePlanner(brief([
        task("practice", question="如何用构造输入检查失败处理？"),
        task("practice", question="如何用重复请求检查幂等性？"),
    ]), produce_plan=True)
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, jobs = prepare(client, "分别为这两份JD设计一个最小验证")
        model.jobs = jobs
        for i, item in enumerate(model.plan["tasks"]):
            item["source_job_ids"] = [jobs[i]]
        response = client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        assert response.status_code == 202, response.text
        data = settled(client, base)
        result = data["results"][0]["result"]
        assert result["status"] == "completed", result
        assert [row["action_indices"] for row in result["investigation"]["outcomes"]] == [[1], [0]]
        assert not data["tasks"]  # Suggestions have not been selected or executed.
        saved = client.post(base + "/tasks", headers=auth, json={
            "step_id": step, "action_indices": [0, 1],
        })
        assert saved.status_code == 200, saved.text
        tasks = saved.json()["tasks"]
        assert [(row["title"], row["source_task_index"]) for row in tasks] == [
            ("合成重复请求对照", 1), ("合成失败输入对照", 0),
        ]
        assert all(row["state"] == "planned" and not row["outcome"] for row in tasks)
        assert all(not case["observed"] for row in tasks for case in row["comparison_rows"])
        record = client.get("/api/projects/" + goal).json()
        store = ResearchStore(tmp_path / "checkpoints.db",
                              namespace=str((tmp_path / "adaptive.db").resolve()))
        try:
            read = LearningNotebook(lambda: record, store).read_experiments(
                [row["id"] for row in tasks],
            )["experiments"]
            for experiment, source_index in zip(read, [1, 0], strict=True):
                context = experiment["task_to_verify"]
                assert context["task_index"] == source_index
                assert len(context["suggested_actions"]) == 1
                assert {row["job_id"] for row in context["evidence"]} == {jobs[source_index]}
        finally:
            store.close()


def test_selected_task_note_plan_observation_and_next_test_keep_their_source(tmp_path):
    plan = brief([
        task(question="具体要做什么工作？"), task("practice", question="怎么检验这个解释？"),
    ])
    model = ScriptedPlanner(plan, produce_plan=True)
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, _ = prepare(client, "解释工作，再给我一个可以检验理解的小练习")
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        data = settled(client, base)
        result = data["results"][0]["result"]
        assert result["status"] == "completed", result
        assert not data["tasks"] and not data["insights"]
        assert result["application_plan"]["purpose"] == "understanding_check"
        assert not model.contexts[0]["application_background"]["background"]
        calls = len(model.contexts)

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        note_data = {
            "previous_view": "我原来只把它理解为写接口。", "observation": "我回看了两份任务描述。",
            "current_view": "还需要解释测试工作，但责任边界仍未知。",
            "open_question": "哪些结果能挑战解释？",
            "source_step_id": step, "source_task_index": 0,
        }
        note = save(base + "/insights", note_data)["insights"][0]
        assert note["source_task_index"] == 0 and note["current_view"] == note_data["current_view"]
        response = client.post(base + "/insights", headers=auth, json={
            **note_data, "source_claim_index": 0,
        })
        assert response.status_code == 422
        assert client.post(base + "/insights", headers=auth, json={
            **note_data, "source_task_index": 2,
        }).status_code == 422
        practice = {
            "title": "自己设计的反例检查", "task_or_ability": "检查任务解释的适用条件",
            "hypothesis": "改变输入可能挑战解释，尚未执行。", "deliverable": "输入与观察表",
            "completion_check": "记录支持与不支持两种情况。", "source_step_id": step,
            "source_task_index": 1,
        }
        manual = save(base + "/experiments", practice)["tasks"][-1]
        assert manual["purpose"] == "understanding_check"
        assert manual["state"] == "planned" and not manual["outcome"]
        imported = save(base + "/tasks", {"step_id": step, "action_indices": [0]})["tasks"][-1]
        assert imported["source_step_id"] == step and imported["source_task_index"] == 1
        assert imported["state"] == "planned" and not imported["outcome"]
        assert all(not row["observed"] for row in imported["comparison_rows"])
        rows = [{**row, "observed": "仍出现重复" if i == 0 else ""}
                for i, row in enumerate(imported["comparison_rows"])]
        save(base + "/tasks/" + imported["id"], {
            "state": "done", "outcome": "只观察一组，仍出现重复，其他条件尚未尝试。",
            "comparison_rows": rows,
        }, "patch")
        follow = save(base + "/experiments", {
            **{key: value for key, value in practice.items() if not key.startswith("source_")},
            "previous_task_id": imported["id"], "design_change": "另查尚未尝试的条件。",
        })["tasks"][-1]
        assert follow["source_task_index"] == 1 and follow["source_step_id"] == step
        assert not follow["outcome"] and follow["state"] == "planned"
        record = client.get("/api/projects/" + goal).json()
        store = ResearchStore(tmp_path / "checkpoints.db",
                              namespace=str((tmp_path / "adaptive.db").resolve()))
        try:
            recalled = learning_record(note, record, store)
            origin = recalled["source_investigation_task"]
            assert origin["task_index"] == 0 and origin["task"]["question"] == "具体要做什么工作？"
            assert origin["outcome"]["answer"] == result["investigation"]["outcomes"][0]["answer"]
            assert origin["evidence"]
            experiment = LearningNotebook(lambda: record, store).read_experiments([follow["id"]])[
                "experiments"
            ][0]
            assert experiment["task_to_verify"]["task_index"] == 1
            assert experiment["task_to_verify"]["suggested_actions"]
            assert not experiment["reported_observation"]
        finally:
            store.close()
        assert len(model.contexts) == calls  # Recording and selecting plans do not run a model.
