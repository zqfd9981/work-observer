"""Observed false rejections of denying a preference-to-requirement rewrite."""

import asyncio

import pytest
from test_denied_preference_status import DenialModel

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.research import agent, requirements, requirements_v4
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository

OBSERVED = [
    "JD明确写“代码能力强优先”；优先措辞应保留为加分倾向，而非一般必备资格。",
    "“代码能力强优先”明确是优先条件，不能改写成必备资格。",
]


@pytest.mark.parametrize(
    ("text", "markers"),
    [
        *[(text, []) for text in OBSERVED],
        ("代码能力强优先，不能改写成必备；Python必备。", ["必备"]),
        ("代码能力强优先，不能只改写成必备。", ["必备"]),
        ("不是一般必备，但必须具备Python能力。", ["必须具备"]),
        ("代码能力强优先；Python是一般必备资格。", ["必备"]),
    ],
)
def test_denied_rewrite_does_not_hide_actual_required_conditions(text, markers):
    assert requirements.required_markers(text, contextual_negation=True) == markers


@pytest.mark.parametrize("text", OBSERVED)
def test_stated_priority_is_preserved_without_deleting_the_denial(tmp_path, text):
    path = tmp_path / "app.db"
    upgrade(path)
    repo = Repository(path)
    try:
        job = import_jd(repo, RawArchive(tmp_path / "raw"), ManualJD(
            title="合成条件", company="合成公司", data_kind="synthetic",
            description="代码能力强优先；无经验但代码能力可以的可培养。",
        ))["job_id"]
        result = asyncio.run(agent.research(
            repo, "代码能力强的要求性质是什么", Settings(), job_ids=[job],
            coverage_mode="question", model=DenialModel(text, "preferred"),
            max_calls=2, allow_proposals=False,
        ))
        assert result["status"] == "completed" and result["model_calls"] == 2
        assert result["claims"][0]["text"] == text
        assert result["claims"][0]["requirement"] == "preferred"
        assert not any(t.get("validation") for t in result["trace"])
    finally:
        repo.close()


def test_actual_v4_fingerprint_and_false_rejections_are_preserved():
    contract = requirements_v4.guard_contract()
    assert contract == {
        "version": "qualification-guard-v4-denied-preference-status",
        "sha256": "dd12c4a70bc069f6eef4c95b761b72ad4f463b9808bc6b536321c20c9e7ae9d8",
    }
    assert requirements.contract_for(contract["version"]) == contract
    for text in OBSERVED:
        assert requirements_v4.required_markers(text, contextual_negation=True) == ["必备"]
