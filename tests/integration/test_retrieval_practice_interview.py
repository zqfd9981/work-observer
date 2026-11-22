"""A retrieval practice becomes interview material with its original evidence scope."""

import json
import re

from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace

from work_observer.research.agent import ModelClient


class RetrievalStoryModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        assert personal["selected_story"]["id"] == self.story
        assert not personal["experiments"]
        review = personal["retrieval_review"]
        assert review["artifact_document_id"] == self.artifact
        assert review["note_origin"]["current_view"] == self.thought
        assert {row["id"] for row in context["fixed_scope"]["jobs"]} == {self.job}
        documents = {self.story_document}
        if self.work_document:
            documents.add(self.work_document)
        if review["available"]:
            documents.add(self.artifact)
        answer = personal.get("selected_answer")
        if answer:
            documents.add(answer["document_id"])
        assert set(context["fixed_scope"]["archived_public_ids"]) == documents
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            reads = [{"document_id": key, "start": 0} for key in sorted(documents)
                     if key != self.artifact]
            if review["available"]:
                reads.append({"document_id": self.artifact,
                              "start": review["runs"][0]["diagnostic_read_start"]})
            name, args = "read_archived_documents", {"reads": reads}
        elif len(outputs) == 1:
            if review.get("source_scope_only"):
                name, args = "read_job", {"job_id": self.job, "start": 0}
            else:
                name, args = "read_historical_job", {
                    "job_id": self.job, "as_of": review["as_of"], "start": 0,
                }
        else:
            own = next(row for row in outputs[0]["evidence"]
                       if row.get("public_document_id") == self.story_document)
            assert "个人练习" in own["quote"] and "未验证语义效果" in own["quote"]
            jd = outputs[1]["evidence"][0]
            name, args = "finish_research", {
                "claims": [
                    {"category": "responsibility", "basis": "direct", "requirement": "unspecified",
                     "text": "用户自述只调整本地查询，未验证语义效果。",
                     "evidence_ids": [own["citation_key"]]},
                    {"category": "task", "basis": "direct", "requirement": "unspecified",
                     "text": jd["quote"], "evidence_ids": [jd["citation_key"]]},
                ],
                "gaps": ["如何解释查询变化与漏回，哪些观察仍不能证明语义效果或岗位胜任？"],
            }
            if not review["available"]:
                args["gaps"].append("原运行记录不在本轮范围，无法重新核对实际返回。")
            parameters = next(tool for tool in self.tools if tool["name"] == name)["parameters"]
            if "revisions" in parameters["properties"]:
                args["revisions"] = []
            if "application_plan" in parameters["properties"]:
                args["application_plan"] = None
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_story_questions_answer_and_followup_keep_the_saved_retrieval_source(tmp_path):
    model = RetrievalStoryModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": "合成实践岗位" + str(i), "company": "合成公司" + str(i),
            "description": text, "data_kind": "synthetic",
        })["job_id"] for i, text in enumerate([
            "负责端云同步与记忆管理。", "负责知识库检索与重排。", "负责其他业务接口。",
        ])]
        created = post("/api/career", {
            "title": "合成复验到面试", "goal": "如实解释小样本检索与迁移边界", "job_ids": jobs,
            "material_title": "原实验工作说明", "material_text": "端云同步需要保留上下文条件。",
        })
        goal, work_document = created["id"], created["materials"][0]["id"]
        base = "/api/career/" + goal
        post(base + "/materials", {"title": "无关资料", "text": "其他项目的业务接口与监控。"})
        inputs = {"baseline": {"terms": ["RAG"]}, "candidate": {"terms": ["端云同步"]},
                  "job_ids": jobs[:1], "document_ids": [work_document],
                  "expected_job_ids": jobs[:1], "expected_document_ids": [work_document],
                  "save": True}
        parent = post(base + "/experiments/retrieval", inputs)
        thought = "词面漏回不代表JD没有该工作；尚未验证语义效果，也不能证明个人胜任。"
        note = post(base + "/insights", {
            "task_id": parent["task_id"], "previous_view": "泛词可以覆盖具体工作表达。",
            "observation": "换了查询表达后返回了原文。", "current_view": thought,
            "open_question": "片段上限会遗漏哪份原文？",
        })["insights"][-1]
        replay = post(base + "/experiments/retrieval", {
            **inputs, "previous_task_id": parent["task_id"], "source_insight_id": note["id"],
            "hypothesis": thought, "top_k": 1,
        })
        task = replay["career"]["tasks"][-1]
        story_data = {
            "title": "合成本地检索个人练习", "source_task_id": task["id"],
            "situation": "检验泛词是否代替原文工作表达。", "action": "只调整本地查询并核对返回。",
            "result": "返回有所变化，仍存在漏回。", "limits": "未验证语义效果或生产环境。",
        }
        story = post(base + "/stories", story_data)["stories"][-1]
        model.job, model.story, model.work_document = jobs[0], story["id"], work_document
        model.story_document, model.artifact, model.thought = (
            story["document_id"], task["artifact_document_id"], thought,
        )

        def prepare(kind, **extra):
            prepared = post(base + "/prepare", {"kind": kind, **extra})
            project = client.get("/api/projects/" + goal).json()
            return next(row for row in project["steps"] if row["id"] == prepared["step_id"])

        first = prepare("interview", story_id=story["id"])
        assert first["job_ids"] == jobs[:1]
        assert set(first["public_document_ids"]) == {
            model.story_document, model.artifact, work_document,
        }
        snapshot = story["retrieval_source"]
        assert snapshot["artifact_document_id"] == task["artifact_document_id"]
        assert snapshot["note_origin"]["current_view"] == thought

        def run(step):
            post("/api/projects/" + goal + "/run", {"step_id": step["id"]})
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
            assert row["result"]["career_learning_context"]["retrieval_review"] == step[
                "career_retrieval_review"
            ]
            return row

        questions = run(first)
        feedback = prepare("answer", source_step_id=questions["step_id"], question_index=0,
                           answer="我只做了本地词面查询对照，仍有漏回，未验证语义效果。")
        assert feedback["job_ids"] == jobs[:1]
        answered = run(feedback)
        followup = prepare("followup", source_step_id=answered["step_id"])
        assert followup["job_ids"] == jobs[:1]
        run(followup)
        pitch = prepare("pitch", story_id=story["id"])
        assert pitch["job_ids"] == jobs[:1]
        assert pitch["career_retrieval_review"] == snapshot
        assert client.delete(base + "/steps/" + pitch["id"], headers=auth).status_code == 200

        # A changed practice does not silently replace the run used to prepare this story.
        changed = client.patch(base + "/tasks/" + task["id"], headers=auth, json={
            "state": "done", "outcome": "后来补记的观察，不能替换旧运行。",
            "hypothesis": "后来改动的解释。", "artifact_title": "后来的手工记录",
            "artifact_text": "这是后来的记录，不是当初保存的本地检索输入。",
        })
        assert changed.status_code == 200, changed.text
        new_artifact = changed.json()["tasks"][-1]["artifact_document_id"]
        assert new_artifact != model.artifact
        revised = client.patch(base + "/stories/" + story["id"], headers=auth, json={
            **story_data, "limits": story_data["limits"] + " 保留最初运行的边界。",
        })
        assert revised.status_code == 200, revised.text
        revised_story = revised.json()["stories"][-1]
        assert revised_story["retrieval_source"] == snapshot
        model.story_document = revised_story["document_id"]
        missing = prepare("interview", story_id=story["id"])
        assert missing["job_ids"] == jobs[:1]
        assert not missing["career_retrieval_review"]["available"]
        assert missing["career_retrieval_review"]["input"] == snapshot["input"]
        assert model.artifact not in missing["public_document_ids"]
        assert new_artifact not in missing["public_document_ids"]
        partial = run(missing)
        assert any("无法重新核对实际返回" in gap for gap in partial["result"]["gaps"])

        # An explicitly chosen new target role remains selected in the answer feedback.
        model.job = jobs[1]
        target = prepare("interview", story_id=story["id"], selected_job_ids=jobs[1:2])
        assert target["job_ids"] == jobs[1:2]
        target_questions = run(target)
        response = prepare("answer", source_step_id=target_questions["step_id"], question_index=0,
                           answer="这个岗位的适用条件仍需核对，不能用旧实验证明胜任。")
        assert response["job_ids"] == jobs[1:2]
        run(response)
        project = client.get("/api/projects/" + goal).json()
        assert model.artifact not in project["public_document_ids"]
        assert project["job_ids"] == jobs
        other = post("/api/career", {
            "title": "合成新目标", "goal": "讨论这份个人练习对另一岗位的适用条件",
            "job_ids": jobs[2:],
        })["id"]
        copied = post("/api/career/" + other + "/reuse", {
            "source_project_id": goal, "kind": "story", "record_id": story["id"],
        })["stories"][-1]
        assert not copied.get("source_task_id") and copied["retrieval_source"] == snapshot
        copied_data = {key: copied[key] for key in (
            "title", "situation", "action", "result", "limits",
        )}
        edited_copy = client.patch("/api/career/" + other + "/stories/" + copied["id"],
                                   headers=auth, json=copied_data)
        assert edited_copy.status_code == 200, edited_copy.text
        copied = edited_copy.json()["stories"][-1]
        assert copied["retrieval_source"] == snapshot
        new_prepare = post("/api/career/" + other + "/prepare", {
            "kind": "interview", "story_id": copied["id"],
        })
        other_project = client.get("/api/projects/" + other).json()
        new_step = next(row for row in other_project["steps"]
                        if row["id"] == new_prepare["step_id"])
        assert new_step["job_ids"] == jobs[2:]
        assert new_step["public_document_ids"] == [copied["document_id"]]
        assert new_step["career_retrieval_review"]["source_scope_only"]
        assert new_step["career_retrieval_review"]["source_project_id"] == goal
        model.job, model.story, model.story_document = jobs[2], copied["id"], copied["document_id"]
        model.work_document = None
        post("/api/projects/" + other + "/run", {"step_id": new_step["id"]})
        new_result = settled(client, "/api/career/" + other)["results"][0]["result"]
        assert new_result["status"] == "completed", new_result.get("stop_reason")
        assert any(row["tool"] == "read_job" for row in new_result["trace"])
        assert other_project["public_document_ids"] == [copied["document_id"]]
