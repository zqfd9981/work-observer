import pytest
from pydantic import ValidationError

from work_observer.research.context_experiment import ContextProbeInput, run_context_experiment


def test_context_merge_preserves_conflicts_origins_and_one_sided_records():
    result = run_context_experiment([{
        "name": "重复、冲突与缺失", "edge": [
            {"key": "m1", "value": "相同内容"}, {"key": "m1", "value": "相同内容"},
            {"key": "m2", "value": "端侧内容"}, {"key": "m3", "value": "仅端侧"},
        ], "cloud": [{"key": "m1", "value": "相同内容"}, {"key": "m2", "value": "云侧内容"}],
    }, {"name": "同内容不同编号", "edge": [{"key": "a", "value": "相同内容"}],
        "cloud": [{"key": "b", "value": "相同内容"}]}, {
        "name": "同一端内部冲突", "edge": [{"key": "c", "value": "内容一"},
                                      {"key": "c", "value": "内容二"}], "cloud": [],
    }])
    first, different, internal = result["cases"]
    assert len(first["appended"]) == 6 and len(first["merged"]) == 3
    assert first["folded_copies"] == 2 and first["conflicting_keys"] == ["m2"]
    assert first["one_sided_keys"] == ["m3"]
    assert first["merged"][0]["variants"][0]["origins"] == [
        {"side": "edge", "position": 1}, {"side": "edge", "position": 2},
        {"side": "cloud", "position": 1},
    ]
    assert [row["value"] for row in first["merged"][1]["variants"]] == ["端侧内容", "云侧内容"]
    assert different["folded_copies"] == 0 and len(different["merged"]) == 2
    assert internal["conflicting_keys"] == ["c"] and internal["one_sided_keys"] == ["c"]
    assert internal["merged"][0]["sides"] == ["edge"]
    assert all(row["expected"] == "" and row["observed"] for row in result["comparison_rows"])
    assert "不能据此解释为删除" in result["conditions"]
    assert "云侧内容" in result["artifact_text"] and "同一端内部冲突" in result["artifact_text"]


@pytest.mark.parametrize("cases", [
    [], [{"name": "空", "edge": [], "cloud": []}],
    [{"name": "相同名称", "edge": [{"key": "x", "value": "a"}], "cloud": []}] * 2,
    [{"name": "过多", "edge": [{"key": "x", "value": "a"}] * 9, "cloud": []}],
])
def test_invalid_or_unbounded_context_input_is_rejected(cases):
    with pytest.raises(ValidationError):
        run_context_experiment(cases)


def test_agent_probe_requires_explicit_prediction_and_bounded_complete_input():
    schema = ContextProbeInput.model_json_schema()
    assert set(schema["required"]) == set(schema["properties"])
    values = {"hypothesis": "先检查冲突", "data_kind": "synthetic", "cases": [
        {"name": "样例", "edge": [{"key": "m", "value": "内容"}], "cloud": []},
    ]}
    assert ContextProbeInput.model_validate(values).hypothesis == "先检查冲突"
    with pytest.raises(ValidationError):
        ContextProbeInput.model_validate({**values, "save": True})
    with pytest.raises(ValidationError):
        ContextProbeInput.model_validate({**values, "hypothesis": "   "})
    with pytest.raises(ValidationError):
        ContextProbeInput.model_validate({**values, "cases": [{
            "name": "过长", "edge": [{"key": str(i), "value": "文" * 500} for i in range(8)],
            "cloud": [{"key": "cloud", "value": "超出总量"}],
        }]})
