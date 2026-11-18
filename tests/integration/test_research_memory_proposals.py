"""研究假设和方法候选的真实服务链，模型与材料均为合成隔离替身。"""

import asyncio
import json

import pytest

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.memory.service import MemoryService
from work_observer.research.agent import research
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


class ProposalModel:
    def __init__(self, job_id, kind, forbidden=False):
        self.job_id, self.kind, self.forbidden = job_id, kind, forbidden
        self.called = 0

    async def turn(self, history):
        self.called += 1
        if self.called == 1:
            name, args = "query_jobs", {}
        elif self.called == 2:
            name, args = "read_job", {"job_id": self.job_id}
        elif self.called == 3:
            ev = json.loads(history[-1]["output"])["evidence"][0]
            name, args = (
                "propose_research_memory",
                dict(
                    kind=self.kind,
                    content="Python接口方法合成候选",
                    basis="实际按指定岗位读取，未验证普遍效果",
                    supporting_tool="compare_history" if self.forbidden else "read_job",
                    evidence_ids=[ev["citation_key"]],
                ),
            )
        else:
            ev = next(
                json.loads(h["output"])["evidence"][0]
                for h in history
                if h.get("type") == "function_call_output" and "evidence" in json.loads(h["output"])
            )
            name, args = (
                "finish_research",
                dict(
                    claims=[
                        dict(
                            category="task",
                            basis="direct",
                            requirement="unspecified",
                            text="合成岗位负责Python接口",
                            evidence_ids=[ev["id"]],
                        )
                    ],
                    gaps=[],
                ),
            )
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(self.called)
        )
        return [call], call


@pytest.mark.parametrize("kind", ["hypothesis", "method"])
def test_agent_candidate_requires_review_and_withdrawal_does_not_recreate(tmp_path, kind):
    db = tmp_path / "app.db"
    upgrade(db)
    repo = Repository(db)
    job_id = import_jd(
        repo,
        RawArchive(tmp_path / "raw", []),
        ManualJD(
            title="合成",
            company="合成",
            description="合成职责：Python接口开发",
            data_kind="synthetic",
        ),
    )["job_id"]
    memory = MemoryService(repo)
    result = asyncio.run(
        research(
            repo,
            "Python接口",
            Settings(),
            job_ids=[job_id],
            model=ProposalModel(job_id, kind),
            max_calls=5,
        )
    )
    assert result["status"] == "completed"
    candidate = result["research_memory_candidates"][0]
    assert candidate["kind"] == kind and candidate["status"] == "candidate"
    assert not memory.recall("Python接口", [job_id])
    item = memory.list()[0]
    memory.activate(item["id"])
    assert memory.recall("Python接口", [job_id])[0]["id"] == item["id"]
    memory.withdraw(item["id"])
    duplicate = memory.create(
        kind,
        item["content"],
        source_run_id=result["run_id"],
        evidence=item["evidence"],
        origin="agent",
    )
    assert duplicate["id"] == item["id"] and duplicate["status"] == "withdrawn"
    assert not memory.recall("Python接口", [job_id])
    repo.close()


def test_method_cannot_claim_an_unperformed_tool_action(tmp_path):
    db = tmp_path / "app.db"
    upgrade(db)
    repo = Repository(db)
    job_id = import_jd(
        repo,
        RawArchive(tmp_path / "raw", []),
        ManualJD(
            title="合成",
            company="合成",
            description="合成职责：Python接口开发",
            data_kind="synthetic",
        ),
    )["job_id"]
    result = asyncio.run(
        research(
            repo,
            "Python接口",
            Settings(),
            job_ids=[job_id],
            model=ProposalModel(job_id, "method", forbidden=True),
            max_calls=5,
        )
    )
    assert result["status"] == "failed"
    assert result["stop_reason"] == "INVALID_RESEARCH_MEMORY_PROPOSAL"
    assert MemoryService(repo).list() == []
    repo.close()
