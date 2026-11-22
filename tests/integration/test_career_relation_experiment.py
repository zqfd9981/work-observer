"""A work-map relation can be tested with conditions and negative observations."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_work_relations import LIMIT, MATERIALS, RelationsBrowserModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.learning import LearningNotebook, learning_record
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


class RelationExperimentModel(RelationsBrowserModel):
    async def turn(self, history):
        context = json.loads(history[1]["content"])
        personal = context["project_context"]["career_evidence"]
        if not personal.get("selected_experiment_id"):
            return await super().turn(history)
        self.contexts.append(context)
        task = next(
            row
            for row in personal["experiments"]
            if row["id"] == personal["selected_experiment_id"]
        )
        origin = task["relation_to_verify"]
        assert origin["relation_index"] == 0
        assert origin["relation"]["transfer_limit"] == LIMIT + "0"
        assert origin["claims"][0]["index"] == 0
        assert len(origin["evidence"]) == 1
        assert task["comparison_rows"][1]["observed"].startswith("合成反例")
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = "read_experiments", {"experiment_ids": [task["id"]]}
        elif len(outputs) == 1:
            assert outputs[0]["experiments"][0]["relation_to_verify"] == origin
            name, args = (
                "read_archived_documents",
                {
                    "reads": [
                        {"document_id": source["public_document_id"], "start": 0}
                        for source in origin["evidence"]
                    ],
                },
            )
        else:
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "inference",
                            "requirement": "unspecified",
                            "text": "合成原文只说明对应任务与交付物，改变验收权限的构造反例"
                            "提醒迁移需要额外条件；个人实际权限和业务适用性仍未知。",
                            "evidence_ids": [row["id"] for row in outputs[-1]["evidence"]],
                        }
                    ],
                    "gaps": ["合成观察不能证明真实业务因果或个人胜任。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_relation_plan_negative_observation_followup_and_recall_keep_exact_edge(tmp_path):
    database = tmp_path / "relation-experiments.db"
    upgrade(database)
    model = RelationExperimentModel()
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model,
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

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成工作关系验证", "goal": "核对任务与交付条件"})
        base = "/api/career/" + goal["id"]
        ids = [
            save(
                base + "/materials",
                {
                    "title": name,
                    "text": f"任务：{task}。交付：{deliverable}。验收权仍未知。",
                },
            )["materials"][-1]["id"]
            for name, task, deliverable in MATERIALS
        ]
        question = save(
            base + "/questions",
            {
                "question": "任务如何产生对应交付物？",
                "material_ids": ids,
            },
        )["questions"][-1]
        original = run_stage(
            client,
            goal["id"],
            auth,
            "map",
            question_id=question["id"],
            question="合成工作关系验证：比较任务与对应产物。",
        )
        source = original["results"][0]
        assert source["result"]["status"] == "completed"
        saved_map, calls = deepcopy(source["result"]["work_map"]), len(model.contexts)
        plan = {
            "title": "合成关系的边界实验",
            "task_or_ability": "核对验收条件",
            "deliverable": "预测、操作和反例记录",
            "completion_check": "分别核对差异与未知",
            "hypothesis": "合成待验证解释：相同任务不一定能在不同权限下产生相同交付物。",
            "source_step_id": source["step_id"],
            "source_relation_index": 0,
            "question_id": question["id"],
            "comparison_rows": [
                {
                    "condition": "原条件",
                    "input": "合成输入甲",
                    "expected": "出现交付物",
                    "observed": "",
                },
                {
                    "condition": "改变验收权",
                    "input": "合成输入乙",
                    "expected": "保留未知",
                    "observed": "",
                },
            ],
        }
        for changes in [
            {"source_step_id": None},
            {"source_relation_index": 2},
            {"source_relation_index": True},
            {"source_claim_index": 0},
            {"source_experiment_id": "0" * 32},
            {"question_id": None},
        ]:
            rejected = client.post(base + "/experiments", headers=auth, json={**plan, **changes})
            assert rejected.status_code == 422
        assert client.get(base).json() == original
        task = save(base + "/experiments", plan)["tasks"][-1]
        assert task["source_relation_index"] == 0 and task["purpose"] == "understanding_check"
        assert task["state"] == "planned" and not task["outcome"] and not task["evidence_ids"]
        rows = deepcopy(plan["comparison_rows"])
        rows[0]["observed"] = "合成原条件下出现差异清单，真实验收未知。"
        rows[1]["observed"] = "合成反例：缺少验收权限，只能提出差异，无法闭环。"
        observation = "合成观察：这次构造反例提示权限条件，尚未在真实业务验证。"
        save(
            base + "/tasks/" + task["id"],
            {
                "state": "done",
                "outcome": observation,
                "comparison_rows": rows,
            },
            "patch",
        )
        assert len(model.contexts) == calls
        library = client.get("/api/career/work-relations", params={"goal_id": goal["id"]}).json()
        zero = next(row for row in library["relations"] if row["relation_index"] == 0)
        assert zero["verification_tasks"][0]["comparison_rows"] == rows
        assert "verification_tasks" not in next(
            row for row in library["relations"] if row["relation_index"] == 1
        )
        reflected = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            task_id=task["id"],
            question_id=question["id"],
            question="按反例回读原关系与引用。",
        )
        result = reflected["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        old_task = result["career_learning_context"]["read_experiments"][0]
        assert old_task["relation_to_verify"]["relation"] == saved_map["work_relations"][0]
        assert old_task["reported_observation"] == observation
        assert len(result["evidence"]) == 1
        note = save(
            base + "/insights",
            {
                "task_id": task["id"],
                "question_id": question["id"],
                "previous_view": "以为任务名称相同就能迁移交付。",
                "observation": observation,
                "current_view": "需要逐项核实验收条件，合成反例仍非真实业务证明。",
                "open_question": "实际验收条件仍需材料支持。",
            },
        )["insights"][-1]
        child = save(
            base + "/experiments",
            {
                **{
                    k: v
                    for k, v in plan.items()
                    if k not in {"source_step_id", "source_relation_index", "comparison_rows"}
                },
                "previous_task_id": task["id"],
                "design_change": "改变交付对象，仍保留验收条件未知。",
            },
        )["tasks"][-1]
        assert child["source_step_id"] == source["step_id"] and child["source_relation_index"] == 0
        assert not child["outcome"] and not child["comparison_rows"]
        project = client.get("/api/projects/" + goal["id"]).json()
        store = ResearchStore(tmp_path / "checkpoints.db", namespace=str(database.resolve()))
        notebook = LearningNotebook(lambda: project, store)
        assert (
            notebook.search_experiments(["末尾迁移前提"], question_id=question["id"])[
                "matching_count"
            ]
            == 2
        )
        matched = client.get(base + "/search", params={
            "q": "末尾迁移前提", "record_kind": "task",
        }).json()
        assert len(matched["records"]) == 2
        negative = client.get(base + "/search", params={
            "q": "无法闭环", "record_kind": "task",
        }).json()
        assert len(negative["records"]) == 1
        read = notebook.read_experiments([child["id"]])["experiments"][0]
        assert read["relation_to_verify"] == old_task["relation_to_verify"]
        linked = learning_record(note, project, store)["linked_experiment"]
        assert linked["relation_to_verify"] == old_task["relation_to_verify"]
        current_source = next(
            row for row in client.get(base).json()["results"] if row["step_id"] == source["step_id"]
        )
        assert current_source["result"]["work_map"] == saved_map
