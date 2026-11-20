import json
from copy import deepcopy

from work_observer.research.answer_feedback import submission_feedback, with_submission_feedback


def test_existing_rejected_submission_is_explained_without_becoming_a_claim():
    result = {
        "status": "incomplete",
        "claims": [],
        "evidence": [{"id": "original", "citation_key": "E1"}],
    }
    claims = [
        {"text": "加分而非两岗位共同必备。", "requirement": "preferred", "evidence_ids": ["E1"]}
    ]
    checkpoint = {
        "history": [
            {
                "type": "function_call",
                "name": "finish_research",
                "call_id": "one",
                "arguments": json.dumps({"claims": claims}),
            },
            {
                "type": "function_call_output",
                "call_id": "one",
                "output": json.dumps(
                    {"error": "existing check", "mixed_requirement_claim_indices": [0]}
                ),
            },
        ]
    }
    original = deepcopy((result, checkpoint))
    view = with_submission_feedback(result, checkpoint)
    assert view["claims"] == [] and view["status"] == "incomplete"
    assert view["submission_feedback"]["reasons"][0]["claim_indices"] == [0]
    assert view["submission_feedback"]["draft_claims"][0]["evidence_ids"] == ["original"]
    assert "不是有效回答" in view["submission_feedback"]["notice"]
    assert (result, checkpoint) == original
    result["status"] = "completed"
    assert "submission_feedback" not in with_submission_feedback(result, checkpoint)


def test_use_latest_rejection_and_only_checks_that_actually_failed():
    good = {"binding_passed": True}
    feedback = submission_feedback(
        [], {"mixed_requirement_claim_indices": [2], "source_finding_check": good}, []
    )
    assert [row["kind"] for row in feedback["reasons"]] == ["requirement"]
    feedback = submission_feedback(
        [],
        {"unknown_evidence_ids": ["missing"], "source_finding_check": {"binding_passed": False}},
        [],
    )
    assert [row["kind"] for row in feedback["reasons"]] == ["citation", "source"]
    checkpoint = {
        "history": [{"type": "function_call_output", "call_id": "not-a-finish", "output": "{}"}]
    }
    assert with_submission_feedback({"status": "failed"}, checkpoint) == {"status": "failed"}
