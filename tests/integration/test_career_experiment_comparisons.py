"""User-run condition comparisons remain distinct from expectations and source facts."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.storage.database import upgrade


class ComparisonExperimentModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        task = next(row for row in personal["experiments"]
                    if row["id"] == personal["selected_experiment_id"])
        rows = task["comparison_rows"]
        assert len(rows) == 3 and rows[0]["observed"] and not rows[2]["observed"]
        assert "末尾限定" in rows[1]["observed"]
        assert "未控制并发" in task["comparison_conditions"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_experiments", {"experiment_ids": [task["id"]]}
        elif len(outputs) == 1:
            assert outputs[0]["experiments"][0]["comparison_rows"] == rows
            source = personal["selected_materials"][0]["document_id"]
            name, args = "read_archived_document", {"document_id": source, "start": 0}
        else:
            evidence = outputs[1]["evidence"][0]
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "direct",
                            "requirement": "unspecified", "text": evidence["quote"],
                            "evidence_ids": [evidence["id"]]}],
                "gaps": ["两组观察由用户记录，未控制并发；第三组尚无结果，不能推定因果。"],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_condition_comparisons_survive_reopen_and_are_read_with_their_original_limits(tmp_path):
    database = tmp_path / "comparisons.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = ComparisonExperimentModel()

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        created = client.post("/api/career", headers=auth, json={
            "title": "合成条件对照", "goal": "检验重复回填的解释",
            "first_question": "合成条件对照调查：改变编号是否影响回填？",
            "material_title": "合成说明", "material_text": "按请求编号核对回填记录，交付差异清单。",
        }).json()
        identity, question = created["id"], created["questions"][0]
        base = f"/api/career/{identity}"
        rows = [{"condition": label, "input": inputs, "expected": expected, "observed": ""}
                for label, inputs, expected in (
                    ("相同编号", "同一编号提交两次", "第二次不增加"),
                    ("改变编号", "第二次改为新编号", "第二次增加一行"),
                    ("并发提交", "同时提交同一编号", "尚无预期"),
                )]
        conditions = "使用同一张合成表格，未控制并发与清理状态。"
        task = client.post(base + "/experiments", headers=auth, json={
            "title": "合成编号对照", "question_id": question["id"],
            "task_or_ability": "检验解释", "deliverable": "对照记录",
            "completion_check": "固定其他条件，记录不同编号的结果。",
            "comparison_conditions": conditions, "comparison_rows": rows,
        }).json()["tasks"][0]
        path = base + "/tasks/" + task["id"]
        assert task["comparison_rows"] == rows and task["comparison_conditions"] == conditions
        assert task["state"] == "planned" and not task["outcome"] and not model.contexts
        response = client.patch(path, headers=auth, json={
            "state": "planned", "comparison_rows": rows, "comparison_conditions": conditions,
        })
        assert response.status_code == 200, response.text
        assert response.json()["tasks"][0]["comparison_rows"] == rows
        assert not response.json()["tasks"][0]["outcome"] and not model.contexts
        bad = client.patch(path, headers=auth, json={"state": "done", "comparison_rows": rows})
        assert bad.status_code == 422 and not model.contexts
        bad = client.patch(path, headers=auth, json={
            "state": "planned", "comparison_rows": [{"condition": "", "observed": "观察"}],
        })
        assert bad.status_code == 422
        rows[0]["observed"] = "实际增加两行，与预期不同。"
        rows[1]["observed"] = "合成观察。" * 100 + "末尾限定：只检查了表格，真实系统未运行。"
        response = client.patch(path, headers=auth, json={
            "state": "done", "comparison_rows": rows,
        })
        assert response.status_code == 200, response.text
        stored = response.json()["tasks"][0]
        assert "2 组实际观察" in stored["outcome"]
        assert stored["comparison_conditions"] == conditions

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        reopened = client.get(base).json()
        assert reopened["tasks"][0] == stored and reopened["questions"][0] == question
        reviewed = run_stage(client, identity, auth, "ask", question_id=question["id"],
                             task_id=task["id"], question="逐组对照实际观察，哪些结论仍不能推出？")
        result = reviewed["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        snapshot = result["career_learning_context"]
        assert snapshot["comparison_inputs"][0]["comparison_rows"] == rows
        assert snapshot["read_experiments"][0]["comparison_rows"] == rows
        assert reviewed["tasks"][0] == stored and reviewed["questions"][0] == question
        client.patch(path, headers=auth, json={"state": "done", "outcome": "后来补充",
                                              "comparison_rows": []})
        later = client.get(base).json()
        assert later["tasks"][0]["comparison_rows"] == []
        assert later["results"][0]["result"]["career_learning_context"] == snapshot
        assert len(model.contexts) == 3

    project = {"career": {"tasks": [stored], "questions": [question]}}
    notebook = LearningNotebook(lambda: project, None)
    found = notebook.search_experiments(["清理状态"])
    assert found["matching_count"] == 1
    found = notebook.search_experiments(["真实系统未运行"])
    assert found["matching_count"] == 1
    assert notebook.read_experiments([task["id"]])["experiments"][0]["comparison_rows"] == rows
