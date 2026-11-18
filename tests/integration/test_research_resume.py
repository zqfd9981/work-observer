"""检查点恢复使用原范围、版本和累计预算；模拟模型不作为真实连通证明。"""

import asyncio
import json

import pytest

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.service import MemoryService
from work_observer.research.agent import research
from work_observer.research.store import ResearchStore
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


def call(name, args):
    item = {"type": "function_call", "name": name, "arguments": json.dumps(args), "call_id": name}
    return [item], item


class InterruptedModel:
    def __init__(self):
        self.waiting = asyncio.Event()

    async def turn(self, history):
        if history[-1].get("role") == "user":
            return call("query_jobs", {})
        self.waiting.set()
        await asyncio.Event().wait()


class Continuation:
    def __init__(self, job_id):
        self.job_id, self.calls = job_id, 0

    async def turn(self, history):
        self.calls += 1
        if history[-1].get("call_id") == "query_jobs":
            return call("read_job", {"job_id": self.job_id})
        evidence = json.loads(history[-1]["output"])["evidence"]
        return call(
            "finish_research",
            {
                "claims": [
                    {
                        "category": "task",
                        "requirement": "unspecified",
                        "text": "模拟任务",
                        "evidence_ids": [evidence[0]["id"]],
                    }
                ],
                "gaps": [],
            },
        )


@pytest.fixture
def setup(tmp_path):
    db = tmp_path / "business.db"
    upgrade(db)
    repo = Repository(db)
    archive = RawArchive(tmp_path / "raw", [])
    jd = ManualJD(title="模拟", company="模拟", external_id="stable", description="最初原文 Python")
    job = import_jd(repo, archive, jd)
    store = ResearchStore(tmp_path / "checkpoints.db", str(db))
    yield repo, archive, jd, job["job_id"], store
    store.close()
    repo.close()


async def interrupt(setup, max_calls=6):
    repo, _, _, job_id, store = setup
    run = store.create({"question": "模拟问题"})
    model = InterruptedModel()
    task = asyncio.create_task(
        research(
            repo,
            "模拟问题",
            Settings(),
            job_ids=[job_id],
            model=model,
            checkpoint=(store, run["id"]),
            max_calls=max_calls,
        )
    )
    await asyncio.wait_for(model.waiting.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return run["id"]


def test_resume_keeps_original_snapshot_and_counts_attempts(setup):
    repo, archive, jd, job_id, store = setup

    async def scenario():
        identity = await interrupt(setup)
        import_jd(repo, archive, jd.model_copy(update={"description": "后来新原文 Java"}))
        continuation = Continuation(job_id)
        result = await research(
            repo,
            "模拟问题",
            Settings(),
            job_ids=[job_id],
            model=continuation,
            checkpoint=(store, identity),
            resume=True,
        )
        assert result["status"] == "completed"
        assert result["model_calls"] == 4 and continuation.calls == 2
        assert result["evidence"][0]["quote"] == "最初原文 Python"
        assert result["review"]["checks"][0]["passed"]

    asyncio.run(scenario())


def test_resume_does_not_reset_exhausted_budget(setup):
    repo, _, _, job_id, store = setup

    async def scenario():
        identity = await interrupt(setup, 2)
        continuation = Continuation(job_id)
        result = await research(
            repo,
            "模拟问题",
            Settings(),
            model=continuation,
            checkpoint=(store, identity),
            resume=True,
        )
        assert result["status"] == "incomplete" and result["model_calls"] == 2
        assert continuation.calls == 0

    asyncio.run(scenario())


def test_changed_memory_requires_fresh_research(setup):
    repo, _, _, job_id, store = setup

    async def scenario():
        identity = await interrupt(setup)
        MemoryService(repo).create("preference", "模拟显式新偏好")
        with pytest.raises(ProbeError, match="RESEARCH_MEMORY_CHANGED_RESTART"):
            await research(
                repo,
                "模拟问题",
                Settings(),
                model=Continuation(job_id),
                checkpoint=(store, identity),
                resume=True,
            )

    asyncio.run(scenario())


def test_store_isolates_databases_and_survives_restart(tmp_path):
    path = tmp_path / "cp.db"
    first = ResearchStore(path, "a")
    run = first.create({"question": "模拟"})
    first.checkpoint(run["id"], {"version": 1})
    first.close()
    again, other = ResearchStore(path, "a"), ResearchStore(path, "b")
    assert again.load_checkpoint(run["id"]) == {"version": 1}
    assert other.list() == []
    with pytest.raises(ProbeError, match="RESEARCH_NOT_FOUND"):
        other.get(run["id"])
    again.close()
    other.close()
