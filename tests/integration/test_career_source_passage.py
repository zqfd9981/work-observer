"""An exact archived passage becomes a persistent, source-aware research question."""

import json
import re

from starlette.testclient import TestClient
from test_career_material_start import MaterialWorkspaceModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class PassageModel(MaterialWorkspaceModel):
    async def turn(self, history):
        context = json.loads(history[1]["content"])
        inquiry = context["project_context"]["career_evidence"].get("selected_inquiry") or {}
        document = (inquiry.get("source_passage") or {}).get("public_document_id")
        allowed = {row["id"] for row in context["fixed_scope"]["public_document_titles"]}
        if document in allowed and not any(
            row.get("type") == "function_call_output" for row in history
        ):
            self.contexts.append(context)
            call = {
                "type": "function_call",
                "name": "read_archived_document",
                "arguments": json.dumps({"document_id": document, "start": 0}),
                "call_id": str(len(history)),
            }
            return [call], call
        return await super().turn(history)


def test_material_passage_retains_exact_position_and_is_prioritized_without_restoring_scope(
    tmp_path,
):
    database = tmp_path / "source-passage.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = PassageModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        quote = "交付样例与观察，但验收权限尚未说明。"
        text = "开头🙂" + chr(13) + chr(10) + quote + chr(13) + chr(10) + "相同段落：" + quote
        goal = post(
            "/api/career",
            {
                "title": "合成原文问题",
                "goal": "从资料中的条件开始调查",
                "material_title": "合成工作说明起点",
                "material_text": text,
            },
        )
        base = "/api/career/" + goal["id"]
        document = goal["materials"][0]["id"]
        start = text.rindex(quote)
        reference = {"public_document_id": document, "start": start, "end": start + len(quote)}
        for index in range(22):
            post(
                base + "/materials",
                {"title": f"合成工作说明补充{index}", "text": "无关的补充文字。"},
            )
        question = post(
            base + "/questions",
            {
                "question": "这些产物与验收权限之间有什么关系？",
                "source_passage": reference,
            },
        )["questions"][0]
        qid = question["id"]
        assert not model.contexts
        assert question["source_passage"]["quote"] == quote
        assert question["source_passage"]["start"] == start
        assert question["source_passage"]["title"] == "合成工作说明起点"
        found = client.get(base + "/search", params={"q": quote}).json()
        assert any(row["id"] == qid and row["kind"] == "question" for row in found["records"])
        invalid = client.post(
            base + "/questions",
            headers=auth,
            json={
                "question": "错误位置",
                "source_passage": {**reference, "end": len(text) + 1},
            },
        )
        assert invalid.status_code == 422 and not model.contexts
        studied = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=qid,
            question="结合这段原文的前后条件解释交付与验收。",
        )
        context = model.contexts[-1]
        assert document in [row["id"] for row in context["fixed_scope"]["public_document_titles"]]
        assert len([row["id"] for row in context["fixed_scope"]["public_document_titles"]]) == 20
        assert (
            context["project_context"]["career_evidence"]["selected_inquiry"]["source_passage"][
                "quote"
            ]
            == quote
        )
        assert any(
            row.get("public_document_id") == document
            for row in studied["results"][0]["result"]["evidence"]
        )
        # Editing a conclusion retains its source without resubmitting client-controlled quote text.
        changed = client.patch(
            base + "/questions/" + qid,
            headers=auth,
            json={
                "question": question["question"],
                "next_evidence": "实际验收的责任说明。",
            },
        )
        assert changed.status_code == 200
        assert changed.json()["questions"][0]["source_passage"] == question["source_passage"]
        removed = client.delete(base + "/materials/" + document, headers=auth)
        assert removed.status_code == 200
        asked = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=qid,
            question="原资料移出后，目前还有什么可核实的依据？",
        )
        assert document not in [
            row["id"] for row in model.contexts[-1]["fixed_scope"]["public_document_titles"]
        ]
        assert document not in asked["document_ids"]
        assert asked["questions"][0]["source_passage"] == question["source_passage"]
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        assert client.get(base).json()["questions"][0]["source_passage"]["quote"] == quote


def test_jd_passage_points_to_the_saved_description_and_is_available_to_research(tmp_path):
    database = tmp_path / "jd-passage.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MaterialWorkspaceModel()
    with TestClient(
        create_app(settings, model=model, reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        imported = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成接口岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证；验收权限未说明。",
            },
        ).json()
        job_id = imported["job_id"]
        job = client.get("/api/jobs/" + job_id).json()
        document = job["provenance"]["description_text"]["document_id"]
        versions = client.get("/api/sources/" + document).json()["versions"]
        version = next(row for row in versions if row["kind"] == "detail")
        text = version["payload"]["description"]
        quote = "负责失败样例验证；验收权限未说明。"
        start = text.index(quote)
        goal = client.post(
            "/api/career",
            headers=auth,
            json={"title": "合成JD调查", "goal": "核对任务与权限", "job_ids": [job_id]},
        ).json()
        base = "/api/career/" + goal["id"]
        response = client.post(
            base + "/questions",
            headers=auth,
            json={
                "question": "负责验证是否意味着拥有验收权？",
                "source_passage": {
                    "document_id": document,
                    "snapshot_id": version["snapshot_id"],
                    "start": start,
                    "end": start + len(quote),
                },
            },
        )
        assert response.status_code == 201, response.text
        question = response.json()["questions"][0]
        assert question["source_passage"]["quote"] == quote
        assert question["source_passage"]["job_id"] == job_id
        studied = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=question["id"],
            question=question["question"],
        )
        assert studied["results"][0]["result"]["status"] == "completed"
        assert (
            model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"][
                "source_passage"
            ]["snapshot_id"]
            == version["snapshot_id"]
        )
