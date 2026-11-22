"""A specific late feedback gap becomes a scoped, still-unrun practice plan."""

import json
import re

import pytest
from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace

from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore

QUESTION = ("如何解释词面漏回？" + "保留原文条件和反例，不从返回数量证明胜任。🤔" * 40
            + "末尾原题限定。")
GAP = "固定同一批原文和查询，只改变返回片段上限，逐份记录漏回；哪组观察能区分表达缺词与数量限制？"


class FeedbackPracticeModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        action = context["project_context"]["career_action"]
        assert {row["id"] for row in context["fixed_scope"]["jobs"]} == {self.job}
        documents = {self.work}
        answer = personal.get("selected_answer")
        feedback = personal.get("feedback_origin")
        if answer:
            documents.add(answer["document_id"])
        if feedback:
            assert feedback["question"] == QUESTION
            assert feedback["gap"] == GAP and feedback["gap_index"] == self.gap_index
            documents.add(feedback["answer_document_id"])
        experiment = next((row for row in personal["experiments"]
                           if row["id"] == personal.get("selected_experiment_id")), {})
        if experiment.get("artifact_document"):
            documents.add(experiment["artifact_document"]["document_id"])
            assert experiment["feedback_to_verify"]["gap"] == GAP
        practice = personal.get("selected_practice_experiment")
        if practice:
            assert practice["feedback_to_verify"]["gap"] == GAP
            assert practice["comparison_rows"][0]["observed"] == "仍有漏回，只做了这一组。"
            assert practice["comparison_rows"][1]["observed"] == ""
            documents.add(practice["artifact_document"]["document_id"])
        pair = personal.get("selected_answer_comparison", [])
        if pair:
            assert len(pair) == 2 and pair[0]["practice_experiment_then"] is None
            original_practice = pair[1]["practice_experiment_then"]
            assert original_practice["comparison_rows"][0]["observed"] == (
                "仍有漏回，只做了这一组。"
            )
            assert original_practice["comparison_rows"][1]["observed"] == ""
            assert "后补说明" not in original_practice["reported_observation"]
            assert pair[1]["feedback_origin_then"]["gap"] == GAP
            assert not personal["selected_experiment_id"]
            documents.update(row["answer_document_id"] for row in pair)
            documents.add(original_practice["artifact_document"]["document_id"])
        assert set(context["fixed_scope"]["archived_public_ids"]) == documents
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        old = [row["research"] for row in outputs if row.get("research")]
        reads = [row for row in outputs if row.get("evidence")]
        if feedback and not old:
            name, args = "read_research_history", {"step_id": feedback["step_id"]}
        elif not reads:
            if old:
                assert GAP in old[0]["unknowns_then"]
                assert old[0]["user_reported_answer"].endswith("还没有生产验证。")
            name, args = "read_archived_documents", {
                "reads": [{"document_id": key, "start": 0} for key in sorted(documents)],
            }
        elif len(reads) == 1:
            name, args = "read_job", {"job_id": self.job, "start": 0}
        else:
            jd = reads[-1]["evidence"][0]
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "direct", "requirement": "unspecified",
                            "text": jd["quote"], "evidence_ids": [jd["citation_key"]]}],
                "gaps": [QUESTION] if action == "teachback" else ["另一组尚未执行，解释仍待检验。"],
            }
            if pair and action == "ask":
                args["gaps"] = ["如果另一组返回相同的来源，两种解释还如何区分？"]
            if action == "answer":
                args["gaps"] = [f"前置核对{i}：" + "原始条件、适用边界与实际观察仍需分别确认。" * 8
                                for i in range(10)] + [GAP]
            if action == "plan":
                args["application_plan"] = {
                    "background_memory_id": context["application_background"]["memory_id"],
                    "actions": [{
                        "title": "只改变片段上限的两组对照",
                        "task_or_ability": "区分查询条件与返回上限",
                        "deliverable": "两组输入、去重来源与漏回记录",
                        "completion_check": "保持资料和表达不变，逐份记录两组返回与未返回。",
                        "hypothesis": "增加片段上限可能找回原来被排除的来源，尚未执行。",
                        "evidence_ids": [jd["citation_key"]], "assumptions": ["只用本地构造原文"],
                        "comparison_conditions": "固定资料、查询、预期标签和别名，只改变片段上限。",
                        "comparison_rows": [
                            {"condition": "少量返回", "input": "上限1", "expected": "可能漏回"},
                            {"condition": "增加返回", "input": "上限3",
                             "expected": "可能找回部分来源"},
                        ],
                    }], "open_questions": ["实际差异尚未观察，不能推断语义质量。"],
                }
            finish = next(tool for tool in self.tools if tool["name"] == name)["parameters"]
            if "application_plan" in finish["properties"]:
                args.setdefault("application_plan", None)
            if "revisions" in finish["properties"]:
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


@pytest.mark.parametrize("direct_inquiry", [False, True])
def test_late_gap_and_full_question_survive_plan_save_observation_and_reflection(
    tmp_path, direct_inquiry,
):
    model = FeedbackPracticeModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": "合成检索岗位" + str(i), "company": "合成公司" + str(i),
            "description": "负责检索召回、失败样本核对与观察记录。", "data_kind": "synthetic",
        })["job_id"] for i in range(3)]
        created = post("/api/career", {
            "title": "合成反馈到验证", "goal": "把尚未回答清楚的问题变成可检查的观察",
            "first_question": QUESTION if direct_inquiry else (
                "检索没有返回是否就说明原文没有相关工作？"
            ),
            "job_ids": jobs,
            "material_title": "合成检索说明", "material_text": "固定原文和表达，比较不同返回上限。",
        })
        goal, work = created["id"], created["materials"][0]["id"]
        base = "/api/career/" + goal
        model.job, model.work = jobs[0], work

        def prepare(kind, **values):
            response = post(base + "/prepare", {"kind": kind, **values})
            return response["step_id"]

        def run(step):
            post("/api/projects/" + goal + "/run", {"step_id": step})
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
            return row

        questions = run(prepare("teachback", question_id=created["focus_question_id"],
                                selected_job_ids=jobs[:1]))
        inquiry_args = {"inquiry_answer": True, "question_id": created["focus_question_id"],
                        "selected_job_ids": jobs[:1]}
        interview_args = {"source_step_id": questions["step_id"], "question_index": 0}
        answer_args = inquiry_args if direct_inquiry else interview_args
        answer = run(prepare("answer", **answer_args,
                             answer="可能同时受查询表达和片段上限影响，我还没有生产验证。"))
        model.gap_index = answer["result"]["gaps"].index(GAP)
        assert GAP not in "\n".join(answer["result"]["gaps"])[:1000]
        assert len(QUESTION) > 700
        unrelated = post(base + "/materials", {
            "title": "回答之后加入的其他资料", "text": "另一项目的账号和接口条件。",
        })["materials"][-1]["id"]
        for invalid in (len(answer["result"]["gaps"]), -1, True):
            rejected = client.post(base + "/prepare", headers=auth, json={
                "kind": "plan", "source_step_id": answer["step_id"], "feedback_gap_index": invalid,
            })
            assert rejected.status_code == 422, rejected.text
        plan_id = prepare("plan", source_step_id=answer["step_id"],
                          feedback_gap_index=model.gap_index)
        project = client.get("/api/projects/" + goal).json()
        step = next(row for row in project["steps"] if row["id"] == plan_id)
        assert step["career_feedback_origin"]["gap"] == GAP
        assert step["job_ids"] == jobs[:1] and unrelated not in step["public_document_ids"]
        planned = run(plan_id)
        assert len(planned["result"]["application_plan"]["actions"]) == 1
        saved = post(base + "/tasks", {"step_id": plan_id})
        task = saved["tasks"][-1]
        assert task["feedback_origin"]["step_id"] == answer["step_id"]
        assert task["feedback_origin"]["question"] == QUESTION
        assert task["feedback_origin"]["gap"] == GAP
        assert task["question_id"] == created["focus_question_id"]
        assert task["state"] == "planned" and not task["outcome"]
        assert all(not row["observed"] for row in task["comparison_rows"])
        unrun = client.post(base + "/prepare", headers=auth, json={
            "kind": "answer", **answer_args,
            "answer": "仍未执行。", "practice_task_id": task["id"],
        })
        assert unrun.status_code == 422 and "实际观察" in unrun.text
        rows = [{**row, "observed": "仍有漏回，只做了这一组。" if i == 0 else ""}
                for i, row in enumerate(task["comparison_rows"])]
        changed = client.patch(base + "/tasks/" + task["id"], headers=auth, json={
            "state": "done", "outcome": "", "comparison_rows": rows,
            "artifact_title": "合成局部观察",
            "artifact_text": "只运行上限1的构造组，其他组尚未执行。",
        })
        assert changed.status_code == 200, changed.text
        task = changed.json()["tasks"][-1]
        reflected = run(prepare("reflect", task_id=task["id"]))
        assert reflected["result"]["career_learning_context"]["feedback_origin"]["gap"] == GAP
        assert unrelated not in reflected["result"]["scope"]["archived_public_ids"]
        mismatched = client.post(base + "/prepare", headers=auth, json={
            "kind": "answer", **(interview_args if direct_inquiry else inquiry_args),
            "answer": "直接回答原调查问题，不是当时那道自测题。", "practice_task_id": task["id"],
        })
        assert mismatched.status_code == 422 and "另一道原题" in mismatched.text
        reanswered = run(prepare(
            "answer", **answer_args,
            answer="第一组仍有漏回，另一组尚未执行，不能分辨两种解释，还没有生产验证。",
            practice_task_id=task["id"],
        ))
        assert reanswered["source_step_id"] == answer["source_step_id"]
        assert reanswered["question_index"] == answer["question_index"]
        assert reanswered["task_id"] == answer["task_id"]
        assert reanswered["practice_task_id"] == task["id"]
        snapshot = reanswered["result"]["career_learning_context"]["practice_experiment"]
        assert snapshot["comparison_rows"][1]["observed"] == ""
        assert snapshot["reported_observation"] == task["outcome"]
        assert unrelated not in reanswered["result"]["scope"]["archived_public_ids"]
        amended = client.patch(base + "/tasks/" + task["id"], headers=auth, json={
            "state": "done", "outcome": "后补说明：仍只执行了第一组，还未验证另一组。",
        })
        assert amended.status_code == 200, amended.text
        compared = run(prepare(
            "ask", question="对照两次解释，指出哪项实际观察改变了什么，哪些条件仍未执行。",
            question_id=created["focus_question_id"],
            comparison_step_ids=[answer["step_id"], reanswered["step_id"]],
        ))
        assert unrelated not in compared["result"]["scope"]["archived_public_ids"]
        pair = compared["result"]["career_learning_context"]["answer_comparison"]
        assert pair[1]["practice_experiment_then"] == snapshot
        next_answer = run(prepare(
            "answer", source_step_id=compared["step_id"], question_index=0,
            answer="即使同样返回，也还需要固定查询和输入条件，另一组还没有生产验证。",
        ))
        assert next_answer["result"]["career_learning_context"]["answer_comparison"] == pair
        assert unrelated not in next_answer["result"]["scope"]["archived_public_ids"]
        followup = run(prepare("followup", source_step_id=next_answer["step_id"]))
        assert followup["result"]["career_learning_context"]["answer_comparison"] == pair
        assert unrelated not in followup["result"]["scope"]["archived_public_ids"]
        project = client.get("/api/projects/" + goal).json()
        store = ResearchStore(tmp_path / "checkpoints.db",
                              namespace=str((tmp_path / "adaptive.db").resolve()))
        try:
            notebook = LearningNotebook(lambda: project, store)
            read = notebook.read_experiments([task["id"]])[
                "experiments"
            ][0]
            assert read["answer_to_verify"]["step_id"] == answer["step_id"]
            assert read["answer_to_verify"]["original_question"] == QUESTION
            assert read["feedback_to_verify"]["gap"] == GAP
            assert read["reported_observation"] != snapshot["reported_observation"]
            assert notebook.search_experiments(["数量限制"])["experiments"][0]["id"] == task["id"]
            historical_plan = notebook.read_research_history(plan_id)["research"]
            assert historical_plan["feedback_origin"]["gap"] == GAP
            original_action = historical_plan["application_plan_then"]["actions"][0]
            assert len(original_action["comparison_rows"]) == 2
            assert "evidence_ids" not in original_action
            assert original_action["source_references_to_reread"]
            history = notebook.read_research_history(reanswered["step_id"])["research"]
            assert history["practice_experiment_then"] == snapshot
        finally:
            store.close()
        assert client.get(base).json()["questions"][0]["state"] == "open"
        other = post("/api/career", {
            "title": "合成另一目标", "goal": "检验旧练习在另一岗位的适用条件", "job_ids": jobs[1:2],
        })["id"]
        reused = post("/api/career/" + other + "/reuse", {
            "source_project_id": goal, "kind": "task", "record_id": task["id"],
        })["tasks"][-1]
        assert reused["feedback_origin"]["project_id"] == goal
        prepared = post("/api/career/" + other + "/prepare", {
            "kind": "reflect", "task_id": reused["id"],
        })
        other_project = client.get("/api/projects/" + other).json()
        new_step = next(row for row in other_project["steps"] if row["id"] == prepared["step_id"])
        assert new_step["job_ids"] == jobs[1:2]
        assert new_step["public_document_ids"] == [reused["artifact_document_id"]]
        assert answer["answer_document_id"] not in new_step["public_document_ids"]
