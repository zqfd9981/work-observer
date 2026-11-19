"""Opt-in cognitive output of the existing single research Agent."""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from work_observer.reports.cognition import WorkMap, checked_map
from work_observer.research.agent import Answer

VERSION = "work-map-v2-revisions"
POLICY = """
本轮成果是工作地图与任务/能力关系，仍由你这个研究Agent选择调查和比较，不是按固定分类填表。
finish_research同时提交claims、gaps、work_map和revisions。work_map.version填work-map-v2-revisions。
先根据业务问题、主要任务和交付物形成可重叠分组，不按职位标题、工具名称或预设五类硬分。
业务场景、技术层级与交付方式可以交叉；任务不足就放unknowns，可令work_types为空。
每个分组写问题、任务、交付物、边界/反例与下一步验证；每个能力关系写具体任务、能力、
为什么相关以及迁移条件。关系和分组中的claim_indices是本次claims的零起始下标，必须实际存在，
并选择能支持本条关系全部已知表述的判断；若边界涉及另一岗位，也需选择该岗位判断和原文。
分组basis为synthesis或inference；关系可为direct/synthesis/inference。
按问题取最少必要分组与关系，表述简短，不凑满字段上限。
不要把自己推导的因果关系写成企业明示；工具、经验、能力和责任分开，保留任职要求性质，
学历/年限和培养例外不混成“未说明”；只按问题需要核对，完整画像未做就不能声称全面覆盖。
scope_note写实际样本范围、正文不足及推断限制；unknowns保留混合/待分类/未知和竞争解释。
不从7份正文外推行业分布、固定互斥比例或时间趋势，不编造用户背景、内部动机和组织权力。
地图是你的分析，不是独立来源或人审；所有已知判断仍需本轮已读原文，派生认识不能重复计证据。
有project_context.previous_findings时，针对本次问题检查相关旧判断，按需要用revisions说明
保留、修订、撤回或尚未解决。previous_claim_index使用旧derived_claims.previous_claim_index，
不是该列表位置。new_claim_indices使用本次claims零起始下标，evidence_ids引用本轮已读原文。
trigger=recheck表示重新解释同一材料，new_evidence须有旧轮未读过的引用；counterexample表示
反例检查，review表示明确复核诊断。没有足够依据不强行修订或编造反例，无旧判断可为空列表。
旧判断仍待审核时不能称已被人类确认；excluded_prior_findings只说明旧结果被隔离，不是证据。
理解修订不等于企业或行业变化；重读材料、增加引用与新发布资料分别说明。
"""


class CognitiveRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previous_run_id: str = Field(pattern="^[a-f0-9]{32}$")
    previous_claim_index: StrictInt = Field(ge=0, le=23)
    decision: Literal["retain", "revise", "withdraw", "unresolved"]
    trigger: Literal["recheck", "new_evidence", "counterexample", "review"]
    new_claim_indices: list[StrictInt] = Field(max_length=24)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=1200)


class CognitionAnswer(Answer):
    work_map: WorkMap
    revisions: list[CognitiveRevision] = Field(default_factory=list, max_length=8)


def tools(base):
    """Replace only the finish contract without mutating the standard tool objects."""
    result = deepcopy(base)
    schema = CognitionAnswer.model_json_schema()

    def strict(value):
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object":
                value["required"] = list(value.get("properties", {}))
            for child in value.values():
                strict(child)
        elif isinstance(value, list):
            for child in value:
                strict(child)

    strict(schema)
    finish = next(item for item in result if item["name"] == "finish_research")
    finish["parameters"] = schema
    finish["description"] = "提交有原文判断、可重叠工作分组、任务能力关系、边界与未知的认知地图。"
    return result


def validate_map(answer, evidence):
    if answer.work_map.version != VERSION:
        raise ValueError("本轮工作地图版本应为" + VERSION)
    return checked_map(
        {
            "work_map": answer.work_map.model_dump(),
            "claims": [claim.model_dump() for claim in answer.claims],
            "evidence": list(evidence.values()),
        }
    )


def validate_revisions(answer, evidence, context):
    """Bind old statements from selected context, never from model-authored quotations."""
    prior = {row["run_id"]: row for row in (context or {}).get("previous_findings", [])}
    checked, seen = [], set()
    for revision in answer.revisions:
        row = prior.get(revision.previous_run_id)
        old = next(
            (
                c
                for c in (row or {}).get("derived_claims", [])
                if c["previous_claim_index"] == revision.previous_claim_index
            ),
            None,
        )
        key = (revision.previous_run_id, revision.previous_claim_index)
        if old is None or key in seen:
            raise ValueError("修订必须唯一定位本轮上下文中实际选入的旧判断")
        seen.add(key)
        if any(i < 0 or i >= len(answer.claims) for i in revision.new_claim_indices):
            raise ValueError("修订引用了不存在的新判断")
        if revision.decision in {"retain", "revise"} and not revision.new_claim_indices:
            raise ValueError("保留或修订需要指向本轮有原文支持的判断")
        if not set(revision.evidence_ids) <= set(evidence):
            raise ValueError("修订只能引用本轮已读原文")
        newly_read = set(revision.evidence_ids) - set(row.get("read_evidence_ids", []))
        if revision.trigger == "new_evidence" and not newly_read:
            raise ValueError("同一原文的重读不能标为旧轮未读的新证据，请使用recheck")
        checked.append(
            {
                **revision.model_dump(),
                "previous_statement": old["text"],
                "previous_review_state": row["review_state"],
                "new_statements": [answer.claims[i].text for i in revision.new_claim_indices],
                "evidence_relation": "new_to_prior_run" if newly_read else "reread",
                "notice": "认识变化记录；不是外部需求变化或独立人审。",
            }
        )
    return checked
