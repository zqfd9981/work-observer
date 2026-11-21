"""One saved question can drive a bounded series without enabling strategy machinery."""

import asyncio
import json
import re
import time

import pytest
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class AutonomousInquiryModel(ModelClient):
    def __init__(self, mode="three"):
        self.mode, self.contexts, self.tool_sets = mode, [], []
        self.last_usage = {}
        self.pause_delay = 1

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        self.tool_sets.append({tool["name"] for tool in self.tools})
        personal = context["project_context"]["career_evidence"]
        rounds = (personal.get("autonomous_inquiry") or {}).get("rounds_remaining", 1)
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        proposed = any(row.get("name") == "propose_investigation" for row in history)
        if self.mode == "pause" and rounds == 2 and not outputs:
            await asyncio.sleep(self.pause_delay)
        if not outputs:
            name, arguments = "read_job", {"job_id": context["fixed_scope"]["jobs"][0]["id"]}
        elif self.mode == "fail":
            raise RuntimeError("local scripted incomplete investigation")
        elif rounds > 1 and not proposed and self.mode != "early":
            question = (
                "合成自主调查：失败验证需要什么原文支持？" if rounds == 3
                else "合成自主调查：还有哪些个人责任尚未披露？"
            )
            if self.mode == "repeat" and rounds == 2:
                question = "合成自主调查：失败验证需要什么原文支持？"
            name, arguments = "propose_investigation", {
                "question": question, "kind": "counterexample",
                "completion": "区分原文明示和仍需实际验证的部分。",
                "evidence_needed": "回读JD的具体任务与责任边界，不假定个人拥有上线决定权。",
            }
        else:
            evidence = outputs[0]["evidence"][0]["id"]
            name, arguments = "finish_research", {
                "claims": [{"category": "ability", "basis": "direct", "requirement": "required",
                            "text": "合成岗位要求Python接口开发与测试能力。",
                            "evidence_ids": [evidence]}],
                "gaps": ["个人上线决定权与生产结果仍需另行核实。"],
                "application_plan": None,
            }
            project = context["project_context"]
            if project.get("previous_findings") or project.get("historical_reply"):
                arguments["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(arguments),
                "call_id": str(len(history))}
        return [call], call


def workspace(tmp_path, model):
    database = tmp_path / "autonomy.db"
    upgrade(database)
    return create_app(Settings(database_path=database, raw_directory=tmp_path / "raw"),
                      model=model, reports_dir=tmp_path / "reports")


def setup(client):
    auth = {"X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]}
    response = client.post("/api/import", headers=auth, json={
        "title": "合成自主调查岗位", "company": "合成团队", "data_kind": "synthetic",
        "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
    })
    job = response.json()["job_id"]
    goal = client.post("/api/career", headers=auth, json={
        "title": "合成连续查证", "goal": "理解工作要求与责任边界",
        "background": "只有本地虚构练习。", "job_ids": [job],
    }).json()["id"]
    base = f"/api/career/{goal}"
    question = client.post(base + "/questions", headers=auth, json={
        "question": "合成自主调查：这个岗位要验证什么？",
    }).json()["questions"][0]
    prepared = client.post(base + "/prepare", headers=auth, json={
        "kind": "ask", "question": question["question"], "question_id": question["id"],
        "autonomous": True,
    })
    assert prepared.status_code == 201, prepared.text
    step = prepared.json()["step_id"]
    return auth, goal, base, question, step


def settled(client, base):
    for _ in range(500):
        data = client.get(base).json()
        if not data["running"]:
            return data
        time.sleep(0.01)
    raise AssertionError("local inquiry worker did not finish")


@pytest.mark.parametrize("mode,expected", [("three", 3), ("early", 1), ("fail", 1), ("repeat", 2)])
def test_autonomy_stays_with_one_question_and_stops(tmp_path, mode, expected):
    model = AutonomousInquiryModel(mode)
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, question, step = setup(client)
        running = client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        assert running.status_code == 202 and running.json()["max_steps"] == 3
        data = settled(client, base)
        chronological = list(reversed(data["results"]))
        assert len(chronological) == expected, data
        assert all(row["question_id"] == question["id"] for row in chronological)
        assert [row["autonomous_rounds"] for row in chronological] == [3, 2, 1][:expected]
        assert all(row["source_step_id"] == chronological[n - 1]["step_id"]
                   for n, row in enumerate(chronological) if n)
        assert data["questions"][0]["state"] == "open" and not data["tasks"]
        assert not any(row["state"] in {"queued", "running"} for row in chronological)
        assert all("propose_research_memory" not in tools and "propose_knowledge" not in tools
                   and "propose_strategy" not in tools for tools in model.tool_sets)
        assert "propose_investigation" in model.tool_sets[0]
        if mode == "three":
            assert all(row["result"]["status"] == "completed" for row in chronological)
            assert "propose_investigation" not in model.tool_sets[-1]
            assert "三轮上限" in chronological[-1]["autonomous_stop"]
            assert data["usage"]["calls"] == 8
        elif mode == "fail":
            assert chronological[0]["result"]["status"] != "completed"
        elif mode == "repeat":
            assert "重复查证" in chronological[-1]["autonomous_stop"]


def test_paused_batch_continues_with_its_remaining_rounds(tmp_path):
    model = AutonomousInquiryModel("pause")
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, _, step = setup(client)
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        for _ in range(300):
            data = client.get(base).json()
            if len(data["results"]) == 2 and data["results"][0]["state"] == "running":
                break
            time.sleep(0.01)
        assert len(data["results"]) == 2
        paused = client.post(f"/api/projects/{goal}/pause", headers=auth, json={})
        assert paused.status_code == 200, paused.text
        data = settled(client, base)
        current = data["results"][0]
        assert current["state"] == "interrupted" and current["autonomous_rounds"] == 2
        resumed = client.post(f"/api/projects/{goal}/run", headers=auth,
                              json={"step_id": current["step_id"]})
        assert resumed.status_code == 202 and resumed.json()["max_steps"] == 2
        data = settled(client, base)
        assert len(data["results"]) == 3
        assert all(row["result"]["status"] == "completed" for row in data["results"])
