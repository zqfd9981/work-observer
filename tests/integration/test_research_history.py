"""History is searchable past the old cap without exposing erased runs or checkpoints."""

import json
from copy import deepcopy

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from work_observer.api.web import create_app
from work_observer.cli import app
from work_observer.config import Settings
from work_observer.research.projects import ProjectService
from work_observer.research.run_history import search_history
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


@pytest.fixture
def history_store(tmp_path):
    db = tmp_path / "app.db"
    upgrade(db)
    store = ResearchStore(tmp_path / "checkpoints.db", str(db.resolve()))
    yield store, db
    store.close()


def saved(store, question="合成历史问题", **result):
    run = store.create({"question": question})
    store.save(run["id"], state="finished", result={"status": "completed", **result})
    return store.get(run["id"])


def test_search_reaches_older_answers_beyond_the_latest_hundred(history_store):
    store, _ = history_store
    old = saved(store, claims=[{"text": "早期合成核验方法"}])
    for index in range(105):
        saved(store, question=f"较新的无关问题{index}")
    assert old["id"] not in {row["id"] for row in store.list()}
    found = search_history(store, q="早期 核验", limit=1)
    assert found["total"] == 1 and found["items"][0]["id"] == old["id"]
    assert found["items"][0]["match"]["field"] == "claim"
    first = search_history(store, limit=7)
    second = search_history(store, limit=7, offset=7)
    assert first["total"] == second["total"] == 106
    assert not {row["id"] for row in first["items"]} & {row["id"] for row in second["items"]}
    assert first == search_history(store, limit=7)
    assert search_history(store, offset=200)["items"] == []


def test_scope_titles_read_titles_gaps_and_literal_terms_are_distinguished(history_store):
    store, _ = history_store
    scope = saved(store, scope={"jobs": [{"title": "未读C++资料"}]})
    read = saved(store, evidence=[{"title": "已读Agent资料"}], claims=[{"text": "合成召回问题"}])
    saved(store, gaps=["还缺合成样本口径"])
    literal = saved(store, question="合成 50%_ 特殊值")
    assert search_history(store, q="未读C++")["items"][0]["match"]["field"] == "scope_source"
    assert search_history(store, q="agent 召回")["items"][0]["id"] == read["id"]
    assert search_history(store, q="样本口径")["items"][0]["match"]["field"] == "gap"
    assert search_history(store, q="%_")["items"][0]["id"] == literal["id"]
    assert search_history(store, q="not-present")["total"] == 0
    before = deepcopy(store.get(scope["id"]))
    search_history(store)
    assert store.get(scope["id"]) == before


def test_reopened_history_finds_map_boundaries_comparisons_and_revision_reasons(history_store):
    store, _ = history_store
    run = saved(
        store,
        work_map={
            "scope_note": "合成两个岗位，不外推行业",
            "work_types": [{"boundary": "提供尽调依据不代表拥有投决权"}],
            "work_relations": [{"transfer_limit": "先核实组织授权才能迁移"}],
            "comparisons": [{"transfer_conditions": "须分别验证回放机制与产品验证能力"}],
            "unknowns": ["尚缺实际交付周期"],
        },
        cognition_revisions=[
            {
                "previous_statement": "内部培训与种子产品孵化都属于岗位任务",
                "reason": "新判断只覆盖内部培训，孵化尚未重查",
                "aspects": [{"reason": "产品市场匹配不是普通工具推广"}],
            }
        ],
    )
    before = deepcopy(store.get(run["id"]))
    reopened = ResearchStore(store.path, store.namespace)
    try:
        for query, field in [
            ("行业", "work_map"),
            ("尽调 投决权", "work_map"),
            ("组织授权", "work_map"),
            ("回放机制 产品验证", "work_map"),
            ("交付周期", "work_map"),
            ("种子产品 内部培训", "cognition_revision"),
            ("孵化 尚未重查", "cognition_revision"),
            ("产品市场匹配", "cognition_revision"),
        ]:
            found = search_history(reopened, q=query)
            assert found["total"] == 1, query
            assert found["items"][0]["match"]["field"] == field
        assert reopened.get(run["id"]) == before
        reopened.invalidate_runs([run["id"]])
        assert search_history(reopened, q="组织授权")["total"] == 0
        assert search_history(reopened, q="产品市场匹配")["total"] == 0
    finally:
        reopened.close()


def test_history_finds_application_deliverables_and_matches_original_glyphs(history_store):
    store, _ = history_store
    run = saved(
        store,
        application_plan={
            "actions": [
                {
                    "title": "合成验证任务",
                    "deliverable": "编写⼯作流回放记录",
                    "completion_check": "由业务同事核对失败恢复过程",
                    "assumptions": ["可取得脱敏样本"],
                }
            ],
            "open_questions": ["是否允许访问评估集"],
        },
    )
    for query in ["工作流", "业务同事", "脱敏样本", "评估集"]:
        found = search_history(store, q=query)
        assert found["total"] == 1
        assert found["items"][0]["id"] == run["id"]
        assert found["items"][0]["match"]["field"] == "application_plan"
    assert "⼯作流" in search_history(store, q="工作流")["items"][0]["match"]["excerpt"]


def test_erased_projects_runs_namespaces_and_private_checkpoint_are_not_returned(history_store):
    store, _ = history_store
    hidden = saved(store, question="合成已忘记内容")
    store.invalidate_runs([hidden["id"]])
    projects = ProjectService(store)
    project = projects.create("合成待遗忘项目", "合成目标", [])
    orphan = store.create({"question": "项目已忘记但旧行仍残留", "project_id": project["id"]})
    projects.erase(project["id"])
    assert store.get(orphan["id"])["state"] != "invalidated"
    kept = saved(store, question="合成保留研究")
    store.checkpoint(kept["id"], {"history": ["秘密模型上下文ONLY"], "raw_path": "不应返回的路径"})
    other = ResearchStore(store.path, "another-namespace")
    try:
        saved(other, question="合成其他工作空间")
        result = search_history(store)
        assert [row["id"] for row in result["items"]] == [kept["id"]]
        assert search_history(store, q="秘密模型")["total"] == 0
        assert "raw_path" not in json.dumps(result, ensure_ascii=False)
        assert "模型上下文" not in json.dumps(result, ensure_ascii=False)
    finally:
        other.close()


def test_http_cli_and_contract_share_paginated_history(history_store, tmp_path):
    store, db = history_store
    run = saved(
        store,
        question="合成C++研究",
        claims=[{"text": "合成Agent结论"}],
        work_map={"comparisons": [{"transfer_conditions": "须验证故障回放再考虑迁移"}]},
    )
    settings = Settings(database_path=db, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        response = client.get("/api/research-history", params={"q": "AGENT", "limit": 1})
        assert response.status_code == 200 and response.json()["items"][0]["id"] == run["id"]
        found = client.get("/api/research-history", params={"q": "故障回放"}).json()
        assert found["items"][0]["match"]["field"] == "work_map"
        assert found["items"][0]["id"] == run["id"]
        assert isinstance(client.get("/api/research").json(), list)
        params = client.get("/api/openapi.json").json()["paths"]["/api/research-history"]["get"][
            "parameters"
        ]
        assert {row["name"] for row in params} == {"q", "limit", "offset"}
        for query in [{"limit": 51}, {"offset": -1}, {"q": "长" * 201}, {"unknown": 1}]:
            assert client.get("/api/research-history", params=query).status_code == 422
    outcome = CliRunner().invoke(
        app,
        [
            "research-history",
            "--q",
            "AGENT",
            "--limit",
            "1",
            "--db",
            str(db),
            "--env-file",
            str(tmp_path / "missing.env"),
        ],
    )
    assert outcome.exit_code == 0, (outcome.stdout, outcome.exception)
    assert json.loads(outcome.stdout)["items"][0]["id"] == run["id"]
