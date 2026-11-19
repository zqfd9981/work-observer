"""Source-first contract checks; fixtures are synthetic, not semantic accuracy evidence."""

from copy import deepcopy

import pytest

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.source_first import (
    REQUIRED_FACETS,
    SourceAnswer,
    check_answer,
    register,
)
from work_observer.research.source_views import build_source_views


def view(text="岗位职责：\n搭建系统；个人分工未披露。", job="j1", start=0, full=None):
    evidence = {
        "id": f"s{job}:{start}:{start + len(text)}",
        "job_id": job,
        "snapshot_id": "s" + job,
        "quote": text,
        "start": start,
        "end": start + len(text),
        "full_text_length": full or len(text),
    }
    return evidence, build_source_views([evidence])


def finding(views, identity="F1", state="stated", facet="work_task", job="j1"):
    sentences = views["jobs"][0]["sources"][0]["sentences"]
    return {
        "id": identity,
        "job_id": job,
        "facet": facet,
        "state": state,
        "sentence_ids": [sentences[1]["sentence_id"]]
        if state in {"stated", "explicitly_denied"}
        else [],
        "supersedes": [],
        "reason": "合成来源核对，不能证明真实质量",
    }


def test_positive_work_and_unknown_personal_share_are_preserved_separately():
    _, views = view()
    values = register(
        {
            "findings": [
                finding(views),
                finding(views, "F2", "not_disclosed", "personal_coding_share"),
            ]
        },
        views,
        [],
        {"j1"},
    )
    assert values[0]["citations"][0]["text"] == "搭建系统；"
    assert values[1]["state"] == "not_disclosed" and not values[1]["citations"]


@pytest.mark.parametrize("state", ["not_disclosed", "unresolved"])
def test_unknown_cannot_overwrite_or_coexist_with_disclosed_work(state):
    _, views = view()
    old = register({"findings": [finding(views)]}, views, [], {"j1"})
    new = finding(views, "F2", state)
    for supersedes in ([], ["F1"]):
        new["supersedes"] = supersedes
        with pytest.raises(ProbeError, match="SOURCE_FIRST_UNKNOWN"):
            register({"findings": [new]}, views, old, {"j1"})
        assert old[0]["active"]


def test_partial_source_is_unresolved_and_never_not_disclosed():
    _, views = view(full=300)
    with pytest.raises(ProbeError, match="NEEDS_FULL_READ"):
        register({"findings": [finding(views, state="not_disclosed")]}, views, [], {"j1"})
    assert register({"findings": [finding(views, state="unresolved")]}, views, [], {"j1"})


def test_display_truncation_cannot_claim_complete_inspection():
    evidence, _ = view()
    views = build_source_views([evidence], max_sentences=1)
    assert views["jobs"][0]["sources"][0]["coverage"]["fully_read"]
    with pytest.raises(ProbeError, match="NEEDS_FULL_READ"):
        register({"findings": [finding(views, state="not_disclosed")]}, views, [], {"j1"})


def test_forged_sentence_and_cross_job_cannot_be_laundered():
    _, views = view()
    row = finding(views)
    row["sentence_ids"] = ["invented"]
    with pytest.raises(ProbeError, match="SENTENCE_NOT_READ"):
        register({"findings": [row]}, views, [], {"j1"})
    row = finding(views, job="j2")
    with pytest.raises(ProbeError, match="WRONG_JOB"):
        register({"findings": [row]}, views, [], {"j1", "j2"})


def test_explicit_denial_keeps_the_exact_negative_source_and_revision_history():
    _, views = view("职责：\n只使用现有系统，不负责开发。")
    old = register({"findings": [finding(views)]}, views, [], {"j1"})
    new = finding(views, "F2", "explicitly_denied")
    new["supersedes"] = ["F1"]
    updated = register({"findings": [new]}, views, old, {"j1"})
    assert old[0]["active"] and not updated[0]["active"] and updated[1]["active"]
    assert "不负责开发" in updated[1]["citations"][0]["text"]


def source_answer(evidence_ids, finding_ids, basis="direct"):
    return SourceAnswer.model_validate(
        {
            "claims": [
                {
                    "category": "task",
                    "basis": basis,
                    "requirement": "unspecified",
                    "text": "合成任务比较，语义仍待审核",
                    "evidence_ids": evidence_ids,
                    "finding_ids": finding_ids,
                }
            ],
            "gaps": [],
        }
    )


def test_unknown_finding_cannot_be_used_to_deny_a_positive_responsibility():
    ev, views = view()
    findings = register(
        {"findings": [finding(views, state="not_disclosed", facet="personal_coding_share")]},
        views,
        [],
        {"j1"},
    )
    checked = check_answer(source_answer([ev["id"]], ["F1"]), findings, {ev["id"]: ev}, set())
    assert not checked["binding_passed"]
    assert checked["claim_finding_issues"][0]["reason"] == (
        "unknown_findings_belong_in_unknown_section"
    )
    assert not checked["semantic_approval"]


@pytest.mark.parametrize(
    "basis,facet,ok",
    [
        ("direct", "work_task", False),
        ("inference", "work_task", True),
        ("synthesis", "release_authority", True),
        ("synthesis", "work_task", True),
    ],
)
def test_cross_job_analysis_can_link_multiple_facets_but_cannot_be_direct(basis, facet, ok):
    ev1, _ = view()
    ev2, _ = view(job="j2")
    views = build_source_views([ev1, ev2])
    second = deepcopy(views)
    second["jobs"] = [second["jobs"][1]]
    rows = [finding(views), finding(second, "F2", facet=facet, job="j2")]
    findings = register({"findings": rows}, views, [], {"j1", "j2"})
    checked = check_answer(
        source_answer([ev1["id"], ev2["id"]], ["F1", "F2"], basis),
        findings,
        {ev1["id"]: ev1, ev2["id"]: ev2},
        set(),
    )
    assert checked["binding_passed"] is ok
    assert checked["semantic_approval"] is False
    assert bool(checked["analysis_notes"]) is (facet != "work_task")


def test_finish_keeps_missing_facets_and_inactive_finding_visible_as_errors():
    ev, views = view()
    findings = register({"findings": [finding(views)]}, views, [], {"j1"})
    checked = check_answer(source_answer([ev["id"]], ["F999"]), findings, {ev["id"]: ev}, {"j1"})
    assert {row["facet"] for row in checked["missing_source_facets"]} == REQUIRED_FACETS - {
        "work_task"
    }
    assert checked["claim_finding_issues"][0]["reason"] == "finding_missing_or_superseded"
