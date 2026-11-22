"""Other goals' experiment observations are recalled separately from current raw evidence."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.storage.database import upgrade

MARKER = "合成跨岗实验"
EXPECTATION = "旧场景中原先预期交付对象变化会影响检查步骤。" * 24 + "末尾预期：仍需受控对照。"
OBSERVATION = "合成用户观察：结果未匹配原先预期，条件尚未控制。" * 45 + (
    "末尾限定：只记录构造样例，不能证明真实业务因果或个人验收权限。"
)
LOG = "合成旧日志：构造样例的两组结果不同，未独立执行验证；真实业务权限未知。"


class OtherGoalExperimentModel(ModelClient):
    def __init__(self):
        self.last_usage, self.contexts = {}, []
        self.artifact_in_scope = False
        self.expected_revalidation = None
        self.expected_new_observation = None

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        if self.expected_revalidation:
            personal = context["project_context"]["career_evidence"]
            assert personal["selected_experiment_id"] == self.expected_revalidation
            current = next(row for row in personal["experiments"]
                           if row["id"] == self.expected_revalidation)
            assert current["purpose"] == "understanding_check"
            assert current["reported_observation"] == self.expected_new_observation
            assert current["template_origin"]["memory"]["reported_observation"] == OBSERVATION
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "search_other_goal_memory", {"terms": [MARKER], "offset": 0}
        elif len(outputs) == 1:
            found = outputs[0]["memories"]
            assert outputs[0]["matching_count"] == len(found) == 3
            assert all(row["kind"] == "experiment" for row in found)
            rows = {row["preview"]["state"]: row for row in found}
            assert rows["done"]["preview"]["preview_is_partial"]
            assert rows["doing"]["preview"]["has_reported_observation"]
            assert not rows["planned"]["preview"]["has_reported_observation"]
            name, args = "read_other_goal_memory", {key: rows["done"][key]
                                                    for key in ("project_id", "kind", "record_id")}
        elif len(outputs) == 2:
            record = outputs[-1]["memory"]
            assert record["reported_observation"] == OBSERVATION
            assert record["prior_expectation"] == EXPECTATION
            assert record["comparison_rows"][0]["observed"] == "构造样例未匹配预期。"
            assert "evidence" not in outputs[-1]
            artifact = record["artifact_document"]
            assert artifact["available_in_goal"] and (
                artifact["in_current_scope"] is self.artifact_in_scope
            )
            current = next(row["id"] for row in context["fixed_scope"]["public_document_titles"]
                           if row["title"].startswith("合成复验当前原文"))
            if not self.artifact_in_scope:
                assert artifact["document_id"] not in context["fixed_scope"]["archived_public_ids"]
            name, args = "read_archived_documents", {"reads": [
                {"document_id": key, "start": 0} for key in [current, *(
                    [artifact["document_id"]] if self.artifact_in_scope else []
                )]
            ]}
        else:
            evidence = outputs[-1]["evidence"]
            assert len({row["public_document_id"] for row in evidence}) == (
                2 if self.artifact_in_scope else 1
            )
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "inference",
                            "requirement": "unspecified",
                            "text": "旧实验记录可用于提出复验方向；当前资料未确认个人验收权限，"
                                    "旧场景的解释不能直接外推。",
                            "evidence_ids": [row["id"] for row in evidence]}],
                "gaps": ["日志已回读但仍是用户提供记录，尚未独立运行或核实真实业务。"]
                if self.artifact_in_scope else ["旧日志不在本轮范围，尚未重新核对。"],
            }
            project = context["project_context"]
            if project.get("previous_findings") or project.get("historical_reply"):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_other_goal_experiment_memory_keeps_original_observations_and_log_scope(tmp_path):
    database = tmp_path / "other-goal-experiments.db"
    upgrade(database)
    model = OtherGoalExperimentModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]}

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        source = save("/api/career", {"title": "合成旧实验场景", "goal": "记录失败与未知"})
        base = "/api/career/" + source["id"]
        design = {"task_or_ability": "核对不同对象下的检查步骤", "deliverable": "构造对照记录",
                  "completion_check": "记录实际差异，不从状态推断能力或成功。",
                  "hypothesis": EXPECTATION, "comparison_rows": [
                      {"condition": "仅改变对象", "input": "构造样例", "expected": "检查不变",
                       "observed": ""},
                  ]}
        for index, state in enumerate(("done", "doing", "planned")):
            task = save(base + "/experiments", {
                **design, "title": MARKER + str(index),
            })["tasks"][-1]
            if state != "planned":
                updated = save(base + "/tasks/" + task["id"], {
                    "state": state, "outcome": OBSERVATION if state == "done" else "",
                    "comparison_rows": [{**design["comparison_rows"][0],
                                         "observed": "构造样例未匹配预期。"}],
                    "artifact_title": "合成旧实验日志",
                    "artifact_text": LOG if state == "done" else "",
                }, "patch")
                if state == "done":
                    completed = next(row for row in updated["tasks"] if row["id"] == task["id"])
        old_log = completed["artifact_document_id"]
        before = client.get(base).json()
        target = save("/api/career", {"title": "合成新工作下的复验", "goal": "核对旧观察能否迁移",
                      "material_title": "合成复验当前原文",
                      "material_text": "当前场景的工作对象不同，个人验收权限未明确。"})
        target_base = "/api/career/" + target["id"]
        study = run_stage(
            client, target["id"], auth, "ask", question="合成跨目标实验复验：参考" + MARKER + "。",
        )["results"][0]
        result = study["result"]
        assert result["status"] == "completed", result["stop_reason"]
        assert result["model_calls"] == 4
        read = result["career_learning_context"]["read_other_goals"][0]
        assert read["kind"] == "experiment"
        assert read["memory"]["reported_observation"] == OBSERVATION
        assert {row["public_document_id"] for row in result["evidence"]} == {
            target["materials"][0]["id"],
        }
        after = client.get(target_base).json()
        assert after["document_ids"] == target["document_ids"] and not after["tasks"]
        assert client.get(base).json() == before
        template = {"title": "在新场景重新核对条件", "task_or_ability": "核对不同对象",
                    "deliverable": "新场景记录", "completion_check": "比较同条件下的观察",
                    "hypothesis": EXPECTATION, "source_step_id": study["step_id"],
                    "source_experiment_id": read["record_id"],
                    "design_change": "把工作对象替换为新场景，保留同样的检查方法。",
                    "comparison_rows": design["comparison_rows"]}
        calls = len(model.contexts)
        for invalid in [{"source_step_id": None}, {"source_experiment_id": "0" * 32},
                        {"design_change": ""}]:
            rejected = client.post(target_base + "/experiments", headers=auth,
                                   json={**template, **invalid})
            assert rejected.status_code == 422, rejected.text
        assert client.get(target_base).json() == after and len(model.contexts) == calls
        planned = save(target_base + "/experiments", template)
        new_task = planned["tasks"][-1]
        assert new_task["state"] == "planned" and not new_task["outcome"]
        assert new_task["purpose"] == "understanding_check"
        assert not new_task.get("artifact_document_id") and not new_task["evidence_ids"]
        assert all(not row["observed"] for row in new_task["comparison_rows"])
        assert planned["document_ids"] == target["document_ids"]
        assert planned["results"] == after["results"] and len(model.contexts) == calls
        new_observation = "新场景用户记录：改变对象后检查步骤也需调整，真实权限仍未知。"
        save(target_base + "/tasks/" + new_task["id"], {
            "state": "done", "outcome": new_observation,
        }, "patch")
        next_task = save(target_base + "/experiments", {
            **{key: value for key, value in template.items()
               if key not in {"source_step_id", "source_experiment_id"}},
            "previous_task_id": new_task["id"],
        })["tasks"][-1]
        assert next_task["source_experiment_id"] == read["record_id"]
        assert next_task["source_step_id"] == study["step_id"] and not next_task["outcome"]
        assert client.get(base).json() == before
        save(target_base + "/materials/attach", {"document_id": old_log})
        model.artifact_in_scope = True
        model.expected_revalidation = new_task["id"]
        model.expected_new_observation = new_observation
        reread = run_stage(client, target["id"], auth, "ask",
                           question="合成跨目标实验复验：重读选入的旧日志。",
                           task_id=new_task["id"])["results"][0]["result"]
        assert reread["status"] == "completed", reread["stop_reason"]
        assert {row["public_document_id"] for row in reread["evidence"]} == {
            target["materials"][0]["id"], old_log,
        }
        assert any(LOG in row["quote"] for row in reread["evidence"])
        assert client.get(base).json() == before
        assert not before["results"]  # This source goal never ran model research.
        erased = client.delete("/api/projects/" + source["id"], headers=auth)
        assert erased.status_code == 200, erased.text
        assert target["id"] in erased.json()["affected_project_ids"]
        cleared = client.get("/api/projects/" + target["id"]).json()
        assert not cleared.get("career") and not cleared["steps"]


def test_other_goal_experiment_can_be_found_by_its_original_explanation():
    answer = "当时的限定。" * 250 + "原先解释中的特殊线索：尚未实际验证。"
    task = {"id": "old-experiment", "source_step_id": "answer", "title": "条件验证",
            "task_or_ability": "核对条件", "deliverable": "观察记录",
            "completion_check": "核对差异",
            "state": "doing", "created_at": "2026-11-22T00:00:00Z", "comparison_rows": [
                {"condition": "部分记录", "input": "样例", "expected": "原预期",
                 "observed": "有差异"},
            ]}
    source = {"id": "source", "title": "原场景", "goal": "解释不同条件", "steps": [],
              "career": {"tasks": [task], "runs": [{"step_id": "answer", "kind": "answer",
                          "interview_question": "为什么需要核对边界？", "answer": answer}]}}
    notebook = LearningNotebook(lambda: {"id": "current"}, None,
                                project_lister=lambda: [source])
    found = notebook.search_other_goal_memory(["特殊线索"])["memories"]
    assert len(found) == 1 and found[0]["kind"] == "experiment"
    assert found[0]["preview"]["has_reported_observation"]
    recalled = notebook.read_other_goal_memory("source", "experiment", "old-experiment")["memory"]
    assert recalled["answer_to_verify"]["user_answer"] == answer
    assert recalled["reported_observation"] == ""  # The observation is in the condition row.
