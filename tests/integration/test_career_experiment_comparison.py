"""Explicit experiment comparisons retain complete conditions and actual input snapshots."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

HYPOTHESIS = "原预期需按对象核对🤔。" * 100 + "末尾预期：真实权限未知。"
OBSERVATION = "用户记录：对象变化后出现差异，尚未控制混杂。" * 90 + "末尾：不能证明因果。"
LOGS = [
    "合成实验甲记录\r\n对象甲出现差异；权限未知。",
    "合成实验乙记录🤔\r\n对象乙出现另一差异；样本构造方式不同。",
]


class ExperimentComparisonModel(ModelClient):
    def __init__(self):
        self.last_usage, self.contexts = {}, []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        records, selected = personal["experiments"], personal["selected_experiment_ids"]
        assert len(records) == len(selected) == 4 and [r["id"] for r in records] == selected
        assert records[0]["prior_expectation"] == HYPOTHESIS
        assert records[0]["state"] == "planned" and not records[0]["reported_observation"]
        assert records[1]["reported_observation"] == OBSERVATION
        assert records[2]["state"] == "doing" and records[2]["comparison_rows"][0]["observed"]
        assert records[3]["state"] == "planned" and not records[3]["reported_observation"]
        assert not personal["selected_experiment_id"]
        assert personal["omitted_experiments"] == 0
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        docs = [r["artifact_document"]["document_id"] for r in records if r["artifact_document"]]
        assert len(docs) == 2
        if not outputs:
            name, args = (
                "read_archived_documents",
                {"reads": [{"document_id": identity, "start": 0} for identity in docs]},
            )
        else:
            evidence = outputs[-1]["evidence"]
            assert {r["public_document_id"] for r in evidence} == set(docs)
            assert all(any(text in r["quote"] for r in evidence) for text in LOGS)
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "inference",
                            "requirement": "unspecified",
                            "text": "两次记录的对象和构造条件不同，"
                            "差异不足以证明旧解释成立或失效；计划和无观察的完成状态仍需补证。",
                            "evidence_ids": [r["id"] for r in evidence],
                        }
                    ],
                    "gaps": ["缺少相同条件下的对照，以及真实验收权限说明。"],
                },
            )
            project = context["project_context"]
            if project.get("previous_findings") or project.get("historical_reply"):
                args["revisions"] = []
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_four_experiments_keep_full_independent_conditions_and_frozen_inputs(tmp_path):
    database = tmp_path / "experiment-comparison.db"
    upgrade(database)
    model = ExperimentComparisonModel()
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model,
            reports_dir=tmp_path / "reports",
        ),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save(
            "/api/career",
            {
                "title": "合成多实验对照",
                "goal": "比较解释的适用条件",
                "first_question": "不同对象下的观察能否支持同一解释？",
            },
        )
        base, question = "/api/career/" + goal["id"], goal["questions"][0]
        tasks = []
        for index in range(5):
            data = save(
                base + "/experiments",
                {
                    "title": "合成条件实验" + str(index),
                    "question_id": question["id"],
                    "task_or_ability": "核对工作对象",
                    "deliverable": "条件与观察记录",
                    "completion_check": "逐项核对差异",
                    "hypothesis": HYPOTHESIS,
                    "comparison_conditions": "分别记录对象和构造方法。",
                    "comparison_rows": [
                        {
                            "condition": "对象" + str(index),
                            "input": "合成输入",
                            "expected": "预计相同",
                            "observed": "",
                        }
                    ],
                },
            )
            task = data["tasks"][-1]
            if index:
                values = {
                    "state": "doing" if index == 2 else "planned" if index == 3 else "done",
                    "outcome": {1: OBSERVATION, 4: "未选中的另一项记录。"}.get(index, ""),
                    "comparison_rows": [
                        {
                            "condition": "对象" + str(index),
                            "input": "合成输入",
                            "expected": "预计相同",
                            "observed": "记录了差异" if index == 2 else "",
                        }
                    ],
                }
                if index in {1, 2}:
                    values.update(
                        artifact_title="合成对照日志" + str(index), artifact_text=LOGS[index - 1]
                    )
                data = save(base + "/tasks/" + task["id"], values, "patch")
                task = next(r for r in data["tasks"] if r["id"] == task["id"])
            tasks.append(task)
        selected = [t["id"] for t in tasks[:4]]
        before = client.get(base).json()
        for invalid in [
            {"experiment_ids": selected[:1]},
            {"experiment_ids": [selected[0]] * 2},
            {"experiment_ids": selected + [tasks[4]["id"]]},
            {"experiment_ids": [selected[0], "0" * 32]},
            {"task_id": selected[0]},
            {"kind": "plan"},
        ]:
            response = client.post(
                base + "/prepare",
                headers=auth,
                json={
                    "kind": "ask",
                    "question": "对照这些实验",
                    "experiment_ids": selected,
                    **invalid,
                },
            )
            assert response.status_code == 422, response.text
        assert client.get(base).json() == before and not model.contexts
        studied = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            experiment_ids=selected,
            question_id=question["id"],
            question="合成多实验对照：检查不同条件。",
        )
        result = studied["results"][0]
        assert result["result"]["status"] == "completed", result["result"]["stop_reason"]
        assert result["experiment_ids"] == selected
        snapshot = deepcopy(result["result"]["career_learning_context"]["selected_experiments"])
        assert len(snapshot) == 4 and snapshot[-1]["id"] == selected[-1]
        assert studied["tasks"] == before["tasks"] and studied["questions"] == before["questions"]
        assert len(result["result"]["evidence"]) == 2
        save(
            base + "/tasks/" + tasks[1]["id"],
            {"state": "doing", "outcome": "后来编辑的观察。"},
            "patch",
        )
        final = client.get(base).json()
        assert (
            final["results"][0]["result"]["career_learning_context"]["selected_experiments"]
            == snapshot
        )
        assert snapshot[1]["reported_observation"] == OBSERVATION
        calls = len(model.contexts)
        continued = save(base + "/prepare", {
            "kind": "ask", "source_step_id": result["step_id"],
            "question": "接着这组实验，核对后来记录的变化。",
        })
        project = client.get("/api/projects/" + goal["id"]).json()
        step = next(row for row in project["steps"] if row["id"] == continued["step_id"])
        assert step["career_experiment_ids"] == selected and len(model.contexts) == calls
