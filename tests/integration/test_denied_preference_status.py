"""A saved real failure, replayed without calling a model or changing its record."""

import asyncio
import json
from copy import deepcopy

import pytest
from test_review_feedback_repair import Model
from test_review_feedback_repair import workspace as workspace

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.research import agent, requirements, requirements_v3
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository

QUALIFICATION = "熟练掌握常用中间件及数据存储（MySQL、Redis、Kafka、Milvus/pgvector 向量检索等）"
OBSERVED = [
    f"一般任职要求明确写“{QUALIFICATION}”；因此 Milvus/pgvector 是一般资格要求中的技术项，"
    "不是仅列为加分项。",
    f"一般任职要求明确写“{QUALIFICATION}”；该项是一般任职资格，而非仅作为加分项列出。",
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        *[(text, []) for text in OBSERVED],
        ("Python并非仅列为优先条件，而是一般资格。", []),
        ("该项不是仅列为加分项；开源贡献优先。", ["优先"]),
        ("该项非仅作为优先条件，另一项经验加分。", ["加分"]),
        ("不仅Python经验加分，Java经验也优先。", ["加分", "优先"]),
        ("不是仅讨论学历，Python经验加分。", ["加分"]),
        ("一般资格包括Python；开源贡献加分。", ["加分"]),
    ],
)
def test_only_the_denied_status_is_excluded(text, expected):
    assert requirements.preferred_markers(text) == expected


class DenialModel:
    def __init__(self, text):
        self.text = text

    async def turn(self, history):
        outputs = [
            json.loads(h["output"]) for h in history if h.get("type") == "function_call_output"
        ]
        if not outputs:
            job = json.loads(history[1]["content"])["fixed_scope"]["jobs"][0]["id"]
            name, arguments = "read_job", {"job_id": job}
        else:
            name, arguments = "finish_research", {
                "claims": [{
                    "category": "ability", "basis": "direct", "requirement": "required",
                    "text": self.text,
                    "evidence_ids": [
                        next(o["evidence"][0]["id"] for o in outputs if o.get("evidence"))
                    ],
                }],
                "gaps": [],
            }
        call = dict(
            type="function_call", name=name, arguments=json.dumps(arguments),
            call_id=str(len(history))
        )
        return [call], call


@pytest.mark.parametrize("text", OBSERVED)
def test_observed_answer_keeps_the_requirement_without_spending_a_retry(tmp_path, text):
    path = tmp_path / "app.db"
    upgrade(path)
    repo = Repository(path)
    try:
        job = import_jd(repo, RawArchive(tmp_path / "raw"), ManualJD(
            title="合成资格", company="合成公司", data_kind="synthetic",
            description="任职要求：" + QUALIFICATION + "。加分项：开源贡献。",
        ))["job_id"]
        result = asyncio.run(agent.research(
            repo, "该项是一般资格还是仅加分", Settings(), job_ids=[job],
            coverage_mode="question", model=DenialModel(text), max_calls=2,
            allow_proposals=False,
        ))
        assert result["status"] == "completed" and result["model_calls"] == 2
        assert result["claims"][0]["text"] == text
        assert result["claims"][0]["requirement"] == "required"
        assert not any(row.get("validation") for row in result["trace"])
    finally:
        repo.close()


def test_v3_contract_and_actual_rejection_stay_unchanged():
    contract = requirements_v3.guard_contract()
    assert contract == {
        "version": "qualification-guard-v3-merge-negation",
        "sha256": "cc9a38d6144e1c6d4056ac12555ddd73642efec817235e76287897e673752d8a",
    }
    assert requirements.contract_for(contract["version"]) == contract
    assert all(requirements_v3.preferred_markers(text) == ["加分"] for text in OBSERVED)


def test_interrupted_v3_preserves_checks_and_remaining_budget(workspace):
    repo, store, job, _, original, _, _ = workspace
    contract = requirements_v3.guard_contract()
    params = dict(question=original["question"], job_ids=[job], max_calls=4, timeout=180,
                  allow_public=False, allow_proposals=False, approach="standard",
                  qualification_validation=contract)
    run = store.create(params)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agent._research(
            repo, original["question"], Settings(), job_ids=[job], max_calls=4,
            checkpoint=(store, run["id"]), allow_proposals=False, model=Model(cancel=True),
            _qualification_guard=contract["version"],
        ))
    store.save(run["id"], state="interrupted")
    before = deepcopy(store.load_checkpoint(run["id"]))
    assert before["result"]["model_calls"] == 3
    result = asyncio.run(agent.research(
        repo, original["question"], Settings(), checkpoint=(store, run["id"]), resume=True,
        model=DenialModel(OBSERVED[0]),
    ))
    assert result["status"] == "incomplete" and result["model_calls"] == 4
    assert result["qualification_validation"] == contract
    assert result["research_method_sha256"] == before["result"]["research_method_sha256"]
    assert store.get(run["id"])["input"] == params
    assert store.load_checkpoint(run["id"])["max_calls"] == 4
    assert any(row.get("validation") == "citation_or_coverage_rejected" for row in result["trace"])
