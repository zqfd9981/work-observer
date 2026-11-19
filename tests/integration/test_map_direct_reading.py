"""A frozen map scope can be read directly without weakening all-job coverage."""

import asyncio
import json

import pytest
from test_cognition_research import MapModel
from test_source_first_research import source_workspace as source_workspace

from work_observer.config import Settings
from work_observer.research.agent import research


class DirectMap(MapModel):
    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs

    async def turn(self, history):
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        evidence = [item for row in outputs for item in row.get("evidence", [])]
        read = {item["job_id"] for item in evidence}
        if missing := [key for key in self.jobs if key not in read]:
            call = dict(
                type="function_call",
                name="read_job",
                call_id=str(len(history)),
                arguments=json.dumps({"job_id": missing[0]}),
            )
            return [call], call
        # Reuse the existing synthetic finish fixture; no query tool executes in the engine.
        fake = {
            "type": "function_call_output",
            "output": json.dumps({"jobs": [{"id": key} for key in self.jobs]}),
        }
        calls, raw = await super().turn([fake, *history])
        args = json.loads(calls[0]["arguments"])
        args["work_map"]["work_types"][0]["claim_indices"] = list(range(len(args["claims"])))
        calls[0]["arguments"] = json.dumps(args)
        return calls, raw


@pytest.mark.parametrize("read_count", [1, 2])
def test_direct_map_reading_preserves_required_scope_and_budget(source_workspace, read_count):
    repo, store, jobs = source_workspace
    result = asyncio.run(
        research(
            repo,
            "合成完整范围地图",
            Settings(),
            job_ids=jobs,
            approach="work_map",
            max_calls=read_count + 1,
            model=DirectMap(jobs[:read_count]),
        )
    )
    assert result["status"] == ("completed" if read_count == 2 else "incomplete")
    assert result["model_calls"] == read_count + 1
    assert [row["tool"] for row in result["trace"]] == ["read_job"] * read_count + [
        "finish_research"
    ]
    checkpoint = store.load_checkpoint(result["run_id"])
    system = checkpoint["history"][0]["content"]
    assert "流程：先 query_jobs" not in system
    assert "确认范围后调用 plan_research" not in system
    assert result["tool_budget_policy"]
