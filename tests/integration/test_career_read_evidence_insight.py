"""Actual read evidence remains useful when no model answer has been completed."""

import re

from starlette.testclient import TestClient
from test_career_passage_insight import NoCalls
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


def test_evidence_only_study_can_origin_a_personal_note_without_completing_research(tmp_path):
    database = tmp_path / "read-evidence.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")

    def app():
        return create_app(settings, model=NoCalls(), reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def save(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成原文独立理解", "goal": "先保留依据与未知"})
        base = "/api/career/" + goal["id"]
        texts = [
            "合成甲🤔\r\n任务产生差异清单，验收权限未知。",
            "合成乙🤔\r\n另一场景记录运行日志，不能据同名工具推断相同权限。",
        ]
        ids = [
            save(base + "/materials", {"title": "合成原文" + str(index), "text": text})[
                "materials"
            ][-1]["id"]
            for index, text in enumerate(texts)
        ]
        qid = save(
            base + "/questions",
            {
                "question": "这两份说明的交付与权限如何区分？",
                "material_ids": ids,
            },
        )["questions"][-1]["id"]
        before = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=qid,
            question="先整理已保存原文。",
            offline=True,
        )
        source = before["results"][0]
        assert source["result"]["status"] == "evidence_only"
        assert not source["result"]["claims"]
        evidence = source["result"]["evidence"]
        assert len(evidence) == 2
        references = [
            {key: row[key] for key in ("public_document_id", "start", "end")} for row in evidence
        ]
        after = save(
            base + "/insights",
            {
                "question_id": qid,
                "source_step_id": source["step_id"],
                "source_claim_index": None,
                "source_passages": references,
                "previous_view": "原先只看工具名称。",
                "observation": "现在分别核对原文的对象与限定。",
                "current_view": "先保留不同交付与权限的未知，再继续查证。",
                "open_question": "实际由谁验收这些交付物？",
            },
        )
        note = after["insights"][-1]
        assert note["source_step_id"] == source["step_id"] and note["source_claim_index"] is None
        assert [row["quote"] for row in note["source_passages"]] == [
            row["quote"] for row in evidence
        ]
        assert after["results"] == before["results"] and after["usage"] == before["usage"]
        assert after["usage"]["calls"] == 0
        project = client.get("/api/projects/" + goal["id"]).json()
        store = ResearchStore(tmp_path / "checkpoints.db", namespace=str(database.resolve()))
        notebook = LearningNotebook(lambda: project, store)
        recalled = notebook.read(note["id"])["note"]
        assert len(recalled["source_locators"]) == 2
        assert "original_analysis" not in recalled
        assert all("evidence_ids" not in row for row in recalled["source_locators"])
        assert notebook.search(["合成原文1"])["matching_count"] == 1

    with TestClient(app(), base_url="http://127.0.0.1") as reopened:
        saved = reopened.get(base).json()
        assert saved["insights"][-1] == note
        assert saved["results"][0]["result"]["status"] == "evidence_only"
        assert saved["usage"]["calls"] == 0
