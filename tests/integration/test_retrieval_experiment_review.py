"""Review an actual local run within its corpus, using scripted model calls only."""

import json
import re

from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace

from work_observer.research.agent import ModelClient


class RetrievalReviewModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        review = personal["retrieval_review"]
        if personal["selected_experiment_id"]:
            assert review["task_id"] == personal["selected_experiment_id"]
        else:
            note = personal["selected_learning_note"]
            assert note["task_id"] == review["task_id"] and not note["use_for_research"]
        assert review["available"] and review["input"]["job_ids"] == [self.job]
        assert review["runs"][0]["metrics"]["source_recall"] == 0
        checks = review["runs"][0]["missing_source_checks"]
        assert {row["reason"] for row in checks} == {"query_expression_missing"}
        assert all("evidence" not in row for row in checks)
        assert {row["id"] for row in context["fixed_scope"]["jobs"]} == {self.job}
        answer = personal.get("selected_answer")
        documents = {self.document, self.artifact}
        if answer:
            documents.add(answer["document_id"])
        assert set(context["fixed_scope"]["archived_public_ids"]) == documents
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_archived_documents", {"reads": [
                {"document_id": self.artifact, "start": review["runs"][0][
                    "diagnostic_read_start"
                ]},
                {"document_id": self.document, "start": 0},
                *([{"document_id": answer["document_id"], "start": 0}] if answer else []),
            ]}
        elif len(outputs) == 1:
            assert any("missing_source_checks" in row["quote"] for row in outputs[0]["evidence"])
            name, args = "read_historical_job", {
                "job_id": self.job, "as_of": review["as_of"], "start": 0,
            }
        else:
            evidence = outputs[0]["evidence"] + outputs[1]["evidence"]
            name, args = "finish_research", {
                "claims": [{"category": "business", "basis": "direct",
                            "requirement": "unspecified", "text": row["quote"],
                            "evidence_ids": [row["citation_key"]]} for row in evidence],
                "gaps": ["本机词面检索的局部观察，不能证明语义效果或个人胜任。"],
            }
            if context["project_context"]["career_action"] in {"teachback", "followup"}:
                args["gaps"] = ["为何一次没找到端云同步，不能直接证明该岗位没有这项工作？"]
            finish = next(tool for tool in self.tools if tool["name"] == name)["parameters"]
            if "revisions" in finish["properties"]:
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_run_review_keeps_original_corpus_and_reads_diagnostics_and_historical_jd(tmp_path):
    model = RetrievalReviewModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        jobs = [client.post("/api/import", headers=auth, json={
            "title": "合成工作" + str(i), "company": "合成公司" + str(i),
            "description": text, "data_kind": "synthetic",
        }).json()["job_id"] for i, text in enumerate([
            "负责端云同步与记忆管理。", "负责知识库检索与重排。", "负责业务接口开发。",
        ])]
        created = client.post("/api/career", headers=auth, json={
            "title": "合成检索复查", "goal": "解释词面漏回", "job_ids": jobs,
            "first_question": "泛词为什么没有找到预期来源？",
            "material_title": "选中的说明", "material_text": "端云同步需要保留上下文条件。",
        }).json()
        goal, document = created["id"], created["materials"][0]["id"]
        base = "/api/career/" + goal
        unrelated = client.post(base + "/materials", headers=auth, json={
            "title": "不在实验中的资料", "text": "负责另一项目的知识库检索。",
        }).json()["materials"][-1]["id"]
        inputs = {"baseline": {"terms": ["RAG"]}, "candidate": {"terms": ["端云同步"]},
                  "job_ids": jobs[:1], "document_ids": [document],
                  "expected_job_ids": jobs[:1], "expected_document_ids": [document],
                  "question_id": created["focus_question_id"], "save": True}
        saved = client.post(base + "/experiments/retrieval", headers=auth, json=inputs)
        assert saved.status_code == 201, saved.text
        task_id = saved.json()["task_id"]
        task = next(row for row in saved.json()["career"]["tasks"] if row["id"] == task_id)
        artifact = task["artifact_document_id"]
        model.job, model.document, model.artifact = (
            jobs[0], document, artifact,
        )

        def prepare(kind, keep=False, **extra):
            response = client.post(base + "/prepare", headers=auth, json={
                "kind": kind, "task_id": task_id, **extra,
            })
            assert response.status_code == 201, response.text
            project = client.get("/api/projects/" + goal).json()
            step = next(row for row in project["steps"] if row["id"] == response.json()["step_id"])
            if not keep:
                ended = client.delete(base + "/steps/" + step["id"], headers=auth)
                assert ended.status_code == 200, ended.text
            return step

        step = prepare("reflect", keep=True)
        assert step["job_ids"] == jobs[:1]
        assert set(step["public_document_ids"]) == {document, artifact}
        assert unrelated not in step["career_source_document_ids"]
        response = client.post("/api/projects/" + goal + "/run", headers=auth,
                               json={"step_id": step["id"]})
        assert response.status_code == 202, response.text
        result = settled(client, base)["results"][0]["result"]
        assert result["status"] == "completed", {
            key: result.get(key) for key in ("stop_reason", "tool_trace", "error")
        }
        assert {row["job_id"] for row in result["evidence"] if row.get("job_id")} == {jobs[0]}
        assert model.contexts

        # Planning, interview and question follow the same saved corpus without running a model.
        for kind, extra in [("plan", {}), ("interview", {}),
                            ("ask", {"question": "带着失败回查原问题"})]:
            pending = prepare(kind, **extra)
            assert pending["job_ids"] == jobs[:1]
            assert set(pending["public_document_ids"]) == {document, artifact}
        explicit = prepare("ask", question="只对读这份工作资料", selected_job_ids=[])
        assert explicit["job_ids"] == []

        noted = client.post(base + "/insights", headers=auth, json={
            "task_id": task_id, "question_id": created["focus_question_id"],
            "previous_view": "只要使用RAG这个泛词，就能找到同步说明。",
            "observation": "RAG未找到预期来源；端云同步找到了两份资料。",
            "current_view": "词面表达会影响这个小样本的返回，尚不清楚语义效果。",
            "open_question": "换掉主题表达后，能否区分查询缺词和片段数量限制？",
        })
        assert noted.status_code == 201, noted.text
        note = noted.json()["insights"][-1]
        held = client.post(base + "/insights/" + note["id"] + "/use", headers=auth,
                           json={"use_for_research": False})
        assert held.status_code == 200, held.text
        quiz = prepare("teachback", keep=True, task_id=None, insight_id=note["id"])
        assert quiz["job_ids"] == jobs[:1]
        assert set(quiz["public_document_ids"]) == {document, artifact}

        def run(step):
            response = client.post("/api/projects/" + goal + "/run", headers=auth,
                                   json={"step_id": step["id"]})
            assert response.status_code == 202, response.text
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
            assert row["result"]["career_learning_context"]["retrieval_review"] == step[
                "career_retrieval_review"
            ]
            return row

        quiz_result = run(quiz)
        feedback = prepare("answer", keep=True, task_id=None, source_step_id=quiz_result["step_id"],
                           answer="只观察到词面漏回，不能证明岗位没有这项工作。尚未验证语义效果。",
                           question_index=0)
        assert feedback["job_ids"] == jobs[:1]
        answered = run(feedback)
        assert answered["insight_id"] == note["id"] and answered["understanding_check"]
        followup = prepare("followup", keep=True, task_id=None, source_step_id=answered["step_id"])
        assert followup["job_ids"] == jobs[:1]
        run(followup)
        follow = client.post(base + "/questions", headers=auth, json={
            "question": note["open_question"], "source_insight_id": note["id"],
            "parent_question_id": created["focus_question_id"], "material_ids": [artifact],
        })
        assert follow.status_code == 201, follow.text
        child_question = follow.json()["questions"][-1]
        child = prepare("ask", task_id=None, question_id=child_question["id"],
                        question="沿着这个未知回查检索记录")
        assert child["job_ids"] == jobs[:1]
        assert set(child["public_document_ids"]) == {document, artifact}
        assert not client.get(base).json()["insights"][-1]["use_for_research"]

        removed = client.delete(base + "/materials/" + document, headers=auth)
        assert removed.status_code == 200, removed.text
        pending = prepare("reflect")
        assert pending["job_ids"] == jobs[:1] and pending["public_document_ids"] == [artifact]
        assert pending["career_retrieval_review"]["input"]["document_ids"] == [document]
        assert document not in client.get("/api/projects/" + goal).json()["public_document_ids"]

        work_only = client.post(base + "/experiments/retrieval", headers=auth, json={
            **inputs, "job_ids": [], "document_ids": [unrelated], "expected_job_ids": [],
            "expected_document_ids": [unrelated],
        })
        assert work_only.status_code == 201, work_only.text
        task_id = work_only.json()["task_id"]
        pending = prepare("reflect")
        assert pending["job_ids"] == []  # An empty experiment JD scope must not become all jobs.
        assert document not in pending["public_document_ids"]
