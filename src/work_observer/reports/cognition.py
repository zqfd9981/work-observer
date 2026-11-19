"""Small, report-local work map. References reuse the report's claims and evidence."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class WorkType(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    problem: str = Field(min_length=1, max_length=1200)
    tasks: str = Field(min_length=1, max_length=1200)
    deliverables: str = Field(min_length=1, max_length=1200)
    claim_indices: list[StrictInt] = Field(min_length=1, max_length=24)
    basis: Literal["synthesis", "inference"] = "inference"
    boundary: str = Field(min_length=1, max_length=1200)
    next_check: str = Field(min_length=1, max_length=1200)


class AbilityRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str = Field(min_length=1, max_length=500)
    ability: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=1200)
    claim_indices: list[StrictInt] = Field(min_length=1, max_length=24)
    basis: Literal["direct", "synthesis", "inference"] = "inference"
    transfer_limit: str = Field(min_length=1, max_length=1200)


class WorkMap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1, max_length=80)
    scope_note: str = Field(min_length=1, max_length=2000)
    work_types: list[WorkType] = Field(max_length=8)
    ability_relations: list[AbilityRelation] = Field(max_length=12)
    unknowns: list[str] = Field(min_length=1, max_length=12)


def checked_map(result):
    """Fail closed on dangling claims; structure validation is not semantic review."""
    if not result.get("work_map"):
        return None
    value = WorkMap.model_validate(result["work_map"])
    claims = result.get("claims", [])
    evidence_ids = {item["id"] for item in result.get("evidence", [])}
    for row in [*value.work_types, *value.ability_relations]:
        for index in row.claim_indices:
            if index < 0 or index >= len(claims):
                raise ValueError("工作地图引用了不存在的判断")
            refs = claims[index].get("evidence_ids", [])
            if not refs or not set(refs) <= evidence_ids:
                raise ValueError("工作地图判断缺少可回查原文")
    return value.model_dump()


def render_map(result, labels):
    value = checked_map(result)
    if value is None:
        return []

    def refs(row):
        ids = dict.fromkeys(
            key for index in row["claim_indices"] for key in result["claims"][index]["evidence_ids"]
        )
        return " ".join(f"[{labels[key]}](#{labels[key].lower()})" for key in ids)

    bases = {"direct": "原文明示", "synthesis": "归纳", "inference": "待验证解释"}
    lines = ["", "## 工作类型地图（可重叠的分析假设）", "", value["scope_note"]]
    for row in value["work_types"]:
        lines.extend(
            [
                "",
                f"### {row['name']}",
                "",
                f"要解决：{row['problem']}",
                f"主要任务：{row['tasks']}",
                f"交付物：{row['deliverables']}",
                f"依据：{refs(row)}",
                f"解释性质：{bases[row['basis']]}",
                f"边界与反例：{row['boundary']}",
                f"下一步验证：{row['next_check']}",
            ]
        )
    lines.extend(["", "## 任务与能力关系（解释仍需核对）", ""])
    for row in value["ability_relations"]:
        lines.extend(
            [
                f"- {row['task']} → {row['ability']}：{row['rationale']} {refs(row)}",
                f"  解释性质：{bases[row['basis']]}",
                f"  迁移边界：{row['transfer_limit']}",
            ]
        )
    lines.extend(["", "## 混合、未知与未分类", "", *[f"- {s}" for s in value["unknowns"]]])
    return lines


def render_revisions(result, labels):
    revisions = result.get("cognition_revisions", [])
    if not revisions:
        return []
    decisions = {"retain": "保留", "revise": "修订", "withdraw": "撤回", "unresolved": "仍待核实"}
    states = {"waiting_review": "待核对", "completed": "项目内已接受（不等于独立质量审核）"}
    lines = ["", "## 认识修正记录", "", "以下是认识变化，不等于外部工作需求变化或人审。"]
    for row in revisions:
        prior_quality = row.get("previous_quality_review") or {}
        quality_notice = (
            "原质量核对未通过（"
            + (
                "人工核对"
                if prior_quality.get("reviewer_kind") == "human"
                else "Agent辅助，非独立人审"
            )
            + "）。"
            if prior_quality.get("status") == "rejected" else None
        )
        lines.extend(
            [
                "",
                f"### {decisions[row['decision']]}旧判断 {row['previous_claim_index'] + 1}",
                f"原运行：`{row['previous_run_id']}`；原步骤状态："
                + states.get(row["previous_review_state"], row["previous_review_state"]),
                *([quality_notice] if quality_notice else []),
                f"旧判断：{row['previous_statement']}",
                *[f"本轮判断：{statement}" for statement in row["new_statements"]],
                f"理由：{row['reason']}",
                "材料关系："
                + (
                    "重读原材料"
                    if row["evidence_relation"] == "reread"
                    else "含旧轮未读的引用；不表示新发布资料"
                ),
                "本轮依据："
                + " ".join(
                    f"[{labels[k]}](#{labels[k].lower()})"
                    for k in row["evidence_ids"]
                    if k in labels
                ),
            ]
        )
    return lines
