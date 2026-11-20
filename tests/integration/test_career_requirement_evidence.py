"""Specific job requirements are checked against explicitly selected personal sources."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_requirement_selects_exact_sources_and_keeps_their_limits(tmp_path):
    database = tmp_path / "requirement-evidence.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = CareerModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成证据对照岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
            },
        ).json()["job_id"]
        identity = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成证据对照",
                "goal": "为具体岗位任务准备可讨论的证据",
                "background": "合成本地接口练习，没有生产评测。",
                "job_ids": [job],
            },
        ).json()["id"]
        base = f"/api/career/{identity}"
        role = run_stage(client, identity, auth, "role")
        requirement = role["requirements"][0]
        key = requirement["key"]
        story = client.post(
            base + "/stories",
            headers=auth,
            json={
                "title": "合成本地接口项目",
                "situation": "检查失败情境",
                "action": "亲自写了超时输入。",
                "result": "只形成过一次本地观察。",
                "limits": "未验证并发，未在生产运行。",
                "requirement_key": key,
            },
        ).json()["stories"][0]
        fallback = client.get(base).json()["requirements"][0]["proof"]
        assert fallback["records"][0]["id"] == story["id"]
        experiment = client.post(
            base + "/experiments",
            headers=auth,
            json={
                "title": "合成重复提交练习",
                "task_or_ability": "检查重复提交",
                "deliverable": "输入与输出记录",
                "completion_check": "比较相同请求标识的输出",
                "hypothesis": "尚不知道超时与并发谁导致问题。",
            },
        ).json()["tasks"][0]
        # A selected plan remains a plan, even with an optimistic hypothesis.
        refs = [{"kind": "story", "id": story["id"]}, {"kind": "task", "id": experiment["id"]}]
        calls = len(model.contexts)
        selected = client.post(
            base + "/requirement-evidence",
            headers=auth,
            json={
                "requirement_key": key,
                "records": refs,
                "missing": "还缺失败输入和实际输出。",
            },
        )
        assert selected.status_code == 200, selected.text
        proof = selected.json()["requirements"][0]["proof"]
        assert proof["records"][1]["state"] == "planned"
        assert not proof["records"][1]["document_id"]
        assert len(model.contexts) == calls
        done = client.patch(
            base + f"/tasks/{experiment['id']}",
            headers=auth,
            json={
                "state": "done",
                "outcome": "合成观察：同一标识出现两次写入。仍未排除并发。",
                "artifact_title": "合成失败输出",
                "artifact_text": "合成输入id=demo。合成输出：两次写入。不能证明原因。",
            },
        )
        assert done.status_code == 200, done.text
        task_doc = done.json()["tasks"][0]["artifact_document_id"]
        material = client.post(
            base + "/materials",
            headers=auth,
            json={
                "title": "合成业务背景",
                "text": "合成业务背景仅作解释，不证明用户拥有生产权限。",
            },
        ).json()["materials"][0]
        data = {
            "requirement_key": key,
            "records": [*refs, {"kind": "material", "id": material["id"]}],
            "relevance": "可以讨论失败处理的具体检查方法。",
            "missing": "生产情境和企业验收口径仍未知。",
        }
        saved = client.post(base + "/requirement-evidence", headers=auth, json=data)
        assert saved.status_code == 200, saved.text
        checked = run_stage(client, identity, auth, "evidence", requirement_key=key)
        latest = checked["results"][0]
        assert latest["result"]["status"] == "completed"
        assert latest["requirement_text"] == requirement["text"]
        context = model.contexts[-1]["project_context"]["career_evidence"]["selected_requirement"]
        assert context["requirement"] == "required"
        assert context["missing"] == data["missing"]
        assert context["records"][0]["limits"] == story["limits"]
        assert context["records"][1]["outcome"].endswith("仍未排除并发。")
        read_documents = {ev.get("public_document_id") for ev in latest["result"]["evidence"]}
        assert {story["document_id"], task_doc, material["id"]} <= read_documents
        assert checked["stories"][0] == story  # Checking never rewrites the user's source.
        assert checked["tasks"][0]["state"] == "done"
        assert (
            len(checked["requirements"]) == 1
        )  # Personal analysis does not replace JD requirements.
        continued = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="这些观察还不能支持哪些说法？",
            source_step_id=latest["step_id"],
        )
        continuation_context = model.contexts[-1]["project_context"]["career_evidence"][
            "selected_requirement"
        ]
        assert continuation_context["key"] == key
        assert {row["document_id"] for row in continuation_context["records"]} == {
            story["document_id"],
            task_doc,
            material["id"],
        }
        assert continued["results"][0]["result"]["status"] == "completed"
        assert (
            client.post(
                base + "/requirement-evidence",
                headers=auth,
                json={**data, "records": [{"kind": "story", "id": "a" * 32}]},
            ).status_code
            == 422
        )
        assert (
            client.post(
                base + "/requirement-evidence",
                headers=auth,
                json={**data, "records": [*data["records"], refs[0]]},
            ).status_code
            == 422
        )
        duplicate = client.post(
            base + "/requirement-evidence",
            headers=auth,
            json={**data, "records": [refs[0], refs[0]]},
        )
        assert duplicate.status_code == 200
        assert len(duplicate.json()["requirements"][0]["proof"]["records"]) == 1
        cleared = client.post(
            base + "/requirement-evidence",
            headers=auth,
            json={"requirement_key": key, "records": [], "missing": "重新挑选证据。"},
        )
        assert cleared.status_code == 200
        assert cleared.json()["requirements"][0]["proof"]["records"] == []
        client.post(base + "/requirement-evidence", headers=auth, json=data)
        client.delete(base + f"/stories/{story['id']}", headers=auth)
        unavailable = client.get(base).json()["requirements"][0]["proof"]["records"][0]
        assert unavailable["available"] is False
        assert (
            client.post(
                base + "/prepare", headers=auth, json={"kind": "evidence", "requirement_key": key}
            ).status_code
            == 422
        )
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()
        assert reopened["requirements"][0]["proof"]["missing"] == data["missing"]
        assert (
            next(row for row in reopened["results"] if row["kind"] == "evidence")["requirement_key"]
            == key
        )
