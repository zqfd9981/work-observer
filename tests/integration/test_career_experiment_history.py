"""Research can find older experiments and compare complete records with archived logs."""

import json
import re

import pytest
from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.storage.database import upgrade


class ExperimentHistoryModel(ModelClient):
    """Local tool script: search both pages, read old records, then read their logs."""

    def __init__(self, long_logs=False):
        self.contexts, self.last_usage = [], {}
        self.long_logs = long_logs

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if len(outputs) < 2:
            if outputs:
                assert outputs[0]["next_offset"] == 6
            name, args = "search_experiments", {
                "terms": ["幂等键"], "offset": 6 if outputs else 0,
                "question_id": personal["selected_inquiry"]["id"],
            }
        elif len(outputs) == 2:
            rows = [row for output in outputs for row in output["experiments"]]
            selected = [row for row in rows if row["title"] in {
                "合成历史：幂等键基线", "合成历史：幂等键条件对照",
            }]
            assert len(selected) == 2 and outputs[-1]["next_offset"] is None
            assert not {row["id"] for row in selected} & {
                row["id"] for row in personal["experiments"]
            }
            assert all(row["preview_is_partial"] for row in selected)
            name, args = "read_experiments", {"experiment_ids": [row["id"] for row in selected]}
        elif len(outputs) == 3:
            rows = outputs[-1]["experiments"]
            assert "evidence" not in outputs[-1]
            assert all(row["reported_observation"].endswith("末尾条件：并发未控制，不能外推生产。")
                       for row in rows)
            assert all(row["prior_expectation"].endswith("末尾预期：仍需对照。") for row in rows)
            assert all(row["proposed_check"].endswith("末尾检查：保留失败。") for row in rows)
            assert all(row["artifact_document"]["in_current_scope"] for row in rows)
            name, args = "read_archived_documents", {"reads": [
                {"document_id": row["artifact_document"]["document_id"], "start": 0}
                for row in rows
            ]}
        elif any(row["has_more"] for row in outputs[-1].get("windows", [])):
            name, args = "read_archived_documents", {"reads": [
                {"document_id": row["document_id"], "start": row["next_start"]}
                for row in outputs[-1]["windows"] if row["has_more"]
            ]}
        else:
            evidence = outputs[-1]["evidence"]
            assert len({row["public_document_id"] for row in evidence}) == 2
            if self.long_logs:
                assert all("实际记录末尾：write=2；并发未控制，不能外推生产。" in "".join(
                    row["quote"] for row in evidence if row["public_document_id"] == key
                ) for key in {row["public_document_id"] for row in evidence})
            name, args = "finish_research", {
                "claims": [{"category": "business", "basis": "inference",
                            "requirement": "unspecified", "text":
                            "合成日志记载两组局部观察，不能仅凭记录确定生产原因；并发条件仍未控制。",
                            "evidence_ids": [row["id"] for row in evidence]}],
                "gaps": ["用户记录不是独立运行，仍需受控对照。"],
            }
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


@pytest.mark.parametrize("extra_materials", [0, 24])
def test_older_experiments_can_be_found_read_and_rechecked_after_reopening(
    tmp_path, extra_materials,
):
    database = tmp_path / "experiments.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = ExperimentHistoryModel(long_logs=bool(extra_materials))

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def save(path, payload, method="post"):
            response = getattr(client, method)(path, headers=auth, json=payload)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成：回查较早实验", "goal": "从旧观察继续修正理解",
                    "material_title": "合成工作说明", "material_text": "记录请求标识和观察条件。"})
        identity = goal["id"]
        base = "/api/career/" + identity
        inquiry = save(base + "/questions", {"question": "幂等键是否足以解释两组观察？"})[
            "questions"][0]
        other = save(base + "/questions", {"question": "另一项未相关的合成调查"})["questions"][-1]
        tasks = []
        for index in range(9):
            title = ["幂等键基线", "幂等键条件对照"][index] if index < 2 else f"幂等键补充{index}"
            task = save(base + "/experiments", {
                "title": "合成历史：" + title, "question_id":
                other["id"] if index == 8 else inquiry["id"],
                "task_or_ability": "比较请求标识与失败观察", "deliverable": "合成运行记录",
                "completion_check": "检查输入条件。" * 50 + "末尾检查：保留失败。",
                "hypothesis": "原先预计局部条件会影响结果。" * 30 + "末尾预期：仍需对照。",
            })["tasks"][-1]
            outcome = ("合成观察：记录失败与未受控条件。" * 50
                       + "末尾条件：并发未控制，不能外推生产。")
            save(base + "/tasks/" + task["id"], {
                "state": "done", "outcome": outcome, "artifact": "用户保存的合成日志",
                "artifact_title": "合成日志" + str(index),
                "artifact_text": f"合成情境{index}：write=2。并发未控制，未独立执行验证。"
                + ("中段记录。" * 1200 + "实际记录末尾：write=2；并发未控制，不能外推生产。"
                   if extra_materials and index < 2 else ""),
            }, "patch")
            tasks.append(task)
        for index in range(extra_materials):
            save(base + "/materials", {"title": f"合成后续说明{index}",
                        "text": "幂等键是否足以解释两组观察？合成实验历史复核："
                        "比较较早基线和条件对照，哪些判断仍需限制？"})
        before = client.get(base).json()
        assert not model.contexts

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        data = run_stage(client, identity, auth, "ask", question_id=inquiry["id"],
                         question="合成实验历史复核：比较较早基线和条件对照，哪些判断仍需限制？")
        result = data["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert result["model_calls"] == (6 if extra_materials else 5)
        if extra_materials:
            old_documents = {row["artifact_document_id"] for row in before["tasks"][:2]}
            initial_scope = model.contexts[0]["fixed_scope"]
            assert not old_documents & set(initial_scope["selected_public_document_ids"])
            shown = {row["id"] for row in initial_scope["public_document_titles"]}
            assert not old_documents & shown
            assert old_documents <= set(initial_scope["archived_public_ids"])
            assert all(row["artifact_document"]["found_via_experiment"]
                       for row in result["career_learning_context"]["read_experiments"])
        assert {row["name"] for row in model.tools} >= {"search_experiments", "read_experiments"}
        snapshot = result["career_learning_context"]
        assert len(snapshot["experiment_searches"]) == 2
        assert {row["id"] for row in snapshot["read_experiments"]} == {
            row["id"] for row in tasks[:2]
        }
        assert data["tasks"] == before["tasks"] and data["questions"] == before["questions"]
        assert not {row["id"] for row in tasks} & {ev["id"] for ev in result["evidence"]}
        original = next(row for row in before["tasks"] if row["id"] == tasks[0]["id"])
        save_data = {"state": "done", "outcome": "后来补充，不能改写当时读取的记录。",
                     "artifact": original["artifact"]}
        response = client.patch(base + "/tasks/" + original["id"], headers=auth, json=save_data)
        assert response.status_code == 200
        historical = client.get(base).json()["results"][0]["result"]["career_learning_context"]
        assert historical == snapshot


def test_experiment_notebook_keeps_goal_and_explicit_inquiry_scopes():
    task = {"id": "local", "title": "合成记录", "question_id": "q", "state": "planned",
            "created_at": "2026-11-21", "task_or_ability": "任务", "deliverable": "产物",
            "completion_check": "检查"}
    project = {"public_document_ids": ["local-log", "unrelated-material"], "career": {
        "tasks": [{**task, "artifact_document_id": "local-log"},
                  {**task, "id": "detached", "artifact_document_id": "detached-log"}],
        "questions": [{"id": "q", "question": "问题"}],
    }}
    notebook = LearningNotebook(lambda: project, None)
    assert notebook.experiment_document_ids() == ["local-log"]
    assert notebook.search_experiments([], question_id="q")["matching_count"] == 2
    assert not notebook.read_experiments(["local"])["experiments"][0]["reported_observation"]
    assert not notebook.read_experiments(["detached"])["experiments"][0][
        "artifact_document"]["available_in_goal"]
    with pytest.raises(ProbeError, match="EXPERIMENT_NOT_AVAILABLE"):
        notebook.read_experiments(["other-goal-task"])
    with pytest.raises(ProbeError, match="EXPERIMENT_INQUIRY_NOT_AVAILABLE"):
        notebook.search_experiments([], question_id="other-goal-inquiry")
    with pytest.raises(ProbeError, match="INVALID_EXPERIMENT_SELECTION"):
        notebook.read_experiments(["local", "local"])
