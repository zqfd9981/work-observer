from copy import deepcopy

from work_observer.research.projects import upstream_revision_notices


def test_later_correction_flags_existing_descendants_without_rewriting_them():
    original = ({"run_id": "original"}, {"claims": [{"text": "待核实的旧判断"}]})
    direct = ({"run_id": "direct"}, {"continued_from": ["original"]})
    indirect = ({"run_id": "indirect"}, {"continued_from": ["direct"]})
    unrelated = ({"run_id": "unrelated"}, {})
    correction = (
        {"run_id": "correction"},
        {
            "continued_from": ["original"],
            "cognition_revisions": [
                {
                    "previous_run_id": "original",
                    "previous_claim_index": 0,
                    "previous_statement": "待核实的旧判断",
                    "decision": "revise",
                    "reason": "责任边界缺少原文支持",
                }
            ],
        },
    )
    later = ({"run_id": "later"}, {"continued_from": ["indirect", "correction"]})
    findings = [original, direct, indirect, unrelated, correction, later]
    before = deepcopy(findings)
    notices = upstream_revision_notices(findings)
    assert set(notices) == {"direct", "indirect"}
    assert notices["direct"]["items"][0]["run_id"] == "correction"
    assert "不能据此断定本轮每条判断错误" in notices["direct"]["notice"]
    assert findings == before
    full_reason = "每项限定仍需查证；" * 60 + "末句：原协作任务不能证明个人权限。"
    correction[1]["cognition_revisions"][0]["reason"] = full_reason
    assert upstream_revision_notices(findings)["direct"]["items"][0]["reason"] == full_reason
    # A rejected/invalid correction is not in the caller's eligible findings.
    assert not upstream_revision_notices(findings[:4])
    correction[1]["cognition_revisions"][0]["previous_statement"] = "未被原判断定位的内容"
    assert not upstream_revision_notices(findings)


def test_retention_is_not_a_conflict_and_visible_limit_is_explicit():
    findings = [
        ({"run_id": "a"}, {"claims": [{"text": "原判断"}]}),
        ({"run_id": "b"}, {"continued_from": ["a"]}),
    ]
    for index, decision in enumerate(["retain", "revise", "unresolved", "withdraw", "revise"]):
        findings.append(
            (
                {"run_id": f"r{index}"},
                {
                    "cognition_revisions": [
                        {
                            "previous_run_id": "a",
                            "previous_claim_index": 0,
                            "previous_statement": "原判断",
                            "decision": decision,
                            "reason": f"意见{index}",
                        }
                    ]
                },
            )
        )
    notices = upstream_revision_notices(findings)["b"]
    assert [row["run_id"] for row in notices["items"]] == ["r2", "r3", "r4"]
    assert notices["omitted"] == 1
