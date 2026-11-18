"""个人记忆遗忘与历史结果审计，仅用隔离模拟资料和临时报告。"""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors import public_documents as public_module
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.service import MemoryService
from work_observer.reports.results import audit_result, forget_reports, render, save_result
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.models import JobAnalysis, MemoryEvent, MemoryRecord, SourceDocument
from work_observer.storage.repository import Repository
from work_observer.tracking.evaluation import config_hash
from work_observer.tracking.models import RetrievalStrategy


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "personal.db"
    upgrade(path)
    repo = Repository(path)
    archive = RawArchive(tmp_path / "raw")

    def add(description="模拟职责：Python开发"):
        return import_jd(
            repo,
            archive,
            ManualJD(
                title="模拟岗位",
                company="模拟公司",
                external_id="stable",
                description=description,
                data_kind="synthetic",
            ),
        )["job_id"]

    job_id = add()
    store = ResearchStore(tmp_path / "checkpoints.db", str(path))
    yield repo, MemoryService(repo), store, job_id, add
    store.close()
    repo.close()


def result_for(repo, job_id, memories=()):
    evidence = Catalog(repo).evidence(job_id)
    return {
        "question": "模拟研究",
        "created_at": now(),
        "status": "completed",
        "scope": Catalog(repo).query(job_ids=[job_id]),
        "memory_used": list(memories),
        "evidence": evidence,
        "claims": [
            {
                "category": "task",
                "requirement": "unspecified",
                "text": "模拟分析",
                "evidence_ids": [evidence[0]["id"]],
            }
        ],
        "gaps": [],
    }


def add_profile(repo, job_id, identity, memory):
    with Session(repo.engine) as session, session.begin():
        session.add(
            JobAnalysis(
                id=identity,
                job_id=job_id,
                snapshot_id=Catalog(repo).evidence(job_id)[0]["snapshot_id"],
                cache_key=identity,
                analyzer_version="test",
                prompt_version="test",
                model_name="simulated",
                memory_versions=[{"id": memory["id"], "version": memory["version"]}],
                result={"private_derived_text": memory["content"]},
                status="completed",
                created_at=now(),
            )
        )


def test_forget_personal_root_clears_every_version_and_only_related_profile_cache(setup):
    repo, memory, _, job_id, _ = setup
    original = repo.job(job_id)
    first = memory.create("preference", "模拟私人偏好甲")
    second = memory.revise(first["id"], "模拟私人偏好乙")
    unrelated = memory.create("correction", "另一条明确纠正")
    add_profile(repo, job_id, "affected", first)
    add_profile(repo, job_id, "unrelated", unrelated)
    result = memory.forget(first["id"])
    assert result["forgotten_memory_ids"] == [first["id"], second["id"]]
    assert result["deleted_profile_ids"] == ["affected"]
    assert repo.job(job_id) == original
    assert all(
        item["id"] not in result["forgotten_memory_ids"] for item in memory.recall("偏好", [job_id])
    )
    with Session(repo.engine) as session:
        forgotten = session.scalars(
            select(MemoryRecord).where(MemoryRecord.root_id == first["id"])
        ).all()
        assert all(row.content == "[已忘记]" and row.status == "forgotten" for row in forgotten)
        assert session.get(JobAnalysis, "affected") is None
        assert session.get(JobAnalysis, "unrelated") is not None
        assert session.get(MemoryRecord, unrelated["id"]).content == unrelated["content"]
        events_before = len(session.scalars(select(MemoryEvent)).all())
    assert memory.forget(second["id"])["forgotten_memory_ids"] == result["forgotten_memory_ids"]
    with Session(repo.engine) as session:
        assert len(session.scalars(select(MemoryEvent)).all()) == events_before


def test_knowledge_uses_withdraw_instead_of_personal_forget(setup):
    repo, memory, _, job_id, _ = setup
    knowledge = memory.create("knowledge", "模拟知识", evidence=Catalog(repo).evidence(job_id))
    with pytest.raises(ProbeError, match="MEMORY_FORGET_PERSONAL_ONLY"):
        memory.forget(knowledge["id"])
    assert memory.withdraw(knowledge["id"])["content"] == "模拟知识"


def test_invalidating_memories_erases_results_checkpoints_and_saved_links_but_not_other_runs(
    setup, tmp_path
):
    repo, memory, store, job_id, _ = setup
    item = memory.create("preference", "PRIVATE_SIMULATED_CONTEXT")
    result = result_for(repo, job_id, [item])
    a = store.create({"question": "PRIVATE_SIMULATED_CONTEXT"})
    store.save(a["id"], state="finished", result=result, saved={"report_id": "a" * 32})
    b = store.create({"question": "另一研究"})
    store.checkpoint(b["id"], {"result": result, "history": [{"content": item["content"]}]})
    safe = store.create({"question": "不相关问题"})
    store.save(safe["id"], state="finished", result={"memory_used": []})
    other_namespace = ResearchStore(tmp_path / "checkpoints.db", "other-namespace")
    other = other_namespace.create({"question": "另一资料库"})
    other_namespace.save(other["id"], result=result)
    try:
        invalid = store.invalidate_memories([item["id"]])
        assert set(invalid["affected_run_ids"]) == {a["id"], b["id"]}
        assert invalid["report_ids"] == ["a" * 32]
        for identity in invalid["affected_run_ids"]:
            record = store.get(identity)
            assert record["state"] == "invalidated"
            assert record["result"] is record["saved"] is None
            assert "PRIVATE_SIMULATED_CONTEXT" not in json.dumps(record)
            assert store.load_checkpoint(identity) is None
            with pytest.raises(ProbeError, match="MEMORY_FORGOTTEN_RESTART"):
                store.save(identity, result=result)
            with pytest.raises(ProbeError, match="MEMORY_FORGOTTEN_RESTART"):
                store.checkpoint(identity, {"result": result})
        assert store.get(safe["id"])["state"] == "finished"
        assert other_namespace.get(other["id"])["result"] == result
        rows = store.db.execute(
            "SELECT record,checkpoint FROM research_checkpoints WHERE namespace=?",
            (store.namespace,),
        ).fetchall()
        assert "PRIVATE_SIMULATED_CONTEXT" not in json.dumps(rows)
    finally:
        other_namespace.close()


def test_forget_reports_deletes_only_explicit_current_exports_and_retains_outside_copy(
    setup, tmp_path
):
    repo, _, _, job_id, _ = setup
    reports = tmp_path / "reports"
    first = save_result(result_for(repo, job_id), reports)
    safe = save_result(result_for(repo, job_id), reports)
    outside = tmp_path / "downloaded-copy.json"
    outside.write_bytes(Path(first["json"]).read_bytes())
    assert forget_reports([first["report_id"]], reports)["deleted_report_ids"] == [
        first["report_id"]
    ]
    assert not Path(first["json"]).exists() and not Path(first["markdown"]).exists()
    assert Path(safe["json"]).is_file() and outside.is_file()
    assert forget_reports([first["report_id"]], reports)["missing_report_ids"] == [
        first["report_id"]
    ]
    with pytest.raises(ProbeError, match="INVALID_REPORT_ID"):
        forget_reports(["../downloaded-copy"], reports)
    assert outside.is_file()


def test_report_cleanup_validates_all_targets_before_deleting_any(tmp_path, monkeypatch):
    directory = tmp_path / "reports"
    directory.mkdir()
    first = directory / (("a" * 32) + ".json")
    second = directory / (("b" * 32) + ".json")
    first.write_text("{}")
    second.write_text("{}")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == second or original(path))
    with pytest.raises(ProbeError, match="REPORT_PATH_DENIED"):
        forget_reports(["a" * 32, "b" * 32], directory)
    assert first.is_file() and second.is_file()


def test_audit_marks_revised_memory_and_later_source_without_destroying_historical_evidence(setup):
    repo, memory, _, job_id, add = setup
    item = memory.create("preference", "模拟偏好")
    result = result_for(repo, job_id, [item])
    assert audit_result(result, repo) == {
        "stale_memory": False,
        "memory_issues": [],
        "changed_sources": [],
        "affected_strategy": [],
    }
    memory.revise(item["id"], "模拟更新偏好")
    add("模拟新职责：Java开发")
    audit = audit_result(result, repo)
    assert audit["stale_memory"]
    assert audit["memory_issues"][0]["reason"] == "superseded"
    assert audit["changed_sources"][0]["reason"] == "job_current_version_changed"
    assert audit["changed_sources"][0]["retained_evidence_valid"] is True
    result["audit"] = audit
    assert "历史结果有效性提示" in render(result)


def test_audit_detects_changed_file_and_rolled_back_strategy_without_research_calls(setup):
    repo, _, _, job_id, _ = setup
    result = result_for(repo, job_id)
    strategy_id = "c" * 32
    result["strategy"] = {"id": strategy_id}
    with Session(repo.engine) as session, session.begin():
        session.add(
            RetrievalStrategy(
                id=strategy_id,
                name="模拟方法",
                config={"aliases": {}},
                status="rolled_back",
                created_at=now(),
            )
        )
        document = session.get(SourceDocument, result["evidence"][0]["document_id"])
        Path(document.path).write_bytes(b"changed")
    audit = audit_result(result, repo)
    assert audit["changed_sources"][0]["retained_evidence_valid"] is False
    assert audit["affected_strategy"] == [{"id": strategy_id, "status": "rolled_back"}]


def test_public_document_markdown_clearly_distinguishes_archived_text(setup):
    repo, _, _, job_id, _ = setup
    result = result_for(repo, job_id)
    public = {
        "id": "public-example",
        "source": "public_web",
        "evidence_kind": "public_document",
        "title": "模拟官网",
        "url": "https://example.com/",
        "observed_at": now(),
        "quote": "模拟已归档网页",
    }
    result["evidence"].append(public)
    output = render(result)
    assert "归档公开正文" in output
    assert "已归档网页提取正文" in output


def test_audit_public_archive_checks_raw_and_extracted_fingerprints(setup, tmp_path, monkeypatch):
    repo, _, _, job_id, _ = setup

    async def fetch(url):
        return 200, {"content-type": "text/plain"}, "模拟官网原文".encode()

    monkeypatch.setattr(public_module, "pinned_request", fetch)
    service = public_module.PublicDocumentService(repo, tmp_path / "public")
    fetched = asyncio.run(service.read("https://example.com/docs"))
    result = result_for(repo, job_id)
    result["evidence"].extend(fetched["evidence"])
    assert audit_result(result, repo)["changed_sources"] == []
    with Session(repo.engine) as session, session.begin():
        document = session.get(public_module.PublicDocument, fetched["document"]["id"])
        document.text = "被修改的提取正文"
    changed = audit_result(result, repo)["changed_sources"]
    assert changed[0]["reason"] == "public_source_integrity_or_quote_changed"
    assert changed[0]["retained_evidence_valid"] is False


def test_audit_strategy_configuration_hash_matches_canonical_unicode_config(setup):
    repo, _, _, job_id, _ = setup
    config = {"aliases": {"Agent": ["智能体"]}}
    identity = "d" * 32
    with Session(repo.engine) as session, session.begin():
        session.add(
            RetrievalStrategy(
                id=identity, name="模拟策略", config=config, status="active", created_at=now()
            )
        )
    result = result_for(repo, job_id)
    result["strategy"] = {"id": identity, "config_sha256": config_hash(config)}
    assert audit_result(result, repo)["affected_strategy"] == []
    result["strategy"]["config_sha256"] = "outdated"
    assert audit_result(result, repo)["affected_strategy"] == [
        {"id": identity, "status": "configuration_changed"}
    ]


def test_forgetting_research_also_erases_derived_knowledge_versions_and_profile_cache(setup):
    repo, memory, store, job_id, _ = setup
    original = repo.job(job_id)
    personal = memory.create("preference", "模拟个人文本")
    run = store.create({"question": "模拟研究"})
    store.save(run["id"], result=result_for(repo, job_id, [personal]))
    first = memory.create(
        "knowledge",
        "模拟个人文本的派生知识",
        source_run_id=run["id"],
        evidence=Catalog(repo).evidence(job_id),
    )
    second = memory.revise(first["id"], "模拟个人文本的修订派生知识")
    unrelated = memory.create(
        "knowledge",
        "不关联该研究的独立知识",
        source_run_id="e" * 32,
        evidence=Catalog(repo).evidence(job_id),
    )
    add_profile(repo, job_id, "derived-profile", second)
    ids = memory.forget(personal["id"])["forgotten_memory_ids"]
    runs = store.invalidate_memories(ids)["affected_run_ids"]
    cleaned = memory.invalidate_research(runs)
    assert cleaned["affected_memory_ids"] == [first["id"], second["id"]]
    assert cleaned["deleted_profile_ids"] == ["derived-profile"]
    with Session(repo.engine) as session:
        for identity in cleaned["affected_memory_ids"]:
            row = session.get(MemoryRecord, identity)
            assert row.content == "[已忘记]" and row.evidence == [] and row.status == "forgotten"
        assert session.get(MemoryRecord, unrelated["id"]).content == unrelated["content"]
    assert repo.job(job_id) == original
