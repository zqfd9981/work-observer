"""Read multiple selected working materials without spending the whole round on reading."""

import json
import re

import pytest
from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


def comparison_material(index, *, long=False):
    return (
        f"第{index}份合成资料描述样例验证与观察记录。\n"
        + ("合成背景细节。\n" * 700 if long else "")
        + "限定：材料不能证明个人拥有生产验收权；实际运行尚未核实。"
    )


class ArchiveComparisonModel(ModelClient):
    def __init__(self, *, batch=True):
        self.batch = batch
        self.last_usage = {}
        self.contexts = []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        scope = context["fixed_scope"]
        documents = [
            row
            for row in scope["public_document_titles"]
            if row["title"].startswith("合成对照材料")
        ]
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        evidence = {row["id"]: row for output in outputs for row in output.get("evidence", [])}
        windows = {}
        for output in outputs:
            if "document" in output:
                windows[output["document"]["id"]] = output
            for window in output.get("windows", []):
                if "document_id" in window:
                    windows[window["document_id"]] = window
        jobs = [
            job
            for job in scope["jobs"]
            if not any(row.get("job_id") == job["id"] for row in evidence.values())
        ]
        unfinished = [
            row for row in documents if row["id"] not in windows or windows[row["id"]]["has_more"]
        ]
        if jobs:
            if len(jobs) > 1:
                name, args = (
                    "read_jobs",
                    {"reads": [{"job_id": row["id"], "start": 0} for row in jobs]},
                )
            else:
                name, args = "read_job", {"job_id": jobs[0]["id"], "start": 0}
        elif unfinished:
            reads = [
                {"document_id": row["id"], "start": windows.get(row["id"], {}).get("next_start", 0)}
                for row in unfinished
            ]
            if self.batch:
                assert "read_archived_documents" in {tool["name"] for tool in self.tools}
                name, args = "read_archived_documents", {"reads": reads}
            else:
                name, args = "read_archived_document", reads[0]
        else:
            claims = []
            for document in documents:
                rows = sorted(
                    (
                        row
                        for row in evidence.values()
                        if row.get("public_document_id") == document["id"]
                    ),
                    key=lambda row: row["start"],
                )
                whole = "".join(row["quote"] for row in rows)
                assert whole.endswith("实际运行尚未核实。")
                claims.append(
                    {
                        "text": document["title"] + "描述样例验证，实际运行尚未核实。",
                        "category": "business",
                        "basis": "direct",
                        "requirement": "unspecified",
                        "evidence_ids": list(dict.fromkeys(
                            row["id"] for row in [rows[0], *rows[-2:]]
                        )),
                    }
                )
            name, args = (
                "finish_research",
                {"claims": claims, "gaps": ["这些合成材料不能单独证明岗位决定权或个人能力。"]},
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


@pytest.mark.parametrize("long,job_count,expected_calls", [(False, 0, 2), (True, 1, 5)])
def test_compare_six_archives_within_existing_call_limit(tmp_path, long, job_count, expected_calls):
    database = tmp_path / "batch-archives.db"
    upgrade(database)
    model = ArchiveComparisonModel(batch=long)
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model,
            reports_dir=tmp_path / "reports",
        ),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        jobs = [
            post(
                "/api/import",
                {
                    "title": f"合成跨材料岗位{i}",
                    "company": "合成团队",
                    "description": "参与样例验证，产出观察记录；验收决定权未披露。",
                    "data_kind": "synthetic",
                },
            )["job_id"]
            for i in range(job_count)
        ]
        goal = post(
            "/api/career",
            {
                "title": "合成：六份材料的条件对照",
                "goal": "读到各份限定，区分资料描述与实际执行",
                "job_ids": jobs,
            },
        )
        api = "/api/career/" + goal["id"]
        texts = {}
        for index in range(6):
            text = comparison_material(index, long=long)
            materials = post(api + "/materials", {"title": f"合成对照材料{index}", "text": text})[
                "materials"
            ]
            texts[materials[-1]["id"]] = text
        if not long:
            stopped = run_stage(
                client, goal["id"], auth, "ask", question="逐份核对六份材料的限定。"
            )
            row = stopped["results"][0]
            assert row["result"]["status"] == "incomplete"
            assert row["result"]["stop_reason"] == "model_call_limit"
            assert row["result"]["model_calls"] == 6
            response = client.delete(api + "/steps/" + row["step_id"], headers=auth)
            assert response.status_code == 200, response.text
            model.batch = True
        studied = run_stage(
            client, goal["id"], auth, "ask", question="对照六份材料，并核实各自末尾限定。"
        )
        row = studied["results"][0]
        result = row["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert result["model_calls"] == expected_calls and len(result["claims"]) == 6
        assert result["public_reads"] == 0 and result["public_searches"] == 0
        evidence = [item for item in result["evidence"] if item.get("public_document_id")]
        assert {item["public_document_id"] for item in evidence} == set(texts)
        assert all(item["evidence_kind"] == "work_material" for item in evidence)
        for identity, text in texts.items():
            rows = sorted(
                (item for item in evidence if item["public_document_id"] == identity),
                key=lambda item: item["start"],
            )
            assert "".join(item["quote"] for item in rows) == text
            assert all(item["quote"] == text[item["start"] : item["end"]] for item in rows)
            assert client.get("/api/public-documents/" + identity).json()["text"] == text
        batches = [entry for entry in result["trace"] if entry["tool"] == "read_archived_documents"]
        assert len(batches) == (3 if long else 1)
        assert all(len(entry["windows"]) == 6 and entry["local_only"] for entry in batches)
        project = client.get("/api/projects/" + goal["id"]).json()
        step = next(item for item in project["steps"] if item["id"] == row["step_id"])
        assert step["max_calls"] == 6 and set(step["job_ids"]) == set(jobs)
