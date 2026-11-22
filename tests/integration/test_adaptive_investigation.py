"""Isolated scripted-model checks; these do not measure real intent/semantic accuracy."""

import asyncio
import json
import re
import time

import pytest
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.research.orchestration import investigate
from work_observer.storage.database import upgrade


def task(intent="understand", terms=None, retry=None, question="这个工作具体要做什么？"):
    return {
        "intent": intent, "question": question, "completion": "分清原文任务和仍未知的责任。",
        "queries": [{"terms": terms or ["怎么把服务跑稳"], "reason": "保留口语表达作为初查。"}],
        "retry_queries": [{"terms": retry or ["接口", "测试"],
                           "reason": "换成原文可能使用的工作任务表达。"}],
    }


def brief(tasks=None, missing=None):
    return {"objective": "解释实际工作，再回应用户提出的其他意图。",
            "tasks": tasks or [task()], "missing_context": missing or []}


class ScriptedPlanner(ModelClient):
    def __init__(self, plan, *, replan=None, pause=False, omit_once=False, produce_plan=False):
        self.plan, self.replan, self.pause = plan, replan, pause
        self.contexts, self.tools_seen = [], []
        self.last_usage = {}
        self.omit_once = omit_once
        self.produce_plan = produce_plan

    async def turn(self, history):
        self.contexts.append(json.loads(history[1]["content"]))
        self.tools_seen.append({tool["name"] for tool in self.tools})
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        plans = [row for row in outputs if row.get("engine") == "langgraph"]
        if not plans:
            name, arguments = "plan_investigation", self.plan
        elif self.replan and len(plans) == 1:
            name, arguments = "plan_investigation", self.replan
        else:
            if self.pause:
                await asyncio.sleep(1)
            latest = plans[-1]
            evidence = latest["evidence"]
            claims = [{"category": "task", "basis": "direct", "requirement": "unspecified",
                       "text": "负责接口开发与测试。", "evidence_ids": [row["citation_key"]]}
                      for row in evidence]
            arguments = {"claims": claims, "gaps": ["资料未说明最终上线决定权。"],
                         "task_outcomes": [{
                             "task_index": index,
                             "status": "partial" if task["retrieval_status"]
                             != "candidates_need_reading" or (
                                 task["intent"] == "practice" and not self.produce_plan
                             ) else "answered",
                             "answer": "合成脚本回应该项问题，仍须核对实际资料与条件。",
                             "claim_indices": list(range(len(claims))),
                             "action_indices": [],
                             "questions": ["接口开发时，你如何取舍测试范围并保留限制？"]
                             if task["intent"] == "interview" else [],
                         } for index, task in enumerate(latest["tasks"])]}
            finish = next(tool for tool in self.tools if tool["name"] == "finish_research")
            if "application_plan" in finish["parameters"]["properties"]:
                arguments["application_plan"] = None
                if self.produce_plan and evidence:
                    arguments["application_plan"] = {
                        "background_memory_id": self.contexts[-1]["application_background"][
                            "memory_id"
                        ],
                        "actions": [{
                            "title": "用两组构造输入检查接口失败处理",
                            "task_or_ability": "接口测试",
                            "deliverable": "两组输入与观察记录",
                            "completion_check": "逐组记录差异和失败。",
                            "hypothesis": "输入变化可能影响处理，尚未验证。",
                            "evidence_ids": [evidence[0]["citation_key"]],
                            "assumptions": ["只用构造资料，不依赖企业权限。"],
                            "comparison_conditions": "保持处理逻辑一致，只改变输入。",
                            "comparison_rows": [
                                {"condition": "原条件", "input": "合成请求A",
                                 "expected": "待检验：仅处理一次"},
                                {"condition": "改变输入", "input": "合成请求B",
                                 "expected": "待检验：可能失败"},
                            ],
                        }], "open_questions": ["个人环境与时间未提供。"],
                    }
                    eligible = [i for i, item in enumerate(latest["tasks"])
                                if item["intent"] in {"practice", "verify"}]
                    if len(eligible) == 1:
                        arguments["task_outcomes"][eligible[0]]["action_indices"] = [0]
            name = "finish_research"
            if self.omit_once:
                arguments["task_outcomes"] = []
                self.omit_once = False
        call = {"type": "function_call", "name": name, "arguments": json.dumps(arguments),
                "call_id": str(len(history))}
        return [call], call


def workspace(tmp_path, model):
    path = tmp_path / "adaptive.db"
    upgrade(path)
    return create_app(Settings(database_path=path, raw_directory=tmp_path / "raw"),
                      model=model, reports_dir=tmp_path / "reports")


def prepare(client, question, cities=None, before_prepare=None):
    auth = {"X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]}
    jobs = [client.post("/api/import", headers=auth, json={
        "title": "合成服务岗位" + str(index), "company": "合成公司" + str(index),
        "data_kind": "synthetic", "description": "负责接口开发与测试。上线责任未披露。",
        **({"city": cities[index]} if cities else {}),
    }).json()["job_id"] for index in range(2)]
    goal = client.post("/api/career", headers=auth, json={
        "title": "合成意图编排", "goal": "理解实际工作", "job_ids": jobs,
    }).json()["id"]
    base = f"/api/career/{goal}"
    if before_prepare:
        before_prepare(client, auth, base)
    response = client.post(base + "/prepare", headers=auth, json={
        "kind": "ask", "question": question, "adaptive": True,
    })
    assert response.status_code == 201, response.text
    return auth, goal, base, response.json()["step_id"], jobs


def settled(client, base):
    for _ in range(500):
        data = client.get(base).json()
        if not data["running"]:
            return data
        time.sleep(0.01)
    raise AssertionError("scripted investigation did not settle")


def test_followup_search_ranks_concrete_requirements_in_the_frozen_job_scope(tmp_path):
    class FollowupSearch(ScriptedPlanner):
        async def turn(self, history):
            outputs = [json.loads(row["output"]) for row in history
                       if row.get("type") == "function_call_output"]
            plans = [row for row in outputs if row.get("engine") == "langgraph"]
            searches = [row for row in outputs if "expanded_terms" in row
                        and "match_note" in row]
            if not plans:
                return await super().turn(history)
            if not searches:
                name, arguments = "search_evidence", {"terms": ["Agent", "端云同步"]}
            else:
                self.followup = searches[-1]
                first = self.followup["evidence"][0]
                assert "端云同步" in first["quote"]
                name = "finish_research"
                arguments = {
                    "claims": [{"category": "ability", "basis": "direct",
                                "requirement": "required", "text": "任职要求写明掌握端云同步记忆。",
                                "evidence_ids": [first["citation_key"]]}],
                    "gaps": ["该合成资料没有披露能力的实际验收方式。"],
                    "task_outcomes": [{"task_index": 0, "status": "answered",
                                       "answer": "任职要求写明掌握端云同步记忆。",
                                       "claim_indices": [0], "action_indices": [], "questions": []}],
                    "application_plan": None,
                }
            call = {"type": "function_call", "name": name,
                    "arguments": json.dumps(arguments), "call_id": str(len(history))}
            return [call], call

    model = FollowupSearch(brief([task(terms=["Agent"], retry=["记忆"])]))
    text = "Agent " * 55 + "。" + "通用业务描述。" * 90 + "任职要求：掌握端云同步记忆。"
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        jobs = [client.post("/api/import", headers=auth, json={
            "title": "合成排序岗位" + str(i), "company": "合成公司" + str(i),
            "description": body, "data_kind": "synthetic",
        }).json()["job_id"] for i, body in enumerate([
            text, "Agent工具集成，Agent平台接口。", "端云同步 " * 100,
        ])]
        goal = client.post("/api/career", headers=auth, json={
            "title": "合成补查排序", "goal": "核对原文要求", "job_ids": jobs[:2],
        }).json()["id"]
        base = f"/api/career/{goal}"
        step = client.post(base + "/prepare", headers=auth, json={
            "kind": "ask", "question": "这些JD写了哪些端云同步要求？", "adaptive": True,
        }).json()["step_id"]
        response = client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        assert response.status_code == 202, response.text
        result = settled(client, base)["results"][0]["result"]
        assert result["status"] == "completed", result
        found = model.followup["evidence"]
        assert found[0]["job_id"] == jobs[0]
        assert found[0]["quote"] == text[found[0]["start"] : found[0]["end"]]
        assert {item["job_id"] for item in found} <= set(jobs[:2])
        assert model.followup["matching_jobs"] == 2
        assert model.followup["reading_guide"]["sources"]


@pytest.mark.parametrize("question,tasks", [
    ("说白了这工作天天忙啥，顺便给个能自己动手验证的小练习", [task(), task("practice")]),
    ("这俩活儿差在哪？面试我该怎么讲取舍", [task("compare"), task("interview")]),
    ("我把这个理解成写接口就够了，对不对？", [task("verify")]),
])
def test_scripted_multi_intent_rewrite_retry_and_delivery(tmp_path, question, tasks):
    model = ScriptedPlanner(brief(tasks, ["个人项目中具体承担过什么仍需补充。"] ))
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, jobs = prepare(client, question)
        response = client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        assert response.status_code == 202, response.text
        row = settled(client, base)["results"][0]
        result = row["result"]
        assert result["status"] == "completed", result
        investigation = result["investigation"]
        assert investigation["original_question"] == question
        assert set(investigation["scope"]["job_ids"]) == set(jobs)
        assert [row["intent"] for row in investigation["tasks"]] == [t["intent"] for t in tasks]
        assert len(investigation["outcomes"]) == len(tasks)
        assert all(row["retried"] for row in investigation["tasks"])
        assert all(row["candidate_sources"] == 2 for row in investigation["tasks"])
        assert model.tools_seen[0] == {"plan_investigation"}
        assert result["model_calls"] == 2  # planning+local recall, then final response
        assert all(row["job_id"] in jobs for row in result["evidence"])
        assert any("待补背景" in value for value in result["gaps"])
        assert "task_outcomes" not in result["claims"][0]
        if any(task["intent"] == "interview" for task in tasks):
            assert result["interview_questions"] == ["接口开发时，你如何取舍测试范围并保留限制？"]
            prepared = client.post(base + "/prepare", headers=auth, json={
                "kind": "answer", "source_step_id": step, "question_index": 0,
                "answer": "合成自述：我只有本地练习，未承担企业上线责任。",
            })
            assert prepared.status_code == 201, prepared.text
            next_row = client.get(base).json()["results"][0]
            assert next_row["interview_question"] == result["interview_questions"][0]


def test_no_hits_can_finish_with_explicit_gaps_and_no_invented_claim(tmp_path):
    model = ScriptedPlanner(brief([task(terms=["未披露的审批权"], retry=["不存在的交付物"])]))
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, _ = prepare(client, "是不是我有最终审批权？")
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        result = settled(client, base)["results"][0]["result"]
        assert result["status"] == "completed", result
        assert result["claims"] == []
        assert result["investigation"]["tasks"][0]["retrieval_status"] == "no_work_evidence"
        assert result["investigation"]["outcomes"][0]["status"] == "partial"


def test_replanning_keeps_original_question_and_history(tmp_path):
    first = brief([task(terms=["不存在"], retry=["还是不存在"])])
    model = ScriptedPlanner(first, replan=brief([task(terms=["接口"], retry=["测试"])]))
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, _ = prepare(client, "服务怎么跑稳？")
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        result = settled(client, base)["results"][0]["result"]
        assert result["status"] == "completed", result
        assert result["investigation"]["original_question"] == "服务怎么跑稳？"
        previous = result["investigation_history"][0]
        assert previous["tasks"][0]["retrieval_status"] == "no_work_evidence"
        assert result["trace"][1]["replanned"]
        assert result["model_calls"] == 3


def test_graph_never_widens_scope_and_separates_personal_sources(tmp_path):
    model = ScriptedPlanner(brief())
    app = workspace(tmp_path, model)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _, _, _, _, jobs = prepare(client, "接口怎么做？")
        # Read only the isolated application repository; never the real workspace data.
        from work_observer.storage.repository import Repository

        repository = Repository(tmp_path / "adaptive.db")
        try:
            data = investigate(
                repository, brief([task(terms=["接口"], retry=["测试"])]),
                original_question="只看第一个岗位", scope={"jobs": [{"id": jobs[0]}],
                                                       "filters": {}, "archived_public_ids": []},
                project_id=None, as_of="2026-11-23T23:59:59+00:00", aliases={},
                personal_document_ids=["out-of-scope-personal"],
            )
            assert data["evidence"] and {row["job_id"] for row in data["evidence"]} == {jobs[0]}
            assert not data["tasks"][0]["retried"]
            assert data["context_characters"] <= 7000
            assert all(row["channel"] == "work" for row in data["tasks"][0]["attempts"])

            from work_observer.connectors.public_documents import PublicDocumentService

            docs = PublicDocumentService(repository, tmp_path / "scoped-public")
            personal = docs.archive_text("合成个人自述", "我负责个人审批与测试。", "合成用户材料。")
            work = docs.archive_text("合成工作说明", "负责业务流程记录。", "合成工作材料。")
            personal_id, work_id = personal["document"]["id"], work["document"]["id"]
            isolated = investigate(
                repository, brief([task("verify", terms=["个人审批"], retry=["个人审批"])]),
                original_question="这个岗位是否拥有审批权？", scope={
                    "jobs": [], "filters": {}, "archived_public_ids": [personal_id, work_id],
                }, project_id=None, as_of=None, aliases={}, personal_document_ids=[personal_id],
            )
            assert {row["public_document_id"] for row in isolated["evidence"]} == {personal_id}
            assert isolated["tasks"][0]["retrieval_status"] == "no_work_evidence"
            assert [row["channel"] for row in isolated["tasks"][0]["attempts"]] == [
                "work", "personal",
            ]  # Repeated retry queries do not run again.
            past = investigate(
                repository, brief([task(terms=["接口"])]), original_question="过去的岗位",
                scope={"jobs": [{"id": jobs[0]}], "filters": {}, "archived_public_ids": []},
                project_id=None, as_of="2000-01-01T00:00:00+00:00", aliases={},
            )
            assert past["evidence"] == []
        finally:
            repository.close()


def test_pause_resume_keeps_accepted_plan_and_evidence(tmp_path):
    model = ScriptedPlanner(brief(), pause=True)
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, _ = prepare(client, "服务怎么跑稳？")
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        for _ in range(300):
            progress = client.get(base).json()["results"][0]
            if (progress.get("result") or {}).get("investigation"):
                break
            time.sleep(0.01)
        assert progress["result"]["investigation"]
        assert client.post(f"/api/projects/{goal}/pause", headers=auth, json={}).status_code == 200
        paused = settled(client, base)["results"][0]
        assert paused["state"] == "interrupted", paused
        model.pause = False
        resumed = client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        assert resumed.status_code == 202, resumed.text
        result = settled(client, base)["results"][0]["result"]
        assert result["status"] == "completed", result
        assert len([entry for entry in result["trace"]
                    if entry["tool"] == "plan_investigation"]) == 1
        assert result["investigation"]["scope"] == paused["result"]["investigation"]["scope"]


def test_omitted_intents_receive_feedback_and_can_be_corrected(tmp_path):
    model = ScriptedPlanner(brief([task(), task("practice")]), omit_once=True)
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, _ = prepare(client, "先解释工作，再设计一个验证")
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        result = settled(client, base)["results"][0]["result"]
        assert result["status"] == "completed", result
        assert result["trace"][1]["validation"] == "investigation_needs_adjustment"
        assert len(result["investigation"]["outcomes"]) == 2
        assert result["model_calls"] == 3


def test_followup_keeps_user_scope_and_explicit_release_reuses_existing_jobs(tmp_path):
    plan = brief()
    plan["constraints"] = [{"field": "city", "value": "上海", "source_text": "只看上海"}]
    model = ScriptedPlanner(plan)
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, jobs = prepare(client, "只看上海，服务怎么跑稳？", ["上海", "北京"])
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        first = settled(client, base)["results"][0]
        assert first["result"]["status"] == "completed", first
        assert first["result"]["investigation"]["effective_scope"]["job_ids"] == [jobs[0]]
        for question, release in [
            ("那应该怎么理解测试工作？", False), ("这次不限城市，都看看", True),
        ]:
            model.plan = brief()
            if release:
                model.plan["released_constraints"] = [{"field": "city", "source_text": "不限城市"}]
            prepared = client.post(base + "/prepare", headers=auth, json={
                "kind": "ask", "source_step_id": step, "question": question, "adaptive": True,
            })
            assert prepared.status_code == 201, prepared.text
            next_step = prepared.json()["step_id"]
            client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": next_step})
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row
            investigation = row["result"]["investigation"]
            expected = jobs if release else jobs[:1]
            assert set(investigation["effective_scope"]["job_ids"]) == set(expected)
            assert model.contexts[-1]["project_context"]["career_evidence"][
                "continued_discussion"
            ]["investigation"]["constraints"] == first["result"]["investigation"]["constraints"]


def test_rewritten_queries_find_old_understanding_without_adopting_or_citing_it(tmp_path):
    model = ScriptedPlanner(brief([task("verify", terms=["idempotency_key"], retry=["接口"])]))
    identities = {}

    def add_notes(client, auth, base):
        for name, use in [("related", True), ("parked", False)]:
            data = {"previous_view": "retry", "observation": "serialization_failure",
                    "current_view": "idempotency_key requires atomic_commit " + name,
                    "open_question": "unique_violation"}
            response = client.post(base + "/insights", headers=auth, json=data)
            assert response.status_code == 201, response.text
            note = next(row for row in response.json()["insights"]
                        if row["current_view"] == data["current_view"])
            identities[name] = note["id"]
            if not use:
                assert client.post(base + "/insights/" + note["id"] + "/use", headers=auth,
                                   json={"use_for_research": False}).status_code == 200

    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, _ = prepare(
            client, "提交失败后再来一次，结果会不会多一份？", before_prepare=add_notes,
        )
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        data = settled(client, base)
        result = data["results"][0]["result"]
        assert result["status"] == "completed", result
        initial = model.contexts[0]["project_context"]["career_evidence"]["learning_notes"]
        assert identities["related"] not in {row["id"] for row in initial}
        recalled = result["investigation"]["memory_recall"]
        assert recalled["context_characters"] <= 5000
        records = recalled["records"]
        assert identities["related"] in {row["record_id"] for row in records}
        assert identities["parked"] not in {row["record_id"] for row in records}
        assert all(row["derived"] and not row["independent_source"] for row in records)
        assert not set(identities.values()) & {row["id"] for row in result["evidence"]}
        assert next(row for row in data["insights"]
                    if row["id"] == identities["parked"])["use_for_research"] is False
        assert result["model_calls"] == 2


def test_one_unavailable_memory_category_does_not_stop_source_investigation(tmp_path, monkeypatch):
    from work_observer.connectors.mcp_probe import ProbeError
    from work_observer.research.learning import LearningNotebook

    def unavailable(*_args, **_kwargs):
        raise ProbeError("LEARNING_NOTE_NOT_AVAILABLE")

    monkeypatch.setattr(LearningNotebook, "search", unavailable)
    model = ScriptedPlanner(brief())
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, _ = prepare(client, "服务怎么跑稳？")
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        result = settled(client, base)["results"][0]["result"]
        assert result["status"] == "completed", result
        assert result["evidence"]
        assert result["investigation"]["memory_recall"]["unavailable_kinds"] == ["understanding"]
