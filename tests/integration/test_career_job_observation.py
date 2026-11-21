"""Append manually supplied JD observations without replacing their original archive."""

import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade
from work_observer.storage.models import Job, SourceDocument
from work_observer.storage.repository import Repository


def test_append_same_manual_job_without_exposing_identity_or_overwriting_old_sources(tmp_path):
    database = tmp_path / "job-observation.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = CareerModel()
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        original_text = "必须掌握Python接口开发与测试。负责失败样例验证。"
        job = post("/api/import", {
            "title": "合成持续观察岗位", "company": "合成团队", "description": original_text,
            "data_kind": "synthetic", "source_published_at": "2026-11-18T09:00:00+08:00",
        })["job_id"]  # The ordinary paste entry did not require a stable user-supplied ID.
        identity = post("/api/career", {
            "title": "合成：继续取得同一岗位的资料", "goal": "分清原文与理解的变化",
            "job_ids": [job],
        })["id"]
        base = "/api/career/" + identity
        original = run_stage(client, identity, auth, "role")["results"][0]
        turns = len(model.contexts)
        repo = Repository(database)
        with Session(repo.engine) as session:
            old_files = {row.path: Path(row.path).read_bytes()
                         for row in session.scalars(select(SourceDocument))}
        new_text = "商科背景更佳。负责接口验证与业务复盘；实际分工仍未知。"
        values = {"description": new_text, "salary": "24-30K", "data_kind": "synthetic",
                  "source_published_raw": "本次资料未写明日期",
                  "note": "合成后续取得，不是企业真实调整。"}
        updated = post(base + "/jobs/" + job + "/observations", values)
        assert [row["id"] for row in updated["jobs"]] == [job]
        assert updated["jobs"][0]["current"]["description_text"] == new_text
        assert updated["jobs"][0]["current"]["salary_raw"] == "24-30K"
        assert "source_job_id" not in updated["jobs"][0]["current"]
        comparison = client.get("/api/jobs/" + job + "/compare-history").json()
        assert comparison["status"] == "compared"
        old_side, new_side = comparison["before"], comparison["after"]
        newer = next(item for item in comparison["evidence"]
                     if item["snapshot_id"] == new_side["snapshot_id"])
        assert newer["source_published_at"] is None  # Never carry an old website date forward.
        assert len(model.contexts) == turns
        assert updated["results"][0]["result"]["evidence"] == original["result"]["evidence"]
        assert not updated["results"][0]["current"]
        assert all(Path(path).read_bytes() == text for path, text in old_files.items())
        question = post(base + "/questions", {
            "question": "两次原文说明工作真的变了吗？", "selected_job_ids": [job],
            "source_passage": {key: comparison["evidence"][0][key]
                               for key in ("document_id", "snapshot_id", "start", "end")},
        })["questions"][0]
        post(base + "/questions/" + question["id"] + "/passages", {
            "passage": {key: newer[key] for key in ("document_id", "snapshot_id", "start", "end")},
        })
        # Saving identical content records another observation, rather than another job or body.
        post(base + "/jobs/" + job + "/observations", values)
        repeated = client.get("/api/jobs/" + job + "/history").json()
        assert len(repeated) == 3 and len({row["snapshot_id"] for row in repeated}) == 2
        post(base + "/jobs/" + job + "/observations", {
            "description": "后来第三份正文，仅保留本地样例运维。", "data_kind": "synthetic",
        })
        saved = client.get(base).json()["questions"][0]
        assert saved["source_passage"]["snapshot_id"] == old_side["snapshot_id"]
        assert saved["evidence_passages"][0]["snapshot_id"] == new_side["snapshot_id"]
        for invalid in ({"description": "https://example.com/jd"},
                        {"description": "原文", "external_id": "cannot-choose-another-id"}):
            response = client.post(base + "/jobs/" + job + "/observations",
                                   headers=auth, json=invalid)
            assert response.status_code == 422, response.text
            if "external_id" not in invalid:
                assert "ManualJD" not in response.json()["message"]
        foreign = post("/api/import", {
            "title": "合成其他岗位", "company": "合成团队", "description": "其他来源的原文。",
            "data_kind": "synthetic",
        })["job_id"]
        response = client.post(base + "/jobs/" + foreign + "/observations", headers=auth,
                               json={"description": "不应写入其他岗位。"})
        assert response.status_code == 422
        # A platform-origin row must not be overwritten or relabelled as manual input.
        with Session(repo.engine) as session, session.begin():
            session.get(Job, foreign).source = "synthetic_platform"
        other = post("/api/career", {
            "title": "合成平台来源保护", "goal": "保留来源", "job_ids": [foreign],
        })["id"]
        response = client.post(f"/api/career/{other}/jobs/{foreign}/observations", headers=auth,
                               json={"description": "不应冒充平台新原文。"})
        assert response.status_code == 422
        preserved = client.get("/api/jobs/" + foreign).json()
        assert preserved["current"]["description_text"] == "其他来源的原文。"
        assert len(model.contexts) == turns
        assert all(Path(path).read_bytes() == text for path, text in old_files.items())
        repo.close()
