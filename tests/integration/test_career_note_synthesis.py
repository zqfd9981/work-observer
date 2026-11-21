"""Several personal views can be researched together without rewriting their inputs."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

MATERIALS = [
    ("合成认识综合：业务核对", "任务：核对请求记录。交付物：差异清单。业务验收权未说明。"),
    ("合成认识综合：平台执行", "任务：维护异步回填执行器。交付物：执行日志和故障说明。"),
    ("合成认识综合：局部观察", "个人练习记录：相同编号仍重复写入，未控制并发，真实系统未运行。"),
]


class NoteSynthesisModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        group = personal.get("selected_learning_notes", [])
        if group:
            assert len(group) == 3
            assert all("末尾限定" in note["current_user_view"] for note in group)
            parked = next(note for note in group if not note["use_for_research"])
        else:
            selected = personal["selected_learning_note"]
            assert selected.get("original_analysis") or selected["source_discussion"][
                "claims_to_recheck"]
            assert len(selected["source_locators"]) == 3
            assert len(selected["source_personal_inputs"]) == 3
            assert all("末尾限定" in note["current_user_view"]
                       for note in selected["source_personal_inputs"])
            assert "后来补充" not in selected["source_personal_inputs"][1]["current_user_view"]
        sources = [row["id"] for row in context["fixed_scope"]["public_document_titles"]
                   if row["title"].startswith("合成认识综合：")]
        assert len(sources) == 3
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs and group:
            name, args = "read_learning_note", {"note_id": parked["id"]}
        elif not any(row.get("evidence") for row in outputs):
            if group:
                assert outputs[0]["note"] == parked and "evidence" not in outputs[0]
            name, args = "read_archived_documents", {
                "reads": [{"document_id": key, "start": 0} for key in sources],
            }
        else:
            evidence = [ev for row in outputs for ev in row.get("evidence", [])]
            name, args = "finish_research", {
                "claims": [{"category": "business", "basis": "synthesis",
                            "requirement": "unspecified", "text":
                            "原文分别描述差异清单、执行日志和局部重复写入记录，不能混同交付与验收权。",
                            "evidence_ids": [ev["id"] for ev in evidence]}],
                "gaps": ["尚未说明共同验收权；个人观察未控制并发，仍需固定条件检验。"],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_selected_views_keep_full_limits_and_feed_a_reusable_synthesis(tmp_path):
    database = tmp_path / "note-synthesis.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = NoteSynthesisModel()

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

        created = save("/api/career", {"title": "合成认识综合", "goal": "把不同工作线的理解连起来"})
        identity, base = created["id"], "/api/career/" + created["id"]
        for title, text in MATERIALS:
            save(base + "/materials", {"title": title, "text": text})
        notes = []
        for index in range(3):
            question = save(base + "/questions", {"question": f"合成工作线{index}说明什么？"})[
                "questions"][-1]
            note = save(base + "/insights", {
                "previous_view": "原先混同工作对象与验收权。",
                "observation": "用户对合成原文的观察。",
                "current_view": "合成认识" + str(index) + "。" + "适用条件需要分别核对。" * 50
                + "末尾限定：只限本资料，责任和并发条件未明。",
                "open_question": "哪些工作关系仍缺少原文支持？", "question_id": question["id"],
            })["insights"][-1]
            notes.append(note)
        save(base + "/insights/" + notes[1]["id"] + "/use", {"use_for_research": False})
        before = client.get(base).json()
        ids = [note["id"] for note in notes]
        other = save("/api/career", {"title": "合成其他目标", "goal": "保持实际研究范围"})
        foreign = save("/api/career/" + other["id"] + "/insights", {
            "previous_view": "其他问题", "observation": "其他材料", "current_view": "不应选入。",
        })["insights"][0]
        for selected in ([ids[0]], [ids[0], ids[0]], [ids[0], foreign["id"]]):
            response = client.post(base + "/prepare", headers=auth, json={
                "kind": "ask", "question": "不应创建", "insight_ids": selected,
            })
            assert response.status_code == 422 and not client.get(base).json()["results"]
        assert not model.contexts
        studied = run_stage(client, identity, auth, "ask", insight_ids=ids,
                            question="合成认识综合：这些任务、交付与观察能怎样连接？")
        first = studied["results"][0]
        assert first["result"]["status"] == "completed", first["result"].get("stop_reason")
        assert first["insight_ids"] == ids
        snapshot = first["result"]["career_learning_context"]["selected_notes"]
        assert [row["id"] for row in snapshot] == ids and not snapshot[1]["use_for_research"]
        assert studied["insights"] == before["insights"]
        assert studied["questions"] == before["questions"]
        assert {ev["public_document_id"] for ev in first["result"]["evidence"]} == {
            row["id"] for row in studied["materials"]
        }

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        continued = run_stage(client, identity, auth, "ask", source_step_id=first["step_id"],
                              question="沿用这组认识，继续核对不能连接的条件。")
        assert continued["results"][0]["insight_ids"] == ids
        assert continued["results"][0]["result"]["status"] == "completed"
        synthesized = client.post(base + "/insights", headers=auth, json={
            "previous_view": "原先是三条分散认识。", "observation": "本轮回读了三份合成原文。",
            "current_view": "工作线有不同交付物，局部观察不能证明共同验收权。",
            "open_question": "如何固定并发条件？", "source_step_id": first["step_id"],
        })
        assert synthesized.status_code == 201, synthesized.text
        summary = synthesized.json()["insights"][-1]
        assert not summary.get("question_id")
        revised = {key: notes[1][key] for key in (
            "previous_view", "observation", "current_view", "open_question", "question_id",
        )}
        revised["current_view"] += " 后来补充：末尾限定仍未得到验证。"
        edited = client.patch(base + "/insights/" + ids[1], headers=auth, json=revised)
        assert edited.status_code == 200
        old = next(row for row in client.get(base).json()["results"]
                   if row["step_id"] == first["step_id"])
        assert old["result"]["career_learning_context"]["selected_notes"] == snapshot
        reviewed = run_stage(client, identity, auth, "ask", insight_id=summary["id"],
                             question="回查这份整体理解的原文依据。")
        assert reviewed["results"][0]["result"]["status"] == "completed"
        assert not next(row for row in reviewed["insights"] if row["id"] == ids[1])[
            "use_for_research"]
        assert len(model.contexts) == 8
