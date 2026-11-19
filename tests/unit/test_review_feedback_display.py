"""Actual UI handler replay, scoped request and safe diagnostics rendering."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("harness", ["review_feedback_display.cjs", "project_feedback_display.cjs"])
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
    )
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
