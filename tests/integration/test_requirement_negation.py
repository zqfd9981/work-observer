"""真实失败模式的合成回归：解释无加分不能迫使模型删掉合法资格。"""

import asyncio
import json

import pytest

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.research import agent
from work_observer.research.requirements import preferred_markers, required_markers
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Python是无加分措辞的资格要求。", []),
        ("该项没有明确的加分条件，Python属于一般资格。", []),
        ("此项未标为优先；要求具备Python能力。", []),
        ("Python并非加分项，而是明确资格。", []),
        ("不含优先或加分措辞。", []),
        ("优先字样未出现。", []),
        ("负责处理优先级与执行顺序。", []),
        ("Python是无加分措辞的资格；Java项目经验优先。", ["优先"]),
        ("未标为优先，但Rust经验属于加分项。", ["加分"]),
        ("无加分说明，Java经验优先考虑。", ["优先"]),
        ("Python必备；Java经验加分。", ["加分"]),
        ("相关经验有则更好。", ["有则更好"]),
    ],
)
def test_negation_only_applies_to_the_local_preference_cue(text, expected):
    assert preferred_markers(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Java经验优先，不是required。", []),
        ("加分项不应当作必备。", []),
        ("优先条件不是硬性要求。", []),
        ("Python按required记录；Java经验优先。", ["required"]),
        ("Python必备；Java经验加分。", ["必备"]),
    ],
)
def test_preferred_claim_cannot_launder_an_explicit_required_condition(text, expected):
    assert required_markers(text) == expected


class QualificationModel:
    def __init__(self, mixed, reverse=False):
        self.mixed, self.reverse, self.calls, self.feedback = mixed, reverse, 0, None

    async def turn(self, history):
        self.calls += 1
        outputs = [
            json.loads(item["output"])
            for item in history
            if item.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = "query_jobs", {}
        elif not any(row.get("evidence") for row in outputs):
            name, args = "read_job", {"job_id": outputs[0]["jobs"][0]["id"]}
        else:
            evidence = next(row["evidence"][0] for row in outputs if row.get("evidence"))
            self.feedback = next((row for row in outputs if row.get("error")), None)
            claim = dict(
                category="ability",
                basis="direct",
                requirement="required",
                text="该岗要求Python接口开发能力，属于无加分措辞的资格要求。",
                evidence_ids=[evidence["id"]],
            )
            claims = [claim]
            if self.mixed and not self.feedback:
                claim["text"] = "该岗要求Python接口开发，Java经验加分。"
                if self.reverse:
                    claim.update(
                        requirement="preferred", text="Python按required记录，Java经验优先。"
                    )
            elif self.mixed:
                claims.append({**claim, "requirement": "preferred", "text": "Java经验加分。"})
            name, args = "finish_research", {"claims": claims, "gaps": []}
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(self.calls)
        )
        return [call], call


@pytest.mark.parametrize(("mixed", "reverse"), [(False, False), (True, False), (True, True)])
def test_research_keeps_the_required_claim_and_only_repairs_actual_mixing(tmp_path, mixed, reverse):
    path = tmp_path / "app.db"
    upgrade(path)
    repo = Repository(path)
    try:
        job = import_jd(
            repo,
            RawArchive(tmp_path / "raw"),
            ManualJD(
                title="合成资格回归",
                company="合成公司",
                data_kind="synthetic",
                description="岗位要求：具备Python接口开发能力；Java项目经验加分。",
            ),
        )["job_id"]
        model = QualificationModel(mixed, reverse)
        result = asyncio.run(
            agent.research(
                repo, "核对要求性质", Settings(), job_ids=[job], model=model, max_calls=4
            )
        )
        assert result["status"] == "completed"
        assert result["claims"][0]["requirement"] == "required"
        assert "Python" in result["claims"][0]["text"]
        assert model.calls == (4 if mixed else 3)
        if mixed:
            assert model.feedback["mixed_requirement_claim_indices"] == [0]
            assert model.feedback["mixed_requirement_markers"] == [
                {"index": 0, "markers": ["required" if reverse else "加分"]}
            ]
            assert result["claims"][1]["requirement"] == "preferred"
        else:
            assert not model.feedback
    finally:
        repo.close()


def test_method_version_is_part_of_the_actual_cache_fingerprint(monkeypatch):
    before = agent.method_fingerprint()
    monkeypatch.setattr(agent, "RESEARCH_METHOD_VERSION", "synthetic-other-guard-version")
    assert agent.method_fingerprint() != before
