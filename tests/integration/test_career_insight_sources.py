"""A user can build a belief from a chosen finding without losing its origin."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_chosen_finding_stays_a_traceable_origin_rather_than_new_evidence(tmp_path):
    database = tmp_path / "insight.db"
    upgrade(database)
    model = CareerModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成原判断回查岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
            },
        ).json()["job_id"]
        identity = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成逐条保留理解",
                "goal": "区分工具提及与个人能力证明",
                "background": "只有本地合成练习。",
                "job_ids": [job],
            },
        ).json()["id"]
        base = f"/api/career/{identity}"
        discussion = run_stage(client, identity, auth, "map")["results"][0]
        claim = discussion["result"]["claims"][2]
        assert claim["text"] != discussion["result"]["claims"][0]["text"]
        note_data = {
            "previous_view": "提到工具就说明能胜任。",
            "observation": "这里只能看到招聘资料提及工具。",
            "current_view": "我自己的理解：工具提及与能力证明需要分开，尚需实际产物。",
            "source_step_id": discussion["step_id"],
            "source_claim_index": 2,
        }
        calls = len(model.contexts)
        saved = client.post(base + "/insights", headers=auth, json=note_data)
        assert saved.status_code == 201, saved.text
        note = saved.json()["insights"][0]
        assert note["source_claim_index"] == 2 and note["current_view"] != claim["text"]
        assert len(model.contexts) == calls
        for changes in ({"source_claim_index": 99}, {"source_step_id": None}):
            rejected = client.post(base + "/insights", headers=auth, json={**note_data, **changes})
            assert rejected.status_code == 422
        run_stage(client, identity, auth, "ask", question="回查这条认识。", insight_id=note["id"])
        context = model.contexts[-1]["project_context"]["career_evidence"]
        selected = context["selected_learning_note"]
        assert selected["current_user_view"] == note_data["current_view"]
        assert selected["original_analysis"] == {
            key: claim[key] for key in ("text", "category", "basis", "requirement")
        }
        assert selected["original_analysis"]["requirement"] == "unspecified"
        assert selected["source_locators"][0]["job_id"] == job
        assert all("id" not in row for row in selected["source_locators"])
        assert "不是当前事实或新证据" in selected["source_notice"]
        edited = client.patch(base + "/insights/" + note["id"], headers=auth, json=note_data)
        assert edited.json()["insights"][0]["source_claim_index"] == 2
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()["insights"][0]
        assert reopened["source_step_id"] == discussion["step_id"]
        assert reopened["source_claim_index"] == 2
