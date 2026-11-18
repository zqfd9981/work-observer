"""等待资料、显式新轮及依赖接续；合成材料/模型只验机制。"""

import asyncio
import json

import pytest

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.service import MemoryService
from work_observer.research.agent import research
from work_observer.research.projects import ProjectService, execute_project
from work_observer.research.store import ResearchStore
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


class SourceModel:
    async def turn(self, history):
        outputs = [
            json.loads(item["output"])
            for item in history
            if item.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = "query_jobs", {}
        elif not any(row.get("evidence") for row in outputs):
            name, args = "read_job", {"job_id": outputs[0]["jobs"][0]["id"]}
        else:
            ev = next(row["evidence"][0] for row in outputs if row.get("evidence"))
            name, args = (
                "finish_research",
                dict(
                    claims=[
                        dict(
                            category="task",
                            basis="direct",
                            requirement="unspecified",
                            text="合成职责Python接口",
                            evidence_ids=[ev["id"]],
                        )
                    ],
                    gaps=[],
                ),
            )
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(len(history))
        )
        return [call], call


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "app.db"
    upgrade(path)
    repo = Repository(path)
    archive = RawArchive(tmp_path / "raw", [])
    jd = ManualJD(
        title="合成补查",
        company="合成公司",
        external_id="stable-refresh",
        description="合成职责：Python接口",
        data_kind="synthetic",
    )
    job_id = import_jd(repo, archive, jd)["job_id"]
    store = ResearchStore(tmp_path / "custom-checkpoints.db", str(path.resolve()))
    repo.bind_research_store(store)
    service = ProjectService(store)
    p = service.create("合成项目", "Python任务", [job_id], max_calls=12)
    p = service.add(p["id"], "Python任务", revision=p["revision"], offline=True)
    p = asyncio.run(execute_project(service, p["id"], repo, Settings()))
    yield repo, store, service, p, archive, jd
    store.close()
    repo.close()


def test_repeat_import_is_not_new_material_and_refresh_preserves_original(setup):
    repo, store, service, p, archive, jd = setup
    original = p["steps"][0]
    result = store.get(original["run_id"])["result"]
    import_jd(repo, archive, jd)
    with pytest.raises(ProbeError, match="NO_NEW_RESEARCH_MATERIAL"):
        service.refresh_waiting(
            p["id"], original["id"], repo, revision=p["revision"], note="重复观察", offline=True
        )
    import_jd(repo, archive, jd.model_copy(update={"description": "合成职责：Python接口和上线"}))
    p = service.refresh_waiting(
        p["id"], original["id"], repo, revision=p["revision"], note="补了上线职责", offline=True
    )
    assert p["steps"][0]["state"] == "superseded" and p["steps"][1]["run_id"] is None
    replay = service.refresh_waiting(
        p["id"], original["id"], repo, revision=p["revision"] - 1, note="补了上线职责", offline=True
    )
    assert replay["revision"] == p["revision"] and len(replay["steps"]) == 2
    with pytest.raises(ProbeError, match="STEP_ALREADY_REFRESHED"):
        service.refresh_waiting(
            p["id"], original["id"], repo, revision=p["revision"], note="不同的补查", offline=True
        )
    p = asyncio.run(execute_project(service, p["id"], repo, Settings()))
    assert p["steps"][1]["state"] == "waiting_material"
    new = store.get(p["steps"][1]["run_id"])["result"]
    assert new["material_signature"] != result["material_signature"]
    assert "上线" in new["evidence"][0]["quote"]
    assert store.get(original["run_id"])["result"] == result
    assert service.usage(p)["calls"] == 0


def test_offline_to_model_replacement_only_unblocks_after_review(setup):
    repo, store, service, p, _, _ = setup
    original = p["steps"][0]
    p = service.add(
        p["id"], "汇总判断", revision=p["revision"], depends_on=[original["id"]], max_calls=6
    )
    p = service.refresh_waiting(
        p["id"],
        original["id"],
        repo,
        revision=p["revision"],
        note="现在明确启动模型分析，先保存",
        offline=False,
        max_calls=6,
    )
    p = asyncio.run(execute_project(service, p["id"], repo, Settings(), model=SourceModel()))
    replacement = p["steps"][-1]
    assert replacement["state"] == "waiting_review" and p["steps"][1]["state"] == "queued"
    p = service.review(
        p["id"],
        replacement["id"],
        revision=p["revision"],
        action="accept",
        note="合成原文核对",
        repository=repo,
    )
    step = service.claim(p["id"])
    assert step["id"] == p["steps"][1]["id"]
    context = service.context(p["id"], step, repo)
    assert context["previous_findings"][0]["run_id"] == replacement["run_id"]
    assert service.usage(service.get(p["id"]))["reserved_calls"] == 12
    assert store.get(original["run_id"])["result"]["status"] == "evidence_only"


def test_source_change_prevents_accepting_stale_step_and_raw_integrity_blocks_model(setup):
    repo, store, service, p, archive, jd = setup
    p = service.refresh_waiting(
        p["id"],
        p["steps"][0]["id"],
        repo,
        revision=p["revision"],
        note="转为明确模型分析",
        offline=False,
        max_calls=6,
    )
    p = asyncio.run(execute_project(service, p["id"], repo, Settings(), model=SourceModel()))
    current = p["steps"][-1]
    import_jd(repo, archive, jd.model_copy(update={"description": "合成职责：Python接口第二版"}))
    with pytest.raises(ProbeError, match="STEP_RESULT_STALE_REFRESH"):
        service.review(
            p["id"],
            current["id"],
            revision=p["revision"],
            action="accept",
            note="源已变化",
            repository=repo,
        )
    from pathlib import Path

    from work_observer.retrieval.catalog import Catalog

    evidence = Catalog(repo).evidence(p["job_ids"][0])[0]
    source = Path(Catalog(repo).document(evidence["document_id"])["path"])
    source.write_text("已改变的合成原始归档", encoding="utf-8")
    with pytest.raises(ProbeError, match="RESEARCH_SOURCE_INTEGRITY_FAILED"):
        asyncio.run(research(repo, "Python", Settings(), job_ids=p["job_ids"], model=SourceModel()))


def test_direct_research_has_authoritative_source_run(setup):
    repo, store, _, p, _, _ = setup
    result = asyncio.run(
        research(repo, "Python任务", Settings(), job_ids=p["job_ids"], model=SourceModel())
    )
    assert store.get(result["run_id"])["state"] == "finished"
    assert store.get(result["run_id"])["result"]["material_signature"]
    memory = MemoryService(repo)
    candidate = memory.create(
        "knowledge", "Python任务", evidence=result["evidence"], source_run_id=result["run_id"]
    )
    memory.activate(candidate["id"])
    assert memory.recall("Python任务", p["job_ids"])[0]["id"] == candidate["id"]


def test_authoritative_run_cannot_be_rebound_or_overwritten(setup):
    repo, store, _, p, _, _ = setup
    run = store.create({"question": "固定原始问题", "job_ids": p["job_ids"], "offline": True})
    before = store.get(run["id"])
    with pytest.raises(ProbeError, match="RESEARCH_INPUT_CHANGED_NEW_RUN_REQUIRED"):
        asyncio.run(
            research(
                repo,
                "另一个问题",
                Settings(),
                offline=True,
                job_ids=p["job_ids"],
                checkpoint=(store, run["id"]),
            )
        )
    assert store.get(run["id"]) == before
    result = asyncio.run(
        research(
            repo,
            "固定原始问题",
            Settings(),
            offline=True,
            job_ids=p["job_ids"],
            checkpoint=(store, run["id"]),
        )
    )
    final = store.get(run["id"])
    assert final["input"]["question"] == result["question"]
    for resume in (False, True):
        with pytest.raises(ProbeError, match="RESEARCH_RUN_ALREADY_FINISHED"):
            asyncio.run(
                research(
                    repo,
                    "固定原始问题",
                    Settings(),
                    offline=True,
                    checkpoint=(store, run["id"]),
                    resume=resume,
                )
            )
        assert store.get(run["id"]) == final


def test_failed_model_checkpoint_redacts_all_configured_credentials(setup):
    repo, store, _, p, _, _ = setup
    marker = "SYNTHETIC_ACCESS_TOKEN_DO_NOT_RETAIN_12345"

    class FailingModel:
        async def turn(self, history):
            raise RuntimeError("synthetic provider failure")

    settings = Settings(access_token=marker)
    result = asyncio.run(
        research(repo, "合成问题" + marker, settings, job_ids=p["job_ids"], model=FailingModel())
    )
    serialized = json.dumps(
        {
            "record": store.get(result["run_id"]),
            "checkpoint": store.load_checkpoint(result["run_id"]),
        }
    )
    assert marker not in serialized
    assert "[REDACTED]" in serialized
