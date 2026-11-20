import pytest

from work_observer.research import requirements, requirements_v5


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("这些不是两岗位共同必备条件。", []),
        ("均为该岗位的偏好，而非两岗位共同必备条件。", []),
        ("不能把AI Builder的加分项改作两岗通用必备。", []),
        ("不能把AI Builder的加分项变成两岗通用必备。", []),
        ("不是两岗位共同必备，但Python对本岗必备。", ["必备"]),
        ("不能把AI Builder的加分项改作两岗通用必备；Python必备。", ["必备"]),
        ("不能只把Python变成两岗通用必备，Java也必备。", ["必备", "必备"]),
        ("两岗位共同必备Java经验。", ["必备"]),
    ],
)
def test_denied_shared_status_does_not_hide_a_positive_requirement(text, expected):
    assert requirements.required_markers(text, contextual_negation=True) == expected


def test_existing_v5_runs_keep_their_original_guard_and_hash():
    text = "均为该岗位的偏好，而非两岗位共同必备条件。"
    assert requirements_v5.required_markers(text, contextual_negation=True) == ["必备"]
    assert requirements.implementation(requirements.REWRITE_GUARD) is requirements_v5
    assert requirements.contract_for(requirements.REWRITE_GUARD) == requirements_v5.guard_contract()
    assert requirements.guard_contract()["version"] != requirements.REWRITE_GUARD
