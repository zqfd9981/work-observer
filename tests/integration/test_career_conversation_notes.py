"""A reported conversation is full work material linked to its inquiry, never a JD."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class ConversationModel(ModelClient):
    def __init__(self):
        self.last_usage, self.contexts = {}, []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        inquiry = context["project_context"]["career_evidence"]["selected_inquiry"]
        document_id = inquiry["evidence_passages"][-1]["public_document_id"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        documents = [row for row in outputs if row.get("document", {}).get("id") == document_id]
        if not outputs:
            name, arguments = "read_job", {
                "job_id": context["fixed_scope"]["jobs"][0]["id"], "start": 0,
            }
        elif not documents or documents[-1]["has_more"]:
            name, arguments = "read_archived_document", {
                "document_id": document_id,
                "start": documents[-1]["next_start"] if documents else 0,
            }
        else:
            evidence = [item for row in documents for item in row["evidence"]]
            whole = "".join(item["quote"] for item in evidence)
            assert "用户自己的转述" in whole and "末尾限定" in whole
            assert "尚未确认岗位个人验收权" in whole
            assert all(item["evidence_kind"] == "work_material" for item in evidence)
            name, arguments = "finish_research", {
                "claims": [{
                    "category": "responsibility", "basis": "inference",
                    "requirement": "unspecified",
                    "text": "据合成用户转述，上线审批仍须进一步核实，不能视为正式岗位权限。",
                    "evidence_ids": [outputs[0]["evidence"][0]["id"], evidence[0]["id"],
                                     evidence[-1]["id"]],
                }],
                "gaps": ["转述中的团队说明与岗位个人责任仍需分别核实。"],
            }
        call = {"type": "function_call", "name": name, "arguments": json.dumps(arguments),
                "call_id": str(len(history))}
        return [call], call


def test_long_reported_reply_is_complete_and_available_after_newer_materials(tmp_path):
    database = tmp_path / "conversation.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = ConversationModel()
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        job = post("/api/import", {
            "title": "合成沟通查证岗位", "company": "合成团队", "data_kind": "synthetic",
            "description": "负责接口失败验证，交付测试记录；个人上线权限未说明。",
        })["job_id"]
        identity = post("/api/career", {
            "title": "合成：把访谈答复带回原调查", "goal": "核对责任与验收边界", "job_ids": [job],
        })["id"]
        base = "/api/career/" + identity
        conclusion = "个人验收责任仍未知，不把团队工作当成个人权限。"
        question = post(base + "/questions", {
            "question": "这个岗位需要独立验收与上线吗？", "state": "answered",
            "conclusion": conclusion,
            "selected_job_ids": [job],
        })["questions"][0]
        answer = ("🙂开头条件：只讨论团队分工，不代表个人权限。\n"
                  + "合成沟通场景细节，不是企业事实。" * 400
                  + "\n末尾限定：平台上线由另一团队审批，尚未确认岗位个人验收权。")
        note = {"asked_question": "谁负责验收与上线？", "answer": answer,
                "wording": "paraphrased", "speaker": "合成招聘同事（虚构）",
                "context": "虚构访谈练习，不是真实企业反馈。",
                "said_when": "只知道是上周，确切日期未知",
                "limits": "仅是团队说明，需进一步确认个人分工和适用时间。"}
        saved = post(base + "/questions/" + question["id"] + "/conversation-notes", note)
        assert not model.contexts and saved["questions"][0]["conclusion"] == conclusion
        passage = saved["questions"][0]["evidence_passages"][0]
        document = client.get("/api/public-documents/" + passage["public_document_id"]).json()
        text = document["text"]
        assert answer in text and note["limits"] in text and note["said_when"] in text
        assert "用户自己的转述" in text and "正式招聘原文" in text
        assert document["evidence_kind"] == "work_material"
        assert passage["quote"] == answer[-2000:]
        assert text[passage["start"]:passage["end"]] == passage["quote"]
        assert passage["relation"] == "unclassified" and "完整记录" in passage["user_note"]
        for index in range(21):
            post(base + "/materials", {"title": f"合成无关补充{index}", "text": "只作库存占位。"})
        researched = run_stage(client, identity, auth, "ask", question=question["question"],
                               question_id=question["id"])
        row = researched["results"][0]
        assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
        assert row["result"]["model_calls"] == 4
        assert passage["public_document_id"] in row["document_ids"] and row["omitted_documents"]
        assert "用户提供的沟通、访谈或转述" in model.contexts[-1]["question"]
        assert researched["questions"][0]["conclusion"] == conclusion
        assert researched["questions"][0]["state"] == "answered"
        invalid = client.post(base + "/questions/" + "f" * 32 + "/conversation-notes",
                              headers=auth, json=note)
        assert invalid.status_code == 422
        assert len(client.get(base).json()["materials"]) == 22
        quoted = post(base + "/questions/" + question["id"] + "/conversation-notes", {
            "asked_question": "个人分工是否已确认？",
            "answer": "合成原话：暂未确认，仍需进一步问清。",
            "wording": "quoted",
        })["questions"][0]["evidence_passages"][-1]
        quoted_source = client.get("/api/public-documents/" + quoted["public_document_id"]).json()
        quoted_text = quoted_source["text"]
        assert "用户记录的原话（系统未独立核实）" in quoted_text
        assert "发生时间（用户填写，未核实）：未说明" in quoted_text
        unchanged = client.get("/api/public-documents/" + passage["public_document_id"]).json()
        assert unchanged["text"] == text
