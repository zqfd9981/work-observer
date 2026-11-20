"""Actual UI handler replay, scoped request and safe diagnostics rendering."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "harness",
    [
        "review_feedback_display.cjs",
        "result_source_context.cjs",
        "claim_correction.cjs",
        "project_export.cjs",
        "project_feedback_display.cjs",
        "research_conversation.cjs",
        "conversation_retry.cjs",
        "research_application.cjs",
        "action_feedback.cjs",
        "research_history.cjs",
        "public_versions.cjs",
        "investigation_proposals.cjs",
        "update_cohort.cjs",
        "domain_lineage.cjs",
        "research_intake.cjs",
    ],
)
def test_review_repair_submit_and_diagnostic_display(harness):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    root = Path(__file__).resolve().parents[2]
    outcome = subprocess.run(
        [
            node,
            str(root / "tests/unit" / harness),
            str(root / "src/work_observer/api/assets/app.js"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
