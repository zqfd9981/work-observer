"""A workspace remembers its research focus without starting or changing investigations."""

import re

from starlette.testclient import TestClient
from test_career_material_start import MaterialWorkspaceModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_focus_survives_reopening_and_does_not_change_research_or_question_states(tmp_path):
    database = tmp_path / "research-focus.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MaterialWorkspaceModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def request(path, data, method="post"):
            response = getattr(client, method)(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = request("/api/career", {
            "title": "合成：下次接着研究", "goal": "持续理解工作",
            "material_title": "合成工作说明",
            "material_text": "合成说明：构造失败请求，交付观察记录。",
        })
        identity, base = goal["id"], f"/api/career/{goal['id']}"
        first = request(base + "/questions", {"question": "失败输入应怎样验证？"})["questions"][0]
        second = request(base + "/questions", {
            "question": "责任边界还需核实什么？"
        })["questions"][-1]
        studied = run_stage(client, identity, auth, "ask", question=first["question"],
                            question_id=first["id"])
        before_questions, before_usage = studied["questions"], studied["usage"]
        before_claims = studied["results"][0]["result"]["claims"]
        calls = len(model.contexts)
        focused = request(base + "/focus", {"question_id": first["id"]}, "patch")
        assert focused["focus_question_id"] == first["id"]
        assert focused["questions"] == before_questions and focused["usage"] == before_usage
        assert focused["results"][0]["result"]["claims"] == before_claims
        assert focused["results"][0]["current"] and len(model.contexts) == calls
        listing = next(row for row in client.get("/api/career").json() if row["id"] == identity)
        assert listing["focus_question"] == first["question"]
        # A conclusion and changed question wording remain user edits, not effects of focus.
        edited = request(base + "/questions/" + first["id"], {
            "question": "失败验证需要哪些对照？", "state": "answered",
            "conclusion": "先比较输入与输出，生产效果仍未知。",
        }, "patch")
        assert edited["focus_question_id"] == first["id"]
        assert edited["questions"][0]["state"] == "answered"
        listing = next(row for row in client.get("/api/career").json() if row["id"] == identity)
        assert listing["focus_question"] == edited["questions"][0]["question"]
        another = request("/api/career", {"title": "另一个合成目标", "goal": "另一个方向"})
        foreign = request(f"/api/career/{another['id']}/questions", {
            "question": "这个问题只属于另一个目标？",
        })["questions"][0]
        invalid = client.patch(base + "/focus", headers=auth, json={"question_id": foreign["id"]})
        assert invalid.status_code == 422
        assert client.get(base).json()["focus_question_id"] == first["id"]
        switched = request(base + "/focus", {"question_id": second["id"]}, "patch")
        assert switched["focus_question_id"] == second["id"]
        assert client.get(f"/api/career/{another['id']}").json()["focus_question_id"] is None
        assert len(model.contexts) == calls
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()
        assert reopened["focus_question_id"] == second["id"]
        assert reopened["questions"] == edited["questions"]
        assert reopened["results"][0]["result"]["claims"] == before_claims
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        cleared = client.patch(base + "/focus", headers=auth, json={"question_id": None})
        assert cleared.status_code == 200
        assert cleared.json()["focus_question_id"] is None
        assert cleared.json()["questions"] == edited["questions"]
        assert len(model.contexts) == calls
