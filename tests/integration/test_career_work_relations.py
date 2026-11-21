"""Browse full saved work relations across goals without running new research."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_material_map import MATERIALS, MaterialMapModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade

LIMIT = "只按当前材料核对，不合并责任。🤔" * 45 + "末尾迁移前提：核实验收权限。"


class RelationsBrowserModel(MaterialMapModel):
    async def turn(self, history):
        output, call = await super().turn(history)
        if call["name"] == "finish_research":
            args = json.loads(call["arguments"])
            original = args["work_map"]["work_relations"]
            size = 14 if "合成关系库长页" in history[1]["content"] else 2
            args["work_map"]["work_relations"] = [
                {**original[index % 2], "transfer_limit": LIMIT + str(index)}
                for index in range(size)
            ]
            call["arguments"] = json.dumps(args)
        return output, call


def test_saved_relations_keep_scope_claims_sources_full_limits_and_independent_pages(tmp_path):
    database = tmp_path / "work-relations.db"
    upgrade(database)
    model = RelationsBrowserModel()
    with TestClient(create_app(
        Settings(database_path=database, raw_directory=tmp_path / "raw"), model=model,
        reports_dir=tmp_path / "reports",
    ), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def save(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        endpoint = "/api/career/work-relations"
        assert client.get(endpoint).json()["relations"] == []
        goals = []
        for title in ["合成关系库长页", "合成关系库另一目标"]:
            goal = save("/api/career", {"title": title, "goal": "比较工作的任务与产出"})
            base = "/api/career/" + goal["id"]
            sources = []
            for name, task, deliverable in MATERIALS:
                data = save(base + "/materials", {
                    "title": name, "text": f"任务：{task}。交付：{deliverable}。验收权仍未知。",
                })
                sources.append(data["materials"][-1]["id"])
            inquiry = save(base + "/questions", {
                "question": title + "：工作如何产出交付物？", "material_ids": sources,
            })["questions"][-1]
            study = run_stage(client, goal["id"], auth, "map", question_id=inquiry["id"],
                              question=title + "：只比较任务与对应产物。")
            assert study["results"][0]["result"]["status"] == "completed"
            goals.append(study)
        snapshots = [deepcopy(client.get("/api/career/" + goal["id"]).json()) for goal in goals]
        calls = len(model.contexts)
        page = client.get(endpoint).json()
        assert page["total_count"] == 16 and len(page["relations"]) == 12
        other = client.get(endpoint, params={"offset": page["next_offset"]}).json()
        assert len(other["relations"]) == 4 and other["next_offset"] is None
        rows = page["relations"] + other["relations"]
        assert len({row["key"] for row in rows}) == 16
        by_goal = {goal["id"]: goal for goal in goals}
        for row in rows:
            source = by_goal[row["project_id"]]["results"][0]
            relation = source["result"]["work_map"]["work_relations"][row["relation_index"]]
            assert row["relation"] == relation and row["current"]
            assert relation["transfer_limit"].startswith(LIMIT)
            assert len(row["claims"]) == 2 and len(row["evidence"]) == 1
            assert row["claims"][0]["text"] == relation["source_text"]
            assert row["claims"][1]["text"] == relation["target_text"]
            assert row["evidence"][0]["id"] in row["claims"][0]["evidence_ids"]
            assert row["scope"] == source["result"]["scope"]
        assert client.get(endpoint, params={"q": "末尾迁移前提 验收权限"}).json()[
            "total_count"
        ] == 16
        assert client.get(endpoint, params={"node_kind": "tool"}).json()["total_count"] == 0
        assert client.get(endpoint, params={"predicate": "requires"}).json()["total_count"] == 0
        assert client.get(endpoint, params={"goal_id": goals[1]["id"]}).json()["total_count"] == 2
        assert client.get(endpoint, params={"goal_id": "0" * 32}).status_code == 422
        assert client.get(endpoint, params={"node_kind": "invented"}).status_code == 422
        assert len(model.contexts) == calls
        assert [client.get("/api/career/" + goal["id"]).json() for goal in goals] == snapshots
        response = client.patch("/api/career/" + goals[0]["id"], headers=auth, json={
            "title": goals[0]["title"], "goal": "换一个调查范围后复核原关系", "job_ids": [],
        })
        assert response.status_code == 200, response.text
        assert client.get(endpoint, params={"state": "current"}).json()["total_count"] == 2
        historical = client.get(endpoint, params={"state": "historical"}).json()
        assert historical["total_count"] == 14
        assert all(not row["current"] for row in historical["relations"])
        assert len(model.contexts) == calls
