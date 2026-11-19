"""Observation panels separate sampling provenance from later opinions and actual source changes."""

import json

from test_dependency_eligibility import dependencies as dependencies
from test_domain_updates import updates as updates
from test_map_revision_notices import make_revision, setup_map

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.memory.lifecycle import forget_personal
from work_observer.reports.domain_updates import DomainUpdateService
from work_observer.retrieval.enhanced import RetrievalService


def test_later_private_opinion_does_not_change_definition_or_get_copied_to_panel(
    dependencies, tmp_path
):
    repo, store, memory, jobs, _ = dependencies
    original, _, _, knowledge = setup_map(dependencies)
    service = DomainUpdateService(store, repo)
    before = service.capture("原知识", job_ids=jobs, terms=["RAG"])
    private = memory.create("preference", "SYNTHETIC_PRIVATE_LATER_OPINION")
    later = make_revision(dependencies, original, memories=[private])
    later["cognition_revisions"][0]["reason"] = "SYNTHETIC_PRIVATE_LATER_OPINION"
    store.save(later["run_id"], result=later)
    assert knowledge.list_relations()[0]["revision_notices"]
    after = service.capture("后续仍未改版", job_ids=jobs, terms=["RAG"])
    report = service.compare(before["id"], after["id"])
    assert not report["method_changes"]["domain_definitions_changed"]
    assert not report["method_changes"]["definition_validity_changed"]
    assert not report["method_changes"]["reviewed_relations_changed"]
    assert not report["method_changes"]["relation_validity_changed"]
    assert report["statistics"]["comparable"] and not report["content_changes"]
    assert all(
        "revision_notices" not in row for row in [*after["definitions"], *after["relations"]]
    )
    assert "SYNTHETIC_PRIVATE_LATER_OPINION" not in json.dumps([before, after, report])
    assert later["run_id"] not in after["source_run_ids"]
    forget_personal(repo, store, private["id"], tmp_path / "reports")
    assert service.report(report["id"])["state"] == "compared"


def test_same_jobs_and_body_with_changed_material_identity_are_not_a_demand_change(dependencies):
    repo, store, _, jobs, archive = dependencies
    service = DomainUpdateService(store, repo)
    before = service.capture("模拟资料范围", job_ids=jobs, terms=["RAG"])
    same_job = import_jd(
        repo,
        archive,
        ManualJD(
            title="合成研究岗位",
            company="合成公司",
            external_id="a",
            description="负责 RAG 评估与 Python 开发。",
            data_kind="user_provided",
        ),
    )["job_id"]
    assert same_job == jobs[0]
    after = service.capture("资料标记改为用户提供", job_ids=jobs, terms=["RAG"])
    report = service.compare(before["id"], after["id"])
    assert before["sample"]["source_composition"] == [
        dict(
            source="manual",
            data_kind="synthetic",
            jobs=2,
            eligible_details=2,
            missing_details=0,
            unknown_scope=0,
            known_published_time=0,
        )
    ]
    assert {(row["data_kind"], row["jobs"]) for row in after["sample"]["source_composition"]} == {
        ("synthetic", 1),
        ("user_provided", 1),
    }
    assert report["content_changes"] == report["metadata_changes"] == []
    assert report["sample_changes"]["source_composition_changed"]
    assert (
        report["sample_changes"]["added_job_ids"]
        == report["sample_changes"]["removed_job_ids"]
        == []
    )
    assert not report["statistics"]["comparable"]
    assert report["statistics"]["before"] == report["statistics"]["after"]


def test_provenance_counts_follow_filter_unknown_and_verified_denominator(updates):
    service, add = updates
    add("matched", city="上海")
    add("unknown")
    add("excluded", city="北京")
    capture = service.capture("明确与未知", filters={"city": "上海"}, terms=["Python"])
    group = capture["sample"]["source_composition"][0]
    assert group["jobs"] == 2 and group["unknown_scope"] == 1
    assert group["eligible_details"] == capture["statistics"][0]["denominator"] == 1
    assert capture["sample"]["scope_total"] == 3


def test_literal_counts_match_retrieval_and_old_matching_is_an_analysis_change(updates):
    service, add = updates
    job_id = add("radicals", "上下⽂溢出与长⽂档问答")
    first = service.capture("同形字比较", terms=["上下文溢出", "长文档问答"])
    actual = RetrievalService(service.repository).stats(
        ["上下文溢出", "长文档问答"], job_ids=[job_id]
    )
    assert [row["literal_jobs"] for row in first["statistics"]] == [1, 1]
    assert [row["literal_jobs"] for row in actual["statistics"]] == [1, 1]
    # Preserve an existing panel's old values and missing rule marker as history.
    legacy = {
        **first,
        "id": "a" * 32,
        "statistics": [{**row, "literal_jobs": 0} for row in first["statistics"]],
    }
    legacy.pop("literal_matching")
    service._write("domain_update_captures", legacy)
    second = service.capture("按统一口径再次冻结", terms=["上下文溢出", "长文档问答"])
    report = service.compare(legacy["id"], second["id"])
    assert report["method_changes"]["literal_matching_changed"]
    assert not report["statistics"]["comparable"] and not report["content_changes"]
    assert report["statistics"]["before"][0]["literal_jobs"] == 0
    assert (
        service._get("domain_update_captures", legacy["id"])["statistics"][0]["literal_jobs"] == 0
    )
