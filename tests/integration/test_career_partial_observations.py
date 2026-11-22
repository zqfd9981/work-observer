"""A partially observed experiment can inform learning without being marked finished."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


class PartialObservationModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        experiment = next(
            row
            for row in personal["experiments"]
            if row["id"] == personal["selected_experiment_id"]
        )
        assert experiment["reported_observation"] == ""
        assert experiment["comparison_rows"][0]["observed"]
        assert experiment["comparison_rows"][1]["observed"] == ""
        document_id = experiment["artifact_document"]["document_id"]
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = "read_archived_document", {"document_id": document_id, "start": 0}
        else:
            evidence = outputs[0]["evidence"][0]
            assert evidence["public_document_id"] == document_id
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "business",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": evidence["quote"],
                            "evidence_ids": [evidence["id"]],
                        }
                    ],
                    "gaps": ["B组仍未观察，无整体结论；用户运行记录未经独立核验。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_partial_case_observations_support_reflection_followup_and_interview(tmp_path):
    database = tmp_path / "partial.db"
    upgrade(database)
    model = PartialObservationModel()  # Local scripted substitute, never a provider.
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model,
            checkpoint_path=tmp_path / "runs.db",
            reports_dir=tmp_path / "reports",
        ),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(
                r'name="wo-token" content="([^"]+)"',
                client.get("/").text,
            )[1]
        }

        def save(path, values, method="POST"):
            response = client.request(method, path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save(
            "/api/career",
            {
                "title": "合成局部观察",
                "goal": "分条件验证解释。",
                "first_question": "理解验证：同编号重试的局部失败，能否说明全部去重规则错误？",
                "material_title": "合成工作规则",
                "material_text": "同编号请求应避免重复记账。真实权限未知。",
                "background": "合成学习者，只记录本机样例。",
            },
        )
        base, qid = "/api/career/" + goal["id"], goal["questions"][0]["id"]
        plan = {
            "title": "合成两条件验证",
            "question_id": qid,
            "task_or_ability": "区分重复编号与改变编号",
            "deliverable": "输入与账本行数记录",
            "completion_check": "逐组比较预期与实际差异",
            "hypothesis": "同编号不应新增行。",
            "comparison_conditions": "合成空白账本；尚未测试并发。",
            "comparison_rows": [
                {
                    "condition": "重复编号",
                    "input": "提交A两次",
                    "expected": "只新增一行",
                    "observed": "",
                },
                {
                    "condition": "改变编号",
                    "input": "提交A和B",
                    "expected": "新增两行",
                    "observed": "",
                },
            ],
        }
        created = save(base + "/experiments", plan)
        task = created["tasks"][-1]
        rejected = client.post(
            base + "/prepare",
            headers=auth,
            json={
                "kind": "reflect",
                "task_id": task["id"],
            },
        )
        assert rejected.status_code == 422
        assert client.get(base).json() == created
        rows = deepcopy(plan["comparison_rows"])
        rows[0]["observed"] = "合成局部观察：同编号第二次仍新增行；还没测试改变编号。"
        partial = save(
            base + "/tasks/" + task["id"],
            {
                "state": "doing",
                "outcome": "",
                "comparison_rows": rows,
                "artifact_title": "合成局部运行记录",
                "artifact_text": "合成记录：A第一次后行数1；A第二次后行数2。未做B组，未测并发。",
            },
            method="PATCH",
        )["tasks"][-1]
        assert partial["state"] == "doing" and not partial["outcome"]
        assert not partial["comparison_rows"][1]["observed"]
        reviewed = run_stage(client, goal["id"], auth, "reflect", task_id=partial["id"])
        study = reviewed["results"][0]
        assert study["result"]["status"] == "completed", study["result"].get("stop_reason")
        assert reviewed["tasks"][-1] == partial
        context = model.contexts[-1]["project_context"]["career_evidence"]
        selected = next(row for row in context["experiments"] if row["id"] == partial["id"])
        assert selected["reported_observation"] == "" and selected["comparison_rows"] == rows
        calls = len(model.contexts)
        noted = save(
            base + "/insights",
            {
                "task_id": partial["id"],
                "question_id": qid,
                "previous_view": "原先以为相同编号一定不会新增行。",
                "observation": rows[0]["observed"],
                "current_view": "先保留同编号样例的反例；其他条件仍未观察。",
                "open_question": "改变编号后会发生什么？",
            },
        )
        note = noted["insights"][-1]
        project = client.get("/api/projects/" + goal["id"]).json()
        store = ResearchStore(tmp_path / "runs.db", namespace=str(database.resolve()))
        memory = LearningNotebook(lambda: project, store).read(note["id"])["note"]
        assert memory["linked_experiment"]["state"] == "doing"
        assert memory["linked_experiment"]["comparison_rows"] == rows
        next_task = save(
            base + "/experiments",
            {
                **plan,
                "title": "合成下一项验证",
                "previous_task_id": partial["id"],
                "hypothesis": "",
                "design_change": "补做改变编号的条件。",
            },
        )["tasks"][-1]
        assert next_task["previous_task_id"] == partial["id"]
        assert next_task["state"] == "planned" and not next_task["outcome"]
        assert all(not row["observed"] for row in next_task["comparison_rows"])
        assert client.get(base).json()["tasks"][0] == partial
        story = save(
            base + "/stories",
            {
                "title": "合成局部失败样例",
                "source_task_id": partial["id"],
                "situation": "在本机合成账本中验证一种条件。",
                "action": "提交相同编号两次。",
                "result": rows[0]["observed"],
                "limits": "B组尚未测试；不证明完整去重能力。",
            },
        )["stories"][-1]
        assert story["source_task_id"] == partial["id"]
        interview = save(base + "/prepare", {"kind": "interview", "task_id": partial["id"]})
        assert interview["step_id"] and len(model.contexts) == calls
        current = client.get(base).json()
        assert next(row for row in current["tasks"] if row["id"] == partial["id"]) == partial
        assert current["questions"][0]["state"] == "open"
