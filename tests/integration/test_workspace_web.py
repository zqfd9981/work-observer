"""G6持久研究和业务记忆的隔离HTTP集成，模型为明确测试替身。"""

import asyncio
import json
import re
import time

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def headers(client):
    token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
    return {"X-WO-Token": token}


def fixture_settings(tmp_path):
    db = tmp_path / "business.db"
    upgrade(db)
    return Settings(database_path=db, raw_directory=tmp_path / "raw")


def add_jd(client, auth):
    return client.post(
        "/api/import",
        json={
            "title": "HTTP隔离测试岗位（非真实招聘）",
            "company": "测试公司",
            "description": "模拟职责：必须掌握 Python，负责接口开发与上线。",
            "external_id": "workspace-http-test",
            "data_kind": "synthetic",
        },
        headers=auth,
    ).json()["job_id"]


def done(client, identity):
    for _ in range(100):
        run = client.get("/api/research/" + identity).json()
        if run["state"] != "running":
            return run
        time.sleep(0.01)
    raise AssertionError("测试研究未及时结束")


class PausingModel:
    """首个调用读取范围，第二个调用等待，恢复后查原文并完成。"""

    def __init__(self, pause=True):
        self.pause = pause

    async def turn(self, history):
        outputs = [
            json.loads(item["output"])
            for item in history
            if item.get("type") == "function_call_output"
        ]
        if not outputs:
            name, arguments = "query_jobs", {}
        elif not any(item.get("evidence") for item in outputs):
            if self.pause:
                await asyncio.sleep(30)
            name, arguments = "read_job", {"job_id": outputs[0]["jobs"][0]["id"]}
        else:
            evidence = next(item["evidence"] for item in outputs if item.get("evidence"))
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "ability",
                            "requirement": "required",
                            "basis": "direct",
                            "text": "测试岗位原文要求掌握 Python。",
                            "evidence_ids": [evidence[0]["id"]],
                        }
                    ],
                    "gaps": ["模拟材料只用于集成机制测试。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "call_id": "test-" + str(len(history)),
            "arguments": json.dumps(arguments, ensure_ascii=False),
        }
        return [call], call


def test_restart_preserves_result_save_id_and_memory_versions(tmp_path):
    settings = fixture_settings(tmp_path)
    kwargs = {"reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = headers(client)
        job_id = add_jd(client, auth)
        memory = client.post(
            "/api/memories",
            json={"kind": "preference", "content": "优先关注上线责任"},
            headers=auth,
        ).json()
        run_id = client.post(
            "/api/research", json={"question": "隔离离线研究", "offline": True}, headers=auth
        ).json()["id"]
        assert done(client, run_id)["result"]["status"] == "evidence_only"
        saved = client.post(f"/api/research/{run_id}/save", headers=auth).json()
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = headers(client)
        run = client.get("/api/research/" + run_id).json()
        assert run["state"] == "finished" and run["saved"] == saved
        assert client.post(f"/api/research/{run_id}/save", headers=auth).json() == saved
        assert len(client.get("/api/reports").json()) == 1
        assert client.get("/api/research").json()[0]["question"] == "隔离离线研究"
        revised = client.post(
            f"/api/memories/{memory['id']}/revise",
            json={"content": "优先关注 Python 上线责任"},
            headers=auth,
        ).json()
        assert revised["version"] == 2
        assert client.get("/api/memories").json()[0]["id"] == revised["id"]
        history = client.get("/api/memories?history=1").json()
        assert len(history) == 2 and any(row["status"] == "superseded" for row in history)
        assert (
            client.post(f"/api/memories/{revised['id']}/withdraw", headers=auth).status_code == 200
        )
        assert client.get("/api/memories").json() == []
        assert (
            client.get("/api/jobs/" + job_id)
            .json()["current"]["description_text"]
            .startswith("模拟")
        )


def test_cancel_restart_resume_uses_checkpoint_and_remaining_budget(tmp_path):
    settings = fixture_settings(tmp_path)
    kwargs = {"reports_dir": tmp_path / "reports"}
    with TestClient(
        create_app(settings, model=PausingModel(), **kwargs), base_url="http://127.0.0.1"
    ) as client:
        auth = headers(client)
        add_jd(client, auth)
        identity = client.post(
            "/api/research", json={"question": "隔离模型研究", "max_calls": 6}, headers=auth
        ).json()["id"]
        for _ in range(100):
            run = client.get("/api/research/" + identity).json()
            if run.get("result", {}).get("model_calls", 0) >= 2:
                break
            time.sleep(0.01)
        assert (
            client.post(f"/api/research/{identity}/cancel", headers=auth).json()["state"]
            == "interrupted"
        )
        interrupted = client.get("/api/research/" + identity).json()
        assert interrupted["resumable"] and interrupted["result"]["model_calls"] == 2
    with TestClient(
        create_app(settings, model=PausingModel(pause=False), **kwargs), base_url="http://127.0.0.1"
    ) as client:
        auth = headers(client)
        assert client.get("/api/overview").json()["active_research"] is None
        assert client.post(f"/api/research/{identity}/resume", headers=auth).status_code == 202
        final = done(client, identity)
        assert final["result"]["status"] == "completed"
        assert final["result"]["model_calls"] == 4
        assert len(client.get("/api/research").json()) == 1
        assert client.post(f"/api/research/{identity}/resume", headers=auth).status_code == 409
        candidate = client.post(
            "/api/memories",
            json={"kind": "knowledge", "source_run_id": identity, "claim_index": 0},
            headers=auth,
        )
        assert candidate.status_code == 201
        item = candidate.json()
        assert item["status"] == "candidate" and item["evidence"][0]["quote"].startswith("模拟")
        adopted = client.post(f"/api/memories/{item['id']}/activate", headers=auth).json()
        assert adopted["status"] == "active"
        assert (
            client.post(
                "/api/memories",
                json={"kind": "knowledge", "content": "不带来源的伪造知识"},
                headers=auth,
            ).status_code
            == 400
        )


def test_memory_writes_use_same_origin_and_unknown_actions_fail(tmp_path):
    settings = fixture_settings(tmp_path)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        auth = headers(client)
        assert (
            client.post("/api/memories", json={"kind": "preference", "content": "测试"}).status_code
            == 403
        )
        assert (
            client.post(
                "/api/memories",
                json={"kind": "preference", "content": "测试"},
                headers={**auth, "Origin": "https://example.com"},
            ).status_code
            == 403
        )
        assert client.post("/api/memories/missing/erase", headers=auth).status_code == 400
        assert (
            client.post(
                "/api/memories",
                json={"kind": "preference", "content": "测试", "security_id": "hidden"},
                headers=auth,
            ).status_code
            == 422
        )


def test_profile_and_matching_are_operable_without_model_and_keep_unknowns(tmp_path):
    settings = fixture_settings(tmp_path)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        auth = headers(client)
        identity = add_jd(client, auth)
        assert client.get("/api/profiles/" + identity).json()["status"] == "not_analyzed"
        result = client.post("/api/profiles/" + identity, json={"offline": True}, headers=auth)
        assert result.status_code == 200
        profile = result.json()
        assert profile["status"] == "evidence_only"
        assert profile["result"]["evidence"] and profile["result"]["claims"] == []
        assert client.get("/api/profiles/" + identity).json()["id"] == profile["id"]
        matching = client.post(
            "/api/matches",
            json={"preferences": {"cities": ["上海"], "salary_min": "20000"}},
            headers=auth,
        ).json()
        assert matching["counts"] == {"matched": 0, "unknown": 1, "excluded": 0}
        assert all(reason["status"] == "unknown" for reason in matching["jobs"][0]["reasons"])
        corrected = client.post(
            f"/api/profiles/{identity}/correction",
            json={"domains": ["business_application"], "reason": "测试原文负责接口开发"},
            headers=auth,
        )
        assert corrected.status_code == 201
        current = client.get("/api/profiles/" + identity).json()
        assert current["stale"]
        assert current["result"]["effective_domains"][0]["status"] == "user_corrected"
        assert (
            client.post(
                "/api/matches",
                json={"preferences": {"salary_min": 50000, "salary_max": 1}},
                headers=auth,
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/profiles/{identity}/correction",
                json={"domains": ["made-up-domain"], "reason": "测试"},
                headers=auth,
            ).status_code
            == 400
        )


def test_profile_analysis_shares_single_research_budget_gate(tmp_path):
    settings = fixture_settings(tmp_path)
    with TestClient(
        create_app(settings, model=PausingModel()), base_url="http://127.0.0.1"
    ) as client:
        auth = headers(client)
        identity = add_jd(client, auth)
        run = client.post("/api/research", json={"question": "隔离慢研究"}, headers=auth).json()
        assert (
            client.post(
                "/api/profiles/" + identity, json={"offline": True}, headers=auth
            ).status_code
            == 409
        )
        client.post(f"/api/research/{run['id']}/cancel", headers=auth)
        assert (
            client.post(
                "/api/profiles/" + identity, json={"offline": True}, headers=auth
            ).status_code
            == 200
        )


def test_saved_structured_preferences_and_strategy_evaluation_flow(tmp_path):
    settings = fixture_settings(tmp_path)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        auth = headers(client)
        add_jd(client, auth)
        assert client.get("/api/preferences").json()["memory_id"] is None
        first = client.post(
            "/api/preferences", json={"cities": ["上海"], "salary_min": "20000"}, headers=auth
        ).json()
        second = client.post("/api/preferences", json={"cities": ["杭州"]}, headers=auth).json()
        assert first["version"] == 1 and second["version"] == 2
        assert client.get("/api/preferences").json()["preferences"]["cities"] == ["杭州"]
        search = client.post(
            "/api/retrieval", json={"terms": ["Python"], "aliases": True}, headers=auth
        ).json()
        assert search["retrieval"]["evidence"]
        assert search["statistics"]["statistics"][0]["literal_jobs"] == 1
        assert search["statistics"]["sample"]["denominator"] == 1
        strategies = client.get("/api/strategies").json()
        item = client.post(
            "/api/strategies",
            json={"name": "隔离测试别名候选", "aliases": strategies["template"]},
            headers=auth,
        ).json()
        identity = item["id"]
        assert client.post(f"/api/strategies/{identity}/activate", headers=auth).status_code == 400
        evaluated = client.post(f"/api/strategies/{identity}/evaluate", headers=auth).json()
        assert evaluated["status"] == "accepted"
        assert evaluated["metrics"]["data_mode"] == "synthetic_test_only"
        assert evaluated["metrics"]["external_calls"] == 0
        assert (
            client.post(f"/api/strategies/{identity}/activate", headers=auth).json()["status"]
            == "active"
        )
        assert client.post("/api/strategies/monitor", headers=auth).json()["status"] == "passed"
        rollback = client.post(
            "/api/strategies/rollback", json={"reason": "隔离HTTP测试回退"}, headers=auth
        ).json()
        assert rollback["rolled_back"] == identity
        assert client.get("/api/overview").json()["jobs"] == 1
        assert (
            client.post(
                "/api/retrieval", json={"terms": ["Python"], "as_of": "2026-01-01"}, headers=auth
            ).status_code
            == 400
        )


def test_second_server_for_same_database_is_rejected(tmp_path):
    import pytest

    from work_observer.connectors.mcp_probe import ProbeError

    settings = fixture_settings(tmp_path)
    with TestClient(create_app(settings), base_url="http://127.0.0.1"):
        with pytest.raises(ProbeError, match="DATABASE_IN_USE"):
            with TestClient(create_app(settings), base_url="http://127.0.0.1"):
                raise AssertionError("第二服务不应取得同库运行权")


def test_operations_keep_pause_task_state_schedule_and_followup_isolated(tmp_path):
    settings = fixture_settings(tmp_path)
    source_root = tmp_path / "paused-source"
    source_root.mkdir()
    (source_root / "cdp_risk_lock.json").write_text("{}", encoding="utf-8")
    mcp_config = tmp_path / "mcp.toml"
    mcp_config.write_text(
        'transport="stdio"\ncommand="must-never-execute"\nargs=["--data-dir",'
        + json.dumps(str(source_root).replace("\\", "/"))
        + "]\n",
        encoding="utf-8",
    )
    settings.mcp_config = mcp_config
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        auth = headers(client)
        created = client.post(
            "/api/watchsets",
            json={"name": "隔离暂停观察", "spec": {"query": "Agent", "city": "上海"}},
            headers=auth,
        )
        assert created.status_code == 201
        watchset = created.json()
        schedule = client.post(
            "/api/schedules", json={"watchset_id": watchset["id"], "enabled": False}, headers=auth
        ).json()
        assert schedule["enabled"] is False and schedule["timezone"] == "Asia/Shanghai"
        task = client.post("/api/tasks", json={"watchset_id": watchset["id"]}, headers=auth).json()
        assert task["state"] == "queued"
        assert client.post(f"/api/tasks/{task['id']}/run", headers=auth).status_code == 202
        for _ in range(100):
            operations = client.get("/api/operations").json()
            if operations["tasks"][0]["state"] == "blocked":
                break
            time.sleep(0.01)
        assert operations["tasks"][0]["error_code"] == "SOURCE_PAUSED_USE_LOCAL_DATA"
        assert client.get("/api/overview").json()["jobs"] == 0
        question = client.post(
            "/api/inbox/followup", json={"question": "隔离待验证问题"}, headers=auth
        ).json()
        assert question["kind"] == "followup" and question["state"] == "unread"
        assert (
            client.post(f"/api/inbox/{question['id']}/read", headers=auth).json()["state"] == "read"
        )
        assert (
            client.post(f"/api/inbox/{question['id']}/resolve", headers=auth).json()["state"]
            == "resolved"
        )
        tick = client.post("/api/operations/tick", headers=auth).json()
        assert tick["scheduled"] == []
        assert (
            client.post(
                "/api/tasks",
                json={"watchset_id": watchset["id"], "replay_bundle": "C:/private"},
                headers=auth,
            ).status_code
            == 422
        )


def test_forgetting_personal_memory_clears_derived_results_and_marks_history(tmp_path):
    from work_observer.reports.results import save_result

    settings = fixture_settings(tmp_path)
    reports = tmp_path / "reports"
    with TestClient(
        create_app(settings, reports_dir=reports), base_url="http://127.0.0.1"
    ) as client:
        auth = headers(client)
        identity = add_jd(client, auth)
        memory = client.post(
            "/api/memories",
            json={"kind": "preference", "content": "隔离隐私偏好：只考虑责任明确的岗位"},
            headers=auth,
        ).json()
        profile = client.post(
            "/api/profiles/" + identity, json={"offline": True}, headers=auth
        ).json()
        assert profile["result"]["memory_used"][0]["id"] == memory["id"]
        run_id = client.post(
            "/api/research", json={"question": "隔离研究", "offline": True}, headers=auth
        ).json()["id"]
        run = done(client, run_id)
        saved = client.post(f"/api/research/{run_id}/save", headers=auth).json()
        # 模拟CLI独立导出：它没有存入ResearchStore.saved，也必须随关联记忆清理。
        independent = save_result(run["result"], reports)
        client.post(f"/api/memories/{memory['id']}/withdraw", headers=auth)
        historical = client.get("/api/reports/" + saved["report_id"]).json()
        assert historical["audit"]["stale_memory"]
        forgotten = client.delete("/api/memories/" + memory["id"], headers=auth)
        assert forgotten.status_code == 200
        assert set(forgotten.json()["deleted_report_ids"]) == {
            saved["report_id"],
            independent["report_id"],
        }
        invalidated = client.get("/api/research/" + run_id).json()
        assert invalidated["state"] == "invalidated" and invalidated["result"] is None
        assert invalidated["resumable"] is False
        assert client.get("/api/reports").json() == []
        history = client.get("/api/memories?history=1").json()
        assert len(history) == 1 and history[0]["status"] == "forgotten"
        assert history[0]["content"] == "[已忘记]" and history[0]["evidence"] == []
        assert client.get("/api/profiles/" + identity).json()["status"] == "not_analyzed"
        assert (
            client.get("/api/jobs/" + identity)
            .json()["current"]["description_text"]
            .startswith("模拟")
        )


def test_forgetting_cascades_through_research_knowledge_and_notifications(tmp_path):
    settings = fixture_settings(tmp_path)
    with TestClient(
        create_app(settings, model=PausingModel(pause=False), reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = headers(client)
        add_jd(client, auth)
        personal = client.post(
            "/api/memories", json={"kind": "preference", "content": "隔离个人偏好"}, headers=auth
        ).json()

        def research_and_adopt(question):
            identity = client.post(
                "/api/research", json={"question": question}, headers=auth
            ).json()["id"]
            result = done(client, identity)
            assert result["result"]["status"] == "completed"
            knowledge = client.post(
                "/api/memories",
                json={"kind": "knowledge", "source_run_id": identity, "claim_index": 0},
                headers=auth,
            ).json()
            assert (
                client.post(f"/api/memories/{knowledge['id']}/activate", headers=auth).status_code
                == 200
            )
            return identity, knowledge["id"]

        first, knowledge_a = research_and_adopt("Python能力一")
        second, knowledge_b = research_and_adopt("Python能力二")
        second_result = client.get("/api/research/" + second).json()["result"]
        assert personal["id"] in {item["id"] for item in second_result["memory_used"]}
        assert knowledge_a in {item["id"] for item in second_result["memory_used"]}
        third = client.post(
            "/api/research", json={"question": "Python能力三", "offline": True}, headers=auth
        ).json()["id"]
        third_result = done(client, third)["result"]
        assert knowledge_b in {item["id"] for item in third_result["memory_used"]}
        client.post(f"/api/research/{third}/save", headers=auth)
        client.post(
            "/api/inbox/followup",
            json={"question": "含个人上下文的派生追问", "source_run_id": second},
            headers=auth,
        )
        client.post(f"/api/memories/{personal['id']}/withdraw", headers=auth)
        current_memories = {item["id"]: item for item in client.get("/api/memories").json()}
        assert not current_memories[knowledge_a]["validity"]["eligible"]
        assert not current_memories[knowledge_b]["validity"]["eligible"]
        forgotten = client.delete("/api/memories/" + personal["id"], headers=auth).json()
        assert {first, second, third}.issubset(forgotten["affected_run_ids"])
        assert {personal["id"], knowledge_a, knowledge_b}.issubset(forgotten["affected_memory_ids"])
        assert len(forgotten["affected_notification_ids"]) == 4
        assert client.get("/api/reports").json() == []
        for identity in (first, second, third):
            assert client.get("/api/research/" + identity).json()["state"] == "invalidated"
        history = client.get("/api/memories?history=1").json()
        assert all(
            item["status"] == "forgotten" and item["content"] == "[已忘记]" for item in history
        )
        inbox = client.get("/api/operations").json()["inbox"]
        assert all(item["state"] == "resolved" and item["details"].get("cleared") for item in inbox)
        assert "含个人上下文的派生追问" not in json.dumps(inbox, ensure_ascii=False)


def test_openapi_tracks_real_routes_request_models_and_offline_docs(tmp_path):
    from starlette.routing import Route

    from work_observer.analysis.profiles import PersonalPreferences
    from work_observer.api.operations import (
        CollectionTaskInput,
        FollowupInput,
        ScheduleInput,
        WatchsetInput,
    )
    from work_observer.api.product import (
        DomainCorrectionInput,
        MatchInput,
        ProfileInput,
        RetrievalInput,
        RollbackInput,
        StrategyInput,
    )
    from work_observer.api.web import MemoryInput, MemoryRevision, ResearchInput
    from work_observer.connectors.manual import ManualJD

    app = create_app(fixture_settings(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        expected = {
            (route.path, method.lower())
            for route in app.routes
            if isinstance(route, Route)
            and route.path.startswith("/api/")
            and route.path not in {"/api/openapi.json", "/api/docs"}
            for method in route.methods - {"HEAD"}
        }
        actual = {
            (path, method) for path, operations in schema["paths"].items() for method in operations
        }
        assert actual == expected
        models = (
            ManualJD,
            ResearchInput,
            MemoryInput,
            MemoryRevision,
            PersonalPreferences,
            CollectionTaskInput,
            FollowupInput,
            ScheduleInput,
            WatchsetInput,
            DomainCorrectionInput,
            MatchInput,
            ProfileInput,
            RetrievalInput,
            RollbackInput,
            StrategyInput,
        )
        definitions = schema["components"]["schemas"]
        for model in models:
            expected_model = model.model_json_schema(ref_template="#/components/schemas/{model}")
            actual_model = definitions[model.__name__]
            assert actual_model["properties"] == expected_model["properties"]
            assert actual_model.get("required", []) == expected_model.get("required", [])

        def check_refs(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    prefix = "#/components/schemas/"
                    assert value["$ref"].startswith(prefix)
                    assert value["$ref"][len(prefix) :] in definitions
                for item in value.values():
                    check_refs(item)
            elif isinstance(value, list):
                for item in value:
                    check_refs(item)

        check_refs(schema)
        docs = client.get("/api/docs")
        assert docs.status_code == 200 and "接口说明" in docs.text
        assert "/api/research" in docs.text and "下载完整OpenAPI合同" in docs.text
        assert "<script" not in docs.text and "https://" not in docs.text
        assert 'href="/api/docs"' in client.get("/").text


def test_readonly_task_endpoints_and_synthetic_history_never_open_sources(tmp_path, monkeypatch):
    settings = fixture_settings(tmp_path)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        auth = headers(client)
        identity = add_jd(client, auth)
        assert (
            client.get(f"/api/jobs/{identity}/compare-history").json()["status"]
            == "insufficient_history"
        )
        changed = client.post(
            "/api/import",
            json={
                "title": "HTTP隔离测试岗位（非真实招聘）",
                "company": "测试公司",
                "description": (
                    "模拟职责：必须掌握 Python，负责接口开发与上线。\n新增评测集维护与线上观测。"
                ),
                "external_id": "workspace-http-test",
                "data_kind": "synthetic",
            },
            headers=auth,
        )
        assert changed.status_code == 201 and changed.json()["job_id"] == identity
        first = client.post(
            "/api/watchsets",
            json={"name": "只读观察测试", "spec": {"query": "Agent", "city": "上海"}},
            headers=auth,
        ).json()
        latest = client.post(
            "/api/watchsets",
            json={"name": "只读观察测试", "spec": {"query": "RAG", "city": "上海"}},
            headers=auth,
        ).json()
        task = client.post("/api/tasks", json={"watchset_id": latest["id"]}, headers=auth).json()
        schedule = client.post(
            "/api/schedules", json={"watchset_id": latest["id"]}, headers=auth
        ).json()
        note = client.post(
            "/api/inbox/followup", json={"question": "只读待研究问题"}, headers=auth
        ).json()

        def reject_source_access(_):
            raise AssertionError("只读接口不得加载或打开招聘来源")

        monkeypatch.setattr(Settings, "load_mcp", reject_source_access)
        watchsets = client.get("/api/watchsets").json()
        assert latest["id"] in {row["id"] for row in watchsets}
        assert first["id"] not in {row["id"] for row in watchsets}
        assert first["id"] in {row["id"] for row in client.get("/api/watchsets?history=1").json()}
        assert client.get("/api/schedules").json()[0]["id"] == schedule["id"]
        assert client.get("/api/tasks").json()[0]["id"] == task["id"]
        assert client.get("/api/tasks/" + task["id"]).json()["state"] == "queued"
        assert client.get("/api/tasks/missing").status_code == 404
        assert client.get("/api/inbox?unread=1").json()[0]["id"] == note["id"]
        client.post(f"/api/inbox/{note['id']}/read", headers=auth)
        assert client.get("/api/inbox?unread=true").json() == []
        assert len(client.get("/api/inbox").json()) == 1
        runs = client.get("/api/collection-runs").json()
        assert len(runs) == 2 and all(row["mode"] == "manual" for row in runs)
        assert client.get("/api/collection-runs/" + runs[0]["id"]).json() == runs[0]
        assert client.get("/api/collection-runs/missing").status_code == 404
        compared = client.get(f"/api/jobs/{identity}/compare-history").json()
        assert (
            compared["status"] == "compared"
            and "+新增评测集维护与线上观测。" in compared["description_diff"]
        )
        assert compared["before"]["data_kind"] == compared["after"]["data_kind"] == "synthetic"
        assert all(row["data_kind"] == "synthetic" for row in compared["evidence"])
        assert "来源内容变化" in "".join(compared["gaps"])
        assert "比较最近正文版本" in client.get("/assets/app.js").text
        malicious_header = client.post(
            "/api/import", json={}, headers=[(b"x-wo-token", "非ASCII恶意值".encode())]
        )
        assert malicious_header.status_code == 403
