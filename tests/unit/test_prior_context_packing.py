"""Whole prior relations retain claim conditions and correction aspects within the context bound."""

import json
from copy import deepcopy

import pytest

from work_observer.memory.service import _tokens
from work_observer.research.projects import _map_context, _prior_claim_context
from work_observer.research.relevance import ranked_claims


@pytest.fixture
def prior_map():
    claims = [
        dict(category="task", text="平台接口开发", requirement="unspecified", evidence_ids=["a"]),
        dict(
            category="ability",
            text="精通分布式系统并具备五年以上经验",
            requirement="required",
            evidence_ids=["a"],
        ),
        dict(category="task", text="内容接口开发", requirement="unspecified", evidence_ids=["b"]),
        dict(
            category="ability",
            text="有大型内容项目经历优先",
            requirement="preferred",
            evidence_ids=["b"],
        ),
    ]
    relations = [
        dict(
            source_kind="task",
            source_text=claims[i]["text"],
            source_claim_index=i,
            target_kind="ability",
            target_text=claims[i + 1]["text"],
            target_claim_index=i + 1,
            predicate="requires",
            rationale="合成任务条件关联",
            transfer_limit="规模与分工仍需核对",
            basis="inference",
            claim_indices=[i, i + 1],
        )
        for i in (0, 2)
    ]
    return dict(
        claims=claims,
        evidence=[dict(id="a"), dict(id="b")],
        work_map=dict(
            version="work-map-v3-work-relations",
            scope_note="只描述两份合成资料",
            work_types=[
                dict(
                    name="平台接口工作",
                    problem="内部交付",
                    tasks="实现接口",
                    deliverables="服务接口",
                    boundary="规模与责任不能外推",
                    next_check="核对上线分工",
                    claim_indices=[0, 1, 1],
                    basis="inference",
                )
            ],
            work_relations=relations,
            comparisons=[
                dict(
                    relation_indices=[0, 1],
                    claim_indices=[0, 1, 2, 3],
                    common_ground="都涉及接口",
                    differences="服务对象不同",
                    transfer_conditions="核对个人分工与规模",
                    basis="inference",
                    unknowns=["实际权限未知"],
                )
            ],
            unknowns=["规模及最终上线分工未知"],
        ),
    )


def test_oversized_comparison_does_not_leave_a_half_added_dependency_or_remove_kept_rows(prior_map):
    result = prior_map
    for field in ("common_ground", "differences", "transfer_conditions"):
        result["work_map"]["comparisons"][0][field] = "限定" * 600
    original = deepcopy(result)
    item = dict(
        derived_claims=[dict(row, previous_claim_index=i) for i, row in enumerate(result["claims"])]
    )
    context = dict(previous_findings=[item], other="x" * 10000)
    assert _map_context(context, item, result, focus=("work_relations", 0))
    kept = deepcopy(item["work_map"])
    assert not _map_context(context, item, result, focus=("comparisons", 0))
    assert item["work_map"] == kept
    assert [row["previous_index"] for row in kept["work_relations"]] == [0]
    assert kept["comparisons"] == [] and kept["omitted"]["comparisons"] == 1
    assert len(json.dumps(context, ensure_ascii=False)) <= 14000
    assert result == original


def test_claims_and_complete_aspects_are_reserved_with_the_relevant_type_without_duplicates(
    prior_map,
):
    result = prior_map
    result["work_map"]["comparisons"] = result["work_map"]["work_relations"] = []
    result["claims"].extend(
        dict(result["claims"][0], text="合成无关条件；" * 140) for _ in range(12)
    )
    original = deepcopy(result)
    decision = dict(
        decision="unresolved",
        reason="职责与权限仍需分别核对",
        aspects=[
            dict(
                previous_excerpt=result["claims"][1]["text"],
                decision="unresolved",
                reason="保留资格强度，未核实其适用团队",
                new_statements=[],
            )
        ],
    )
    item = dict(run_id="source", derived_claims=[], omitted_claims=len(result["claims"]))
    context = dict(previous_findings=[item], other="x" * 6000)
    query = _tokens("规模与责任")
    _prior_claim_context(
        context, item, result, ranked_claims(result, query), {("source", 1): [decision]}, query
    )
    indices = [row["previous_claim_index"] for row in item["derived_claims"]]
    assert len(indices) == len(set(indices)) and {0, 1} <= set(indices)
    ability = next(row for row in item["derived_claims"] if row["previous_claim_index"] == 1)
    assert ability["text"] == result["claims"][1]["text"]
    assert ability["requirement"] == "required"
    assert ability["followup_decisions"] == [decision]
    assert item["work_map"]["work_types"][0]["claim_indices"] == [0, 1, 1]
    assert item["omitted_claims"] == len(result["claims"]) - len(indices) > 0
    assert len(json.dumps(context, ensure_ascii=False)) <= 14000
    assert result == original


def test_a_claim_with_oversized_corrections_is_omitted_whole_instead_of_losing_its_notice(
    prior_map,
):
    result = prior_map
    result["work_map"]["comparisons"] = result["work_map"]["work_relations"] = []
    aspects = [
        dict(
            previous_excerpt=result["claims"][1]["text"],
            decision="unresolved",
            reason="待核理由；" * 150,
            new_statements=["合成后续判断；" * 140],
        )
        for _ in range(9)
    ]
    decision = dict(decision="unresolved", reason="完整保留逐项疑问", aspects=aspects)
    item = dict(run_id="source", derived_claims=[], omitted_claims=len(result["claims"]))
    context = dict(previous_findings=[item])
    query = _tokens("规模与责任")
    _prior_claim_context(
        context, item, result, ranked_claims(result, query), {("source", 1): [decision]}, query
    )
    assert 1 not in {row["previous_claim_index"] for row in item["derived_claims"]}
    assert item["work_map"]["work_types"] == []
    assert item["work_map"]["omitted"]["work_types"] == 1
    assert item["omitted_claims"] == 1
    assert len(json.dumps(context, ensure_ascii=False)) <= 14000
    assert decision["aspects"] == aspects
