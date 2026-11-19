"""Explicit, result-bound review diagnostics for a new local research round.

Review text is not source evidence or a user preference. Rejected claims are never
copied into the new round. The source run is retained only as a privacy lineage.
"""

import json
import re

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.quality.service import digest
from work_observer.reports.results import audit_result
from work_observer.retrieval.catalog import Filters

VERSION = "research-method-v7-review-feedback"
POLICY = """
review_feedback 是用户明确选择的旧结果复核诊断，不是新原文、用户偏好或人类批准。
保留 reviewer_kind；Agent意见仍可能错误，须逐条回查。不要沿用旧答案或把诊断中的引文当证据。
按原问题与本轮原文重新调查，特别检查复核指出的遗漏、资格性质、主体和支持子集。
明确交付用户要求的对照、建议和核实问题；未能完成的事项具体写入gaps，不用旁列原文替代回答。
本轮是新运行，项目内仍累计原项目总预算；旧结果、复核和已消耗额度保留，不能修改或重置。
"""


def load_feedback(
    store, repository, run_id, *, question, job_ids, filters=None, review_id=None, project_id=None
):
    from work_observer.quality.reviews import QualityReviewService

    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ProbeError("RESEARCH_FEEDBACK_INVALID_RUN")
    run = store.get(run_id)
    result = (run or {}).get("result") or {}
    if not run or run["state"] != "finished" or result.get("status") != "completed":
        raise ProbeError("RESEARCH_FEEDBACK_UNAVAILABLE")
    if run["input"].get("project_id") or result.get("project_id"):
        from work_observer.research.project_feedback import validate_source

        validate_source(store, run, project_id)
    elif project_id:
        raise ProbeError("RESEARCH_FEEDBACK_PROJECT_MISMATCH")
    original_jobs = sorted(row["id"] for row in result.get("scope", {}).get("jobs", []))
    if (
        not original_jobs
        or sorted(set(job_ids or [])) != original_jobs
        or question.strip() != result.get("question", "").strip()
        or Filters.model_validate(filters or {}).model_dump(mode="json")
        != Filters.model_validate(run["input"].get("filters") or {}).model_dump(mode="json")
        or any(row.get("source") == "public_web" for row in result.get("evidence", []))
    ):
        raise ProbeError("RESEARCH_FEEDBACK_FIXED_LOCAL_SCOPE_REQUIRED")
    audit = audit_result(result, repository)
    if any(
        audit.get(key)
        for key in (
            "stale_memory",
            "stale_knowledge",
            "stale_dependencies",
            "changed_sources",
            "affected_strategy",
        )
    ):
        raise ProbeError("RESEARCH_FEEDBACK_SOURCES_CHANGED")
    reviews = QualityReviewService(store, repository).list_run(run_id)
    latest = next((row for row in reviews if not row["stale_result"]), None)
    if not latest or latest["status"] != "rejected":
        raise ProbeError("RESEARCH_FEEDBACK_REJECTION_REQUIRED")
    if review_id is not None and latest["id"] != review_id:
        raise ProbeError("RESEARCH_FEEDBACK_CHANGED_NEW_RUN_REQUIRED")
    context = {
        "version": "review-diagnostics-v1",
        "run_id": run_id,
        "review_id": latest["id"],
        "result_sha256": digest(result),
        "review_sha256": digest(
            {key: value for key, value in latest.items() if key != "stale_result"}
        ),
        "reviewer_kind": latest["reviewer_kind"],
        "decision": latest["decision"],
        "note": latest["note"][:1000],
        "dimensions": {},
        "claim_issues": [],
        "omitted_claim_reviews": 0,
        "notice": "复核诊断需回查，不是原文事实、用户偏好或人审批准。旧答案未放入上下文。",
    }
    for key, value in latest["dimensions"].items():
        if value["rating"] not in {"pass", "not_applicable"}:
            context["dimensions"][key] = {
                "rating": value["rating"],
                "reason": value["reason"][:300],
            }
    for value in latest["claim_reviews"]:
        if value["support"] == "supported" and value["requirement"] == "correct":
            continue
        selected = {key: value[key] for key in ("index", "support", "requirement")}
        selected["note"] = value["note"][:300]
        context["claim_issues"].append(selected)
        if len(json.dumps(context, ensure_ascii=False)) > 6000:
            context["claim_issues"].pop()
            context["omitted_claim_reviews"] += 1
    while len(json.dumps(context, ensure_ascii=False)) > 6000 and context["claim_issues"]:
        context["claim_issues"].pop()
        context["omitted_claim_reviews"] += 1
    return context


def repair_preview(store, repository, identity):
    """UI preparation only; never starts work or changes the reviewed run."""
    run = store.get(identity)
    result = (run or {}).get("result") or {}
    jobs = [row["id"] for row in result.get("scope", {}).get("jobs", [])]
    filters = (run or {}).get("input", {}).get("filters") or {}
    try:
        context = load_feedback(
            store,
            repository,
            identity,
            question=result.get("question", ""),
            job_ids=jobs,
            filters=filters,
        )
    except (ProbeError, KeyError, TypeError, ValueError) as exc:
        preview = {
            "available": False,
            "reason": getattr(exc, "code", "RESEARCH_FEEDBACK_UNAVAILABLE"),
        }
        project_id = result.get("project_id")
        if (
            preview["reason"] == "RESEARCH_FEEDBACK_USE_PROJECT_BUDGET"
            and isinstance(project_id, str)
            and re.fullmatch(r"[a-f0-9]{32}", project_id)
        ):
            preview["project_id"] = project_id
        return preview
    return {
        "available": True,
        "review_run_id": identity,
        "review_id": context["review_id"],
        "question": result["question"],
        "job_ids": jobs,
        "filters": filters,
        "previous_model_calls": result.get("model_calls", 0),
        "notice": "参考本次复核新建一轮；重读原固定本地岗位。"
        "新预算单独计数，旧答案与额度保留，复核不是事实。",
    }
