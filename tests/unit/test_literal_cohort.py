"""Same-job literal comparisons use frozen eligibility, terms and source provenance."""

from copy import deepcopy
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_domain_updates import updates as updates

from work_observer.storage.models import JobObservation, JobSnapshot


def test_same_jobs_separate_literal_changes_from_jobs_added_and_removed(updates):
    service, add = updates
    one, removed = add("one", "Python接口"), add("removed", "Python脚本")
    before = service.capture("较早", job_ids=[one, removed], terms=["Python"])
    add("one", "Java接口")
    added = add("added", "Python新资料")
    after = service.capture("较晚", job_ids=[one, added], terms=["Python"])
    original = deepcopy((before, after))
    add("one", "Python再次出现，不能改写早期计数")
    report = service.compare(before["id"], after["id"])
    assert not report["statistics"]["comparable"]
    assert report["statistics"]["before"][0]["literal_jobs"] == 2
    assert report["statistics"]["after"][0]["literal_jobs"] == 1
    common = report["common_cohort"]
    assert common["comparable"] and common["job_ids"] == [one]
    assert common["statistics"] == [
        dict(
            term="Python", before=1, after=0, denominator=1,
            newly_mentioned_job_ids=[], no_longer_mentioned_job_ids=[one],
        )
    ]
    assert common["jobs"][0]["before"]["source"] == before["jobs"][0]["source"]
    assert common["jobs"][0]["after"]["literal_hits"] == []
    assert service._get("domain_update_captures", before["id"]) == original[0]
    assert service._get("domain_update_captures", after["id"]) == original[1]
    assert report["trend_status"] == "insufficient_comparable_time_series"


def test_unknown_scope_and_later_body_completion_do_not_enter_the_common_denominator(updates):
    service, add = updates
    stable = add("stable", city="上海")
    unknown = add("unknown")
    missing = add("missing", city="上海")
    with Session(service.repository.engine) as session, session.begin():
        for row in session.scalars(select(JobObservation).where(JobObservation.job_id == missing)):
            row.kind = "list"
            snapshot = session.get(JobSnapshot, row.snapshot_id)
            snapshot.kind = "list"
            snapshot.payload = {
                key: value for key, value in snapshot.payload.items() if key != "description"
            }
    before = service.capture("尚未补齐", filters={"city": "上海"}, terms=["Python"])
    add("unknown", city="上海")
    add("missing", "Python补全正文", city="上海")
    after = service.capture("已补齐", filters={"city": "上海"}, terms=["Python"])
    report = service.compare(before["id"], after["id"])
    common = report["common_cohort"]
    assert common["job_ids"] == [stable]
    assert common["shared_jobs"] == 3
    assert {row["job_id"] for row in common["excluded"]} == {unknown, missing}
    assert all(row["reasons"] == ["before_not_eligible"] for row in common["excluded"])
    assert common["statistics"][0]["denominator"] == 1
    assert report["statistics"]["after"][0]["denominator"] == 3


def test_old_panels_without_saved_job_hits_stay_unknown_and_are_not_recounted(updates):
    service, add = updates
    job = add("one")
    before = service.capture("旧面板", terms=["Python"])
    legacy = deepcopy(before)
    legacy["id"] = "old_without_hits"
    for row in legacy["jobs"]:
        row.pop("literal_hits")
    service._write("domain_update_captures", legacy)
    after = service.capture("新面板", terms=["Python"])
    add("one", "今天的Java资料不能补算旧面板")
    report = service.compare(legacy["id"], after["id"])
    common = report["common_cohort"]
    assert not common["comparable"] and not common["statistics"]
    assert common["excluded"] == [dict(job_id=job, reasons=["before_hits_unrecorded"])]
    assert service._get("domain_update_captures", legacy["id"]) == legacy
    assert report["statistics"]["before"] == legacy["statistics"]


def test_common_terms_are_compared_without_treating_other_terms_as_zero(updates):
    service, add = updates
    add("one", "Python与Java上下⽂")
    before = service.capture("词项一", terms=["Python", "Go", "上下文"])
    after = service.capture("词项二", terms=["Python", "Java", "上下文"])
    common = service.compare(before["id"], after["id"])["common_cohort"]
    assert common["comparable"]
    assert [row["term"] for row in common["statistics"]] == ["Python", "上下文"]
    assert all(row["before"] == row["after"] == 1 for row in common["statistics"])
    assert common["uncompared_terms"] == dict(before=["Go"], after=["Java"])


def test_body_with_unverifiable_archive_is_excluded_at_the_later_capture(updates):
    service, add = updates
    job = add("one")
    before = service.capture("可核验", terms=["Python"])
    document = before["jobs"][0]["source"]["document_id"]
    from work_observer.storage.models import SourceDocument

    with Session(service.repository.engine) as session:
        path = Path(session.get(SourceDocument, document).path)
    path.write_bytes(b"synthetic corrupt archive")
    after = service.capture("完整性变化", terms=["Python"])
    common = service.compare(before["id"], after["id"])["common_cohort"]
    assert not common["comparable"] and common["denominator"] == 0
    assert common["excluded"] == [dict(job_id=job, reasons=["after_not_eligible"])]
