"""A personal relation explanation stays a hypothesis and survives later edits to its inquiry."""

import json
import re

from starlette.testclient import TestClient
from test_career_work_relations import RelationsBrowserModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

EXPLANATION = (
    "我把这条联系理解为核对具体业务账本，形成差异清单；工具使用本身不能替代业务口径。🤔" * 18
    + "末尾限定：这仍是个人理解，尚未明确真实验收权限。"
)
UNKNOWN = "换一种业务对象后，哪些交付和验收条件必须重新核对？"


class RelationExplanationModel(ModelClient):
    def __init__(self):
        self.initial = RelationsBrowserModel()
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        if context["project_context"]["career_action"] == "map":
            self.initial.tools = self.tools
            return await self.initial.turn(history)
        personal = context["project_context"]["career_evidence"]
        inquiry = personal["selected_inquiry"]
        assert inquiry["conclusion"] == EXPLANATION and inquiry["state"] == "open"
        assert inquiry["next_evidence"] == UNKNOWN
        assert inquiry["origin_discussion"]["work_map"]["work_relations"][0][
            "source_text"
        ] == "核对退款请求与回填账本"
        selected = personal["selected_materials"]
        assert len(selected) == 1
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_archived_document", {
                "document_id": selected[0]["document_id"], "start": 0,
            }
        else:
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "inference", "requirement": "unspecified",
                            "text": "合成原文将核对账本与差异清单放在同一条工作线上；"
                                    "个人解释保留了业务口径这一条件，但真实验收权限仍未知。",
                            "evidence_ids": [row["id"] for row in outputs[0]["evidence"]]}],
                "gaps": [UNKNOWN, "若改成另一类账本，什么观察能检验这条联系是否仍成立？"],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_feedback_retains_original_personal_explanation_when_the_inquiry_changes(tmp_path):
    database = tmp_path / "explanation.db"
    upgrade(database)
    model = RelationExplanationModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = post("/api/career", {"title": "合成关系解释练习", "goal": "先解释，再回读原文"})
        base = "/api/career/" + goal["id"]
        sources = []
        for label, task, deliverable in (
            ("A", "核对退款请求与回填账本", "差异清单"),
            ("B", "维护异步回填执行器与超时追踪", "执行记录和故障说明"),
        ):
            saved = post(base + "/materials", {
                "title": "合成解释练习原文" + label,
                "text": f"任务：{task}。交付：{deliverable}。验收权仍未知。",
            })
            sources.append(saved["materials"][-1]["id"])
        mapped = run_stage(client, goal["id"], auth, "map", material_ids=sources,
                           question="合成关系库长页：分别核对任务与交付物。")
        original = mapped["results"][0]
        assert original["result"]["status"] == "completed"
        calls = len(model.contexts)
        payload = {
            "question": "请核对我对原地图第1条工作关系的解释。", "state": "open",
            "conclusion": EXPLANATION, "next_evidence": UNKNOWN,
            "source_step_id": original["step_id"], "material_ids": [sources[0]],
        }
        created = post(base + "/questions", payload)
        question = created["questions"][-1]
        assert len(model.contexts) == calls and question["conclusion"] == EXPLANATION
        assert not created["tasks"] and not created["insights"]
        reviewed = run_stage(client, goal["id"], auth, "ask", question_id=question["id"],
                             question="根据原文，反馈我保存的解释，保留未明确条件。")
        result = reviewed["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        snapshot = result["career_learning_context"]["inquiry_at_start"]
        assert snapshot["id"] == question["id"] and snapshot["conclusion"] == EXPLANATION
        assert snapshot["source_step_id"] == original["step_id"]
        assert {row["public_document_id"] for row in result["evidence"]} == {sources[0]}
        assert reviewed["questions"] == created["questions"] and not reviewed["insights"]
        changed = client.patch(base + "/questions/" + question["id"], headers=auth, json={
            **payload, "conclusion": "后来修订的个人解释，仍需核对。",
        })
        assert changed.status_code == 200, changed.text
        final = changed.json()
        assert final["questions"][-1]["conclusion"] != EXPLANATION
        assert final["results"][0]["result"]["career_learning_context"]["inquiry_at_start"] == (
            snapshot
        )
        old = next(row for row in final["results"] if row["step_id"] == original["step_id"])
        assert old["result"]["work_map"] == original["result"]["work_map"]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        restored = client.get(base).json()["results"][0]["result"]
        assert restored["career_learning_context"]["inquiry_at_start"] == snapshot
