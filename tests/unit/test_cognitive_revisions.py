"""Revision links must point to selected old claims and newly read source receipts."""

from copy import deepcopy

import pytest

from work_observer.research.cognition import VERSION, CognitionAnswer, validate_revisions


def data():
    answer = {
        "claims": [
            {
                "category": "task",
                "basis": "inference",
                "requirement": "unspecified",
                "text": "合成新判断",
                "evidence_ids": ["e1"],
            }
        ],
        "gaps": [],
        "work_map": {
            "version": VERSION,
            "scope_note": "合成范围",
            "work_types": [],
            "work_relations": [],
            "unknowns": ["待核实"],
        },
        "revisions": [
            {
                "previous_run_id": "a" * 32,
                "previous_claim_index": 4,
                "decision": "revise",
                "trigger": "recheck",
                "new_claim_indices": [0],
                "evidence_ids": ["e1"],
                "reason": "合成重读修订",
            }
        ],
    }
    context = {
        "previous_findings": [
            {
                "run_id": "a" * 32,
                "review_state": "waiting_review",
                "read_evidence_ids": ["e1"],
                "derived_claims": [
                    {"previous_claim_index": 4, "text": "不可由模型覆写的合成旧判断"}
                ],
            }
        ]
    }
    return answer, context


def test_revision_copies_canonical_old_statement_and_preserves_review_state():
    value, context = data()
    before = deepcopy(context)
    result = validate_revisions(CognitionAnswer.model_validate(value), {"e1": {}}, context)
    assert context == before
    assert result[0]["previous_statement"] == "不可由模型覆写的合成旧判断"
    assert result[0]["previous_review_state"] == "waiting_review"
    assert result[0]["new_statements"] == ["合成新判断"]
    assert result[0]["evidence_relation"] == "reread"


@pytest.mark.parametrize(
    "change", ["omitted_old", "new_index", "unknown_source", "duplicate", "new_label"]
)
def test_forged_or_mislabelled_revision_is_rejected(change):
    value, context = data()
    row = value["revisions"][0]
    if change == "omitted_old":
        row["previous_claim_index"] = 0
    elif change == "new_index":
        row["new_claim_indices"] = [1]
    elif change == "unknown_source":
        row["evidence_ids"] = ["missing"]
    elif change == "duplicate":
        value["revisions"].append(deepcopy(row))
    elif change == "new_label":
        row["trigger"] = "new_evidence"
    with pytest.raises(ValueError):
        validate_revisions(CognitionAnswer.model_validate(value), {"e1": {}}, context)


def test_new_evidence_means_new_to_old_read_receipts_not_new_publication():
    value, context = data()
    value["revisions"][0].update(trigger="new_evidence", evidence_ids=["e2"])
    value["claims"][0]["evidence_ids"] = ["e2"]
    result = validate_revisions(
        CognitionAnswer.model_validate(value), {"e1": {}, "e2": {}}, context
    )
    assert result[0]["evidence_relation"] == "new_to_prior_run"
    assert "不是外部需求变化" in result[0]["notice"]


def partial_recheck():
    value, context = data()
    context["previous_findings"][0]["derived_claims"][0]["text"] = (
        "建设内部工具，孵化产品并支持技术尽调。"
    )
    value["claims"][0]["text"] = "这份资料明示建设内部工具。"
    revision = value["revisions"][0]
    revision.update(
        decision="unresolved",
        aspects=[
            dict(
                previous_excerpt="建设内部工具",
                decision="retain",
                new_claim_indices=[0],
                evidence_ids=["e1"],
                reason="本轮原文支持此任务。",
            ),
            dict(
                previous_excerpt="孵化产品并支持技术尽调",
                decision="unresolved",
                new_claim_indices=[],
                evidence_ids=["e1"],
                reason="本轮尚未复查这些任务及其交付细节。",
            ),
        ],
    )
    return value, context


def test_partial_recheck_binds_exact_old_parts_and_keeps_unreviewed_work_explicit():
    value, context = partial_recheck()
    result = validate_revisions(CognitionAnswer.model_validate(value), {"e1": {}}, context)[0]
    assert result["decision"] == "unresolved"
    assert result["aspects"][0]["new_statements"] == [value["claims"][0]["text"]]
    assert result["aspects"][1]["new_statements"] == []
    assert "语义已经验证" in result["comparison_notice"]


@pytest.mark.parametrize(
    "mistake", ["whole_retained", "rewritten_quote", "wrong_link", "wrong_source"]
)
def test_partial_recheck_cannot_hide_unknowns_or_forge_its_mapping(mistake):
    value, context = partial_recheck()
    revision = value["revisions"][0]
    if mistake == "whole_retained":
        revision["decision"] = "retain"
    elif mistake == "rewritten_quote":
        revision["aspects"][0]["previous_excerpt"] = "独立决定投资"
    elif mistake == "wrong_link":
        revision["aspects"][0]["new_claim_indices"] = [1]
    else:
        revision["aspects"][0]["evidence_ids"] = ["e2"]
    with pytest.raises(ValueError):
        validate_revisions(CognitionAnswer.model_validate(value), {"e1": {}, "e2": {}}, context)


def test_legacy_unpartitioned_revision_is_reported_without_rewriting_the_saved_record():
    value, context = data()
    before = deepcopy(value)
    result = validate_revisions(CognitionAnswer.model_validate(value), {"e1": {}}, context)[0]
    assert result["aspects"] == [] and "未提供逐项对照" in result["comparison_notice"]
    assert value == before
