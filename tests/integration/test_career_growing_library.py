"""Keep accumulating source material while each investigation reads a small chosen set."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_growing_library_keeps_old_work_samples_readable_and_research_scope_bounded(tmp_path):
    database = tmp_path / "growing-library.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = CareerModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(url, data, method="post"):
            response = getattr(client, method)(url, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        job = post(
            "/api/import",
            {
                "title": "合成长期资料岗位",
                "company": "合成团队",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
                "data_kind": "synthetic",
            },
        )["job_id"]

        def goal(title):
            return post(
                "/api/career",
                {
                    "title": title,
                    "goal": "根据原文持续调查",
                    "job_ids": [job],
                    "background": "本地虚构练习，不代表生产验证。",
                },
            )["id"]

        identity = goal("合成不断积累的研究")
        base = f"/api/career/{identity}"
        old = post(
            base + "/materials",
            {"title": "合成最初的调查笔记", "text": "最初的合成记录，结论仍待验证。"},
        )["materials"][0]

        def experiment(title, previous=None):
            task = post(
                base + "/experiments",
                {
                    "title": title,
                    "task_or_ability": "核对解释边界",
                    "deliverable": "输入输出与错误记录",
                    "completion_check": "保留失败与未知",
                    "previous_task_id": previous,
                },
            )["tasks"][-1]
            saved = post(
                base + "/tasks/" + task["id"],
                {
                    "state": "done",
                    "outcome": "合成观察：两组都失败，不能确认原因。",
                    "artifact_title": title + "日志",
                    "artifact_text": title + "：本地合成输入与失败输出，未在生产运行。",
                },
                "patch",
            )
            return saved["tasks"][-1]

        parent = experiment("合成较早的原实验")
        child = experiment("合成较早的后续验证", parent["id"])
        material_ids = []
        for index in range(24):
            saved = post(
                base + "/materials",
                {
                    "title": f"合成积累资料{index}",
                    "text": f"单独查找积累编号{index}：只有合成业务说明，不证明个人能力。",
                },
            )
            material_ids.append(saved["materials"][-1]["id"])
        for index in range(4):
            experiment("合成近期其他练习" + str(index))
        post(
            base + "/resume",
            {"title": "合成后来导入的简历", "text": "用户虚构简历，仅用于本地测试。"},
            "patch",
        )
        post(
            base + "/stories",
            {
                "title": "合成后来补充的经历",
                "situation": "本地虚构场景。",
                "action": "只编写了合成样例。",
                "result": "尚未验证生产效果。",
            },
        )
        saved = client.get(base).json()
        assert len(saved["document_ids"]) > 30 and len(saved["materials"]) == 25
        assert set(material_ids) <= {row["id"] for row in saved["materials"]}
        assert not model.contexts
        studied = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="对照这份旧资料与两次实验的实际观察。",
            task_id=child["id"],
            material_id=old["id"],
        )
        latest = studied["results"][0]
        assert latest["result"]["status"] == "completed", latest["result"].get("stop_reason")
        assert latest["result"]["model_calls"] <= 6
        scope = set(latest["document_ids"])
        focused = {old["id"], parent["artifact_document_id"], child["artifact_document_id"]}
        assert focused <= scope and len(scope) == 20
        assert latest["omitted_documents"] == len(saved["document_ids"]) - 20
        assert len(studied["document_ids"]) == len(saved["document_ids"])
        read = {row.get("public_document_id") for row in latest["result"]["evidence"]}
        assert focused <= read
        # A material omitted from this run remains searchable and readable in the same goal.
        assert material_ids[0] not in scope
        found = client.get(base + "/search", params={"q": "单独查找积累编号0："}).json()
        assert found["originals"]["evidence"][0]["public_document_id"] == material_ids[0]
        assert (
            "单独查找积累编号0："
            in client.get("/api/public-documents/" + material_ids[0]).json()["text"]
        )
        understood = run_stage(client, identity, auth, "role")
        role_scope = set(understood["results"][0]["document_ids"])
        personal = {
            saved["resume"]["document_id"],
            saved["stories"][0]["document_id"],
            *(row["artifact_document_id"] for row in saved["tasks"]),
        }
        assert len(role_scope) == 20 and not role_scope & personal

        other = goal("合成其他目标")
        external = post(
            f"/api/career/{other}/materials",
            {"title": "合成跨目标资料", "text": "这份资料的适用性需要重新核对。"},
        )["materials"][0]
        attached = post(base + "/materials/attach", {"document_id": external["id"]})
        assert external["id"] in attached["document_ids"]
        foreign_task = post(
            f"/api/career/{other}/experiments",
            {
                "title": "合成外部目标的新作品",
                "task_or_ability": "核对失败边界",
                "deliverable": "本地记录",
                "completion_check": "保留未知",
            },
        )["tasks"][0]
        foreign_task = post(
            f"/api/career/{other}/tasks/{foreign_task['id']}",
            {
                "state": "done",
                "outcome": "合成失败观察。",
                "artifact_text": "独立的合成作品记录。",
            },
            "patch",
        )["tasks"][0]
        copied = post(
            base + "/reuse",
            {"source_project_id": other, "kind": "task", "record_id": foreign_task["id"]},
        )
        assert copied["tasks"][-1]["artifact_document_id"] == foreign_task["artifact_document_id"]
        assert foreign_task["artifact_document_id"] in copied["document_ids"]
        updated = post(
            base,
            {
                "title": "合成调整后的长期目标",
                "goal": "继续核对工作与观察",
                "background": "本地虚构练习。",
                "constraints": "",
                "job_ids": [job],
            },
            "patch",
        )
        assert set(updated["document_ids"]) == set(copied["document_ids"])
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()
        assert set(reopened["document_ids"]) == set(copied["document_ids"])
        assert len(reopened["materials"]) == 26
