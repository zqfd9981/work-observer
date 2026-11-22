"""New evidence can join its inquiry without changing old research or other questions."""

import re

from starlette.testclient import TestClient
from test_career_question_materials import QuestionMaterialModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_add_material_to_inquiry_then_reread_after_reopening(tmp_path):
    database = tmp_path / "intake.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = QuestionMaterialModel()

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def save(path, payload):
            response = client.post(path, headers=auth, json=payload)
            assert response.status_code == 201, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成：补资料接着调查", "goal": "核对实际交付"})
        identity = goal["id"]
        base = "/api/career/" + identity
        original = save(base + "/materials", {"title": "合成工作说明", "text": "先记录测试输入。"})
        first_id = original["added_material_id"]
        data = save(base + "/questions", {"question": "合成：实际记录了什么？",
                    "state": "open", "material_ids": [first_id]})
        question = data["questions"][0]
        question_id = question["id"]
        data = save(base + "/questions", {"question": "合成：另一个独立问题？", "state": "open"})
        other = data["questions"][1]
        old_study = run_stage(client, identity, auth, "ask", question_id=question_id,
                              question=question["question"])["results"][0]
        added = save(base + "/materials", {"title": "合成新观察",
                     "text": "只观察到输出日志，权限未核实。",
                     "source_name": "用户的合成实验记录", "question_id": question_id})
        second_id = added["added_material_id"]
        updated = next(row for row in added["questions"] if row["id"] == question_id)
        assert updated["material_ids"] == [first_id, second_id]
        assert updated["state"] == "open" and not updated["conclusion"]
        assert added["questions"][1] == other
        assert added["results"][0] == old_study
        assert len(model.contexts) == 2  # Saving the new evidence did not call the model.

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        study = run_stage(client, identity, auth, "ask", question_id=question_id,
                          question="合成：结合新记录再核对。")["results"][0]
        assert study["result"]["status"] == "completed"
        assert study["material_ids"] == [first_id, second_id]
        assert {row["public_document_id"] for row in study["result"]["evidence"]} == {
            first_id, second_id,
        }
        for index in range(4):
            response = client.post(base + "/materials", headers=auth, json={
                "title": f"合成补充{index}", "text": "补充局部记录。", "question_id": question_id,
            })
            assert response.status_code == 201, response.text
        before = client.get(base).json()
        raw_before = sorted(path.relative_to(tmp_path).as_posix()
                            for path in settings.raw_directory.rglob("*") if path.is_file())
        for target in (question_id, "f" * 32):
            response = client.post(base + "/materials", headers=auth, json={
                "title": "合成：未保存的输入", "text": "仍应保留在编辑框。", "question_id": target,
            })
            assert response.status_code == 422, response.text
            assert client.get(base).json() == before
        assert sorted(path.relative_to(tmp_path).as_posix()
                      for path in settings.raw_directory.rglob("*") if path.is_file()) == raw_before
        response = client.post(base + "/materials", headers=auth, json={
            "title": "合成：仅保存到资料库", "text": "无需替换任何已选重点资料。",
        })
        assert response.status_code == 201, response.text
        assert response.json()["questions"] == before["questions"]
        assert len(model.contexts) == 4
