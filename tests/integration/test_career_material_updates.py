"""A corrected work note can be used to revisit an inquiry without rewriting its history."""

import json
import re
from pathlib import Path

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class MaterialUpdateModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        selected = personal["selected_material"]["document_id"]
        assert selected in [row["id"] for row in context["fixed_scope"]["public_document_titles"]]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_archived_document", {"document_id": selected, "start": 0}
        else:
            evidence = outputs[-1]["evidence"][0]
            assert evidence["public_document_id"] == selected
            corrected = "负责人复核" in evidence["quote"]
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "direct",
                            "requirement": "unspecified", "text": (
                                "合成工作记录描述构造失败请求，交付记录后由负责人复核。"
                                if corrected else "合成工作记录描述构造失败请求并交付记录。"
                            ), "evidence_ids": [evidence["id"]]}],
                "gaps": ["粘贴笔记未经独立核实，实际生产权限和岗位个人责任仍未知。"],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_corrected_material_revisits_an_inquiry_and_keeps_original_sources(tmp_path):
    database = tmp_path / "material-updates.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MaterialUpdateModel()
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        original = "合成工作记录：构造失败请求并交付记录；生产权限未知。"
        goal = post("/api/career", {"title": "合成：调查笔记补充后继续查证",
                    "goal": "理解验证和责任边界", "material_title": "合成资料补充原文",
                    "material_text": original, "resume_text": "虚构个人经历，不能当作工作原文。"})
        identity, old = goal["id"], goal["materials"][0]["id"]
        base = "/api/career/" + identity
        old_source = client.get("/api/public-documents/" + old).json()
        first = run_stage(client, identity, auth, "ask", question="这份记录描述什么工作？",
                          material_id=old)["results"][0]
        assert first["result"]["status"] == "completed", first["result"].get("stop_reason")
        conclusion = "原先只看到构造失败请求和记录，交付后的责任未知。"
        question = post(base + "/questions", {
            "question": "交付记录后谁复核，个人责任到哪里？", "state": "answered",
            "conclusion": conclusion, "source_step_id": first["step_id"],
            "conclusion_step_id": first["step_id"],
            "source_passage": {"public_document_id": old, "start": 0, "end": len(original)},
        })["questions"][0]
        other = post("/api/career", {"title": "合成其他调查", "goal": "保留另一个调查的范围"})
        post("/api/career/" + other["id"] + "/materials/attach", {"document_id": old})
        unrelated = post(base + "/materials", {"title": "合成无关资料", "text": "无关记录"})
        unrelated_id = next(row["id"] for row in unrelated["materials"] if row["id"] != old)
        correction = {"title": "合成资料补充原文", "text":
                      "合成工作记录：构造失败请求，交付记录后由负责人复核；生产权限未知。",
                      "source_name": "虚构调查笔记，待核实"}
        url = base + "/materials/" + old + "/revisions"
        assert client.post(url, json=correction).status_code == 403
        for target, values in [
            (url, {**correction, "base_document_id": unrelated_id}),
            (base + "/materials/" + goal["resume"]["document_id"] + "/revisions", correction),
            ("/api/career/" + other["id"] + "/materials/" + unrelated_id + "/revisions",
             correction),
        ]:
            response = client.post(target, headers=auth, json=values)
            assert response.status_code == 422, response.text
        updated = post(url, correction)
        current = next(row for row in updated["materials"] if row["id"] != unrelated_id)
        new = current["id"]
        assert new != old and set(current["related_document_ids"]) == {old, new}
        assert old not in updated["document_ids"] and new in updated["document_ids"]
        assert updated["questions"][0] == question
        assert client.get("/api/career/" + other["id"]).json()["document_ids"] == [old]
        retained = client.get("/api/public-documents/" + old).json()
        assert retained["text"] == original and retained["evidence"] == old_source["evidence"]
        assert retained["sha256"] == old_source["sha256"]
        assert any(path.read_bytes() == original.encode() for path in
                   (settings.raw_directory / "public").glob("*.txt"))
        stale = client.post(url, headers=auth, json=correction)
        assert stale.status_code == 422
        checked = run_stage(client, identity, auth, "ask", question="补充后请重新核对原判断。",
                            material_id=new, question_id=question["id"])["results"][0]
        assert checked["result"]["status"] == "completed", checked["result"].get("stop_reason")
        assert checked["question_id"] == question["id"] and checked["result"]["model_calls"] == 2
        assert checked["result"]["evidence"][0]["public_document_id"] == new
        assert "负责人复核" in checked["result"]["claims"][0]["text"]
        assert client.get(base).json()["questions"][0] == question
        before_files = set(Path(settings.raw_directory / "public").glob("*.txt"))
        # Another goal can deliberately adopt the already-corrected text on reopening its editor.
        adopted = post("/api/career/" + other["id"] + "/materials/" + old + "/revisions",
                       {**correction, "base_document_id": new})
        assert adopted["document_ids"] == [new]
        assert set(Path(settings.raw_directory / "public").glob("*.txt")) == before_files
        final = client.get(base).json()
        assert next(row for row in final["results"] if row["step_id"] == first["step_id"])[
            "result"]["claims"] == first["result"]["claims"]
        assert next(row for row in final["results"] if row["step_id"] == first["step_id"])[
            "result"]["evidence"] == first["result"]["evidence"]
