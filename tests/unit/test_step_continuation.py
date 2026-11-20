from copy import deepcopy

import pytest

from work_observer.research.projects import step_continuation


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("ready", None),
        ("calls", "calls_exhausted"),
        ("time", "time_exhausted"),
        ("scope", "scope_changed"),
        ("material", "material_changed"),
        ("missing", "no_checkpoint"),
    ],
)
def test_original_limits_and_unavailable_reasons(case, reason):
    project = {"state": "active", "scope_version": 2}
    step = {"state": "failed", "scope_version": 2}
    run = {"state": "finished", "result": {"status": "failed", "model_calls": 2}}
    checkpoint = {"max_calls": 4, "timeout": 90, "elapsed": 10, "result": {"model_calls": 2}}
    audit = {}
    if case == "calls":
        checkpoint["result"]["model_calls"] = 4
    if case == "time":
        checkpoint["elapsed"] = 90
    if case == "scope":
        step["scope_version"] = 1
    if case == "material":
        audit["stale_memory"] = True
    if case == "missing":
        checkpoint = None
    before = deepcopy((project, step, run, checkpoint, audit))
    result = step_continuation(project, step, run, checkpoint, audit)
    assert result["reason"] == reason and result["available"] is (reason is None)
    if case == "ready":
        assert (result["remaining_calls"], result["remaining_seconds"]) == (2, 80)
    assert (project, step, run, checkpoint, audit) == before


def test_pending_request_time_uses_the_existing_resume_accounting():
    result = step_continuation(
        {"state": "active", "scope_version": 1},
        {"state": "interrupted", "scope_version": 1},
        {"state": "interrupted"},
        {
            "max_calls": 4,
            "timeout": 60,
            "elapsed": 10,
            "result": {"model_calls": 2},
            "pending_since": "2026-11-20T00:00:00+00:00",
        },
        {},
        at="2026-11-20T00:02:00+00:00",
    )
    assert not result["available"] and result["reason"] == "time_exhausted"
