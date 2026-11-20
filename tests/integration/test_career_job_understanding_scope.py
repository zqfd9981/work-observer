"""Editing personal background must not discard unchanged JD-only findings."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_background_edit_keeps_job_findings_and_refreshes_personal_analysis(tmp_path):
    database = tmp_path / "job-scope.db"
    upgrade(database)
    model = CareerModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, model=model, reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        source = {
            "title": "合成资料范围岗位",
            "company": "合成团队",
            "data_kind": "synthetic",
            "external_id": "understanding-scope",
            "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
        }
        job = client.post("/api/import", headers=auth, json=source).json()["job_id"]
        profile = {
            "title": "合成资料范围目标",
            "goal": "看清实际工作，再讨论个人经历。",
            "background": "个人背景专有标记：曾参与本地接口练习。",
            "constraints": "每周六小时",
            "job_ids": [job],
        }
        goal = client.post(
            "/api/career",
            headers=auth,
            json={**profile, "resume_text": "个人简历专有标记：只在本地练习，未在生产运行。"},
        ).json()
        identity = goal["id"]
        base = f"/api/career/{identity}"
        story = client.post(
            base + "/stories",
            headers=auth,
            json={
                "title": "个人经历专有标记",
                "situation": "本地检查",
                "action": "自己构造失败输入。",
                "result": "只得到一份本地观察。",
                "limits": "未验证生产效果。",
            },
        ).json()["stories"][0]
        task = client.post(
            base + "/experiments",
            headers=auth,
            json={
                "title": "个人练习专有标记",
                "task_or_ability": "失败检查",
                "deliverable": "运行输出",
                "completion_check": "观察错误分支",
            },
        ).json()["tasks"][0]
        observed = client.patch(
            base + f"/tasks/{task['id']}",
            headers=auth,
            json={
                "state": "done",
                "outcome": "个人观察专有标记：本地出现失败。",
                "artifact_text": "个人产物专有标记：合成运行日志。",
            },
        ).json()["tasks"][0]
        work_doc = client.post(
            base + "/materials",
            headers=auth,
            json={
                "title": "合成工作背景资料",
                "text": "仅用于解释工作流程，不证明用户亲自负责。",
            },
        ).json()["materials"][0]
        private_ids = {
            goal["resume"]["document_id"],
            story["document_id"],
            observed["artifact_document_id"],
        }
        for kind in ("role", "map"):
            done = run_stage(client, identity, auth, kind)
            assert done["results"][0]["result"]["status"] == "completed"
            context = model.contexts[-1]
            assert not context.get("application_background")
            assert not any(
                "个人背景专有标记" in note.get("content", "") for note in context["memory_context"]
            )
            assert not private_ids.intersection(context["fixed_scope"]["archived_public_ids"])
            assert work_doc["id"] in context["fixed_scope"]["archived_public_ids"]
            assert not context["project_context"]["career_evidence"].get("stories")
            assert not context["project_context"]["career_evidence"].get("resume")
        initial = run_stage(client, identity, auth, "gaps")
        assert initial["results"][0]["current"] is True
        assert model.contexts[-1]["application_background"]["background"] == profile["background"]
        assert private_ids <= set(model.contexts[-1]["fixed_scope"]["archived_public_ids"])
        calls = len(model.contexts)
        revised_profile = {**profile, "background": "更正：只协助构造样例，未独立实现接口。"}
        changed = client.patch(base, headers=auth, json=revised_profile)
        assert changed.status_code == 200, changed.text
        rows = {row["kind"]: row for row in changed.json()["results"]}
        assert rows["role"]["current"] is True and rows["map"]["current"] is True
        assert rows["gaps"]["current"] is False
        assert len(changed.json()["requirements"]) == 3
        assert len(model.contexts) == calls
        refreshed = run_stage(client, identity, auth, "gaps")
        assert refreshed["results"][0]["current"] is True
        assert (
            model.contexts[-1]["application_background"]["background"]
            == revised_profile["background"]
        )
        # Changing the actual JD must still invalidate its old interpretation.
        updated_source = client.post(
            "/api/import",
            headers=auth,
            json={**source, "description": "岗位内容已改为图像处理，不再包含原接口描述。"},
        )
        assert updated_source.status_code == 201, updated_source.text
        assert updated_source.json()["job_id"] == job
        changed_jd = client.get(base).json()
        assert not changed_jd["requirements"]
        assert all(
            not row["current"] for row in changed_jd["results"] if row["kind"] in {"role", "map"}
        )
