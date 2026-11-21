"""Long selected JDs can be read through their final conditions in a normal research round."""

import json
import re

import pytest
from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


def long_jd(index):
    return (
        f"岗位{index}负责接口验证。\n"
        + "合成上下文细节。\n" * 700
        + "任职资格\n本科及以上学历；商科背景更佳。\n责任边界\n不负责生产上线审批。"
    )


class LongBatchModel(ModelClient):
    def __init__(self):
        self.last_usage = {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        windows = {
            window["job_id"]: window for output in outputs for window in output.get("windows", [])
        }
        jobs = context["fixed_scope"]["jobs"]
        unfinished = [
            job for job in jobs if job["id"] not in windows or windows[job["id"]]["has_more"]
        ]
        if unfinished:
            name, arguments = (
                "read_jobs",
                {
                    "reads": [
                        {"job_id": job["id"], "start": windows.get(job["id"], {}).get("next_start")}
                        for job in unfinished
                    ]
                },
            )
        else:
            evidence = {
                item["id"]: item for output in outputs for item in output.get("evidence", [])
            }
            claims = []
            for job in jobs:
                sources = sorted(
                    (item for item in evidence.values() if item["job_id"] == job["id"]),
                    key=lambda item: item["start"],
                )
                whole = "".join(item["quote"] for item in sources)
                assert "商科背景更佳" in whole and "不负责生产上线审批" in whole
                claims.append(
                    {
                        "category": "ability",
                        "basis": "direct",
                        "requirement": "preferred",
                        "text": job["title"] + "写明商科背景更佳，属于加分条件。",
                        "evidence_ids": [item["id"] for item in sources[-2:]],
                    }
                )
            name, arguments = (
                "finish_research",
                {
                    "claims": claims,
                    "gaps": ["合成长文只验证读取，实际分工与个人能力仍未知。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": str(len(history)),
        }
        return [call], call


@pytest.mark.parametrize("job_count,expected_calls", [(2, 3), (6, 4)])
def test_long_comparison_reaches_final_qualifications_without_raising_call_limit(
    tmp_path,
    job_count,
    expected_calls,
):
    database = tmp_path / "long-comparison.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, model=LongBatchModel(), reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        jobs, texts = [], {}
        for index in range(job_count):
            text = long_jd(index)
            # Six full texts fit the existing 60-fragment evidence cap; each exceeds one read.
            assert 5600 < len(text) < 7000
            response = client.post(
                "/api/import",
                headers=auth,
                json={
                    "title": f"合成长文批读岗位{index}",
                    "company": "合成团队",
                    "description": text,
                    "data_kind": "synthetic",
                },
            )
            assert response.status_code == 201, response.text
            job = response.json()["job_id"]
            jobs.append(job)
            texts[job] = text
        goal = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成：长JD的完整条件对照",
                "goal": "并排读取到末尾再核对性质",
                "job_ids": jobs,
            },
        ).json()
        studied = run_stage(
            client, goal["id"], auth, "ask", question="逐份核对这些长JD的任职条件。"
        )
        row = studied["results"][0]
        result = row["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert result["model_calls"] == expected_calls
        assert len(result["claims"]) == job_count
        assert all(claim["requirement"] == "preferred" for claim in result["claims"])
        assert [entry["tool"] for entry in result["trace"]] == (
            ["read_jobs"] * (expected_calls - 1) + ["finish_research"]
        )
        for identity, text in texts.items():
            evidence = sorted(
                (item for item in result["evidence"] if item.get("job_id") == identity),
                key=lambda item: item["start"],
            )
            assert "".join(item["quote"] for item in evidence) == text
            assert all(item["quote"] == text[item["start"] : item["end"]] for item in evidence)
            assert client.get("/api/jobs/" + identity).json()["current"]["description_text"] == text
        project = client.get("/api/projects/" + goal["id"]).json()
        step = next(item for item in project["steps"] if item["id"] == row["step_id"])
        assert step["max_calls"] == 6
        assert set(step["job_ids"]) == set(jobs)
