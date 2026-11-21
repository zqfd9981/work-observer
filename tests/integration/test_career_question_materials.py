"""A saved inquiry remembers its materials; explicit one-round choices remain independent."""

import hashlib
import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class QuestionMaterialModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        catalog = {row["id"]: row for row in context["fixed_scope"]["public_document_titles"]}
        selected = [row["document_id"] for row in personal["selected_materials"]]
        if personal["selected_material"]:
            assert not selected
            selected = [personal["selected_material"]["document_id"]]
        if not selected:
            selected = [next(iter(catalog))]
        assert set(selected) <= set(catalog)
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_archived_documents", {
                "reads": [{"document_id": key, "start": 0} for key in selected],
            }
        else:
            evidence = outputs[0]["evidence"]
            assert {row["public_document_id"] for row in evidence} == set(selected)
            name, args = "finish_research", {
                "claims": [{"category": "business", "basis": "direct",
                            "requirement": "unspecified", "text":
                            catalog[row["public_document_id"]]["title"] + "记录：" + row["quote"],
                            "evidence_ids": [row["id"]]} for row in evidence],
                "gaps": ["这些用户提供的资料仍需核实，不能直接证明实际分工或个人权限。"],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_inquiry_material_defaults_survive_reopening_and_allow_explicit_overrides(tmp_path):
    database = tmp_path / "question-materials.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = QuestionMaterialModel()

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

        goal = save("/api/career", {"title": "合成：调查记住重点资料",
                    "goal": "持续核对工作与条件"})
        identity = goal["id"]
        base = "/api/career/" + identity
        documents = []
        for index in range(3):
            data = save(base + "/materials", {"title": f"合成默认资料{index}",
                        "text": f"合成工作说明{index}：记录局部工作和交付条件，实际权限未知。"})
            documents.append(data["materials"][-1]["id"])
        for index in range(22):
            save(base + "/materials", {"title": f"其他合成资料{index}", "text": "其他背景。"})
        qdata = {"question": "实际工作和交付条件之间有什么关系？", "state": "answered",
                 "conclusion": "先保留局部说明，实际分工仍需核实。"}
        question = save(base + "/questions", {**qdata, "material_ids": documents[:2]})[
            "questions"][0]
        qpath = base + "/questions/" + question["id"]
        assert question["material_ids"] == documents[:2] and not model.contexts
        original_raw = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in settings.raw_directory.rglob("*") if path.is_file()}
        first = run_stage(client, identity, auth, "ask", question_id=question["id"],
                          question=qdata["question"])["results"][0]
        assert first["result"]["status"] == "completed", first["result"].get("stop_reason")
        assert first["material_ids"] == documents[:2] and first["omitted_documents"] == 5
        assert set(documents[:2]) <= set(first["document_ids"])
        defaults = documents[1:]
        updated = save(qpath, {**qdata, "material_ids": defaults}, "patch")["questions"][0]
        assert updated["material_ids"] == defaults and updated["conclusion"] == qdata["conclusion"]
        # An unrelated question edit omitting this field keeps its saved material defaults.
        retained = save(qpath, {**qdata, "next_evidence": "保留未知，补实际分工。"}, "patch")
        assert retained["questions"][0]["material_ids"] == defaults
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        assert client.get(base).json()["questions"][0]["material_ids"] == defaults
        reopened = run_stage(client, identity, auth, "ask", question_id=question["id"],
                             question="重新打开后继续查证。")["results"][0]
        assert reopened["result"]["status"] == "completed" and reopened["material_ids"] == defaults
        overridden = run_stage(client, identity, auth, "ask", question_id=question["id"],
                               material_ids=documents[:1], question="本轮临时只重点读一份。")[
                                   "results"][0]
        assert overridden["result"]["status"] == "completed"
        assert overridden["material_ids"] == documents[:1]
        cleared_once = run_stage(client, identity, auth, "ask", question_id=question["id"],
                                 material_ids=[], question="本轮不固定重点原文。")["results"][0]
        assert cleared_once["result"]["status"] == "completed"
        assert cleared_once["material_ids"] == []
        assert model.contexts[-1]["project_context"]["career_evidence"]["selected_materials"] == []
        single = run_stage(client, identity, auth, "ask", question_id=question["id"],
                           material_id=documents[0], question="本轮使用单份资料入口。")[
                               "results"][0]
        assert single["result"]["status"] == "completed"
        assert single["material_id"] == documents[0] and single["material_ids"] == []
        continued = run_stage(client, identity, auth, "ask", source_step_id=single["step_id"],
                              question="沿这份单独资料的讨论继续。")["results"][0]
        assert continued["result"]["status"] == "completed"
        assert continued["material_id"] == documents[0] and continued["material_ids"] == []
        assert client.get(base).json()["questions"][0]["material_ids"] == defaults
        other = client.post("/api/career", headers=auth,
                            json={"title": "合成其他目标", "goal": "另一范围"}).json()
        foreign = client.post("/api/career/" + other["id"] + "/materials", headers=auth,
                              json={"title": "未选入资料", "text": "这份不在原调查目标。"}).json()[
                                  "materials"][0]["id"]
        for material_ids in [[foreign], [documents[0], documents[0]], documents * 3]:
            response = client.patch(qpath, headers=auth,
                                    json={**qdata, "material_ids": material_ids})
            assert response.status_code == 422, response.text
        assert client.delete(base + "/materials/" + defaults[0], headers=auth).status_code == 200
        response = client.post(base + "/prepare", headers=auth,
                               json={"kind": "ask", "question_id": question["id"],
                                     "question": "不能悄悄跳过或重新加入缺少的重点原文。"})
        assert response.status_code == 422 and "移出" in response.json()["message"]
        # Keeping an already-saved unavailable reference does not block editing the inquiry itself.
        kept = client.patch(qpath, headers=auth, json={**qdata, "material_ids": defaults,
                            "hypothesis_a": "可能是不同条件，需要补证。"})
        assert kept.status_code == 200 and kept.json()["questions"][0]["material_ids"] == defaults
        cleared = client.patch(qpath, headers=auth, json={**qdata, "material_ids": []})
        assert cleared.status_code == 200
        final = client.get(base).json()
        assert final["questions"][0]["material_ids"] == []
        assert final["questions"][0]["conclusion"] == qdata["conclusion"]
        assert defaults[0] not in final["document_ids"]
        historical = next(row for row in final["results"] if row["step_id"] == first["step_id"])
        assert historical["material_ids"] == documents[:2]
        assert historical["result"]["claims"] == first["result"]["claims"]
        assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in original_raw
                } == original_raw
