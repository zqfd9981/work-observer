"""Frozen naming metadata completes new packets; synthetic records are not human review."""

import hashlib
import json
from copy import deepcopy

import pytest
from sqlalchemy.orm import Session
from test_research_benchmark import benchmark as benchmark
from test_research_benchmark import prepare_round

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.quality import research_benchmark as module
from work_observer.quality.research_benchmark import TABLES
from work_observer.quality.service import digest
from work_observer.storage.models import Company, Job


def update_names(service, job_id, *, title, company_raw, status):
    with Session(service.repository.engine) as session, session.begin():
        job = session.get(Job, job_id)
        job.title, job.company_name_raw = title, company_raw
        job.address = "PRIVATE_ADDRESS_NOT_IN_PACKET_CONTEXT"
        job.access_context = {"private": "PRIVATE_ACCESS_NOT_IN_PACKET_CONTEXT"}
        company = session.get(Company, job.company_id)
        company.identity_status = status
        company.name = "CANONICAL_COMPANY_NAME_NOT_RAW_SOURCE_NAME"
        company.introduction = "PRIVATE_INTRODUCTION_NOT_IN_PACKET_CONTEXT"


def test_new_packet_uses_frozen_metadata_even_if_live_changes_before_context_read(
    benchmark, monkeypatch
):
    service, _, tasks, source, create = benchmark
    job_id = tasks[0]["job_ids"][0]
    update_names(
        service, job_id, title="合成冻结岗位名", company_raw="合成来源公司全称", status="unverified"
    )
    real_freeze = module.freeze

    def freeze_then_change_live(database, directory):
        result = real_freeze(database, directory)
        update_names(
            service, job_id, title="后来岗位名", company_raw="后来公司名", status="source_id"
        )
        return result

    monkeypatch.setattr(module, "freeze", freeze_then_change_live)
    identity = create()["id"]
    protocol = service._protocol(identity)[0]["protocol"]
    assert protocol["packet_context_version"] == 2
    stored = deepcopy(protocol["tasks"][0]["scope_context"])
    assert set(stored) == {"notice", "jobs"}
    assert stored["jobs"] == [
        {
            "job_id": job_id,
            "title": "合成冻结岗位名",
            "company_name_raw": "合成来源公司全称",
            "company_identity_status": "unverified",
            "snapshot_id": protocol["tasks"][0]["sources"][0]["snapshot_id"],
            "layer": "frozen_job_metadata",
        }
    ]
    assert "不是JD逐字业务声明" in stored["notice"]
    assert "不证明岗位的组织隶属" in stored["notice"]
    assert "当前仍在招聘" in stored["notice"]
    assert "PRIVATE_" not in json.dumps(stored)
    assert "CANONICAL_COMPANY" not in json.dumps(stored)
    path = service.root / identity / "corpus" / "corpus.db"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    sealed, _ = prepare_round(service, identity, tasks, source)
    packet = service.blind_packet(identity, sealed["packet_ids"][0])
    assert packet["scope_context"] == stored
    assert "company_name_raw" not in packet["frozen_sources"][0]
    assert "合成来源公司全称" not in packet["frozen_sources"][0]["text"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    update_names(service, job_id, title="再改岗位名", company_raw="再改公司名", status="unknown")
    assert service.blind_packet(identity, sealed["packet_ids"][0])["scope_context"] == stored


@pytest.mark.parametrize("keep_internal_context", [False, True])
def test_legacy_missing_version_has_no_extra_packet_fields_or_hash_changes(
    benchmark, keep_internal_context
):
    service, _, tasks, source, create = benchmark
    identity = create()["id"]
    record = service._get(TABLES[0], identity)
    del record["protocol"]["packet_context_version"]
    if not keep_internal_context:
        for task in record["protocol"]["tasks"]:
            del task["scope_context"]
    record["protocol_sha256"] = digest(record["protocol"])
    with service.store.lock, service.store.db:
        service._save(TABLES[0], record)
    sealed, _ = prepare_round(service, identity, tasks, source)
    packet = service.blind_packet(identity, sealed["packet_ids"][0])
    assert set(packet) == {
        "packet_id",
        "protocol_sha256",
        "question",
        "completion_criteria",
        "declared_budget",
        "claims",
        "gaps",
        "execution_status",
        "mechanical_issues",
        "frozen_sources",
        "notice",
        "packet_sha256",
    }
    assert "scope_context" not in packet and "packet_context_version" not in packet
    unsigned = {key: value for key, value in packet.items() if key != "packet_sha256"}
    assert packet["packet_sha256"] == digest(unsigned)
    before = deepcopy(packet)
    update_names(
        service,
        tasks[0]["job_ids"][0],
        title="新版名称",
        company_raw="新版公司",
        status="unverified",
    )
    assert service.blind_packet(identity, sealed["packet_ids"][0]) == before
    # Reading an old packet never migrates its sealed protocol or inserts naming context.
    current = service._get(TABLES[0], identity)
    assert current["protocol"] == record["protocol"]
    assert current["protocol_sha256"] == record["protocol_sha256"]


def test_missing_company_stays_unknown_and_raw_name_is_not_invented(benchmark):
    service, _, tasks, _, create = benchmark
    job_id = tasks[0]["job_ids"][0]
    with Session(service.repository.engine) as session, session.begin():
        job = session.get(Job, job_id)
        job.company_id = None
        job.company_name_raw = None
    identity = create()["id"]
    row = service.development_tasks(identity)[0]["scope_context"]["jobs"][0]
    assert row["company_name_raw"] is None
    assert row["company_identity_status"] == "unknown"
    assert set(row) == {
        "job_id",
        "title",
        "company_name_raw",
        "company_identity_status",
        "snapshot_id",
        "layer",
    }


def test_scope_context_is_in_the_locked_protocol_digest(benchmark):
    service, _, _, _, create = benchmark
    identity = create()["id"]
    record = service._get(TABLES[0], identity)
    record["protocol"]["tasks"][0]["scope_context"]["jobs"][0]["company_name_raw"] = "篡改的名称"
    with service.store.lock, service.store.db:
        service._save(TABLES[0], record)
    with pytest.raises(ProbeError, match="BENCHMARK_PROTOCOL_CHANGED"):
        service.development_tasks(identity)
