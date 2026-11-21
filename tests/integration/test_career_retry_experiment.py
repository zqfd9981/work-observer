"""Execute real local rule comparisons and save their bounded observations, with no model."""

import re
from copy import deepcopy

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.research.agent import ModelClient
from work_observer.research.retry_experiment import run_retry_experiment
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


def test_local_retry_comparison_runs_before_saving_and_preserves_inquiry(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("The local experiment must not call a model")

    monkeypatch.setattr(ModelClient, "turn", forbidden)
    database, raw = tmp_path / "retry.db", tmp_path / "raw"
    upgrade(database)
    cases = [
        {"name": "相同编号重试", "requests": [
            {"request_id": "r1", "business_id": "A", "action": "确认"},
            {"request_id": "r1", "business_id": "A", "action": "确认"},
        ]},
        {"name": "更换编号重试", "requests": [
            {"request_id": "r1", "business_id": "A", "action": "确认"},
            {"request_id": "r2", "business_id": "A", "action": "确认"},
        ]},
        {"name": "同一业务不同动作", "requests": [
            {"request_id": "r1", "business_id": "A", "action": "确认"},
            {"request_id": "r2", "business_id": "A", "action": "取消<局部模拟>"},
        ]},
        {"name": "请求编号碰撞", "requests": [
            {"request_id": "r1", "business_id": "A", "action": "确认"},
            {"request_id": "r1", "business_id": "B", "action": "确认"},
        ]},
    ]
    with TestClient(create_app(Settings(database_path=database, raw_directory=raw)),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        goal = client.post("/api/career", headers=auth, json={
            "title": "合成本地实验", "goal": "理解规则边界", "first_question": "重试一定安全吗？",
            "material_text": "合成原文：任务是检查失败与重复记录，实际业务协议未说明。",
        }).json()
        identity, qid = goal["id"], goal["focus_question_id"]
        endpoint = "/api/career/" + identity + "/experiments/retry"
        before = client.get("/api/career/" + identity).json()
        payload = {"cases": cases, "question_id": qid, "hypothesis": "请求编号是否总能区分操作？"}
        response = client.post(endpoint, headers=auth, json=payload)
        assert response.status_code == 200, response.text
        result = response.json()["experiment"]
        assert "task_id" not in response.json()
        assert client.get("/api/career/" + identity).json() == before
        counts = [{run["rule"]: len(run["accepted"]) for run in case["runs"]}
                  for case in result["cases"]]
        assert counts == [
            {"none": 2, "request": 1, "business": 1, "business_action": 1},
            {"none": 2, "request": 2, "business": 1, "business_action": 1},
            {"none": 2, "request": 2, "business": 1, "business_action": 2},
            {"none": 2, "request": 1, "business": 2, "business_action": 2},
        ]
        assert result["cases"][2]["requests"][1]["action"] == "取消<局部模拟>"
        assert all(row["expected"] == "" for row in result["comparison_rows"])
        assert "没有网络" in result["conditions"] and "真实业务键" in result["outcome"]
        response = client.post(endpoint, headers=auth, json={**payload, "save": True})
        assert response.status_code == 201, response.text
        recorded = response.json()
        assert recorded["experiment"] == result
        task = next(t for t in recorded["career"]["tasks"] if t["id"] == recorded["task_id"])
        assert task["state"] == "done" and task["question_id"] == qid
        assert task["hypothesis"] == payload["hypothesis"]
        assert task["comparison_rows"] == result["comparison_rows"]
        assert task["outcome"] == result["outcome"]
        assert set(before["document_ids"]) <= set(recorded["career"]["document_ids"])
        assert recorded["career"]["questions"] == before["questions"]
        assert recorded["career"]["focus_question_id"] == qid
        assert recorded["career"]["usage"]["calls"] == 0 and not recorded["career"]["results"]
        saved_before = client.get("/api/career/" + identity).json()
        for invalid in (
            {**payload, "question_id": "f" * 32},
            {"cases": []},
            {"cases": [{"name": "缺字段", "requests": [{"request_id": "r"}]}]},
            {"cases": [{"name": "超出总量", "requests": cases[0]["requests"] * 10}, cases[0]]},
        ):
            failed = client.post(endpoint, headers=auth, json={**invalid, "save": True})
            assert failed.status_code == 422, failed.text
        assert client.get("/api/career/" + identity).json() == saved_before
    repository = Repository(database)
    try:
        archived = PublicDocumentService(repository, raw / "public").document(
            task["artifact_document_id"],
        )
        assert result["artifact_text"] in archived["text"]
        assert "本机计算输出" in archived["text"] and "取消<局部模拟>" in archived["text"]
    finally:
        repository.close()


def test_bounded_local_record_preserves_input_and_fits_existing_artifact_limit():
    cases = [{"name": "条件" * 75, "requests": [
        {"request_id": "请求" * 30, "business_id": "业务" * 30, "action": "动作" * 30}
        for _ in range(20)
    ]}]
    before = deepcopy(cases)
    result = run_retry_experiment(cases)
    assert cases == before
    assert len(result["artifact_text"]) <= 20_000
    assert len(result["comparison_rows"][0]["observed"]) <= 1000
    assert result["cases"][0]["runs"][0]["accepted"] == list(range(1, 21))
    assert result["cases"][0]["runs"][1]["skipped"] == list(range(2, 21))
