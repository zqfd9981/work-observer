"""Collected originals refer to a concrete explanation, even when that explanation changes."""

import hashlib
import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class PassageHypothesesModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        inquiry = context["project_context"]["career_evidence"]["selected_inquiry"]
        assert inquiry["hypothesis_a"] and inquiry["hypothesis_b"]
        passages = inquiry["evidence_passages"]
        assert any(row.get("target_view") for row in passages)
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            allowed = {row["id"] for row in context["fixed_scope"]["public_document_titles"]}
            documents = list(dict.fromkeys(row["public_document_id"] for row in passages
                                           if row["public_document_id"] in allowed))
            name, args = "read_archived_documents", {
                "reads": [{"document_id": key, "start": 0} for key in documents],
            }
        else:
            evidence = outputs[0]["evidence"]
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "synthesis",
                            "requirement": "unspecified", "text":
                            "合成说明分别描述已有能力配置和复杂集成开发，工作条件仍需分别核实。",
                            "evidence_ids": [item["id"] for item in evidence]}],
                "gaps": ["用户支持或挑战的标注不是事实；原句变更后仍需重核适用条件。"],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_passages_keep_their_exact_explanation_and_research_rereads_their_sources(tmp_path):
    database = tmp_path / "passage-hypotheses.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = PassageHypothesesModel()
    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def save(path, payload, method="post"):
            response = getattr(client, method)(path, headers=auth, json=payload)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        texts = ["合成配置说明：已有能力只需配置和核对参数，复杂集成未说明。",
                 "合成集成说明：复杂集成需要开发适配接口和测试，验收权限未知。"]
        goal = save("/api/career", {"title": "合成：把原文对照到具体解释",
                    "goal": "区分工作条件，保留相反线索", "material_title": "合成解释对读配置",
                    "material_text": texts[0]})
        base = "/api/career/" + goal["id"]
        first = goal["materials"][0]["id"]
        documents = save(base + "/materials", {"title": "合成解释对读集成", "text": texts[1]})
        second = next(row["id"] for row in documents["materials"] if row["id"] != first)
        a = "已有能力配置可能无需开发接口。" + "只限既有能力场景，复杂集成尚未知；" * 29
        b = "复杂集成可能需要开发适配接口，但不代表所有配置工作都要写代码。"
        qdata = {"question": "配置和集成开发为何有不同的工作要求？", "hypothesis_a": a,
                 "hypothesis_b": b, "conclusion": "目前保留两种解释，实际分工仍需查证。",
                 "state": "answered"}
        question = save(base + "/questions", qdata)["questions"][0]
        qpath = base + "/questions/" + question["id"]
        annotations = []
        for doc, text, relation, view in [
            (first, texts[0], "supports", a), (second, texts[1], "supports", b),
            (second, texts[1], "challenges", a), (first, texts[0], "unclassified", ""),
        ]:
            saved = save(qpath + "/passages", {
                "passage": {"public_document_id": doc, "start": 0, "end": len(text)},
                "relation": relation, "target_view": view, "user_note": "先核对适用场景。",
            })
            annotations.append(saved["questions"][0]["evidence_passages"][-1])
        assert not model.contexts
        raw_before = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in settings.raw_directory.rglob("*") if path.is_file()}
        studied = run_stage(client, goal["id"], auth, "ask", question_id=question["id"],
                            question="按每句具体解释核对原文，不按材料条数选胜者。")
        result = studied["results"][0]
        assert result["result"]["status"] == "completed", result["result"].get("stop_reason")
        assert result["result"]["model_calls"] == 2
        sent = model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"]
        assert sent["evidence_passages"] == annotations
        assert {first, second} == {row["public_document_id"]
                                   for row in result["result"]["evidence"]}
        changed_a = "配置阶段也可能需要少量适配，需单独核对交付边界。"
        updated = save(qpath, {**qdata, "hypothesis_a": changed_a}, "patch")["questions"][0]
        assert updated["evidence_passages"] == annotations
        found = client.get(base + "/search", params={"q": "只限既有能力场景"}).json()
        assert any(row["kind"] == "question" and row["id"] == question["id"]
                   for row in found["records"])
        rerun = run_stage(client, goal["id"], auth, "ask", question_id=question["id"],
                          question="解释A调整后，旧原句的标注还能说明什么？")
        assert rerun["results"][0]["result"]["status"] == "completed"
        context = model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"]
        assert context["hypothesis_a"] == changed_a
        assert context["evidence_passages"][0]["target_view"] == a
        calls = len(model.contexts)
        corrected = save(qpath + "/passages/" + annotations[0]["id"], {
            "relation": "conditions", "target_view": changed_a,
            "user_note": "手动改为针对新解释；原文只描述已有能力。",
        }, "patch")["questions"][0]
        assert len(model.contexts) == calls
        assert corrected["evidence_passages"][0]["quote"] == annotations[0]["quote"]
        assert corrected["evidence_passages"][0]["target_view"] == changed_a
        assert corrected["evidence_passages"][2]["target_view"] == a
        assert corrected["conclusion"] == qdata["conclusion"] and corrected["state"] == "answered"
        assert sent["evidence_passages"][0]["target_view"] == a
        assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in raw_before
                } == raw_before
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()
        retained = reopened["questions"][0]
        assert retained["hypothesis_a"] == changed_a
        assert retained["evidence_passages"] == corrected["evidence_passages"]
        historical = next(row for row in reopened["results"] if row["step_id"] == result["step_id"])
        assert historical["result"]["claims"] == result["result"]["claims"]
        assert historical["result"]["evidence"] == result["result"]["evidence"]
