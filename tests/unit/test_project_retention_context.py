"""Synthetic stored findings; reopen and follow up without external model or network calls."""

import asyncio
import json
from copy import deepcopy

from test_dependency_eligibility import dependencies as dependencies
from test_dependency_eligibility import source

from work_observer.config import Settings
from work_observer.research.agent import research
from work_observer.research.projects import ProjectService
from work_observer.research.store import ResearchStore


class ReadTaskModel:
    """Only replays the synthetic task; does not evaluate semantic revisions."""

    async def turn(self, history):
        self.context = json.loads(history[1]["content"])
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name = "read_job"
            args = {"job_id": self.context["fixed_scope"]["jobs"][0]["id"]}
        else:
            receipt = outputs[0]["evidence"][0]
            name = "finish_research"
            args = {
                "claims": [
                    dict(
                        category="task",
                        basis="direct",
                        requirement="unspecified",
                        text="负责 RAG 评估与 Python 开发。",
                        evidence_ids=[receipt.get("citation_key", receipt["id"])],
                    )
                ],
                "gaps": ["个人验收权限仍未知。"],
            }
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(len(history))
        )
        return [call], call


def test_reopened_project_carries_retentions_with_their_earlier_challenge(dependencies):
    repo, store, _, jobs, _ = dependencies
    project = ProjectService(store).create(
        "合成复核接续", "RAG任务与权限", jobs[:1], max_calls=60, max_seconds=1800
    )
    original = source(repo, store, jobs[:1], project_id=project["id"])
    downstream = source(
        repo, store, jobs[:1], project_id=project["id"], continued_from=[original["run_id"]]
    )
    before = deepcopy(store.get(downstream["run_id"]))
    revisions = []
    for decision, reason in [
        ("unresolved", "评估任务与独立验收权应分开核对"),
        ("retain", "重读确认评估任务，保留原判断；不推断个人独立验收权"),
    ]:
        later = source(repo, store, jobs[:1], project_id=project["id"])
        later["cognition_revisions"] = [
            dict(
                previous_run_id=original["run_id"],
                previous_claim_index=0,
                previous_statement=original["claims"][0]["text"],
                decision=decision,
                new_claim_indices=[0],
                new_statements=[later["claims"][0]["text"]],
                evidence_ids=later["claims"][0]["evidence_ids"],
                reason=reason,
                aspects=[
                    dict(
                        previous_excerpt=original["claims"][0]["text"],
                        decision=decision,
                        reason=reason,
                    )
                ],
            )
        ]
        store.save(later["run_id"], result=later)
        revisions.append(later["run_id"])
    reopened = ResearchStore(store.path, store.namespace)
    repo.bind_research_store(reopened)
    try:
        service = ProjectService(reopened)
        current = service.get(project["id"])
        current = service.add(
            current["id"],
            "RAG任务与权限继续核对",
            revision=current["revision"],
            reply_to_step_id=current["steps"][1]["id"],
        )
        context = service.context(current["id"], current["steps"][-1], repo)
        prior = next(
            row for row in context["previous_findings"] if row["run_id"] == downstream["run_id"]
        )
        notices = prior["upstream_revision_notices"]["items"]
        assert [row["run_id"] for row in notices] == revisions
        assert [row["decision"] for row in notices] == ["unresolved", "retain"]
        assert "独立验收权" in notices[-1]["reason"]
        assert reopened.get(downstream["run_id"]) == before
        # Even if only the old descendant fits the next context, both review
        # opinions must reach the model and remain recorded as ancestry.
        context["previous_findings"] = [prior]
        model = ReadTaskModel()
        result = asyncio.run(
            research(
                repo,
                "RAG任务与权限继续核对",
                Settings(),
                job_ids=jobs[:1],
                conversation_context=context,
                project_id=project["id"],
                model=model,
                max_calls=3,
                coverage_mode="question",
            )
        )
        assert result["status"] == "completed", result
        seen = model.context["project_context"]["previous_findings"][0][
            "upstream_revision_notices"
        ]["items"]
        assert [row["run_id"] for row in seen] == revisions
        assert set(result["continued_from"]) == {downstream["run_id"], *revisions}
        reopened.invalidate_runs([revisions[-1]])
        context = service.context(current["id"], current["steps"][-1], repo)
        prior = next(
            row for row in context["previous_findings"] if row["run_id"] == downstream["run_id"]
        )
        assert [row["run_id"] for row in prior["upstream_revision_notices"]["items"]] == revisions[
            :1
        ]
    finally:
        reopened.close()
        repo.bind_research_store(store)
