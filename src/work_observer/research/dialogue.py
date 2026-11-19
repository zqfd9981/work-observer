"""Source-bound revisions in ordinary project answers, without a work-map contract."""

from copy import deepcopy

from pydantic import Field

from work_observer.research.agent import Answer
from work_observer.research.cognition import CognitiveRevision, validate_revisions

VERSION = "standard-dialogue-v2"
POLICY = """
本轮是普通持续研究，不需要工作地图。finish_research的revisions可为空列表。
若与project_context.previous_findings中的旧判断相关，用最少必要记录说明保留、修订、撤回或未解决；
previous_claim_index使用旧derived_claims里的previous_claim_index，不是展示位置；
new_claim_indices使用本轮claims下标，evidence_ids只引用本轮读过的原文。
保留/修订的依据须用于所指的新判断，不能借无关新引用声称改变认识。
同一引用重读用recheck，旧轮未读的片段才可new_evidence；都不等于新发布资料或外部工作变化。
review只用于确有明确复核反馈的修正。不要捏造人审、旧结论原话或反例。
旧判断与新修正都是待核对认识。旧判断有followup_decisions时，先检查后续修正，
不要静默当作仍获支持；后续修正也不自动成为已核实事实，仍须重读当前原文。
无足够证据就记未解决，不强行修改；不额外登记计划或为修正另开调用。
claims.text、gaps和reason用读者可理解的表述，不写previous_claim_index、run_id等内部字段名；
需要提旧判断时用其内容说明，精确编号与运行回链交由revisions字段和程序展示。
"""


class DialogueAnswer(Answer):
    revisions: list[CognitiveRevision] = Field(default_factory=list, max_length=8)


def tools(base):
    result = deepcopy(base)
    schema = DialogueAnswer.model_json_schema()

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
    finish = next(row for row in result if row["name"] == "finish_research")
    finish["parameters"] = schema
    finish["description"] = "提交有原文依据的回答；必要时说明相关旧判断为何保留或改变。"
    return result


def validate(answer, evidence, context, review_feedback=None):
    for revision in answer.revisions:
        if revision.trigger == "review":
            historical = (context or {}).get("historical_reply") or {}
            diagnostic = historical.get("review_diagnostic") or {}
            explicit_rejection = (
                historical.get("run_id") == revision.previous_run_id
                and diagnostic.get("id")
                and diagnostic.get("status") == "rejected"
            )
            if not explicit_rejection and (
                not review_feedback or review_feedback.get("run_id") != revision.previous_run_id
            ):
                raise ValueError("本轮没有该旧判断的明确复核反馈，重读原文应使用recheck")
    checked = validate_revisions(answer, evidence, context)
    for revision in answer.revisions:
        if revision.decision in {"retain", "revise"}:
            sources = set(revision.evidence_ids)
            claims = [answer.claims[i] for i in revision.new_claim_indices]
            bound = {key for claim in claims for key in claim.evidence_ids}
            if not sources <= bound or any(
                not sources.intersection(c.evidence_ids) for c in claims
            ):
                raise ValueError("修正依据必须实际用于所指的新判断，且每条新判断有相应依据")
    return checked
