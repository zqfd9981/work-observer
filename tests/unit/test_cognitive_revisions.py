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
            "ability_relations": [],
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
    result = validate_revisions(
        CognitionAnswer.model_validate(value), {"e1": {}, "e2": {}}, context
    )
    assert result[0]["evidence_relation"] == "new_to_prior_run"
    assert "不是外部需求变化" in result[0]["notice"]
