"""Synthetic actual-engine feedback repair, privacy closure and scoped HTTP entry."""

import asyncio
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from work_observer.api.web import create_app
from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.maintenance import backup_workspace, restore_workspace
from work_observer.memory.lifecycle import forget_personal
from work_observer.memory.service import MemoryService
from work_observer.quality.feedback import VERSION, load_feedback
from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import DIMENSIONS
from work_observer.reports.results import read_result, save_result
from work_observer.research.agent import method_fingerprint, research
from work_observer.research.store import ResearchStore
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


class Model:
    def __init__(self, *, original=False, cancel=False, after=None):
        self.original, self.cancel, self.after = original, cancel, after
        self.contexts = []

    async def turn(self, history):
        payload = json.loads(history[1]["content"])
        self.contexts.append(payload)
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = "query_jobs", {}
        elif not any(row.get("evidence") for row in outputs):
            name, args = "read_job", {"job_id": outputs[0]["jobs"][0]["id"]}
        else:
            if self.cancel:
                raise asyncio.CancelledError()
            ev = next(row["evidence"] for row in outputs if row.get("evidence"))
            claim = dict(
                category="ability",
                basis="direct",
                requirement="required" if self.original else "preferred",
                text="旧结论错误标记：Docker为必备" if self.original else "Docker实战经验者优先",
                evidence_ids=[ev[0]["id"]],
            )
            name, args = "finish_research", dict(claims=[claim], gaps=[])
        if self.after:
            callback, self.after = self.after, None
            callback()
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(len(history))
        )
        return [call], call


class EmptyMemory:
    def recall(self, *args, **kwargs):
        return []


def reject(
    service, run_id, *, kind="agent_assisted", note="复核私有标记：Docker应为优先，请重读原文"
):
    p = service.packet(run_id)
    return service.submit(
        run_id,
        dict(
            result_sha256=p["result_sha256"],
            reviewer="合成核对",
            reviewer_kind=kind,
            decision="reject",
            note=note,
            dimensions={
                key: dict(rating="fail", reason="合成缺口，非语义通过") for key in DIMENSIONS
            },
            claim_reviews=[
                dict(
                    index=row["index"],
                    support="unsupported",
                    requirement="incorrect",
                    note="应保留原文优先性质",
                )
                for row in p["claims"]
            ],
        ),
    )


@pytest.fixture
def workspace(tmp_path):
    database = tmp_path / "app.db"
    upgrade(database)
    repo = Repository(database)
    store = ResearchStore(tmp_path / "checkpoints.db", str(database.resolve()))
    repo.bind_research_store(store)
    job = import_jd(
        repo,
        RawArchive(tmp_path / "raw"),
        ManualJD(
            title="合成反馈岗位",
            company="合成公司",
            external_id="feedback-fixture",
            description="任职要求：\n具备Python开发能力；Docker实战经验者优先。",
            data_kind="synthetic",
        ),
    )["job_id"]
    memory = MemoryService(repo).create("preference", "隐私根记忆", subject="feedback-fixture")
    original = asyncio.run(
        research(
            repo,
            "合成资格核对",
            Settings(),
            job_ids=[job],
            model=Model(original=True),
            max_calls=4,
            allow_proposals=False,
        )
    )
    assert original["status"] == "completed" and original["memory_used"]
    svc = QualityReviewService(store, repo)
    review = reject(svc, original["run_id"])
    yield repo, store, job, memory, original, review, tmp_path
    store.close()
    repo.close()


def options(job, original):
    return dict(
        job_ids=[job],
        review_run_id=original["run_id"],
        max_calls=5,
        allow_proposals=False,
        memory=EmptyMemory(),
    )


@pytest.mark.parametrize("human", [False, True])
def test_review_is_version_bound_diagnostic_not_old_claims_or_factual_ancestry(workspace, human):
    repo, store, job, _, original, _, _ = workspace
    if human:
        reject(
            QualityReviewService(store, repo),
            original["run_id"],
            kind="human",
            note="人工拒绝也只作诊断",
        )
    old = deepcopy(store.get(original["run_id"]))
    model = Model()
    result = asyncio.run(
        research(repo, original["question"], Settings(), model=model, **options(job, original))
    )
    assert result["status"] == "completed" and result["model_calls"] == 3
    assert result["research_method_version"] == VERSION
    assert result["research_method_sha256"] == method_fingerprint(review_feedback=True)
    assert result["research_method_sha256"] != method_fingerprint()
    assert result["continued_from"] == [] and result["feedback_from"] == [original["run_id"]]
    feedback = model.contexts[0]["review_feedback"]
    assert feedback["reviewer_kind"] == ("human" if human else "agent_assisted")
    assert "旧结论错误标记" not in json.dumps(model.contexts, ensure_ascii=False)
    assert not result["memory_used"]
    assert store.get(original["run_id"]) == old
    assert store.get(result["run_id"])["input"]["review_id"] == feedback["review_id"]


def test_resume_preserves_review_and_original_remaining_budget(workspace):
    repo, store, job, _, original, _, _ = workspace
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                original["question"],
                Settings(),
                model=Model(cancel=True),
                **options(job, original),
            )
        )
    run = next(row for row in store.list() if row["id"] != original["run_id"])
    assert run["result"]["model_calls"] == 3
    result = asyncio.run(
        research(
            repo,
            original["question"],
            Settings(),
            checkpoint=(store, run["id"]),
            resume=True,
            model=Model(),
            memory=EmptyMemory(),
            allow_proposals=False,
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 4
    assert store.load_checkpoint(run["id"])["max_calls"] == 5


def test_changed_review_stops_inflight_round_and_cannot_silently_resume(workspace):
    repo, store, job, _, original, _, _ = workspace

    def change():
        reject(QualityReviewService(store, repo), original["run_id"], note="后续复核版本变化")

    result = asyncio.run(
        research(
            repo,
            original["question"],
            Settings(),
            model=Model(after=change),
            **options(job, original),
        )
    )
    assert result["status"] == "failed" and result["model_calls"] == 1
    assert result["stop_reason"] == "RESEARCH_FEEDBACK_CHANGED_NEW_RUN_REQUIRED"
    model = Model()
    with pytest.raises(ProbeError, match="RESEARCH_FEEDBACK_CHANGED"):
        asyncio.run(
            research(
                repo,
                original["question"],
                Settings(),
                checkpoint=(store, result["run_id"]),
                resume=True,
                model=model,
            )
        )
    assert not model.contexts


@pytest.mark.parametrize("wrong", ["question", "job", "filters"])
def test_feedback_cannot_cross_question_or_scope(workspace, wrong):
    repo, store, job, _, original, _, _ = workspace
    args = dict(question=original["question"], job_ids=[job], filters={})
    if wrong == "question":
        args["question"] = "另一问题"
    if wrong == "job":
        args["job_ids"] = ["b" * 32]
    if wrong == "filters":
        args["filters"] = {"city": "其他城市"}
    with pytest.raises(ProbeError, match="FIXED_LOCAL_SCOPE"):
        load_feedback(store, repo, original["run_id"], **args)


def test_erasure_cascades_through_feedback_including_queued_and_orphan_report(workspace):
    repo, store, job, memory, original, _, root = workspace
    result = asyncio.run(
        research(repo, original["question"], Settings(), model=Model(), **options(job, original))
    )
    queued = store.create(
        {"review_run_id": original["run_id"], "question": "queued_private_marker"}
    )
    report = save_result(result, root / "reports")
    store.save(result["run_id"], saved={"report_id": report["report_id"]})
    orphan = save_result({**result, "run_id": "f" * 32}, root / "reports")
    backup_workspace(
        repo.path if hasattr(repo, "path") else root / "app.db", root / "backup", root / "reports"
    )
    restored = restore_workspace(root / "backup", root / "restored")
    restored_repo = Repository(Path(restored["database"]))
    restored_store = ResearchStore(
        root / "restored/checkpoints.db", str((root / "restored/app.db").resolve())
    )
    restored_repo.bind_research_store(restored_store)
    assert restored_store.get(result["run_id"])["result"] == result
    assert (
        read_result(report["report_id"], root / "restored/reports")["review_feedback"]
        == result["review_feedback"]
    )
    forget_personal(repo, store, memory["id"], root / "reports")
    assert all(
        store.get(x)["state"] == "invalidated"
        for x in (original["run_id"], result["run_id"], queued["id"])
    )
    assert not (root / "reports" / (orphan["report_id"] + ".json")).exists()
    assert restored_store.get(result["run_id"])["state"] == "finished"
    forget_personal(restored_repo, restored_store, memory["id"], root / "restored/reports")
    assert restored_store.get(result["run_id"])["state"] == "invalidated"
    restored_store.close()
    restored_repo.close()


def test_http_repair_preview_and_offline_round_preserve_original(workspace):
    repo, store, job, _, original, _, root = workspace
    before = store.get(original["run_id"])
    with TestClient(
        create_app(Settings(database_path=root / "app.db"), reports_dir=root / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        headers = {"X-WO-Token": token}
        packet = client.get("/api/quality/runs/" + original["run_id"]).json()
        assert packet["repair"]["available"]
        payload = {
            key: packet["repair"][key]
            for key in ("question", "job_ids", "filters", "review_run_id", "review_id")
        }
        response = client.post(
            "/api/research", headers=headers, json={**payload, "offline": True, "max_calls": 5}
        )
        assert response.status_code == 202
        run = client.get("/api/research/" + response.json()["id"]).json()
        assert run["result"]["status"] == "evidence_only"
        assert run["result"]["review_feedback"]["review_id"] == payload["review_id"]
        assert run["result"]["model_calls"] == 0
        bad = client.post(
            "/api/research", headers=headers, json={**payload, "question": "另一问题"}
        )
        assert bad.status_code == 400
    assert store.get(original["run_id"]) == before


@pytest.mark.parametrize("extra", [{"approach": "source_first"}, {"allow_public": True}])
def test_repair_cannot_enable_other_methods_or_public_search(workspace, extra):
    repo, _, job, _, original, _, _ = workspace
    model = Model()
    with pytest.raises(ProbeError, match="FEEDBACK_STANDARD_ONLY"):
        asyncio.run(
            research(
                repo,
                original["question"],
                Settings(),
                model=model,
                **options(job, original),
                **extra,
            )
        )
    assert not model.contexts


def test_project_results_cannot_get_an_independent_repair_budget(workspace):
    repo, store, job, _, original, _, _ = workspace
    result = {**original, "project_id": "c" * 32}
    store.save(original["run_id"], result=result)
    with pytest.raises(ProbeError, match="USE_PROJECT_BUDGET"):
        load_feedback(store, repo, original["run_id"], question=original["question"], job_ids=[job])


def test_review_pin_and_latest_pending_decision_prevent_using_old_rejection(workspace):
    repo, store, job, _, original, review, _ = workspace
    kwargs = dict(question=original["question"], job_ids=[job])
    with pytest.raises(ProbeError, match="FEEDBACK_CHANGED"):
        load_feedback(store, repo, original["run_id"], review_id="e" * 32, **kwargs)
    record = {
        **review,
        "id": "f" * 32,
        "created_at": "2099-01-01T00:00:00+00:00",
        "status": "pending",
        "decision": "pending",
    }
    with store.db:
        store.db.execute(
            "INSERT INTO quality_reviews VALUES (?,?,?,?)",
            (store.namespace, record["id"], original["run_id"], json.dumps(record)),
        )
    with pytest.raises(ProbeError, match="REJECTION_REQUIRED"):
        load_feedback(store, repo, original["run_id"], **kwargs)


def test_changed_job_text_requires_a_new_unassisted_scope(workspace):
    repo, store, job, _, original, _, root = workspace
    import_jd(
        repo,
        RawArchive(root / "raw"),
        ManualJD(
            title="合成反馈岗位",
            company="合成公司",
            external_id="feedback-fixture",
            description="内容已更新，Docker性质待核对",
            data_kind="synthetic",
        ),
    )
    with pytest.raises(ProbeError, match="SOURCES_CHANGED"):
        load_feedback(store, repo, original["run_id"], question=original["question"], job_ids=[job])


def test_feedback_context_is_bounded_and_does_not_copy_claim_bodies(workspace):
    repo, store, job, _, original, _, _ = workspace
    result = {**original, "claims": original["claims"] * 60}
    store.save(original["run_id"], result=result)
    service = QualityReviewService(store, repo)
    review = reject(service, original["run_id"], note="诊断" * 1000)
    review["dimensions"] = {key: dict(rating="unknown", reason="待核" * 600) for key in DIMENSIONS}
    for item in review["claim_reviews"]:
        item["note"] = "条目" * 600
    with store.db:
        store.db.execute(
            "UPDATE quality_reviews SET record=? WHERE namespace=? AND id=?",
            (json.dumps(review), store.namespace, review["id"]),
        )
    context = load_feedback(
        store, repo, original["run_id"], question=original["question"], job_ids=[job]
    )
    encoded = json.dumps(context, ensure_ascii=False)
    assert len(encoded) <= 6000 and context["omitted_claim_reviews"] > 0
    assert len(context["note"]) == 1000
    assert context["omitted_claim_reviews"] + len(context["claim_issues"]) == 60
    assert "旧结论错误标记" not in encoded


def test_cli_offline_repair_saves_feedback_receipt_without_network(workspace, monkeypatch):
    _, store, job, _, original, review, root = workspace
    monkeypatch.setattr(
        Settings, "load", classmethod(lambda cls, *a, **k: Settings(database_path=root / "app.db"))
    )

    def forbidden(*a, **k):
        raise AssertionError("离线入口不得调用网络")

    monkeypatch.setattr("httpx.AsyncClient", forbidden)
    response = CliRunner().invoke(
        app,
        [
            "research",
            "--question",
            original["question"],
            "--job-id",
            job,
            "--review-run-id",
            original["run_id"],
            "--offline",
            "--save",
            "--reports-dir",
            str(root / "reports"),
        ],
    )
    assert response.exit_code == 0, (response.stdout, response.exception)
    run = next(row for row in store.list() if row["id"] != original["run_id"])
    assert run["input"]["review_id"] == review["id"]
    assert run["result"]["model_calls"] == 0
    saved = read_result(run["saved"]["report_id"], root / "reports")
    assert saved["review_feedback"]["reviewer_kind"] == "agent_assisted"
