"""Expose existing submission checks without accepting the rejected draft."""

import json


def submission_feedback(claims, validation, evidence):
    reasons = []
    indices = validation.get("mixed_requirement_claim_indices", [])
    if indices:
        reasons.append(
            {
                "kind": "requirement",
                "claim_indices": indices,
                "message": "要求性质检查对这些条目提出疑问：请核对必备、加分及否定措辞。"
                "这是程序提示，不是对原文含义的最终判断。",
            }
        )
    for key, kind, message in (
        ("unknown_evidence_ids", "citation", "部分引用无法定位到本轮已读原文。"),
        ("missing_job_ids", "coverage", "本轮要求覆盖的部分岗位尚未得到引用。"),
        ("query_jobs_required", "scope", "提交前尚未完成本轮范围确认。"),
        ("work_map_error", "map", "工作地图与支撑判断的对应未通过检查。"),
        ("revision_error", "revision", "旧判断与本轮修订的对应未通过检查。"),
        ("application_error", "application", "行动建议与背景或原文的对应未通过检查。"),
        ("reader_answer_error", "answer", "回答的组织或对照表仍需调整。"),
    ):
        if validation.get(key):
            reasons.append(
                {
                    "kind": kind,
                    "message": message,
                    **({"detail": validation[key]} if isinstance(validation[key], str) else {}),
                }
            )
    finding_check = validation.get("source_finding_check")
    if isinstance(finding_check, dict) and finding_check.get("binding_passed") is False:
        reasons.append({"kind": "source", "message": "逐条原文与判断的对应未通过检查。"})
    if not reasons:
        reasons.append(
            {"kind": "source", "message": "提交未满足来源与判断类型的检查条件，请回看原文。"}
        )
    aliases = {row.get("citation_key"): row["id"] for row in evidence if row.get("citation_key")}
    drafts = [
        {
            "index": index,
            **{key: row.get(key) for key in ("text", "category", "basis", "requirement")},
            "evidence_ids": [aliases.get(key, key) for key in row.get("evidence_ids", [])],
        }
        for index, row in enumerate(claims)
    ]
    return {
        "reasons": reasons,
        "draft_claims": drafts,
        "notice": "最近一次未通过的提交，仅供定位问题。不是有效回答，"
        "不进入当前认识、知识采纳或后续研究前提。"
        "检查提示可能有误，仍须核对原文；原消耗和剩余额度不因此重置。",
    }


def with_submission_feedback(result, checkpoint):
    """Read retained history of old unfinished runs; never rewrite their result."""
    if not result or result.get("status") not in {"incomplete", "failed"}:
        return result
    if result.get("submission_feedback"):
        return result
    pending = {}
    latest = None
    for row in (checkpoint or {}).get("history", []):
        if row.get("type") == "function_call" and row.get("name") == "finish_research":
            pending[row.get("call_id")] = row
        elif row.get("type") == "function_call_output" and row.get("call_id") in pending:
            try:
                output = json.loads(row["output"])
                arguments = json.loads(pending.pop(row["call_id"])["arguments"])
            except (KeyError, TypeError, ValueError):
                continue
            if isinstance(output, dict) and output.get("error") and isinstance(arguments, dict):
                claims = arguments.get("claims")
                if isinstance(claims, list) and all(
                    isinstance(claim, dict)
                    and isinstance(claim.get("text"), str)
                    and isinstance(claim.get("evidence_ids"), list)
                    and all(isinstance(key, str) for key in claim["evidence_ids"])
                    for claim in claims
                ):
                    latest = submission_feedback(claims, output, result.get("evidence", []))
    return {**result, "submission_feedback": latest} if latest else result
