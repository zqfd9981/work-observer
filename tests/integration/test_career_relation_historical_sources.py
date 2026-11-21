"""A pair investigation retains old JD identity even after the current JD changes."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.collection.contracts import now
from work_observer.config import Settings
from work_observer.research.historical_sources import read
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


def test_relation_pair_can_reread_the_original_job_snapshot_after_an_update(tmp_path):
    database = tmp_path / "relation-history.db"
    upgrade(database)
    model = CareerModel()
    with TestClient(create_app(
        Settings(database_path=database, raw_directory=tmp_path / "raw"), model=model,
        reports_dir=tmp_path / "reports",
    ), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        origins, refs = [], []
        for index in range(2):
            job = post("/api/import", {
                "title": "合成岗位" + str(index), "company": "合成团队", "data_kind": "synthetic",
                "description": "必须掌握Python接口测试。负责失败样例验证。原限定：只做本地样例。",
            })["job_id"]
            goal = post("/api/career", {
                "title": "合成旧JD关系" + str(index), "goal": "核对任务与工具关系",
                "job_ids": [job],
            })
            source = run_stage(client, goal["id"], auth, "map")["results"][0]
            assert source["result"]["status"] == "completed"
            origins.append((goal, job, source))
            refs.append({"project_id": goal["id"], "step_id": source["step_id"],
                         "relation_index": 0})
        first, job, _ = origins[0]
        post(f"/api/career/{first['id']}/jobs/{job}/observations", {
            "description": "合成新JD：改为原型讨论，不再沿用原来的失败样例说明。",
            "data_kind": "synthetic",
        })
        calls = len(model.contexts)
        paired = post("/api/career/work-relations/inquiry", {
            "question": "原来两条关系的依据是否相同？", "relations": refs,
        })
        carried = paired["questions"][0]["carried_understanding"]
        assert {row["id"] for row in paired["jobs"]} == {row[1] for row in origins}
        reference = next(row for row in carried["source_references"] if row["job_id"] == job)
        repository = Repository(database)
        try:
            observed = read(repository, job, reference["as_of"], 0,
                            {row[1] for row in origins}, now())
            assert observed["status"] == "read"
            assert {row["snapshot_id"] for row in observed["evidence"]} == {
                reference["snapshot_id"],
            }
            assert "原限定：只做本地样例。" in "".join(
                row["quote"] for row in observed["evidence"]
            )
        finally:
            repository.close()
        assert len(model.contexts) == calls and not paired["results"]
