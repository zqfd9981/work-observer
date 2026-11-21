"""Question-only onboarding can lead to a source-grounded learning experiment."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class LearningExperimentModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        project = context["project_context"]
        personal = project["career_evidence"]
        inquiry = personal["selected_inquiry"]
        assert inquiry and "理解验证" in inquiry["question"]
        selected = [row["document_id"] for row in personal["selected_materials"]]
        experiment = next(
            (
                row
                for row in personal.get("experiments", [])
                if row["id"] == personal.get("selected_experiment_id")
            ),
            {},
        )
        artifact = (experiment.get("artifact_document") or {}).get("document_id")
        if artifact:
            selected.append(artifact)
        assert selected
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = (
                "read_archived_documents",
                {
                    "reads": [{"document_id": key, "start": 0} for key in dict.fromkeys(selected)],
                },
            )
        else:
            evidence = outputs[0]["evidence"]
            assert {row["public_document_id"] for row in evidence} == set(selected)
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "business",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": row["quote"],
                            "evidence_ids": [row["id"]],
                        }
                        for row in evidence
                    ],
                    "gaps": ["只读了用户提供的记录，未独立运行；不能证明个人能力或生产效果。"],
                },
            )
            if project.get("previous_findings") or project.get("historical_reply"):
                args["revisions"] = []
            if project["career_action"] == "plan":
                background = context["application_background"]
                assert background["background"] == ""
                assert background["purpose"] == "understanding_check"
                assert "合成案例" in history[0]["content"]
                args["application_plan"] = {
                    "background_memory_id": background["memory_id"],
                    "actions": [
                        {
                            "title": "合成重复请求对照",
                            "task_or_ability": "检验重复回填的解释",
                            "deliverable": "三组输入与对应账本记录",
                            "completion_check": ("相同请求编号提交两次，再改变编号；"
                                "逐次记录新增行数。"),
                            "hypothesis": ("相同编号的第二次提交不会重复回填；"
                                "不同编号仍应产生新记录。"),
                            "evidence_ids": [evidence[0]["id"]],
                            "assumptions": ["仅用本地合成表格，不需要企业数据或账号"],
                        }
                    ],
                    "open_questions": ["真实系统中的并发与权限仍未知。"],
                }
            else:
                assert "application_background" not in context
                assert experiment["reported_observation"] and artifact
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_question_only_learning_experiment_returns_observation_after_reopen(tmp_path):
    database = tmp_path / "learning-experiment.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = LearningExperimentModel()

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        created = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成理解验证",
                "goal": "检验重复回填的解释",
                "first_question": "合成理解验证：同一请求的重复提交是否会重复回填？",
                "material_title": "合成回填说明",
                "material_text": ("按请求编号核对回填记录，交付差异清单；"
                    "重复请求应避免重复回填。并发行为未说明。"),
            },
        ).json()
        identity, question = created["id"], created["questions"][0]
        source = created["materials"][0]["id"]
        assert created["profile"] is None and not created["results"]
        planned = run_stage(client, identity, auth, "plan", question_id=question["id"])
        row = planned["results"][0]
        assert row["result"]["status"] == "completed"
        plan = row["result"]["application_plan"]
        assert plan["purpose"] == "understanding_check" and len(plan["actions"]) == 1
        assert {ev["public_document_id"] for ev in row["result"]["evidence"]} == {source}
        imported = client.post(
            f"/api/career/{identity}/tasks", headers=auth, json={"step_id": row["step_id"]}
        )
        assert imported.status_code == 200, imported.text
        task = imported.json()["tasks"][0]
        assert task["question_id"] == question["id"] and task["state"] == "planned"
        assert task["purpose"] == "understanding_check" and not task["outcome"]
        outcome = "合成表格观察：同编号第二次提交仍新增一行，原先预期未得到支持。"
        updated = client.patch(
            f"/api/career/{identity}/tasks/{task['id']}",
            headers=auth,
            json={
                "state": "done",
                "outcome": outcome,
                "artifact": "本地合成表格",
                "artifact_title": "合成重复提交记录",
                "artifact_text": ("输入编号A两次，账本行数依次1、2；"
                    "编号B一次后为3。末尾限定：未测试并发，也未独立运行。"),
            },
        )
        assert updated.status_code == 200, updated.text
        stored = updated.json()["tasks"][0]

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        reopened = client.get(f"/api/career/{identity}").json()
        assert reopened["profile"] is None and reopened["tasks"][0] == stored
        reviewed = run_stage(
            client,
            identity,
            auth,
            "ask",
            question_id=question["id"],
            task_id=task["id"],
            question="对照实际观察，哪些解释仍成立？",
        )
        result = reviewed["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert {ev["public_document_id"] for ev in result["evidence"]} == {
            source,
            stored["artifact_document_id"],
        }
        assert any("未测试并发" in ev["quote"] for ev in result["evidence"])
        assert reviewed["questions"][0] == question and reviewed["tasks"][0] == stored
        assert reviewed["profile"] is None and len(model.contexts) == 4
