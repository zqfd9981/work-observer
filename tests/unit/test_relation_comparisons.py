"""Bind comparisons to both sides without authoring a second set of citations."""

from copy import deepcopy

import pytest

from work_observer.reports.cognition import checked_map, render_map
from work_observer.research.cognition import VERSION, CognitionAnswer, validate_map


def comparison_answer():
    claims = [
        dict(
            category=category, text=text, basis="direct", requirement="required", evidence_ids=[ev]
        )
        for category, text, ev in [
            ("task", "平台服务开发", "a"),
            ("ability", "精通分布式设计：" + "合成限定条件；" * 80, "a"),
            ("task", "内容发布接口开发", "b"),
            ("ability", "熟悉后端开发", "b"),
        ]
    ]
    return CognitionAnswer.model_validate(
        dict(
            claims=claims,
            gaps=["独立交付尚未核实"],
            revisions=[],
            work_map=dict(
                version=VERSION,
                scope_note="合成双方，不代表真实质量验收",
                work_types=[],
                work_relations=[
                    dict(
                        source_claim_index=i,
                        target_claim_index=i + 1,
                        predicate="requires",
                        basis="inference",
                        rationale="限定于原判断的联系",
                        transfer_limit="个人责任未知",
                    )
                    for i in (0, 2)
                ],
                comparisons=[
                    dict(
                        relation_indices=[0, 1],
                        common_ground="均描述开发工作",
                        differences="要求对象和强度不同",
                        transfer_conditions="需核实系统规模和个人分工",
                        basis="inference",
                        unknowns=["不能据此证明能力可直接迁移"],
                    )
                ],
                unknowns=["两侧执行情况未知"],
            ),
        )
    )


def test_canonical_endpoints_keep_strength_and_comparison_collects_both_sides():
    answer = comparison_answer()
    evidence = {key: dict(id=key) for key in ("a", "b")}
    value = validate_map(answer, evidence)
    assert value["work_relations"][0]["target_text"] == answer.claims[1].text
    assert len(value["work_relations"][0]["target_text"]) > 500
    assert value["comparisons"][0]["claim_indices"] == [0, 1, 2, 3]
    result = dict(
        work_map=value,
        claims=[c.model_dump() for c in answer.claims],
        evidence=list(evidence.values()),
    )
    markdown = "\n".join(render_map(result, dict(a="E1", b="E2")))
    assert "共用、差异与迁移比较" in markdown and "[E1](#e1) [E2](#e2)" in markdown
    for mutation in ("shortened", "one_side"):
        bad = deepcopy(result)
        if mutation == "shortened":
            bad["work_map"]["work_relations"][0]["target_text"] = "分布式设计"
        else:
            bad["work_map"]["comparisons"][0]["claim_indices"] = [2, 3]
        with pytest.raises(ValueError):
            checked_map(bad)


@pytest.mark.parametrize("indices", [[0, 0], [0, 2], [-1, 0]])
def test_comparison_cannot_omit_second_relation_or_reference_missing_one(indices):
    answer = comparison_answer()
    answer.work_map.comparisons[0].relation_indices = indices
    with pytest.raises(ValueError, match="至少两条不同"):
        validate_map(answer, {key: dict(id=key) for key in ("a", "b")})


def test_missing_endpoint_rejected_and_existing_free_text_relations_remain_readable():
    answer = comparison_answer()
    evidence = {key: dict(id=key) for key in ("a", "b")}
    value = validate_map(answer, evidence)
    value.pop("comparisons")
    for row in value["work_relations"]:
        row.pop("source_claim_index")
        row.pop("target_claim_index")
    legacy = dict(
        work_map=value,
        claims=[c.model_dump() for c in answer.claims],
        evidence=list(evidence.values()),
    )
    assert checked_map(legacy) == value
    answer.work_map.work_relations[0].target_claim_index = 20
    with pytest.raises(ValueError, match="实际存在"):
        validate_map(answer, evidence)
