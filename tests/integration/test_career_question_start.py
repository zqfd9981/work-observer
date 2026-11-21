"""Save the first question with its source and reopen it before any model execution."""

import re

from starlette.testclient import TestClient
from test_career_question_materials import QuestionMaterialModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_question_start_persists_focus_and_original_before_research(tmp_path):
    database = tmp_path / "question-start.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = QuestionMaterialModel()

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    first = "合成默认资料调查：" + "如何理解工作原文与实际交付的边界？" * 60
    first = first[:960] + "末尾问题：材料没有说明的验收权应怎样核实？"
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        response = client.post("/api/career", headers=auth, json={
            "title": "合成从问题开始", "goal": "沿工作原文持续查证", "first_question": first,
            "material_title": "合成起始说明",
            "material_text": "任务：核对记录。交付：差异清单。验收权未说明。",
            "resume_text": "合成个人简历，不作为工作原文的默认选择。",
        })
        assert response.status_code == 201, response.text
        created = response.json()
        identity = created["id"]
        question = created["questions"][0]
        source = created["materials"][0]["id"]
        assert created["focus_question_id"] == question["id"]
        assert question["question"] == first and question["state"] == "open"
        assert not question["conclusion"] and question["material_ids"] == [source]
        assert created["resume"]["document_id"] not in question["material_ids"]
        assert not created["results"] and not model.contexts
        before = len(client.get("/api/career").json())
        invalid = client.post("/api/career", headers=auth, json={
            "title": "不应创建", "goal": "保留原记录", "first_question": "问" * 1001,
        })
        assert invalid.status_code == 422 and len(client.get("/api/career").json()) == before
        pending = client.post("/api/career", headers=auth, json={
            "title": "合成仅记录未知", "goal": "稍后补充资料",
            "first_question": "这项职责究竟交付什么？",
        }).json()
        assert pending["focus_question_id"] == pending["questions"][0]["id"]
        assert not pending["document_ids"] and not pending["results"]
        legacy = client.post("/api/career", headers=auth, json={
            "title": "合成长期目标", "goal": "先保存广泛方向", "resume_text": "合成个人背景。",
        }).json()
        assert not legacy["questions"] and not legacy["focus_question_id"]
        assert legacy["resume"] and not model.contexts

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        reopened = client.get("/api/career/" + identity).json()
        assert reopened["focus_question_id"] == question["id"]
        assert reopened["questions"][0] == question
        studied = run_stage(client, identity, auth, "ask", question_id=question["id"],
                            question=first)
        result = studied["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert {row["public_document_id"] for row in result["evidence"]} == {source}
        assert studied["questions"][0] == question
