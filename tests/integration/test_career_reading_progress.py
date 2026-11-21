"""A scripted Agent can choose unread source positions across research sessions."""

import json
import re

import pytest
from starlette.testclient import TestClient
from test_career_autonomous_inquiry import settled
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

HEAD = "合成任务：核对输入样例与业务对象。"
TAIL = "末尾限定：交付差异清单；最终验收由业务负责人决定。"
BODY = HEAD + "\n这是合成工作背景🤔，核对业务对象与任务条件，不能外推个人权限。" * 260 + TAIL
assert 5600 < len(BODY) < 11200


class ReadingProgressModel(ModelClient):
    """Local substitute: choices follow the actual returned reading metadata."""

    def __init__(self):
        self.last_usage, self.decisions = {}, []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        jobs = context["fixed_scope"]["jobs"]
        followup = "合成按缺口续读" in context["question"]
        autonomy = context["project_context"]["career_evidence"].get("autonomous_inquiry")
        evidence = [row for output in outputs for row in output.get("evidence", [])]
        if jobs and not outputs:
            name, args = "query_jobs", {}
        elif not jobs and not outputs and "分页目录" in context["question"]:
            name, args = "list_archived_sources", {"offset": 0}
        elif not evidence:
            if jobs:
                source = outputs[-1]["jobs"][0]
            else:
                selected = context["fixed_scope"]["selected_public_document_ids"]
                documents = outputs[-1]["documents"] if outputs else (
                    context["fixed_scope"]["public_document_titles"])
                source = next(row for row in documents
                              if row["id"] in selected)
            progress = source["reading_progress"]
            assert progress["recorded_ranges"] == ([[0, 5600]] if followup else [])
            assert progress["next_unread_start"] == (5600 if followup else 0)
            assert "quote" not in progress and "evidence_ids" not in progress
            self.decisions.append({"kind": "job" if jobs else "archive",
                                   "id": source["id"], "start": progress["next_unread_start"]})
            name, args = ("read_job", {"job_id": source["id"],
                                      "start": progress["next_unread_start"]}) if jobs else (
                "read_archived_document", {"document_id": source["id"],
                                           "start": progress["next_unread_start"]})
        else:
            read_output = next(output for output in reversed(outputs)
                               if output.get("source_reading_progress"))
            progress = read_output["source_reading_progress"][0]["reading_progress"]
            assert progress["recorded_ranges"] == [[0, len(BODY)]] if followup else (
                progress["recorded_ranges"] == [[0, 5600]])
            assert progress["next_unread_start"] is None if followup else (
                progress["next_unread_start"] == 5600)
            if (autonomy and progress["next_unread_start"] is not None
                    and not any(row.get("name") == "propose_investigation" for row in history)):
                args = {"question": ("合成缺口Agent：合成按缺口续读，"
                                     "通过分页目录核对后文交付与验收。"),
                        "kind": "investigate", "completion": "核实后文的交付物及验收责任。",
                        "evidence_needed": "此前只读到5600；按缺口起点5600继续读取同一原文。"}
                call = {"type": "function_call", "name": "propose_investigation",
                        "arguments": json.dumps(args), "call_id": str(len(history))}
                return [call], call
            text = TAIL if followup else HEAD
            reference = next(row for row in evidence if text in row["quote"])
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "direct", "requirement": "unspecified",
                            "text": text, "evidence_ids": [reference["id"]]}],
                "gaps": ["合成资料不能证明实际执行、个人权限或招聘动机。"],
            }
            if (context["project_context"].get("previous_findings")
                    or context["project_context"].get("historical_reply")):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


@pytest.mark.parametrize("kind", ["archive", "job"])
def test_agent_uses_prior_reading_to_reach_tail_without_reusing_old_citations(tmp_path, kind):
    database = tmp_path / "reading-progress.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = ReadingProgressModel()
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]}

        def save(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        values = {"title": "合成读取进度", "goal": "核对后文的交付与验收条件"}
        if kind == "archive":
            values.update(material_title="合成缺口续读原文", material_text=BODY)
        else:
            job = save("/api/import", {"title": "合成缺口续读岗位", "company": "合成团队",
                                      "description": BODY, "data_kind": "synthetic"})["job_id"]
            values["job_ids"] = [job]
        goal = save("/api/career", values)
        identity, base = goal["id"], "/api/career/" + goal["id"]
        focus = {"material_ids": [goal["materials"][0]["id"]]} if kind == "archive" else {}
        first = run_stage(client, identity, auth, "ask", question="合成积累读取：先核对开头任务。",
                          **focus)["results"][0]
        assert first["result"]["status"] == "completed", first["result"]["stop_reason"]
        original = json.loads(json.dumps(first["result"]["evidence"]))
        assert max(row["end"] for row in original) == 5600
        second = run_stage(
            client, identity, auth, "ask",
            question="合成按缺口续读：通过分页目录核对后文交付与验收。",
            source_step_id=first["step_id"], **focus)["results"][0]
        result = second["result"]
        assert result["status"] == "completed", result["stop_reason"]
        assert result["claims"][0]["text"] == TAIL
        assert min(row["start"] for row in result["evidence"]) == 5600
        assert result["claims"][0]["evidence_ids"][0] in {row["id"] for row in result["evidence"]}
        assert any(row["reading_guides"] for row in result["trace"] if "reading_guides" in row)
        assert model.decisions[-1]["start"] == 5600
        assert next(row for row in client.get(base).json()["results"]
                    if row["step_id"] == first["step_id"])["result"]["evidence"] == original

        # A second goal has no reading history even when it selects the exact same source.
        foreign = save("/api/career", {"title": "合成独立目标", "goal": "不沿用其他目标的进度",
                                       **({"job_ids": [job]} if kind == "job" else {})})
        if kind == "archive":
            save("/api/career/" + foreign["id"] + "/materials/attach",
                 {"document_id": goal["materials"][0]["id"]})
        row = run_stage(client, foreign["id"], auth, "ask",
                        question="合成独立目标从头核对。", **focus)["results"][0]
        assert row["result"]["status"] == "completed", row["result"]["stop_reason"]
        assert model.decisions[-1]["start"] == 0

        # The same hints work inside the existing autonomous batch: fill the relevant
        # tail, then stop after two rounds instead of manufacturing a third round.
        auto = save("/api/career", {"title": "合成连续缺口调查", "goal": "按问题补读后文",
                                    **({"job_ids": [job]} if kind == "job" else {})})
        auto_base = "/api/career/" + auto["id"]
        if kind == "archive":
            save(auto_base + "/materials/attach", {"document_id": goal["materials"][0]["id"]})
        question = save(auto_base + "/questions", {
            "question": "合成缺口Agent：这个工作的交付和验收边界是什么？", **focus,
        })["questions"][-1]
        prepared = save(auto_base + "/prepare", {
            "kind": "ask", "question": question["question"],
            "question_id": question["id"], "autonomous": True,
        })
        running = client.post("/api/projects/" + auto["id"] + "/run", headers=auth,
                              json={"step_id": prepared["step_id"]})
        assert running.status_code == 202 and running.json()["max_steps"] == 3
        auto_result = settled(client, auto_base)
        rounds = sorted(auto_result["results"], key=lambda row: -row["autonomous_rounds"])
        assert len(rounds) == 2 and [row["autonomous_rounds"] for row in rounds] == [3, 2]
        assert min(item["start"] for item in rounds[1]["result"]["evidence"]) == 5600
        assert rounds[1]["result"]["claims"][0]["text"] == TAIL
        assert "未提出可继续的补查" in rounds[1]["autonomous_stop"]
        assert auto_result["questions"][0]["state"] == "open"

        # New original identity / JD snapshot does not inherit coverage of the previous original.
        if kind == "archive":
            revised = save(base + "/materials/" + goal["materials"][0]["id"] + "/revisions",
                           {"title": "合成缺口续读原文更正", "text": BODY + "补充来源说明。"})
            focus = {"material_ids": [revised["updated_material_id"]]}
        else:
            save(base + "/jobs/" + job + "/observations", {"description": BODY + "补充来源说明。"})
        row = run_stage(client, identity, auth, "ask", question="合成新原文从头核对。",
                        **focus)["results"][0]
        assert row["result"]["status"] == "completed", row["result"]["stop_reason"]
        assert model.decisions[-1]["start"] == 0
