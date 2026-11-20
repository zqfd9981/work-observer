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


class WorkRelationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: Literal["business", "task", "deliverable", "responsibility", "ability", "tool"]
    source_text: str = Field(min_length=1, max_length=1200)
    target_kind: Literal["business", "task", "deliverable", "responsibility", "ability", "tool"]
    target_text: str = Field(min_length=1, max_length=1200)
    predicate: Literal["supports", "requires", "produces", "contradicts"]
    rationale: str = Field(min_length=1, max_length=1200)
    claim_indices: list[StrictInt] = Field(min_length=1, max_length=24)
    basis: Literal["direct", "synthesis", "inference"]
    transfer_limit: str = Field(min_length=1, max_length=1200)
    source_claim_index: StrictInt | None = None
    target_claim_index: StrictInt | None = None


class ReferencedRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_claim_index: StrictInt = Field(ge=0, le=23)
    target_claim_index: StrictInt = Field(ge=0, le=23)
    predicate: Literal["supports", "requires", "produces", "contradicts"]
    basis: Literal["direct", "synthesis", "inference"]
    rationale: str = Field(min_length=1, max_length=1200)
    transfer_limit: str = Field(min_length=1, max_length=1200)


class RelationComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation_indices: list[StrictInt] = Field(min_length=2, max_length=4)
    common_ground: str = Field(min_length=1, max_length=1200)
    differences: str = Field(min_length=1, max_length=1200)
    transfer_conditions: str = Field(min_length=1, max_length=1200)
    basis: Literal["synthesis", "inference"]
    unknowns: list[str] = Field(min_length=1, max_length=4)


class BoundComparison(RelationComparison):
    claim_indices: list[StrictInt] = Field(min_length=1, max_length=24)


class MapContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1, max_length=80)
    scope_note: str = Field(min_length=1, max_length=2000)
    work_types: list[WorkType] = Field(max_length=8)
    unknowns: list[str] = Field(min_length=1, max_length=12)


class WorkMap(MapContent):
    # Read existing reports without changing their stored representation.
    ability_relations: list[AbilityRelation] = Field(default_factory=list, max_length=12)
    work_relations: list[WorkRelationItem] = Field(default_factory=list, max_length=18)
    comparisons: list[BoundComparison] = Field(default_factory=list, max_length=4)


class ResearchWorkMap(MapContent):
    work_relations: list[ReferencedRelation] = Field(max_length=18)
    comparisons: list[RelationComparison] = Field(default_factory=list, max_length=4)


def checked_map(result):
    """Fail closed on dangling claims; structure validation is not semantic review."""
    if not result.get("work_map"):
        return None
    value = WorkMap.model_validate(result["work_map"])
    claims = result.get("claims", [])
    evidence_ids = {item["id"] for item in result.get("evidence", [])}
    for row in [
        *value.work_types,
        *value.ability_relations,
        *value.work_relations,
        *value.comparisons,
    ]:
        for index in row.claim_indices:
            if index < 0 or index >= len(claims):
                raise ValueError("工作地图引用了不存在的判断")
            refs = claims[index].get("evidence_ids", [])
            if not refs or not set(refs) <= evidence_ids:
                raise ValueError("工作地图判断缺少可回查原文")
    for row in value.work_relations:
        for side in ("source", "target"):
            index = getattr(row, side + "_claim_index")
            if index is not None and (
                not 0 <= index < len(claims)
                or getattr(row, side + "_text") != claims[index]["text"]
                or getattr(row, side + "_kind") != claims[index]["category"]
                or index not in row.claim_indices
            ):
                raise ValueError("关系两端必须保留所引用判断的完整表述与性质")
    for row in value.comparisons:
        refs = set(row.relation_indices)
        if len(refs) < 2 or any(i < 0 or i >= len(value.work_relations) for i in refs):
            raise ValueError("比较必须定位至少两条不同的已有关系")
        expected = {i for key in refs for i in value.work_relations[key].claim_indices}
        if set(row.claim_indices) != expected:
            raise ValueError("比较依据必须覆盖所比较关系的两端判断")
    output = value.model_dump(exclude_none=True)
    for key in ("ability_relations", "work_relations", "comparisons"):
        if key not in result["work_map"]:
            output.pop(key)
    return output


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
    if value.get("ability_relations"):
        lines.extend(["", "## 任务与能力关系（解释仍需核对）", ""])
    for row in value.get("ability_relations", []):
        lines.extend(
            [
                f"- {row['task']} → {row['ability']}：{row['rationale']} {refs(row)}",
                f"  解释性质：{bases[row['basis']]}",
                f"  迁移边界：{row['transfer_limit']}",
            ]
        )
    dimensions = {
        "business": "业务问题",
        "task": "任务",
        "deliverable": "交付物",
        "responsibility": "责任",
        "ability": "能力",
        "tool": "工具",
    }
    predicates = {"supports": "支撑", "requires": "需要", "produces": "产出", "contradicts": "反驳"}
    if value.get("work_relations"):
        lines.extend(["", "## 业务与工作关系（解释仍需核对）", ""])
    for row in value.get("work_relations", []):
        lines.extend(
            [
                f"- {dimensions[row['source_kind']]}：{row['source_text']} → "
                f"{predicates[row['predicate']]} → {dimensions[row['target_kind']]}："
                f"{row['target_text']}",
                f"  解释：{row['rationale']} {refs(row)}",
                f"  解释性质：{bases[row['basis']]}；适用与迁移边界：{row['transfer_limit']}",
            ]
        )
    if value.get("comparisons"):
        lines.extend(
            ["", "## 共用、差异与迁移比较", "", "依据来自所连接关系的两端判断；比较解释仍需核对。"]
        )
    for row in value.get("comparisons", []):
        lines.extend(
            [
                "",
                "比较关系："
                + "；".join(
                    f"{value['work_relations'][i]['source_text']} → "
                    f"{value['work_relations'][i]['target_text']}"
                    for i in row["relation_indices"]
                ),
                f"共用点：{row['common_ground']}",
                f"差异：{row['differences']}",
                f"迁移条件：{row['transfer_conditions']}",
                f"解释性质：{bases[row['basis']]}；依据：{refs(row)}",
                "仍待核实：" + "；".join(row["unknowns"]),
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
            if prior_quality.get("status") == "rejected"
            else None
        )
        lines.extend(
            [
                "",
                f"### {decisions[row['decision']]}旧判断 {row['previous_claim_index'] + 1}",
                f"原运行：`{row['previous_run_id']}`；原步骤状态："
                + states.get(row["previous_review_state"], row["previous_review_state"]),
                *([quality_notice] if quality_notice else []),
                *(
                    [
                        "研究范围或目标已经调整；本次是在新范围内重新核对旧判断，不表示外部工作发生变化。"
                    ]
                    if type(row.get("previous_scope_version")) is int
                    and type(row.get("current_scope_version")) is int
                    and row["previous_scope_version"] != row["current_scope_version"]
                    else []
                ),
                f"旧判断：{row['previous_statement']}",
                *[f"本轮判断：{statement}" for statement in row["new_statements"]],
                f"理由：{row['reason']}",
                row.get("comparison_notice")
                or ("这条历史记录未提供逐项对照，不能仅凭简写确认整条旧判断已保留。"),
                *[
                    f"- {decisions[part['decision']]}：旧内容「{part['previous_excerpt']}」；"
                    + "；".join(f"对应判断：{text}" for text in part.get("new_statements", []))
                    + f"；理由：{part['reason']}；依据："
                    + " ".join(
                        f"[{labels[k]}](#{labels[k].lower()})"
                        for k in part["evidence_ids"]
                        if k in labels
                    )
                    for part in row.get("aspects", [])
                ],
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
