"""Find complete individual judgments inside saved discussions without new research."""

import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_claim_recheck import LONG_CLAIM, ClaimRecheckModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_library_locates_late_complete_claims_and_keeps_each_original_owner(tmp_path):
    database = tmp_path / "claim-search.db"
    upgrade(database)
    with TestClient(create_app(
        Settings(database_path=database, raw_directory=tmp_path / "raw"),
        model=ClaimRecheckModel(), reports_dir=tmp_path / "reports",
    ), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        studies = []
        for index in range(2):
            response = client.post("/api/career", headers=auth, json={
                "title": f"合成判断检索目标{index}", "goal": "找回原句与限定",
                "material_title": f"合成原资料{index}", "material_text": "虚构局部工作说明。",
            })
            assert response.status_code == 201, response.text
            goal = response.json()
            studied = run_stage(client, goal["id"], auth, "ask",
                                question=f"合成目录标题线索{index}，核对工作原文。",
                                material_id=goal["materials"][0]["id"])
            assert studied["results"][0]["result"]["status"] == "completed"
            studies.append(deepcopy(studied))

        base = "/api/career/" + studies[0]["id"]

        def search(q, **extra):
            response = client.get(base + "/search", params={
                "q": q, "record_kind": "discussion", **extra,
            })
            assert response.status_code == 200, response.text
            return response.json()

        found = search("末尾限定")
        assert found["record_count"] == 1
        row = found["records"][0]
        assert row["step_id"] == studies[0]["results"][0]["step_id"]
        assert row["project_id"] == studies[0]["id"]
        assert row["claim_match_count"] == 1
        assert row["claim_matches"] == [{
            "index": 23, "text": LONG_CLAIM, "basis": "inference", "category": "task",
            "requirement": "unspecified", "source_titles": ["合成原资料0"],
        }]
        many = search("局部样例")["records"][0]
        assert many["claim_match_count"] == 24
        assert [claim["index"] for claim in many["claim_matches"]] == [0, 1, 2]
        assert many["claim_matches"][0]["text"] == (
            studies[0]["results"][0]["result"]["claims"][0]["text"]
        )
        # A title-only match or words split across claims must not invent an individual hit.
        title = search("合成目录标题线索0")["records"][0]
        assert title["claim_matches"] == [] and title["claim_match_count"] == 0
        split = search("合成第 末尾限定")["records"][0]
        assert split["claim_matches"] == [] and split["claim_match_count"] == 0
        all_goals = search("末尾限定", scope="all")
        assert {row["project_id"] for row in all_goals["records"]} == {
            goal["id"] for goal in studies
        }
        assert all(row["claim_matches"][0]["index"] == 23 for row in all_goals["records"])
        assert len({row["step_id"] for row in all_goals["records"]}) == 2
        for before in studies:
            after = client.get("/api/career/" + before["id"]).json()
            assert after["usage"] == before["usage"]
            assert after["results"] == before["results"]
            assert after["insights"] == before["insights"]
            assert after["materials"] == before["materials"]
