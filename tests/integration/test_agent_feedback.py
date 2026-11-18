"""单Agent候选与固定反馈：隔离模拟，不宣称真实市场改善。"""

import asyncio
import json

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.memory.service import MemoryService
from work_observer.research.agent import research
from work_observer.retrieval.enhanced import DEFAULT_ALIASES
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository
from work_observer.tracking.evaluation import StrategyService


class FeedbackModel:
    def __init__(self, job_id, mode="valid", memory=None):
        self.job_id, self.mode, self.memory = job_id, mode, memory
        self.calls, self.evidence = 0, []

    async def turn(self, history):
        self.calls += 1
        if history[-1].get("type") == "function_call_output":
            self.evidence += json.loads(history[-1]["output"]).get("evidence", [])
        if self.calls == 1:
            name, args = "query_jobs", {}
        elif self.calls == 2:
            name, args = "read_job", {"job_id": self.job_id}
        elif self.calls == 3:
            if self.mode == "memory_changed":
                self.memory.create("preference", "模拟新明确偏好，旧研究应停止")
                name, args = "query_jobs", {}
            else:
                name, args = (
                    "propose_knowledge",
                    {
                        "content": "模拟：来源包含智能体任务",
                        "evidence_ids": [self.evidence[0]["citation_key"]],
                    },
                )
        elif self.calls == 4:
            aliases = DEFAULT_ALIASES if self.mode == "valid" else {"个人私密新词": ["无来源支持"]}
            name, args = (
                "propose_retrieval_strategy",
                {"aliases": [{"term": key, "variants": values} for key, values in aliases.items()]},
            )
        elif self.calls == 5:
            name, args = "evaluate_retrieval_strategy", {}
        else:
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "requirement": "unspecified",
                            "text": "模拟智能体任务",
                            "evidence_ids": [self.evidence[0]["id"]],
                        }
                    ],
                    "gaps": [],
                },
            )
        call = {
            "type": "function_call",
            "call_id": str(self.calls),
            "name": name,
            "arguments": json.dumps(args),
        }
        return [call], call


def run_case(tmp_path, mode, **options):
    upgrade(tmp_path / "isolated.db")
    repo = Repository(tmp_path / "isolated.db")
    text = "【合成资料】职责：智能体开发。" + "、".join(
        term for key, variants in DEFAULT_ALIASES.items() for term in [key, *variants]
    )
    identity = import_jd(
        repo,
        RawArchive(tmp_path / "raw"),
        ManualJD(title="合成", company="合成", description=text, data_kind="synthetic"),
    )["job_id"]
    model = FeedbackModel(identity, mode, MemoryService(repo))
    result = asyncio.run(
        research(
            repo,
            "模拟检索不足复盘并提出待审核候选",
            Settings(),
            job_ids=[identity],
            model=model,
            **options,
        )
    )
    return repo, result


def test_agent_proposes_evaluates_but_cannot_activate(tmp_path):
    repo, result = run_case(tmp_path, "valid")
    try:
        assert result["status"] == "completed" and result["model_calls"] == 6
        assert result["claims"][0]["evidence_ids"][0] == result["evidence"][0]["id"]
        assert result["knowledge_candidates"][0]["status"] == "candidate"
        assert result["strategy_candidate"]["evaluation"]["status"] == "accepted"
        assert StrategyService(repo).active_config()["aliases"] == {}
        assert not MemoryService(repo).recall("模拟智能体", [result["scope"]["jobs"][0]["id"]])
    finally:
        repo.close()


def test_agent_rejects_terms_not_in_sources_and_denies_proposals_when_disabled(tmp_path):
    repo, result = run_case(tmp_path, "unsupported")
    repo.close()
    assert result["stop_reason"] == "STRATEGY_SOURCE_TERMS_REQUIRED"
    assert result["strategy_candidate"] is None
    other = tmp_path / "disabled"
    other.mkdir()
    repo, result = run_case(other, "valid", allow_proposals=False)
    repo.close()
    assert result["stop_reason"] == "RESEARCH_PROPOSAL_LIMIT"


def test_new_explicit_preference_interrupts_old_context(tmp_path):
    repo, result = run_case(tmp_path, "memory_changed")
    repo.close()
    assert result["status"] == "failed"
    assert result["stop_reason"] == "RESEARCH_MEMORY_CHANGED_RESTART"
    assert result["claims"] == []
