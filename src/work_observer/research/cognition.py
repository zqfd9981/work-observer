"""Opt-in cognitive output of the existing single research Agent."""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from work_observer.reports.cognition import ResearchWorkMap, checked_map
from work_observer.research.agent import Answer

VERSION = "work-map-v3-work-relations"
REVISION_POLICY = """
先核对旧判断的主体、适用材料、任务/交付物、责任边界和资格性质，再写本轮回答。
每条revision用aspects逐项对照旧判断中与本题有关的不同内容；previous_excerpt逐字摘取旧判断，
不能由你改写原话。每项单独说明保留、修订、撤回或未解决，连接真正表达该内容的新判断与本轮原文。
新判断只重述了旧判断的一部分时，不能据此声称整条保留；旧判断其他内容须补查，
或用unresolved项明确哪些未复查及原因，整条decision相应使用unresolved或revise。
旧判断已有followup_decisions时，按先旧后新的顺序核对最后一次处理及其逐项内容；
早期的疑问可能已被后续调查处理，不能只复制最早疑问，也不能把最后意见自动当作证实。
例如旧判断同时写了内部工具、产品孵化和技术尽调，新判断只写内部工具：
内部工具可列retain，另外两项若未查应列unresolved，不能把整条标retain。
主体或范围扩大、推断改为直接事实、优先改为必备、支持决策改为拥有决定权，均是实质改动，
不能列retain。没有读到不等于原判断被反驳，withdraw须解释反证或原推理为何不成立。
reason解释这次核对为何这样处理；aspects.reason解释每个具体对应，不以新增引用数量代替理由。
aspects不能遗漏会改变原判断含义的限定；只是话题相关或措辞相近不表示语义等价。
这些逐项解释也是待核对的Agent分析，不代表程序已经判定新旧语义完全一致。
"""
POLICY = (
    """
本轮成果是工作地图与业务/工作关系，仍由你这个研究Agent选择调查和比较，不是按固定分类填表。
finish_research同时提交claims、gaps、work_map和revisions。work_map.version填work-map-v3-work-relations。
先根据业务问题、主要任务和交付物形成可重叠分组，不按职位标题、工具名称或预设五类硬分。
业务场景、技术层级与交付方式可以交叉；任务不足就放unknowns，可令work_types为空。
同一正文含多个方向时，先说明共同范围，再按各方向的任务与交付对象解释；
“可深入专攻之一”不等于每人全部承担，也不能将多个方向重复计为多个独立岗位。
共同任职条件、限定某方向的条件和可选替代分别保留，未披露方向分配就保持未知。
每个分组写问题、任务、交付物、边界/反例与下一步验证。work_relations按本题需要连接business业务问题、
task任务、deliverable交付物、responsibility责任、ability能力、tool工具；两端用source_claim_index、
target_claim_index定位本次claims，程序保留完整原判断及category，不再重复抄写或缩写节点。
写关系方向、
为什么相关以及适用/迁移边界。predicate可为supports支撑、requires需要、produces产出、contradicts反驳；
requires表示本条工作关系的条件，不自动表示招聘必备资格，任职要求强度仍以claims.requirement为准。
不要强行凑齐六维或把工具提及改写为个人能力。分组claim_indices和关系两端都是本次claims零起始下标，必须实际存在。
解释工作时先串联有依据的业务问题、实际任务与交付物，再说明能力/工具如何支持该任务，
责任只描述原文明示的分工；协作或为决策提供依据不能推成独立负责或拥有决定权。
同一岗位既做内部工具、又做产品探索或专业分析时，应保留这些不同任务与交付对象，
不能因共用Agent或某种框架而合并为一种工作。共同技术栈只支持技术联系，不直接证明职责可迁移。
单条关系的rationale/transfer_limit只解释所连接判断；跨关系或跨岗位的共用、差异、迁移比较放comparisons，
每项relation_indices至少选两条不同关系，写common_ground、differences、transfer_conditions和unknowns。
程序从被比较关系汇集全部两端判断和引用，不再另填一套可能漏侧的比较claim_indices；比较仍需语义核对。
能力来自任职要求时，关系说明保留原文强度及其对象，例如“精通分布式设计”不能只写“设计能力”
或换成“较强”。节点由程序保留完整判断，不让地图概括冲淡支撑判断。
跨岗位迁移比较需在comparisons中连接两侧相关关系；整图引用两侧不等于该比较已得到支持。
一侧未明示某项要求不表示实际不需要；证据不足时缩小关系表述，明确迁移仍待核实。
分组basis为synthesis或inference；关系可为direct/synthesis/inference。
按问题取最少必要分组与关系，表述简短，不凑满字段上限。
不要把自己推导的因果关系写成企业明示；工具、经验、能力和责任分开，保留任职要求性质，
学历/年限和培养例外不混成“未说明”；只按问题需要核对，完整画像未做就不能声称全面覆盖。
scope_note写实际样本范围、正文不足及推断限制；unknowns保留混合/待分类/未知和竞争解释。
不从7份正文外推行业分布、固定互斥比例或时间趋势，不编造用户背景、内部动机和组织权力。
地图是你的分析，不是独立来源或人审；所有已知判断仍需本轮已读原文，派生认识不能重复计证据。
公开产品/技术说明只支持相应业务背景或所描述的工作，不证明具体岗位个人责任；用户补充资料保持自述性质。
仅公开网页时，以business背景或tool行为判断为依据，其他工作联系保持归纳或待验证解释，不改成任职职责。
同一来源的归纳不能重复计为多份独立证据；没有原文支持的责任、产出或因果关系留作未知。
有project_context.previous_findings时，针对本次问题检查相关旧判断，按需要用revisions说明
保留、修订、撤回或尚未解决。previous_claim_index使用旧derived_claims.previous_claim_index，
不是该列表位置。new_claim_indices使用本次claims零起始下标，evidence_ids引用本轮已读原文。
trigger=recheck表示重新解释同一材料，new_evidence须有旧轮未读过的引用；counterexample表示
反例检查，review表示明确复核诊断。没有足够依据不强行修订或编造反例，无旧判断可为空列表。
旧判断仍待审核时不能称已被人类确认；excluded_prior_findings只说明旧结果被隔离，不是证据。
理解修订不等于企业或行业变化；重读材料、增加引用与新发布资料分别说明。
"""
    + REVISION_POLICY
)


class RevisionAspect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previous_excerpt: str = Field(min_length=1, max_length=1200)
    decision: Literal["retain", "revise", "withdraw", "unresolved"]
    new_claim_indices: list[StrictInt] = Field(max_length=24)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=800)


class CognitiveRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previous_run_id: str = Field(pattern="^[a-f0-9]{32}$")
    previous_claim_index: StrictInt = Field(ge=0, le=23)
    decision: Literal["retain", "revise", "withdraw", "unresolved"]
    trigger: Literal["recheck", "new_evidence", "counterexample", "review"]
    new_claim_indices: list[StrictInt] = Field(max_length=24)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=1200)
    aspects: list[RevisionAspect] = Field(default_factory=list, min_length=1, max_length=10)


class CognitionAnswer(Answer):
    work_map: ResearchWorkMap
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
    finish["description"] = (
        "提交有原文判断、可重叠工作分组、业务/任务/交付物/责任/能力/工具关系及边界的地图。"
    )
    return result


def validate_map(answer, evidence):
    if answer.work_map.version != VERSION:
        raise ValueError("本轮工作地图版本应为" + VERSION)
    value = answer.work_map.model_dump()
    claims = [claim.model_dump() for claim in answer.claims]
    relations = []
    for item in value["work_relations"]:
        indices = [item["source_claim_index"], item["target_claim_index"]]
        if any(i < 0 or i >= len(claims) for i in indices):
            raise ValueError("关系必须引用本轮实际存在的判断")
        source, target = [claims[i] for i in indices]
        relations.append(
            {
                **item,
                "source_kind": source["category"],
                "source_text": source["text"],
                "target_kind": target["category"],
                "target_text": target["text"],
                "claim_indices": sorted(set(indices)),
            }
        )
    value["work_relations"] = relations
    for item in value["comparisons"]:
        refs = set(item["relation_indices"])
        if len(refs) < 2 or any(i < 0 or i >= len(relations) for i in refs):
            raise ValueError("比较必须定位至少两条不同的已有关系")
        item["claim_indices"] = sorted({i for key in refs for i in relations[key]["claim_indices"]})
    return checked_map(
        {
            "work_map": value,
            "claims": claims,
            "evidence": list(evidence.values()),
        }
    )


def validate_revisions(answer, evidence, context):
    """Bind old statements from selected context, never from model-authored quotations."""
    prior = {row["run_id"]: row for row in (context or {}).get("previous_findings", [])}
    if historical := (context or {}).get("historical_reply"):
        prior[historical["run_id"]] = historical
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
        if revision.decision in {"retain", "revise"}:
            sources = set(revision.evidence_ids)
            claims = [answer.claims[i] for i in revision.new_claim_indices]
            bound = {key for claim in claims for key in claim.evidence_ids}
            if not sources <= bound or any(
                not sources.intersection(claim.evidence_ids) for claim in claims
            ):
                raise ValueError("修正依据必须实际用于所指的新判断，且每条新判断有相应依据")
        newly_read = set(revision.evidence_ids) - set(row.get("read_evidence_ids", []))
        if revision.trigger == "new_evidence" and not newly_read:
            raise ValueError("同一原文的重读不能标为旧轮未读的新证据，请使用recheck")
        aspects = []
        for aspect in revision.aspects:
            if aspect.previous_excerpt not in old["text"]:
                raise ValueError("逐项对照必须逐字摘取所指旧判断，不能改写旧原话")
            if not set(aspect.new_claim_indices) <= set(revision.new_claim_indices):
                raise ValueError("逐项对照只能指向本条修正所列的新判断")
            if not set(aspect.evidence_ids) <= set(revision.evidence_ids):
                raise ValueError("逐项对照只能使用本条修正已列出的本轮依据")
            if aspect.decision in {"retain", "revise"}:
                bound = {
                    key
                    for i in aspect.new_claim_indices
                    for key in answer.claims[i].evidence_ids
                }
                if (
                    not aspect.new_claim_indices
                    or not set(aspect.evidence_ids) <= bound
                    or any(
                        not set(aspect.evidence_ids).intersection(answer.claims[i].evidence_ids)
                        for i in aspect.new_claim_indices
                    )
                ):
                    raise ValueError("逐项保留或修订须连接表达该内容且使用对应依据的新判断")
            if revision.decision == "retain" and aspect.decision != "retain":
                raise ValueError("有修订、撤回或未解决的内容时，不能把整条旧判断标为保留")
            if revision.decision == "withdraw" and aspect.decision in {"retain", "revise"}:
                raise ValueError("仍有保留或修订的内容时，不能把整条旧判断标为撤回")
            aspects.append(
                {
                    **aspect.model_dump(),
                    "new_statements": [answer.claims[i].text for i in aspect.new_claim_indices],
                }
            )
        checked.append(
            {
                **revision.model_dump(),
                "previous_statement": old["text"],
                "previous_review_state": row["review_state"],
                **(
                    {
                        "previous_quality_review": {
                            key: row["review_diagnostic"][key]
                            for key in ("id", "status", "reviewer_kind")
                        }
                    }
                    if row.get("review_diagnostic")
                    else {}
                ),
                "new_statements": [answer.claims[i].text for i in revision.new_claim_indices],
                "aspects": aspects,
                "comparison_notice": (
                    "逐项对应是Agent的解释，仍须核对主体、范围与遗漏，不能视为语义已经验证。"
                    if aspects
                    else (
                        "这条记录未提供逐项对照；新表述可能只覆盖旧判断的一部分，"
                        "不能据此确认整条含义已保留。"
                    )
                ),
                "evidence_relation": "new_to_prior_run" if newly_read else "reread",
                "notice": "认识变化记录；不是外部需求变化或独立人审。",
            }
        )
        previous_scope, current_scope = (
            row.get("source_scope_version"),
            row.get("current_scope_version"),
        )
        if (
            type(previous_scope) is int
            and type(current_scope) is int
            and previous_scope != current_scope
        ):
            checked[-1].update(
                previous_scope_version=previous_scope, current_scope_version=current_scope
            )
    return checked
