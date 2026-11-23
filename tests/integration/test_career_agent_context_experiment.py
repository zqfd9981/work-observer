"""A scoped investigation runs real local context calculations without fabricating evidence."""

import json
import re

import pytest
from starlette.testclient import TestClient
from test_adaptive_investigation import ScriptedPlanner, brief, settled, task, workspace
from test_requirement_interview import RequirementInterviewModel

from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore

PREDICTION = "冲突不提供新旧依据，仍需区分输入条件。" * 52 + "末尾预期：删除和断连仍未验证。"


class ContextProbeModel(ScriptedPlanner):
    def __init__(self, bad_first=False):
        super().__init__(brief([task(terms=["上下文"], retry=["记忆"],
                                    question="用两组小样本解释上下文合并的边界。")]))
        self.bad_first, self.cite_probe = bad_first, False

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        if context["project_context"]["career_action"] == "role":
            return await RequirementInterviewModel.turn(self, history)
        personal = context["project_context"]["career_evidence"]
        assert personal["selected_requirement"] == self.target
        assert {row["id"] for row in context["fixed_scope"]["jobs"]} == {self.selected_job}
        assert context["fixed_scope"]["archived_public_ids"] == []
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        plans = [row for row in outputs if row.get("engine") == "langgraph"]
        if not plans:
            return await super().turn(history)
        assert "run_context_experiment" in {row["name"] for row in self.tools}
        probe = next((row for row in outputs if row.get("kind") == "local_context_merge"), None)
        if not probe:
            self.contexts.append(context)
            name, values = "run_context_experiment", {
                "hypothesis": PREDICTION, "data_kind": "synthetic", "cases": [
                    {"name": "相同副本", "edge": [{"key": "m1", "value": "相同内容"}],
                     "cloud": [{"key": "m1", "value": "相同内容"}]},
                    {"name": "冲突与单端", "edge": [{"key": "m2", "value": "端侧内容"},
                                                   {"key": "m3", "value": "仅在快照里的独特样例"}],
                     "cloud": [{"key": "m2", "value": "云侧内容<局部样例>"}]},
                ],
            }
            if self.bad_first and not any(row.get("error") for row in outputs):
                values["save"] = True
            call = {"type": "function_call", "name": name, "arguments": json.dumps(values),
                    "call_id": str(len(history))}
            return [call], call
        assert probe["hypothesis"] == PREDICTION
        assert probe["cases"][0]["folded_copies"] == 1
        assert probe["cases"][1]["conflicting_keys"] == ["m2"]
        assert len(probe["cases"][1]["merged"][0]["variants"]) == 2
        assert probe["cases"][1]["one_sided_keys"] == ["m3"]
        assert "artifact_text" not in probe and "evidence_ids" not in json.dumps(probe)
        returned, call = await super().turn(history)
        values = json.loads(call["arguments"])
        for claim in values["claims"]:
            claim["text"] = self.target["text"]
            if self.cite_probe:
                claim["evidence_ids"] = ["local_context_merge"]
        values["gaps"] = ["真实协议、时序、断连和删除传播仍未验证。"]
        call["arguments"] = json.dumps(values)
        return returned, call


@pytest.mark.parametrize("bad_first", [False, True])
def test_natural_question_runs_context_probe_and_keeps_history_distinct_from_sources(
    tmp_path, bad_first,
):
    model = ContextProbeModel(bad_first)
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": "合成自动上下文示例岗位" + str(i), "company": "合成团队" + str(i),
            "description": text, "data_kind": "synthetic",
        })["job_id"] for i, text in enumerate([
            "可选专攻方向之一：上下文工程与记忆，负责端云上下文管理。", "维护其他支付工作。",
        ])]
        goal = post("/api/career", {
            "title": "合成自然问题到本机运行", "goal": "用已有JD和小样本区分记忆与同步条件",
            "job_ids": jobs, "material_title": "未选资料", "material_text": "其他任务笔记。",
        })
        base = "/api/career/" + goal["id"]
        model.selected_job = jobs[0]

        def run(values):
            step = post(base + "/prepare", values)
            post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
            return settled(client, base)["results"][0]

        assert run({"kind": "role"})["result"]["status"] == "completed"
        point = client.get(base).json()["requirements"][0]
        inquiry = post(base + "/questions", {
            "requirement_key": point["key"], "question": "能用小样本说明上下文合并吗？",
        })["questions"][-1]
        model.target = inquiry["target_requirement"]
        before = client.get(base).json()
        asked = {"kind": "ask", "question_id": inquiry["id"], "question": inquiry["question"],
                 "adaptive": True, "allow_public": False}
        row = run(asked)
        result = row["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        probes = result["career_learning_context"]["context_experiments"]
        assert len(probes) == 1 and probes[0]["hypothesis"] == PREDICTION
        trace = [entry for entry in result["trace"] if entry["tool"] == "run_context_experiment"]
        assert trace[-1]["case_count"] == 2 and trace[-1]["record_count"] == 5
        if bad_first:
            assert trace[0]["validation"] == "INVALID_CONTEXT_EXPERIMENT_INPUT"
        after = client.get(base).json()
        for field in ("tasks", "insights", "questions", "document_ids"):
            assert after[field] == before[field]
        assert all(ev.get("job_id") == jobs[0] for ev in result["evidence"])
        note = post(base + "/insights", {
            "source_step_id": row["step_id"], "question_id": inquiry["id"],
            "previous_view": "以为编号相同就能自动覆盖。",
            "observation": "构造对照保留了冲突内容。",
            "current_view": "同编号不说明权威与新旧，仍需协议条件。",
        })["insights"][-1]
        project = client.get("/api/projects/" + goal["id"]).json()
        store = ResearchStore(tmp_path / "checkpoints.db",
                              namespace=str((tmp_path / "adaptive.db").resolve()))
        try:
            notebook = LearningNotebook(lambda: project, store)
            original = notebook.read_research_history(row["step_id"])["research"]
            assert original["local_calculations"]["context_experiments"] == probes
            recalled = notebook.read(note["id"])["note"]
            assert recalled["source_calculations"]["context_experiments"] == probes
            found = notebook.search_research_history(["仅在快照里的独特样例"])
            assert any(item["step_id"] == row["step_id"] for item in found["research"])
        finally:
            store.close()
        if not bad_first:
            model.cite_probe = True
            rejected = run(asked)
            assert rejected["result"]["status"] != "completed"
