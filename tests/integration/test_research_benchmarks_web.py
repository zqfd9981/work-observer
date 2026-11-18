"""真实HTTP/备份/遗忘接线；所有资料与模型均为明确合成替身。"""

import asyncio
import hashlib
import json
import re
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.maintenance import backup_workspace, restore_workspace
from work_observer.memory.service import MemoryService
from work_observer.quality.profile_reviews import ProfileQualityReviewService
from work_observer.quality.research_benchmark import TABLES, ResearchBenchmarkService
from work_observer.quality.service import DIMENSIONS
from work_observer.research.agent import RESEARCH_METHOD_VERSION, method_fingerprint, research
from work_observer.research.store import ResearchStore
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


class SourceModel:
    async def turn(self, history):
        outputs = [
            json.loads(i["output"]) for i in history if i.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = "query_jobs", {}
        elif not any(row.get("evidence") for row in outputs):
            name, args = "read_job", {"job_id": outputs[0]["jobs"][0]["id"]}
        else:
            ev = next(row["evidence"][0] for row in outputs if row.get("evidence"))
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "负责Python接口开发",
                            "evidence_ids": [ev["id"]],
                        }
                    ],
                    "gaps": [],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


@pytest.fixture
def workspace(tmp_path):
    database = (tmp_path / "app.db").resolve()
    upgrade(database)
    repo = Repository(database)
    store = ResearchStore(tmp_path / "checkpoints.db", str(database))
    repo.bind_research_store(store)
    job = import_jd(
        repo,
        RawArchive(tmp_path / "raw"),
        ManualJD(
            title="合成协议HTTP",
            company="合成公司",
            description="负责Python接口开发；上线审批未披露。",
            data_kind="synthetic",
        ),
    )["job_id"]
    memory = MemoryService(repo).create("preference", "SYNTHETIC_PRIVATE_BENCHMARK_NOTE")
    question = "合成开发任务：说明任务和未知边界"
    sources = [
        asyncio.run(
            research(repo, question, Settings(), job_ids=[job], model=SourceModel(), max_calls=3)
        )["run_id"]
        for _ in range(2)
    ]
    svc = ResearchBenchmarkService(store, repo)
    methods = {
        arm: {
            "output_type": "research",
            "method_sha256": method_fingerprint(),
            "method_version": RESEARCH_METHOD_VERSION,
        }
        for arm in ("baseline", "candidate")
    }
    tasks = [
        {
            "id": "D1",
            "split": "development",
            "question": question,
            "job_ids": [job],
            "criteria": [{"id": "tasks", "description": "按原文说明任务"}],
            "max_model_calls": 3,
            "max_elapsed_seconds": 180,
        },
        {
            "id": "H1",
            "split": "holdout",
            "question": "SYNTHETIC_UNEXPOSED_QUESTION",
            "job_ids": [job],
            "criteria": [{"id": "missing", "description": "说明未披露事项"}],
        },
    ]
    protocol = svc.preregister(
        "合成固定业务题组",
        tasks,
        methods,
        task_author="合成开发者",
        allow_retrospective_development=True,
        dependency_memory_refs=[{"id": memory["id"], "version": memory["version"]}],
    )
    yield database, repo, store, svc, protocol["id"], sources, memory["id"]
    store.close()
    repo.close()


def pending_review(packet):
    return {
        "packet_sha256": packet["packet_sha256"],
        "reviewer": "合成Agent审核者",
        "reviewer_kind": "agent_assisted",
        "independent_review_declared": False,
        "blinded_review_declared": True,
        "note": "SYNTHETIC_PRIVATE_BLIND_FEEDBACK",
        "dimensions": {
            key: {"rating": "unknown", "reason": "合成机制检查，不能当人审"} for key in DIMENSIONS
        },
        "claim_ratings": [
            {
                "index": row["index"],
                "support": "unknown",
                "requirement": "unknown",
                "reason": "尚待独立核对",
            }
            for row in packet["claims"]
        ],
        "criterion_ratings": [
            {"id": row["id"], "rating": "unknown", "reason": "尚待独立核对"}
            for row in packet["completion_criteria"]
        ],
    }


def test_http_keeps_holdout_and_arm_hidden_then_forgetting_clears_the_whole_protocol(
    workspace, tmp_path
):
    database, repo, store, svc, identity, sources, memory_id = workspace
    job_id = svc.development_tasks(identity)[0]["job_ids"][0]
    prefix = f"/api/research-benchmarks/{identity}"
    with TestClient(
        create_app(Settings(database_path=database), reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        page = client.get("/").text
        auth = {"X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', page)[1]}
        assert 'id="page-research-benchmarks"' in page
        assert client.get("/assets/research-benchmarks.js").status_code == 200
        assert "SYNTHETIC_UNEXPOSED_QUESTION" not in client.get(prefix).text
        assert "SYNTHETIC_UNEXPOSED_QUESTION" not in client.get(prefix + "/development").text
        assert client.get(prefix + "/phases/holdout").json()["state"] == "not_opened"
        assert client.post(prefix + "/phases/development/open", json={}).status_code == 403
        assert (
            client.post(prefix + "/phases/development/open", json={}, headers=auth).status_code
            == 201
        )
        for arm, source in zip(("baseline", "candidate"), sources, strict=True):
            registered = client.post(
                prefix + "/submissions",
                headers=auth,
                json={"task_id": "D1", "arm": arm, "source_id": source},
            )
            assert registered.status_code == 201
            assert "actual_method" not in registered.json()
        sealed = client.post(prefix + "/phases/development/seal", json={}, headers=auth)
        assert sealed.status_code == 201
        packets = sealed.json()["packet_ids"]
        assert len(packets) == 2
        for opaque in packets:
            packet = client.get(prefix + "/packets/" + opaque).json()
            assert not any(source in json.dumps(packet) for source in sources)
            assert not {"arm", "actual_method", "usage", "reviews"} & packet.keys()
            assert packet["completion_criteria"][0]["description"] == "按原文说明任务"
            assert (
                client.post(
                    prefix + "/packets/" + opaque + "/reviews",
                    json=pending_review(packet),
                    headers=auth,
                ).status_code
                == 201
            )
        report = client.post(prefix + "/phases/development/close", json={}, headers=auth).json()
        assert report["decision"] == "no_demonstrated_change"
        assert not report["independent_human_review_complete"]
        assert not report["automatic_activation"]
        closed = client.get(prefix + "/packets/" + packets[0])
        assert closed.status_code == 400
        assert closed.json()["error_code"] == "BENCHMARK_BLIND_REVIEW_CLOSED"
        schema = client.get("/api/openapi.json").json()
        assert prefix.replace(identity, "{id}") + "/packets/{packet_id}/reviews" in schema["paths"]
        forgotten = client.delete(f"/api/memories/{memory_id}", headers=auth)
        assert forgotten.status_code == 200, forgotten.text
        assert identity in forgotten.json()["invalidated_research_benchmark_ids"]
        erased = client.get(prefix)
        assert erased.status_code == 400
        assert erased.json()["error_code"] == "BENCHMARK_DEPENDENCY_FORGOTTEN"
    for table in TABLES:
        records = [row[0] for row in store.db.execute(f"SELECT record FROM {table}")]
        assert all(
            "SYNTHETIC_PRIVATE" not in raw and question not in raw
            for raw in records
            for question in ("合成开发任务", "SYNTHETIC_UNEXPOSED_QUESTION")
        )
    assert repo.counts()["jobs"] == 1
    assert repo.job(job_id)["current"]["description_text"] == "负责Python接口开发；上线审批未披露。"


def test_backup_restores_corpus_bytes_and_filters_every_new_namespace(workspace, tmp_path):
    database, repo, store, svc, identity, sources, _ = workspace
    svc.open_phase(identity, "development")
    for arm, source in zip(("baseline", "candidate"), sources, strict=True):
        svc.register(identity, "D1", arm, source)
    sealed = svc.seal_phase(identity, "development")
    ProfileQualityReviewService(store, repo)
    for table in TABLES:
        key = uuid4().hex
        store.db.execute(
            f"INSERT INTO {table} VALUES (?,?,?)",
            ("unrelated", key, json.dumps({"id": key, "private": "UNRELATED_NAMESPACE_PRIVATE"})),
        )
    key = uuid4().hex
    store.db.execute(
        "INSERT INTO profile_quality_reviews VALUES (?,?,?,?)",
        (
            "unrelated",
            key,
            uuid4().hex,
            json.dumps({"id": key, "private": "UNRELATED_NAMESPACE_PRIVATE"}),
        ),
    )
    store.db.commit()
    corpus = tmp_path / "research-benchmarks" / identity / "corpus" / "corpus.db"
    sha = hashlib.sha256(corpus.read_bytes()).hexdigest()
    backup = tmp_path / "backup"
    backup_workspace(database, backup, tmp_path / "reports")
    assert b"UNRELATED_NAMESPACE_PRIVATE" not in (backup / "checkpoints.db").read_bytes()
    restored = tmp_path / "restored"
    result = restore_workspace(backup, restored)
    assert result["restored_research_benchmark_corpora"] == 1
    assert (
        hashlib.sha256(
            (restored / "research-benchmarks" / identity / "corpus/corpus.db").read_bytes()
        ).hexdigest()
        == sha
    )
    copy_repo = Repository(restored / "app.db")
    copy_store = ResearchStore(restored / "checkpoints.db", str((restored / "app.db").resolve()))
    try:
        copy = ResearchBenchmarkService(copy_store, copy_repo)
        assert copy.blind_packet(identity, sealed["packet_ids"][0])["claims"]
        for table in (*TABLES, "profile_quality_reviews"):
            assert {row[0] for row in copy_store.db.execute(f"SELECT namespace FROM {table}")} <= {
                str((restored / "app.db").resolve())
            }
    finally:
        copy_store.close()
        copy_repo.close()


def test_mixed_source_protocol_does_not_describe_synthetic_rows_as_real(workspace, tmp_path):
    _, repo, _, svc, _, _, _ = workspace
    other = import_jd(
        repo,
        RawArchive(tmp_path / "raw"),
        ManualJD(
            title="明确用户提供资料",
            company="用户提供示例",
            description="负责Java接口维护。",
            data_kind="user_provided",
        ),
    )["job_id"]
    original = svc.development_tasks(svc.overview()[0]["id"])[0]
    task = {
        key: original[key]
        for key in (
            "id",
            "split",
            "question",
            "job_ids",
            "criteria",
            "max_model_calls",
            "max_elapsed_seconds",
        )
    }
    task["job_ids"] = [*task["job_ids"], other]
    methods = {
        arm: {"method_sha256": method_fingerprint(), "method_version": RESEARCH_METHOD_VERSION}
        for arm in ("baseline", "candidate")
    }
    protocol = svc.preregister(
        "混合来源应披露合成记录", [task], methods, task_author="合成测试作者"
    )
    assert svc.overview(protocol["id"])["data_kind"] == "mixed"
