import asyncio

import pytest
from test_requirement_negation import QualificationModel
from test_source_first_research import source_workspace as source_workspace

from work_observer.config import Settings
from work_observer.reports.results import render
from work_observer.research.agent import research


@pytest.mark.parametrize("calls", [3, 4])
def test_rejected_submission_stays_separate_and_resolved_issue_is_removed(source_workspace, calls):
    repo, _, jobs = source_workspace
    result = asyncio.run(
        research(
            repo,
            "合成要求性质核对",
            Settings(),
            job_ids=jobs[:1],
            model=QualificationModel(mixed=True),
            max_calls=calls,
            allow_proposals=False,
        )
    )
    if calls == 3:
        assert result["status"] == "incomplete" and result["claims"] == []
        assert result["submission_feedback"]["reasons"][0]["claim_indices"] == [0]
        assert len(result["submission_feedback"]["draft_claims"]) == 1
        report = render(result)
        assert "最近一次提交为何未通过" in report and "不作为当前认识" in report
        assert "[E1](#e1)" in report
    else:
        assert result["status"] == "completed" and len(result["claims"]) == 2
        assert "submission_feedback" not in result
