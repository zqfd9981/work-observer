"""Material-only research follows a counterexample and returns to the saved question."""

import json
import re
import time

from starlette.testclient import TestClient
from test_career_material_start import MaterialWorkspaceModel

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class MaterialAutonomyModel(MaterialWorkspaceModel):
    async def turn(self, history):
        returned, call = await super().turn(history)
        context = json.loads(history[1]["content"])
        personal = context["project_context"]["career_evidence"]
        rounds = (personal.get("autonomous_inquiry") or {}).get("rounds_remaining", 1)
        documents = context["fixed_scope"]["public_document_titles"]
        second = next(row for row in documents if row["title"].endswith("B"))
        if call["name"] == "read_archived_document":
            chosen = second if rounds == 2 else next(
                row for row in documents if row["title"].endswith("A")
            )
            call["arguments"] = json.dumps({"document_id": chosen["id"], "start": 0})
        elif call["name"] == "finish_research":
            outputs = [json.loads(row["output"]) for row in history
                       if row.get("type") == "function_call_output"]
            originals = [ev for output in outputs for ev in output.get("evidence", [])]
            if rounds == 1 and not any(ev.get("public_document_id") == second["id"]
                                       for ev in originals):
                call.update(name="read_archived_document", arguments=json.dumps({
                    "document_id": second["id"], "start": 0,
                }))
            elif rounds > 1 and not any(row.get("name") == "propose_investigation"
                                        for row in history):
                call.update(name="propose_investigation", arguments=json.dumps({
                    "question": "正常响应也重复写入时，原来的超时解释还成立吗？" if rounds == 3
                    else "回到原问题：哪些解释有资料支持，哪些仍需实际验证？",
                    "kind": "counterexample", "completion": "解释反例能挑战什么与不能证明什么。",
                    "evidence_needed": "读取合成工作说明B的正常响应记录，保留并发未控制的限制。",
                }))
            elif rounds == 1:
                answer = json.loads(call["arguments"])
                answer["claims"] = [{
                    "category": "task", "basis": "synthesis", "requirement": "unspecified",
                    "text": ("两份用户资料分别描述超时与正常响应时重复写入，"
                             "不能仅用超时解释所有重复；并发因素仍未知。"),
                    "evidence_ids": [ev["id"] for ev in originals],
                }]
                answer["gaps"] = [
                    "这些是用户提供的合成记录，并未独立执行；需要固定请求标识与并发条件。"
                ]
                call["arguments"] = json.dumps(answer)
            else:
                answer = json.loads(call["arguments"])
                answer["claims"] = [{"category": "task", "basis": "direct",
                                     "requirement": "unspecified",
                                     "text": "用户提供的资料记录：" + originals[0]["quote"],
                                     "evidence_ids": [originals[0]["id"]]}]
                call["arguments"] = json.dumps(answer)
        return returned, call


def test_three_material_only_rounds_read_both_originals_and_keep_user_conclusion(tmp_path):
    database = tmp_path / "material-autonomy.db"
    upgrade(database)
    model = MaterialAutonomyModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        goal = post("/api/career", {
            "title": "合成：资料反例驱动的调查", "goal": "理解重复写入的解释边界",
            "material_title": "合成工作说明A",
            "material_text": "合成记录A：超时后重复写入，原因未知。",
        })
        identity = goal["id"]
        base = f"/api/career/{identity}"
        second = post(base + "/materials", {
            "title": "合成工作说明B", "text": "合成记录B：正常响应也重复写入，尚未控制并发。",
        })["materials"][-1]
        question = post(base + "/questions", {"question": "超时能否解释重复写入？"})["questions"][0]
        prepared = post(base + "/prepare", {"kind": "ask", "question": question["question"],
                                            "question_id": question["id"], "autonomous": True})
        running = post(f"/api/projects/{identity}/run", {"step_id": prepared["step_id"]})
        assert running["max_steps"] == 3
        for _ in range(400):
            data = client.get(base).json()
            if not data["running"]:
                break
            time.sleep(0.01)
        assert len(data["results"]) == 3
        assert all(row["result"]["status"] == "completed" for row in data["results"])
        answer = data["results"][0]
        assert {ev["public_document_id"] for ev in answer["result"]["evidence"]} == {
            goal["materials"][0]["id"], second["id"],
        }
        assert all(not ctx["fixed_scope"]["jobs"] for ctx in model.contexts)
        assert not data["requirements"] and data["questions"][0]["state"] == "open"
        calls = len(model.contexts)
        conclusion = "两份合成记录使我不能只归因于超时；并发与生产效果仍未知。"
        response = client.patch(base + "/questions/" + question["id"], headers=auth, json={
            "question": question["question"], "conclusion": conclusion, "state": "answered",
            "conclusion_step_id": answer["step_id"],
        })
        assert response.status_code == 200, response.text
        assert response.json()["questions"][0]["conclusion"] == conclusion
        assert len(model.contexts) == calls
