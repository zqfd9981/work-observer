"""Explicit review repair within the existing project reservation and step graph."""

import re
from uuid import uuid4

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError


def validate_source(store, run, project_id):
    from work_observer.research.projects import ProjectService

    if not project_id:
        raise ProbeError("RESEARCH_FEEDBACK_USE_PROJECT_BUDGET")
    if any(
        value != project_id
        for value in (run["input"].get("project_id"), run["result"].get("project_id"))
    ):
        raise ProbeError("RESEARCH_FEEDBACK_PROJECT_MISMATCH")
    service = ProjectService(store)
    project = service.get(project_id)
    service._editable(project)
    source = next((s for s in project["steps"] if s.get("run_id") == run["id"]), None)
    if not source or source["scope_version"] != project["scope_version"]:
        raise ProbeError("STEP_SCOPE_CHANGED_REPLAN")
    return project, source


def validate_execution(store, run_id, parameters):
    """A project_id alone cannot authorize a new budget outside a claimed step."""
    from work_observer.research.projects import ProjectService

    project_id = parameters.get("project_id")
    if not project_id:
        raise ProbeError("RESEARCH_FEEDBACK_USE_PROJECT_BUDGET")
    service = ProjectService(store)
    project = service.get(project_id)
    service._editable(project)
    step = next((s for s in project["steps"] if s.get("run_id") == run_id), None)
    if not step or step["state"] != "running" or step["scope_version"] != project["scope_version"]:
        raise ProbeError("RESEARCH_FEEDBACK_PROJECT_CLAIM_REQUIRED")
    keys = (
        "question",
        "job_ids",
        "public_document_ids",
        "offline",
        "max_calls",
        "timeout",
        "allow_public",
        "review_run_id",
        "review_id",
    )
    if any(step.get(key) != parameters.get(key) for key in keys) or not step.get("review_id"):
        raise ProbeError("RESEARCH_FEEDBACK_PROJECT_CLAIM_REQUIRED")
    source = next((s for s in project["steps"] if s["id"] == step.get("replaces_step_id")), None)
    origin = next(
        (s for s in project["steps"] if s["id"] == step.get("review_source_step_id")), None
    )
    if (
        not source
        or source.get("replacement_step_id") != step["id"]
        or not origin
        or origin.get("run_id") != step["review_run_id"]
    ):
        raise ProbeError("RESEARCH_FEEDBACK_PROJECT_CLAIM_REQUIRED")
    if source["id"] != origin["id"] and source.get("review_run_id") != step["review_run_id"]:
        raise ProbeError("RESEARCH_FEEDBACK_PROJECT_CLAIM_REQUIRED")
    used = service.usage(project)
    if (
        used["reserved_calls"] > project["budget"]["max_calls"]
        or used["reserved_seconds"] > project["budget"]["max_seconds"]
        or used["public"] > project["budget"]["max_public"]
    ):
        raise ProbeError("PROJECT_REPAIR_BUDGET_EXHAUSTED")


def repair_reviewed(
    service,
    identity,
    step_id,
    repository,
    *,
    revision,
    review_id,
    note,
    offline=True,
    max_calls=8,
    timeout=180,
):
    from work_observer.quality.feedback import load_feedback
    from work_observer.research.projects import step_reservation

    if (
        not isinstance(review_id, str)
        or not re.fullmatch(r"[a-f0-9]{32}", review_id)
        or not isinstance(note, str)
        or not note.strip()
        or len(note) > 1000
        or type(offline) is not bool
        or type(max_calls) is not int
        or not 1 <= max_calls <= 12
        or type(timeout) is not int
        or not 1 <= timeout <= 300
    ):
        raise ProbeError("INVALID_STEP_REPAIR")
    with service.store.lock, service.store.db:
        project = service.get(identity)
        service._editable(project)
        source = next((s for s in project["steps"] if s["id"] == step_id), None)
        if not source:
            raise ProbeError("STEP_NOT_FOUND")
        if source["scope_version"] != project["scope_version"]:
            raise ProbeError("STEP_SCOPE_CHANGED_REPLAN")
        if source.get("replacement_step_id"):
            replacement = next(
                s for s in project["steps"] if s["id"] == source["replacement_step_id"]
            )
            if (
                replacement.get("review_id"),
                replacement.get("repair_note"),
                replacement["offline"],
                replacement["max_calls"],
                replacement["timeout"],
            ) == (review_id, note.strip(), offline, max_calls, timeout):
                return project
            raise ProbeError("STEP_ALREADY_REFRESHED")
        service._editable(project, revision)
        if any(s["state"] == "running" for s in project["steps"]):
            raise ProbeError("PROJECT_RUNNING")
        if source["state"] not in {
            "waiting_review",
            "waiting_material",
            "completed",
            "failed",
            "queued",
            "interrupted",
        }:
            raise ProbeError("STEP_NOT_REVIEWABLE")
        origin = _review_source(service, project, source)
        if (
            origin["id"] != source["id"]
            and source["state"] != "failed"
            and source.get("review_id") == review_id
            and (source["state"] in {"queued", "interrupted"} or source["offline"] and offline)
        ):
            raise ProbeError("STEP_REPAIR_ALREADY_PLANNED")
        feedback = load_feedback(
            service.store,
            repository,
            origin["run_id"],
            question=source["question"],
            job_ids=source["job_ids"],
            review_id=review_id,
            project_id=identity,
        )
        if len(project["steps"]) >= project["budget"]["max_rounds"]:
            raise ProbeError("PROJECT_ROUND_LIMIT")
        reservation = step_reservation(
            dict(offline=offline, max_calls=max_calls, timeout=timeout, allow_public=False)
        )
        used = service.usage(project)
        if (
            used["reserved_calls"] + reservation["calls"] > project["budget"]["max_calls"]
            or used["reserved_seconds"] + reservation["seconds"] > project["budget"]["max_seconds"]
        ):
            raise ProbeError("PROJECT_REPAIR_BUDGET_EXHAUSTED")
        step = {
            **source,
            "id": uuid4().hex,
            "key": "review-repair:" + feedback["review_id"],
            "origin": "user",
            "state": "queued",
            "run_id": None,
            "offline": offline,
            "allow_public": False,
            "max_calls": max_calls,
            "timeout": timeout,
            "created_at": now(),
            "stop_reason": None,
            "replaces_step_id": source["id"],
            "review_source_step_id": origin["id"],
            "review_run_id": origin["run_id"],
            "review_id": feedback["review_id"],
            "repair_note": note.strip(),
        }
        for key in (
            "started_at",
            "finished_at",
            "review",
            "replacement_step_id",
            "refresh_note",
            "refresh_material_signature",
            "legacy_material_basis",
        ):
            step.pop(key, None)
        source.update(state="superseded", replacement_step_id=step["id"])
        project["steps"].append(step)
        project["turns"].append(
            dict(
                id=step["id"],
                role="user",
                text=note.strip(),
                scope_version=project["scope_version"],
                created_at=now(),
            )
        )
        return service._write(project)


def _review_source(service, project, step):
    run = service.store.get(step["run_id"]) if step.get("run_id") else {}
    if (run.get("result") or {}).get("status") == "completed":
        return step
    if step.get("review_run_id"):
        origin = next(
            (s for s in project["steps"] if s.get("run_id") == step["review_run_id"]), None
        )
        if origin:
            return origin
    raise ProbeError("STEP_NOT_REVIEWABLE")


def repair_preview(service, project, step, repository):
    from work_observer.quality.feedback import load_feedback

    if step.get("replacement_step_id") or step["state"] not in {
        "waiting_review",
        "waiting_material",
        "completed",
        "failed",
        "queued",
        "interrupted",
    }:
        return {"available": False}
    try:
        origin = _review_source(service, project, step)
        feedback = load_feedback(
            service.store,
            repository,
            origin["run_id"],
            question=step["question"],
            job_ids=step["job_ids"],
            project_id=project["id"],
        )
        if (
            origin["id"] != step["id"]
            and step["state"] != "failed"
            and step.get("review_id") == feedback["review_id"]
            and step["state"] in {"queued", "interrupted"}
        ):
            return {"available": False}
    except (ProbeError, ValueError, TypeError, KeyError) as exc:
        return {"available": False, "reason": getattr(exc, "code", "RESEARCH_FEEDBACK_UNAVAILABLE")}
    used = service.usage(project)
    return dict(
        available=True,
        review_id=feedback["review_id"],
        reviewer_kind=feedback["reviewer_kind"],
        offline_preview_done=origin["id"] != step["id"] and step["offline"],
        remaining_calls=max(0, project["budget"]["max_calls"] - used["reserved_calls"]),
        remaining_seconds=max(0, project["budget"]["max_seconds"] - used["reserved_seconds"]),
    )
