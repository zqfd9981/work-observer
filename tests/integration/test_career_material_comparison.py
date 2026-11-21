"""Explicitly selected material groups stay available to the Agent and its follow-up."""

import hashlib
import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class MaterialComparisonModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        selected = [row["document_id"] for row in personal["selected_materials"]]
        assert 1 <= len(selected) <= 6 and len(set(selected)) == len(selected)
        assert personal["selected_material"] is None
        catalog = {row["id"]: row for row in context["fixed_scope"]["public_document_titles"]}
        assert set(selected) <= set(catalog)
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_archived_documents", {
                "reads": [{"document_id": key, "start": 0} for key in selected],
            }
        else:
            evidence = outputs[0]["evidence"]
            assert {item["public_document_id"] for item in evidence} == set(selected)
            name, args = "finish_research", {
                "claims": [{"category": "business", "basis": "direct",
                            "requirement": "unspecified", "text":
                            catalog[item["public_document_id"]]["title"] + "记录：" + item["quote"],
                            "evidence_ids": [item["id"]]} for item in evidence],
                "gaps": ["原文分别描述各自工作条件，不能把一侧任务接到另一侧产出。"
                         "用户提供的资料还需核实，未能重读的内容仍未知。"],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_selected_materials_survive_catalog_limits_continuation_and_reopening(tmp_path):
    database = tmp_path / "material-comparison.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MaterialComparisonModel()

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, payload):
            response = client.post(path, headers=auth, json=payload)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        created = post("/api/career", {"title": "合成：多份原文对读", "goal": "保留不同工作线"})
        identity = created["id"]
        base = "/api/career/" + identity
        documents = []
        for index in range(6):
            text = ("归集投研信息，交付内部检索工具和观察记录；投资决定权未知。"
                    if index % 2 == 0 else
                    "调研种子用户并迭代原型，交付产品MVP；不代表内部工具的工作产出。")
            data = post(base + "/materials", {"title": f"合成资料对读{index}",
                        "text": text, "source_name": "虚构工作说明，尚未独立核实"})
            documents.append(data["materials"][-1]["id"])
        for index in range(22):
            post(base + "/materials", {"title": f"合成较新无关记录{index}", "text": "其他记录。"})
        selected = documents[::-1]
        raw_before = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in settings.raw_directory.rglob("*") if path.is_file()}
        first = run_stage(client, identity, auth, "ask", material_ids=selected,
                          question="对读选定的工作说明，保留各自任务和交付对象。")["results"][0]
        assert first["result"]["status"] == "completed", first["result"].get("stop_reason")
        assert first["material_ids"] == selected and first["material_id"] is None
        assert first["result"]["model_calls"] == 2 and first["omitted_documents"] == 8
        assert set(selected) <= set(first["document_ids"]) and len(first["document_ids"]) == 20
        assert {row["public_document_id"] for row in first["result"]["evidence"]} == set(selected)
        followed = run_stage(client, identity, auth, "ask", source_step_id=first["step_id"],
                             question="同一组资料里哪些条件还不能互相套用？")["results"][0]
        assert followed["result"]["status"] == "completed"
        assert followed["material_ids"] == selected
        override = [documents[1], documents[4]]
        changed = run_stage(client, identity, auth, "ask", source_step_id=first["step_id"],
                            material_ids=override, question="这次明确只重点对读选中的两份。")[
                                "results"][0]
        assert changed["result"]["status"] == "completed" and changed["material_ids"] == override
        assert {row["public_document_id"] for row in changed["result"]["evidence"]} == set(override)
        single = run_stage(client, identity, auth, "ask", material_ids=[documents[0]],
                           question="只重点回查其中一份。")["results"][0]
        assert single["result"]["status"] == "completed" and single["material_ids"] == documents[:1]
        other = post("/api/career", {"title": "合成别的目标", "goal": "保持实际选择"})
        foreign = post("/api/career/" + other["id"] + "/materials", {
            "title": "合成外部范围资料", "text": "这份资料没有加入目标。",
        })["materials"][0]["id"]
        for payload in [
            {"kind": "ask", "material_ids": [documents[0], foreign]},
            {"kind": "ask", "material_ids": [documents[0], documents[0]]},
            {"kind": "ask", "material_ids": documents + [foreign]},
            {"kind": "ask", "material_id": documents[0], "material_ids": documents[1:3]},
            {"kind": "role", "material_ids": documents[:2]},
        ]:
            response = client.post(base + "/prepare", headers=auth,
                                   json={"question": "不应开始研究", **payload})
            assert response.status_code == 422, response.text
        removed = client.delete(base + "/materials/" + selected[0], headers=auth)
        assert removed.status_code == 200
        for payload in [{"material_ids": selected}, {"source_step_id": first["step_id"]}]:
            response = client.post(base + "/prepare", headers=auth, json={
                "kind": "ask", "question": "不能悄悄少读一侧或自动恢复原文。", **payload,
            })
            assert response.status_code == 422 and "移出" in response.json()["message"]
        assert selected[0] not in client.get(base).json()["document_ids"]
        assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in raw_before
                } == raw_before
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()
        retained = next(row for row in reopened["results"] if row["step_id"] == first["step_id"])
        assert retained["material_ids"] == selected
        assert retained["result"]["claims"] == first["result"]["claims"]
        assert retained["result"]["scope"]["public_document_titles"] == (
            first["result"]["scope"]["public_document_titles"]
        )
