"""A saved answer can lead to a user-designed, unexecuted verification plan."""

import re

from starlette.testclient import TestClient
from test_career_inquiry_answer import ANSWER, MATERIAL, QUESTION, InquiryAnswerModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.learning import LearningNotebook, experiment_answer_origin
from work_observer.storage.database import upgrade


def test_answer_plan_observation_and_reflection_keep_the_original_answer(tmp_path):
    database = tmp_path / "answer-experiment.db"
    upgrade(database)
    model = InquiryAnswerModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]}

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成解释到验证", "goal": "用实际观察修正解释",
                    "material_title": "合成直接作答工作原文", "material_text": MATERIAL})
        base = "/api/career/" + goal["id"]
        question = save(base + "/questions", {
            "question": QUESTION, "material_ids": [goal["materials"][0]["id"]],
            "state": "parked", "conclusion": "原理解，尚待验证。",
        })["questions"][0]
        answer = run_stage(
            client, goal["id"], auth, "answer", inquiry_answer=True,
            question_id=question["id"], question=QUESTION, answer=ANSWER,
        )["results"][0]
        assert answer["result"]["status"] == "completed"
        before = client.get(base).json()
        calls = len(model.contexts)
        plan = {"title": "改变交付对象后核对责任", "task_or_ability": "区分工具与责任边界",
                "deliverable": "两种条件下的预测和实际记录",
                "completion_check": "逐项核对并保留未知",
                "hypothesis": "同一工具未必对应同一验收权限。",
                "source_step_id": answer["step_id"], "question_id": question["id"],
                "comparison_rows": [
                    {"condition": "原条件", "input": "", "expected": "", "observed": ""},
                    {"condition": "改变对象", "input": "", "expected": "", "observed": ""},
                ]}
        for invalid in [{"source_step_id": "0" * 32}, {"question_id": None}]:
            rejected = client.post(base + "/experiments", headers=auth, json={**plan, **invalid})
            assert rejected.status_code == 422, rejected.text
        assert client.get(base).json() == before and len(model.contexts) == calls
        saved = save(base + "/experiments", plan)
        task = saved["tasks"][0]
        assert task["source_step_id"] == answer["step_id"]
        assert task["purpose"] == "understanding_check" and task["origin"] == "user"
        assert task["state"] == "planned" and not task["outcome"] and not task["evidence_ids"]
        assert all(not row["observed"] for row in task["comparison_rows"])
        assert saved["results"] == before["results"] and saved["questions"] == before["questions"]
        outcome = "用户手动核对构造样例：对象改变后需要另查验收权限，真实业务仍未知。"
        updated = save(base + "/tasks/" + task["id"], {
            "state": "done", "outcome": outcome, "artifact": "仅本地构造记录，无真实业务验证。",
        }, "patch")
        assert updated["tasks"][0]["source_step_id"] == answer["step_id"]
        note = save(base + "/insights", {
            "task_id": task["id"], "question_id": question["id"],
            "previous_view": task["hypothesis"], "observation": outcome,
            "current_view": "对工具的解释需带上工作对象与验收条件。",
            "open_question": "实际权限仍待核实。",
        })["insights"][-1]
        assert note["task_id"] == task["id"]
        next_task = save(base + "/experiments", {
            **{key: value for key, value in plan.items() if key != "source_step_id"},
            "previous_task_id": task["id"], "design_change": "仅改变交付对象。",
        })["tasks"][-1]
        assert next_task["source_step_id"] == answer["step_id"]
        assert next_task["purpose"] == "understanding_check" and not next_task["outcome"]
        assert len(model.contexts) == calls
        assert client.get(base).json()["questions"] == before["questions"]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()
        assert reopened["results"] == before["results"]
        assert reopened["tasks"][0]["outcome"] == outcome
        assert all(row["source_step_id"] == answer["step_id"] for row in reopened["tasks"])


def test_agent_experiment_reader_retains_the_full_answer_and_its_old_question():
    source = {"step_id": "answer", "kind": "answer", "interview_question": QUESTION,
              "answer": ANSWER, "answer_document_id": "archived-answer"}
    task = {"id": "experiment", "title": "解释验证", "source_step_id": "answer",
            "question_id": "inquiry", "task_or_ability": "区分条件", "deliverable": "观察记录",
            "completion_check": "核对反例", "state": "planned", "outcome": "",
            "created_at": "2026-11-22T00:00:00+00:00"}
    career = {"runs": [source], "tasks": [task], "questions": [
        {"id": "inquiry", "question": "后来改写的问题？"},
    ]}
    origin = experiment_answer_origin(career, task)
    assert origin["original_question"] == QUESTION and origin["user_answer"] == ANSWER
    notebook = LearningNotebook(lambda: {"career": career}, None)
    record = notebook.read_experiments([task["id"]])["experiments"][0]
    assert record["answer_to_verify"] == origin and record["reported_observation"] == ""
    assert record["inquiry_question"] == "后来改写的问题？"
    assert not experiment_answer_origin(career, {**task, "source_step_id": "other"})
