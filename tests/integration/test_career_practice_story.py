"""Practice-derived interview material keeps its reported origin and original text."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class PracticeStoryModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        story = context["project_context"]["career_evidence"]["selected_story"]
        assert story["source_task_id"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_archived_document", {"document_id": story["document_id"], "start": 0}
        else:
            evidence = outputs[0]["evidence"][0]
            assert "由个人练习整理" in evidence["quote"] and "来源练习" in evidence["quote"]
            assert "仍新增一行" in evidence["quote"] and "并发未测试" in evidence["quote"]
            name, args = "finish_research", {
                "claims": [{"category": "responsibility", "basis": "direct",
                            "requirement": "unspecified", "text":
                            "用户保存的是个人练习记录：重复提交仍新增一行，并发未测试。",
                            "evidence_ids": [evidence["id"]]}],
                "gaps": ["这份记录尚未独立核验，不能当作企业工作经历或生产效果。"],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_practice_story_keeps_origin_when_reopened_and_used_for_interview(tmp_path):
    database = tmp_path / "practice-story.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = PracticeStoryModel()

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def save(path, data, method="post"):
            response = getattr(client, method)(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        created = save("/api/career", {"title": "合成练习证据整理", "goal": "解释实验结果",
                        "first_question": "合成练习取材：重复提交的解释如何检验？",
                        "material_title": "合成说明", "material_text": "按编号核对回填记录。"})
        identity = created["id"]
        base = f"/api/career/{identity}"
        task = save(base + "/experiments", {
            "title": "合成重复提交练习", "question_id": created["focus_question_id"],
            "task_or_ability": "理解回填条件", "deliverable": "观察记录",
            "completion_check": "比较两组输入",
        })["tasks"][0]
        story = {"title": "合成个人练习记录", "situation": "检验重复提交的解释",
                 "action": "记录输入A、A后核对行数；原先预期不会新增。",
                 "result": "重复提交后仍新增一行，与原先预期不同。",
                 "limits": "这是个人练习；并发未测试，真实环境未验证。",
                 "source_task_id": task["id"]}
        rejected = client.post(base + "/stories", headers=auth, json=story)
        assert rejected.status_code == 422 and not client.get(base).json()["stories"]
        observed = save(base + "/tasks/" + task["id"], {
            "state": "done", "outcome": "重复提交仍新增一行，未控制并发。",
            "comparison_conditions": "合成表格；并发未测试。",
            "comparison_rows": [{"condition": "重复编号", "input": "提交A、A",
                                 "expected": "第二次不新增", "observed": "仍新增一行"}],
        }, "patch")["tasks"][0]
        other = save("/api/career", {"title": "合成另一个目标", "goal": "不混入其他目标练习"})
        foreign = client.post(f"/api/career/{other['id']}/stories", headers=auth, json=story)
        assert foreign.status_code == 422
        saved = save(base + "/stories", story)["stories"][0]
        assert saved["source_task_id"] == task["id"] and not model.contexts
        document = client.get("/api/public-documents/" + saved["document_id"]).json()["text"]
        assert "由个人练习整理，不代表企业工作经历或生产效果。" in document
        assert task["title"] in document and story["result"] in document
        assert client.get(base).json()["tasks"][0] == observed

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        reopened = client.get(base).json()
        assert reopened["stories"][0] == saved
        studied = run_stage(client, identity, auth, "pitch", story_id=saved["id"])
        result = studied["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert {row["public_document_id"] for row in result["evidence"]} == {saved["document_id"]}
        assert studied["stories"][0] == saved and len(model.contexts) == 2
        response = client.patch(base + "/tasks/" + task["id"], headers=auth, json={
            "state": "planned", "outcome": "", "comparison_rows": [],
        })
        assert response.status_code == 200
        assert client.get(base).json()["stories"][0] == saved
        assert (client.get("/api/public-documents/" + saved["document_id"]).json()["text"]
                == document)
        reused = client.post(f"/api/career/{other['id']}/reuse", headers=auth, json={
            "source_project_id": identity, "kind": "story", "record_id": saved["id"],
        })
        assert reused.status_code == 200, reused.text
        copied = reused.json()["stories"][0]
        assert not copied.get("source_task_id") and copied["document_id"] == saved["document_id"]
        payload = {key: copied[key] for key in ("title", "situation", "action", "result", "limits")}
        edited = client.patch(f"/api/career/{other['id']}/stories/{copied['id']}",
                              headers=auth, json=payload)
        assert edited.status_code == 200, edited.text
        edited = client.patch(base + "/stories/" + saved["id"], headers=auth,
                              json={**story, "limits": story["limits"] + " 保留当时观察。"})
        assert edited.status_code == 200, edited.text
        assert edited.json()["stories"][0]["source_task_id"] == task["id"]
