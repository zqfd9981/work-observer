"""业务研究benchmark机制；合成记录与actor人审不等于真实模型/人类质量证据。"""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.service import MemoryService
from work_observer.quality.research_benchmark import TABLES, ResearchBenchmarkService
from work_observer.quality.service import DIMENSIONS
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def benchmark(tmp_path):
    path = tmp_path / "app.db"
    upgrade(path)
    repo = Repository(path)
    job = import_jd(
        repo,
        RawArchive(tmp_path / "raw"),
        ManualJD(
            title="合成研究岗位",
            company="合成公司",
            description="负责Python接口开发，Docker加分；未说明上线审批。",
            data_kind="synthetic",
        ),
    )["job_id"]
    store = ResearchStore(tmp_path / "custom-checkpoints.db", str(path.resolve()))
    service = ResearchBenchmarkService(store, repo)
    methods = {
        arm: {
            "output_type": "research",
            "method_sha256": char * 64,
            "method_version": "synthetic-method-" + char,
        }
        for arm, char in (("baseline", "a"), ("candidate", "b"))
    }
    tasks = [
        {
            "id": identity,
            "split": split,
            "question": question,
            "job_ids": [job],
            "criteria": [
                {"id": "answer", "description": "具体回答本题"},
                {"id": "unknown", "description": "保留未披露事项"},
            ],
            "max_model_calls": 4,
            "max_elapsed_seconds": 30,
        }
        for identity, split, question in (
            ("D1", "development", "合成开发问题：有哪些工具？"),
            ("H1", "holdout", "合成预留问题：Docker是什么性质？"),
            ("H2", "holdout", "合成预留问题：上线审批责任明确吗？"),
        )
    ]

    def source(task, arm="candidate", *, status="completed", mutate=None, memories=None):
        run = store.create(
            {"question": task["question"], "job_ids": [job], "max_calls": 4, "timeout": 30}
        )
        evidence = Catalog(repo).evidence(job)
        result = {
            "run_id": run["id"],
            "created_at": run["created_at"],
            "question": task["question"],
            "status": status,
            "research_method_sha256": methods[arm]["method_sha256"],
            "research_method_version": methods[arm]["method_version"],
            "scope": {"jobs": [{"id": job}]},
            "evidence": evidence,
            "claims": [
                {
                    "text": "Docker为加分，上线审批未说明"
                    if arm == "candidate"
                    else "负责Python接口开发",
                    "category": "tool",
                    "basis": "direct",
                    "requirement": "preferred" if arm == "candidate" else "unspecified",
                    "evidence_ids": [evidence[0]["id"]],
                }
            ]
            if status == "completed"
            else [],
            "gaps": ["合成资料，未披露上线责任保持未知"],
            "model_calls": 2,
            "elapsed_seconds": 3.0,
            "usage": [{"input_tokens": 40, "output_tokens": 20, "total_tokens": 60}],
            "memory_used": memories or [],
            "mode": "synthetic_test_double",
        }
        if mutate:
            mutate(result)
        store.save(
            run["id"], state="finished" if status == "completed" else "failed", result=result
        )
        store.checkpoint(
            run["id"],
            {
                "history": [
                    {"role": "system", "content": "synthetic system"},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "project_context": None,
                                "memory_context": memories or [],
                                "question": task["question"],
                                "fixed_scope": {"jobs": [{"id": job}]},
                            }
                        ),
                    },
                ]
            },
        )
        return run["id"]

    def register_protocol(**kwargs):
        values = {
            "title": "合成业务研究协议",
            "tasks": tasks,
            "methods": methods,
            "task_author": "synthetic-human-task-actor",
            "task_author_kind": "human",
            "independent_tasks_declared": True,
            "existing_corpus_exposed": True,
        }
        values.update(kwargs)
        return service.preregister(**values)

    yield service, methods, tasks, source, register_protocol
    store.close()
    repo.close()


def review(packet, *, good=True, kind="human", reviewer="synthetic-independent-actor"):
    return {
        "packet_sha256": packet["packet_sha256"],
        "reviewer": reviewer,
        "reviewer_kind": kind,
        "independent_review_declared": kind == "human",
        "blinded_review_declared": kind == "human",
        "dimensions": {
            key: {
                "rating": "pass"
                if good or key not in {"profile_coverage", "question_answered"}
                else "fail",
                "reason": "合成actor按冻结资料核对",
            }
            for key in DIMENSIONS
        },
        "claim_ratings": [
            {
                "index": row["index"],
                "support": "supported",
                "requirement": "correct",
                "reason": "合成actor核对原文",
            }
            for row in packet["claims"]
        ],
        "criterion_ratings": [
            {
                "id": row["id"],
                "rating": "satisfied" if good else "omitted",
                "reason": "合成actor评判完成条件",
            }
            for row in packet["completion_criteria"]
        ],
        "note": "synthetic test actor only, not real independent human annotation",
    }


def prepare_round(service, identity, tasks, source, phase="holdout"):
    service.open_phase(identity, phase)
    ids = {}
    for task in tasks:
        if task["split"] != phase:
            continue
        for arm in ("baseline", "candidate"):
            key = source(task, arm)
            ids[key] = arm
            registered = service.register(identity, task["id"], arm, key)
            assert registered["contract_issues"] == []
    return service.seal_phase(identity, phase), ids


def test_preregister_run_binding_blind_reviews_and_paired_business_dimensions(benchmark):
    service, methods, tasks, source, create = benchmark
    protocol = create()
    identity = protocol["id"]
    assert service.development_tasks(identity) == [
        service._protocol(identity)[0]["protocol"]["tasks"][0]
    ]
    assert "合成预留问题" not in json.dumps(service.overview(), ensure_ascii=False)
    sealed, ids = prepare_round(service, identity, tasks, source)
    with pytest.raises(ProbeError, match="BENCHMARK_UNBLIND_REQUIRES_CLOSED_REVIEWS"):
        service.paired_report(identity, "holdout")
    for packet_id in sealed["packet_ids"]:
        packet = service.blind_packet(identity, packet_id)
        raw = json.dumps(packet, ensure_ascii=False)
        assert not set(ids) & {value for value in ids if value in raw}
        assert methods["baseline"]["method_sha256"] not in raw
        assert "baseline" not in packet and "candidate" not in packet and "usage" not in packet
        good = packet["claims"][0]["text"].startswith("Docker")
        grade = review(packet, good=good)
        service.submit_review(identity, packet_id, grade)
        assert service.blind_packet(identity, packet_id)["packet_sha256"] == packet["packet_sha256"]
        service.submit_review(identity, packet_id, grade)
    paired = service.close_phase(identity, "holdout")
    assert paired["decision"] == "accepted_in_frozen_scope"
    assert paired["data_kind"] == "synthetic"
    assert paired["candidate_tasks_satisfied"] == 2 and paired["baseline_tasks_satisfied"] == 0
    assert paired["generalization_scope"] == "same_corpus_task_holdout"
    assert paired["automatic_activation"] is False
    assert paired["pairs"][0]["arms"]["baseline"]["business_scores"]["omitted_criteria"] == 2
    assert paired["pairs"][0]["arms"]["candidate"]["usage"]["total_tokens"] == 60
    with pytest.raises(ProbeError, match="BENCHMARK_BLIND_REVIEW_CLOSED"):
        service.blind_packet(identity, sealed["packet_ids"][0])


def test_agent_assessment_never_becomes_independent_human_acceptance(benchmark):
    service, _, tasks, source, create = benchmark
    identity = create()["id"]
    sealed, _ = prepare_round(service, identity, tasks, source)
    for packet_id in sealed["packet_ids"]:
        packet = service.blind_packet(identity, packet_id)
        service.submit_review(
            identity,
            packet_id,
            review(
                packet, good=packet["claims"][0]["text"].startswith("Docker"), kind="agent_assisted"
            ),
        )
    paired = service.close_phase(identity, "holdout")
    assert paired["decision"] == "insufficient"
    assert not paired["independent_human_review_complete"]
    assert paired["review_sufficiency"] == "insufficient"


def test_holdout_reserves_before_runs_one_attempt_and_same_id_cannot_be_relabeled(benchmark):
    service, _, tasks, source, create = benchmark
    old = source(tasks[1], "baseline")
    identity = create()["id"]
    service.open_phase(identity, "holdout")
    registered = service.register(identity, "H1", "baseline", old)
    assert "run_predates_reserved_attempt" in registered["contract_issues"]
    swapped = service.register(identity, "H1", "candidate", old)
    assert "same_authoritative_output_reused" in swapped["contract_issues"]
    assert "method_contract_mismatch:method_sha256" in swapped["contract_issues"]
    with pytest.raises(ProbeError, match="BENCHMARK_ATTEMPT_ALREADY_REGISTERED"):
        service.register(identity, "H1", "candidate", source(tasks[1], "candidate"))
    with pytest.raises(ProbeError, match="BENCHMARK_PHASE_ALREADY_RESERVED"):
        service.open_phase(identity, "holdout")
    sealed = service.seal_phase(identity, "holdout", record_missing=True)
    assert len(sealed["packet_ids"]) == 4
    with pytest.raises(ProbeError, match="BENCHMARK_PHASE_ALREADY_SEALED"):
        service.register(identity, "H2", "candidate", source(tasks[2]))


def test_failures_missing_budget_and_source_mismatches_remain_visible(benchmark):
    service, _, tasks, source, create = benchmark
    identity = create()["id"]
    service.open_phase(identity, "development")
    failed = source(tasks[0], "baseline", status="incomplete")
    first = service.register(identity, "D1", "baseline", failed)
    assert first["execution_status"] == "incomplete"
    assert "execution_not_completed" in first["contract_issues"]

    def broken(result):
        result["model_calls"] = 99
        result["evidence"][0]["quote"] = "合成伪造原文"

    bad = source(tasks[0], mutate=broken)
    second = service.register(identity, "D1", "candidate", bad)
    assert "budget_exceeded_or_usage_unknown" in second["contract_issues"]
    assert "source_outside_frozen_contract" in second["contract_issues"]
    sealed = service.seal_phase(identity, "development")
    for key in sealed["packet_ids"]:
        packet = service.blind_packet(identity, key)
        service.submit_review(identity, key, review(packet, good=False, kind="agent_assisted"))
    report = service.close_phase(identity, "development")
    assert report["decision"] == "insufficient"
    assert report["pairs"][0]["arms"]["candidate"]["usage"]["model_calls"] == 99


def test_same_method_and_renamed_old_tasks_cannot_claim_new_improvement(benchmark):
    service, methods, tasks, source, create = benchmark
    same = {"baseline": methods["baseline"], "candidate": methods["baseline"]}
    identity = create(methods=same)["id"]
    service.open_phase(identity, "holdout")
    for task in tasks[1:]:
        for arm in ("baseline", "candidate"):
            service.register(identity, task["id"], arm, source(task, "baseline"))
    sealed = service.seal_phase(identity, "holdout")
    for key in sealed["packet_ids"]:
        service.submit_review(identity, key, review(service.blind_packet(identity, key)))
    assert service.close_phase(identity, "holdout")["decision"] == "no_demonstrated_change"
    renamed = deepcopy(tasks)
    for index, task in enumerate(renamed):
        task["id"] = "new-" + str(index)
    second = create(tasks=renamed)["id"]
    assert all(
        task["reused_case_detected"] for task in service._protocol(second)[0]["protocol"]["tasks"]
    )


def test_retrospective_development_is_explicit_and_registered_output_cannot_change(benchmark):
    service, _, tasks, source, create = benchmark
    old = source(tasks[0], "baseline")
    identity = create(allow_retrospective_development=True)["id"]
    service.open_phase(identity, "development")
    registered = service.register(identity, "D1", "baseline", old)
    assert (
        registered["retrospective_development"]
        and "run_predates_reserved_attempt" not in registered["contract_issues"]
    )
    service.register(identity, "D1", "candidate", source(tasks[0]))
    sealed = service.seal_phase(identity, "development")
    result = service.store.get(old)["result"]
    result["claims"][0]["text"] = "修改已登记输出"
    service.store.save(old, result=result)
    with pytest.raises(ProbeError, match="BENCHMARK_REGISTERED_OUTPUT_CHANGED"):
        for key in sealed["packet_ids"]:
            service.blind_packet(identity, key)


def test_forgetting_erases_protocol_and_reviews_and_does_not_restore_old_text(benchmark):
    service, _, tasks, source, create = benchmark
    memory = MemoryService(service.repository).create(
        "preference", "synthetic private benchmark preference"
    )
    identity = create(title="synthetic private benchmark title")["id"]
    service.open_phase(identity, "development")
    baseline = source(
        tasks[0], "baseline", memories=[{"id": memory["id"], "version": memory["version"]}]
    )
    service.register(identity, "D1", "baseline", baseline)
    service.register(identity, "D1", "candidate", source(tasks[0]))
    sealed = service.seal_phase(identity, "development")
    for key in sealed["packet_ids"]:
        packet = service.blind_packet(identity, key)
        service.submit_review(identity, key, review(packet, kind="agent_assisted"))
    invalid = service.invalidate(memory_ids=[memory["id"]])
    assert invalid["invalidated_research_benchmark_ids"] == [identity]
    assert service.invalidate(memory_ids=[memory["id"]])["invalidated_research_benchmark_ids"] == [
        identity
    ]
    with pytest.raises(ProbeError, match="BENCHMARK_DEPENDENCY_FORGOTTEN"):
        service.blind_packet(identity, sealed["packet_ids"][0])
    for table in TABLES:
        assert "synthetic private" not in json.dumps(service._all(table))
        assert "synthetic test actor" not in json.dumps(service._all(table))
    assert service.repository.counts()["jobs"] == 1


def test_full_profile_type_is_explicitly_unsupported_not_base_run_substitution(benchmark):
    _, methods, _, _, create = benchmark
    wrong = deepcopy(methods)
    wrong["candidate"]["output_type"] = "profile"
    with pytest.raises(ValidationError):
        create(methods=wrong)


def test_effective_checkpoint_refresh_note_changes_context_with_same_references(benchmark):
    service, _, tasks, source, create = benchmark
    identity = create()["id"]
    service.open_phase(identity, "development")
    registered = []
    for arm, note in (("baseline", ""), ("candidate", "保留旧资格，只修复明确错误")):
        run = source(tasks[0], arm)
        checkpoint = service.store.load_checkpoint(run)
        payload = json.loads(checkpoint["history"][1]["content"])
        payload["project_context"] = {
            "goal": "合成目标",
            "completion": "保留支持证据",
            "previous_findings": [],
            "refresh_note": note,
        }
        checkpoint["history"][1]["content"] = json.dumps(payload)
        service.store.checkpoint(run, checkpoint)
        registered.append(service.register(identity, "D1", arm, run))
    assert (
        registered[0]["actual_method"]["context_reference_sha256"]
        == registered[1]["actual_method"]["context_reference_sha256"]
    )
    assert (
        registered[0]["actual_method"]["context_sha256"]
        != registered[1]["actual_method"]["context_sha256"]
    )
    assert all(
        row["actual_method"]["context_verifiability"] == "verified_effective_prompt"
        for row in registered
    )
    sealed = service.seal_phase(identity, "development")
    for key in sealed["packet_ids"]:
        service.submit_review(
            identity, key, review(service.blind_packet(identity, key), kind="agent_assisted")
        )
    report = service.close_phase(identity, "development")
    assert report["uncontrolled_context_or_strategy"]
    assert report["strict_single_variable_claim"] is False
    assert report["decision"] == "insufficient"
    raw = json.dumps(service._all(TABLES[1]), ensure_ascii=False)
    assert "保留旧资格" not in raw and "previous_findings" not in raw


def test_missing_effective_prompt_is_reference_only_and_cannot_be_strict_pair(benchmark):
    service, _, tasks, source, create = benchmark
    identity = create()["id"]
    service.open_phase(identity, "development")
    for arm in ("baseline", "candidate"):
        run = source(tasks[0], arm)
        service.store.checkpoint(run, {})
        submission = service.register(identity, "D1", arm, run)
        assert submission["actual_method"]["context_verifiability"] == "reference_only"
        assert submission["actual_method"]["context_sha256"] is None
        assert "context_unverifiable" in submission["contract_issues"]
    sealed = service.seal_phase(identity, "development")
    for key in sealed["packet_ids"]:
        service.submit_review(identity, key, review(service.blind_packet(identity, key)))
    assert service.close_phase(identity, "development")["uncontrolled_context_or_strategy"]


def test_different_humans_still_conflict_after_one_actor_corrects_review(benchmark):
    service, _, tasks, source, create = benchmark
    identity = create()["id"]
    sealed, _ = prepare_round(service, identity, tasks, source)
    target = sealed["packet_ids"][0]
    for key in sealed["packet_ids"]:
        packet = service.blind_packet(identity, key)
        first = review(packet)
        service.submit_review(identity, key, first)
        if key == target:
            altered = deepcopy(first)
            altered["criterion_ratings"][0]["rating"] = "omitted"
            service.submit_review(identity, key, altered)
            other = review(packet, good=True, reviewer="second-independent-synthetic-actor")
            service.submit_review(identity, key, other)
    report = service.close_phase(identity, "holdout")
    assert report["decision"] == "insufficient"
    assert any(arm["review_conflict"] for pair in report["pairs"] for arm in pair["arms"].values())


def test_same_declared_actor_latest_review_counts_once_and_history_is_sealed(benchmark):
    service, _, tasks, source, create = benchmark
    identity = create()["id"]
    sealed, _ = prepare_round(service, identity, tasks, source)
    target = sealed["packet_ids"][0]
    for key in sealed["packet_ids"]:
        packet = service.blind_packet(identity, key)
        current = review(packet, reviewer="ＳＹＮＴＨＥＴＩＣ   Reviewer")
        if key == target:
            initial = deepcopy(current)
            initial["dimensions"]["unknown_handling"]["rating"] = "unknown"
            first = service.submit_review(identity, key, initial)
            current["reviewer"] = "synthetic reviewer"
            corrected = service.submit_review(identity, key, current)
            assert corrected["id"] != first["id"]
            assert service.submit_review(identity, key, current)["id"] == corrected["id"]
        else:
            service.submit_review(identity, key, current)
    report = service.close_phase(identity, "holdout")
    arms = [arm for pair in report["pairs"] for arm in pair["arms"].values()]
    revised = next(arm for arm in arms if arm["review_history_count"] == 2)
    assert revised["effective_review_count"] == revised["independent_human_reviews"] == 1
    assert revised["review_conflict"] is False
    assert revised["business_scores"]["unknown_handling"] == "pass"
    round_record = service._round(identity, "holdout")
    assert len(round_record["review_ids"]) == len(sealed["packet_ids"]) + 1
    with pytest.raises(ProbeError, match="BENCHMARK_BLIND_REVIEW_CLOSED"):
        service.submit_review(identity, target, current)


def test_context_claim_cannot_be_forged_by_caller_or_changed_after_registration(benchmark):
    service, methods, tasks, source, create = benchmark
    locked = deepcopy(methods)
    locked["candidate"]["context_sha256"] = "f" * 64
    identity = create(methods=locked)["id"]
    service.open_phase(identity, "development")
    service.register(identity, "D1", "baseline", source(tasks[0], "baseline"))
    run = source(tasks[0])
    bound = service.register(identity, "D1", "candidate", run)
    assert "method_contract_mismatch:context_sha256" in bound["contract_issues"]
    sealed = service.seal_phase(identity, "development")
    checkpoint = service.store.load_checkpoint(run)
    checkpoint["history"][1]["content"] = json.dumps(
        {
            "project_context": {"refresh_note": "changed after registration"},
            "memory_context": [],
            "question": tasks[0]["question"],
            "fixed_scope": {"jobs": [{"id": tasks[0]["job_ids"][0]}]},
        }
    )
    service.store.checkpoint(run, checkpoint)
    with pytest.raises(ProbeError, match="BENCHMARK_REGISTERED_OUTPUT_CHANGED"):
        for key in sealed["packet_ids"]:
            service.blind_packet(identity, key)


def test_version_label_and_personal_context_alone_are_not_method_improvement(benchmark):
    service, methods, tasks, source, create = benchmark
    methods["candidate"]["method_sha256"] = methods["baseline"]["method_sha256"]
    # Actual outputs have distinct version labels, yet the same executable method SHA.
    identity = create()["id"]
    service.open_phase(identity, "development")
    for arm in ("baseline", "candidate"):
        run = source(tasks[0], arm)
        saved = service.store.load_checkpoint(run)
        payload = json.loads(saved["history"][1]["content"])
        payload["project_context"] = {"refresh_note": arm}
        saved["history"][1]["content"] = json.dumps(payload)
        service.store.checkpoint(run, saved)
        service.register(identity, "D1", arm, run)
    sealed = service.seal_phase(identity, "development")
    for packet in sealed["packet_ids"]:
        service.submit_review(identity, packet, review(service.blind_packet(identity, packet)))
    report = service.close_phase(identity, "development")
    assert report["decision"] == "no_demonstrated_change"
    assert report["method_change_locked"] is False
    assert report["uncontrolled_context_or_strategy"]
