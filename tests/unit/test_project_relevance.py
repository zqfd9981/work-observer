"""Prior research can be found by content without selecting metadata as knowledge."""

from copy import deepcopy

from work_observer.memory.service import _tokens
from work_observer.research.relevance import finding_score, ranked_claims


def test_question_wording_is_not_required_to_locate_saved_boundaries_and_unknowns():
    result = {
        "claims": [{"text": "维护内部平台", "requirement": "unspecified"}],
        "gaps": ["决策权限待核实"],
        "work_map": {
            "version": "metadata-marker-99",
            "work_types": [
                {
                    "boundary": "不包括外部客户实施",
                    "next_check": "核对审批角色",
                    "claim_indices": [0],
                }
            ],
            "unknowns": ["负载规模尚未说明"],
        },
        "evidence": [{"quote": "raw-only-marker"}],
    }
    original = deepcopy(result)
    for phrase in ("内部平台", "决策权限", "客户实施", "审批角色", "负载规模"):
        assert finding_score(_tokens(phrase), "初次概览", result)
    for metadata in ("metadata-marker-99", "raw-only-marker", "claim_indices", "unspecified"):
        assert not finding_score(_tokens(metadata), "初次概览", result)
    assert result == original


def test_transfer_question_prioritizes_both_comparison_sides_without_rewriting_strength():
    claims = [
        dict(text="无关话题" + str(i), requirement="required") for i in range(8)
    ]
    claims[5] = dict(text="精通平台系统并具备大型项目经验", requirement="required")
    claims[7] = dict(text="内容接口开发经历优先", requirement="preferred")
    result = {
        "claims": claims,
        "work_map": {
            "comparisons": [
                {
                    "transfer_conditions": "迁移前核对个人分工与负载规模",
                    "unknowns": ["上线审批仍未知"],
                    "claim_indices": [5, 7],
                }
            ]
        },
    }
    original = deepcopy(result)
    ranked = ranked_claims(result, _tokens("个人分工与负载规模"))
    assert [index for index, _ in ranked[:2]] == [5, 7]
    assert ranked[0][1]["text"] == claims[5]["text"]
    assert ranked[1][1]["requirement"] == "preferred"
    assert result == original


def test_relevance_uses_existing_same_glyph_matching_on_original_claim_text():
    result = {"claims": [dict(text="⼯具调用与上下⽂管理", requirement="required")]}
    assert finding_score(_tokens("工具调用与上下文"), "概览", result)
    assert ranked_claims(result, _tokens("上下文"))[0][1]["text"] == "⼯具调用与上下⽂管理"
