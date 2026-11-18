"""本地观察/收件箱机制仅使用隔离模拟来源，不发真实平台请求。"""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.orm import Session

from work_observer.collection.contracts import Capture, WatchsetSpec
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.reports.inbox import InboxService
from work_observer.storage.database import upgrade
from work_observer.storage.locks import exclusive
from work_observer.storage.operations_models import WorkTask
from work_observer.storage.repository import Repository
from work_observer.tasks.service import TaskService


@pytest.fixture
def operations(tmp_path):
    path = tmp_path / "operations.db"
    upgrade(path)
    repository = Repository(path)
    risk = tmp_path / "connector"
    risk.mkdir()
    config = tmp_path / "mcp.toml"
    config.write_text(
        'command="unused-test-only"\nargs=["--data-dir",' + json.dumps(str(risk)) + "]\n",
        encoding="utf-8",
    )
    settings = Settings(database_path=path, raw_directory=tmp_path / "raw", mcp_config=config)
    service = TaskService(repository)
    watchset = service.save_watchset("模拟观察", {"query": "Agent", "city": "上海"})
    yield service, repository, settings, watchset, risk
    repository.close()


class SimulatedSource:
    mode = "live"

    def __init__(self, repository, description="模拟任务：开发服务接口", fail=False):
        self.repository, self.description, self.fail, self.calls = repository, description, fail, []

    @asynccontextmanager
    async def open(self):
        self.calls.append("open")
        yield self

    def _capture(self, body):
        assert self.repository.engine.pool.checkedout() == 0
        return Capture(
            raw={"content": [{"type": "text", "text": json.dumps(body)}]},
            request={},
            observed_at="2026-11-18T00:00:00+00:00",
            provenance={"origin": "simulated_test_only"},
        )

    async def search(self, spec, page):
        self.calls.append("search")
        if self.fail:
            raise ProbeError("NETWORK_ERROR")
        return self._capture(
            {
                "ok": True,
                "data": [
                    {
                        "job_id": "simulated-1",
                        "title": "模拟岗位",
                        "company": "模拟公司",
                        "security_id": "private-test-context",
                        "city": "上海",
                    }
                ],
                "pagination": {"page": page, "has_more": False},
            }
        )

    async def detail(self, job):
        self.calls.append("detail")
        return self._capture({"ok": True, "data": {**job, "description": self.description}})


def execute(operations, **changes):
    service, repository, settings, watchset, _ = operations
    task = service.create_collection(watchset["id"])
    source = SimulatedSource(repository, **changes)
    result = asyncio.run(service.run(task["id"], settings, source=source))
    return result, source


def test_watchset_versions_pin_config_and_task_deduplication(operations):
    service, _, _, initial, _ = operations
    assert service.save_watchset("模拟观察", initial["config"])["id"] == initial["id"]
    changed = service.save_watchset("模拟观察", {**initial["config"], "query": "RAG"})
    assert changed["version"] == 2 and changed["id"] != initial["id"]
    assert service.watchsets()[0] == changed
    assert len(service.watchsets(True)) == 2
    task = service.create_collection(initial["id"], dedupe_key="same-request")
    assert service.create_collection(initial["id"], dedupe_key="same-request")["id"] == task["id"]
    with pytest.raises(ProbeError, match="TASK_KEY_CONFLICT"):
        service.create_collection(changed["id"], dedupe_key="same-request")


def test_source_pause_stops_before_adapter_and_retry_is_bounded(operations):
    service, repository, settings, watchset, risk = operations
    (risk / "cdp_risk_lock.json").write_text("{}", encoding="utf-8")
    result, source = execute(operations)
    assert result["state"] == "blocked"
    assert result["error_code"] == "SOURCE_PAUSED_USE_LOCAL_DATA"
    assert source.calls == [] and result["result_id"] is None
    assert repository.counts()["collection_runs"] == 0
    service.retry(result["id"])
    again = asyncio.run(service.run(result["id"], settings, source=source))
    assert again["attempts"] == 2 and source.calls == []
    with pytest.raises(ProbeError, match="TASK_RETRY_LIMIT"):
        service.retry(result["id"])
    assert len(service.inbox.list(unread=True)) == 2


def test_collection_task_progress_and_deterministic_updates(operations):
    service, repository, _, _, _ = operations
    first, source = execute(operations)
    assert first["state"] == "success" and source.calls == ["open", "search", "detail"]
    assert first["progress"]["stats"]["details_received"] == 1
    assert len(first["collection_run_ids"]) == 1
    notice = service.inbox.collection_update(first["result_id"])
    assert len(notice["details"]["new_job_ids"]) == 1
    assert service.inbox.collection_update(first["result_id"])["id"] == notice["id"]
    second, _ = execute(operations)
    unchanged = service.inbox.collection_update(second["result_id"])["details"]
    assert not unchanged["new_job_ids"] and not unchanged["content_changes"]
    changed, _ = execute(operations, description="模拟任务：上线维护并维护评估集")
    delta = service.inbox.collection_update(changed["result_id"])["details"]
    assert delta["content_changes"][0]["kind"] == "detail"
    assert not delta["sample_scope_changed"] and not delta["analysis_changed"]
    assert repository.counts()["jobs"] == 1 and repository.counts()["job_snapshots"] == 3
    assert "private-test-context" not in json.dumps(service.list())


def test_network_failure_is_failed_observation_not_market_signal(operations):
    service, repository, _, _, _ = operations
    failed, _ = execute(operations, fail=True)
    assert failed["state"] == "failed" and failed["error_code"] == "NETWORK_ERROR"
    update = service.inbox.collection_update(failed["result_id"])
    assert update["details"]["error_codes"] == ["NETWORK_ERROR"]
    assert update["details"]["observed_jobs"] == 0
    assert "未取得资料的部分保持未知" in update["body"]
    assert repository.counts()["jobs"] == 0


def test_schedule_default_pause_shanghai_slots_and_repeat_tick(operations):
    service, _, settings, watchset, _ = operations
    schedule = service.save_schedule(watchset["id"])
    assert schedule["enabled"] is False
    assert not asyncio.run(service.tick(settings, at="2026-11-18T00:30:00+00:00", run=False))[
        "scheduled"
    ]
    service.save_schedule(watchset["id"], enabled=True, schedule_id=schedule["id"])
    assert not asyncio.run(service.tick(settings, at="2026-11-18T00:29:59+00:00", run=False))[
        "scheduled"
    ]
    first = asyncio.run(service.tick(settings, at="2026-11-18T00:30:00+00:00", run=False))[
        "scheduled"
    ][0]
    again = asyncio.run(service.tick(settings, at="2026-11-18T22:00:00+08:00", run=False))[
        "scheduled"
    ][0]
    assert first["id"] == again["id"]
    tomorrow = asyncio.run(service.tick(settings, at="2026-11-19T08:30:00+08:00", run=False))[
        "scheduled"
    ][0]
    assert tomorrow["id"] != first["id"]
    with pytest.raises(ProbeError, match="SCHEDULE_TIME_REQUIRES_TIMEZONE"):
        asyncio.run(service.tick(settings, at="2026-11-19T08:30:00", run=False))


def test_explicit_tick_respects_source_pause_without_constructing_adapter(operations, monkeypatch):
    service, _, settings, watchset, risk = operations
    (risk / "cdp_risk_lock.json").write_text("{}", encoding="utf-8")
    service.save_schedule(watchset["id"], enabled=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("暂停期间不能构造来源")

    monkeypatch.setattr("work_observer.tasks.service.MCPSource", forbidden)
    result = asyncio.run(service.tick(settings, at="2026-11-18T08:30:00+08:00"))
    assert result["executed"][0]["state"] == "blocked"


def test_crash_recovery_preserves_attempt_and_requires_explicit_retry(operations):
    service, repository, settings, watchset, _ = operations
    task = service.create_collection(watchset["id"])
    spec = WatchsetSpec.model_validate(watchset["config"])
    run_id = repository.begin_run(watchset["name"], spec, "live")
    with Session(repository.engine) as session, session.begin():
        row = session.get(WorkTask, task["id"])
        row.state, row.result_id, row.collection_run_ids, row.attempts = (
            "running",
            run_id,
            [run_id],
            1,
        )
    recovered = service.recover_interrupted()
    assert recovered[0]["id"] == task["id"]
    assert service.get(task["id"])["state"] == "interrupted"
    assert repository.run(run_id)["status"] == "failed"
    service.retry(task["id"])
    final = asyncio.run(service.run(task["id"], settings, source=SimulatedSource(repository)))
    assert final["state"] == "success" and final["attempts"] == 2
    assert final["collection_run_ids"][0] == run_id and len(final["collection_run_ids"]) == 2


def test_collection_worker_mutex_prevents_overlapping_execution(operations):
    service, _, settings, watchset, _ = operations
    task = service.create_collection(watchset["id"])
    with exclusive(settings.database_path, purpose="collection"):
        with pytest.raises(ProbeError, match="DATABASE_IN_USE"):
            asyncio.run(service.run(task["id"], settings))
    assert service.get(task["id"])["attempts"] == 0


def test_inbox_state_followup_and_hypothesis_are_not_source_facts(operations):
    _, repository, _, _, _ = operations
    inbox = InboxService(repository)
    item = inbox.add_followup("哪些职责明确涉及上线？", "a" * 32)
    hypothesis = inbox.create(
        "hypothesis", "待验证假设", "评估职责是否增加仍缺可比历史。", dedupe_key="hypothesis-1"
    )
    assert len(inbox.list(True)) == 2 and item["related_id"] == "a" * 32
    assert inbox.mark_read(item["id"])["state"] == "read"
    assert len(inbox.list(True)) == 1
    assert inbox.resolve(hypothesis["id"])["state"] == "resolved"
    assert inbox.mark_read(hypothesis["id"])["state"] == "resolved"
    assert not inbox.list(True)
    assert repository.counts()["source_documents"] == 0


def test_forgetting_research_clears_only_linked_derived_notifications(operations):
    _, repository, _, _, _ = operations
    inbox = InboxService(repository)
    run_id = "a" * 32
    source = inbox.create("collection", "来源通知", "保留来源运行摘要", related_id=run_id)
    derived = [
        inbox.create(
            kind, "个人敏感标题", "个人敏感正文", related_id=run_id, dedupe_key=kind + ":个人敏感键"
        )
        for kind in ("research", "followup", "hypothesis")
    ]
    unrelated = inbox.create("research", "其他研究", "其他研究保留", related_id="b" * 32)
    result = inbox.invalidate_research([run_id])
    assert set(result["affected_notification_ids"]) == {item["id"] for item in derived}
    assert inbox.invalidate_research([run_id]) == {"affected_notification_ids": []}
    assert inbox.invalidate_research([]) == {"affected_notification_ids": []}
    items = {item["id"]: item for item in inbox.list()}
    assert items[source["id"]]["body"] == source["body"]
    assert items[unrelated["id"]]["body"] == unrelated["body"]
    for item in derived:
        assert "个人敏感" not in json.dumps(items[item["id"]], ensure_ascii=False)
        assert items[item["id"]]["state"] == "resolved"
