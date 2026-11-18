"""受限来源分项试验；精确定位和结构检查不等于语义审核通过。"""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from work_observer.connectors.mcp_probe import ProbeError

VERSION = "source-first-v1"
FACETS = {
    "work_task": "岗位建设与工作任务",
    "deliverable": "工作产出",
    "personal_coding_share": "个人编码分工",
    "independent_delivery": "独立端到端负责程度",
    "release_authority": "上线决策与责任",
    "runtime_role": "平台运行中的角色",
    "human_control": "人工控制与接管",
    "qualification": "任职资格与强度",
    "tool_usage": "工具使用",
    "business_context": "岗位业务方向",
}
STATES = {
    "stated": "原文明示（语义待核）",
    "explicitly_denied": "原文明示否定（语义待核）",
    "not_disclosed": "已读归档正文中未披露（判断待核）",
    "unresolved": "尚不能判断，继续核对",
}
POLICY = """
本次明确选用source_first试验方法，仍由同一个研究Agent完成；没有额外的隐形审核调用。
先逐岗阅读原文并使用source_view的精确分句，调用record_source_findings批量登记各维度。
finding只保存分句引用和维度，不另写一套自由事实。分句上下级标题只帮助定位，不是职责分类。
岗位建设任务work_task与个人编码份额personal_coding_share、独立端到端程度independent_delivery、
上线责任release_authority分开；“搭建、实现、改造、集成、维护、自研”任务不能因个人分工未知而删除。
平台运行角色runtime_role与招聘岗位承担的建设任务分开。CEO/Leader/执行Agent不自动等于应聘者。
stated和explicitly_denied必须引用原文分句；否定需要原文明示否定，不能由缺少说明得出。
not_disclosed仅用于完整阅读本次冻结归档正文后核对的指定维度；不等于现实中没有该职责。
未读全、上下文或含义仍不清楚用unresolved；不能用内部语料池的存在冒充已经读到。
保留重要正面动作、协作限定、人工控制边界及资格强度。未知不能替换同维度明示记录。
修正已登记记录须用新id、supersedes和具体理由，历史保留；不得覆盖原记录。
最终每条claim的finding_ids只引用活动的明示/明示否定finding，evidence_ids使用这些finding的原证据。
未知finding单独展示，不能用来支撑“没有开发职责”等肯定的排除性结论；具体待核实事项另列gaps。
一条跨岗比较只比较一个维度，逐侧绑定同维度finding，用basis=synthesis，引用双方原文。
自由综合仍是待核分析，不能覆盖旁边已登记的正面原文动作；绑定检查不证明概括语义正确。
完成前检查每个有正文岗位的work_task、personal_coding_share、independent_delivery、release_authority、
runtime_role、human_control这六个维度。没有披露的分别记录，不把未知合成否定全部职责。
本试验仅使用固定本地JD，公开资料研究继续使用standard方法。所有登记、纠错和回答占原调用预算。
"""

Facet = Literal[
    "work_task",
    "deliverable",
    "personal_coding_share",
    "independent_delivery",
    "release_authority",
    "runtime_role",
    "human_control",
    "qualification",
    "tool_usage",
    "business_context",
]
State = Literal["stated", "explicitly_denied", "not_disclosed", "unresolved"]
REQUIRED_FACETS = {
    "work_task",
    "personal_coding_share",
    "independent_delivery",
    "release_authority",
    "runtime_role",
    "human_control",
}


class SourceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^F[1-9][0-9]{0,2}$")
    job_id: str = Field(min_length=1, max_length=100)
    facet: Facet
    state: State
    sentence_ids: list[str] = Field(max_length=8)
    supersedes: list[str] = Field(max_length=4)
    reason: str = Field(min_length=1, max_length=500)


class FindingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    findings: list[SourceFinding] = Field(min_length=1, max_length=120)


class SourceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    category: Literal["business", "task", "deliverable", "responsibility", "ability", "tool"]
    basis: Literal["direct", "synthesis", "inference"]
    requirement: Literal["required", "preferred", "unspecified"]
    text: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    finding_ids: list[str] = Field(min_length=1, max_length=12)


class SourceAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    claims: list[SourceClaim] = Field(min_length=1, max_length=24)
    gaps: list[str] = Field(max_length=12)


def tools(base):
    selected = deepcopy(base)
    schema = SourceAnswer.model_json_schema()
    selected[-1]["parameters"] = {"type": "object", **schema}
    selected[-1]["description"] += " 每条claim还须绑定已登记的活动finding_ids。"
    schema = FindingsInput.model_json_schema()
    selected.insert(
        -1,
        {
            "type": "function",
            "name": "read_source_window",
            "description": "读取已冻结候选JD从指定字符位置起的最多8个片段；用阅读缺口补齐长正文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "start": {"type": "integer", "minimum": 0},
                },
                "required": ["job_id", "start"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    )
    selected.insert(
        -1,
        {
            "type": "function",
            "name": "record_source_findings",
            "description": "按岗位与职责维度批量登记原文分句；未知与否定分开，保留修订历史。"
            "这只是可审计的来源梳理，不是独立语义审核或方法批准。",
            "parameters": {"type": "object", **schema},
            "strict": True,
        },
    )
    return selected


def sentence_index(views):
    return {
        sentence["sentence_id"]: {
            **sentence,
            "job_id": job["job_id"],
            "snapshot_id": source.get("snapshot_id"),
        }
        for job in views["jobs"]
        for source in job["sources"]
        for sentence in source["sentences"]
    }


def fully_read_jobs(views):
    return {
        job["job_id"]
        for job in views["jobs"]
        if len(job["sources"]) == 1
        and job["sources"][0]["coverage"]["fully_read"]
        and job["sources"][0].get("all_sentences_shown", False)
    }


def register(arguments, views, previous, scope_jobs):
    """只接纳已显示给本轮模型的精确分句；未知不能抹掉已登记明示。"""
    batch = [row.model_dump() for row in FindingsInput.model_validate(arguments).findings]
    sentences = sentence_index(views)
    full = fully_read_jobs(views)
    known = {row["id"]: row for row in previous}
    if len(known) + len(batch) > 160 or len({row["id"] for row in batch}) != len(batch):
        raise ProbeError("SOURCE_FIRST_FINDING_LIMIT_OR_DUPLICATE")
    for row in batch:
        if row["id"] in known or row["job_id"] not in scope_jobs or not row["reason"].strip():
            raise ProbeError("SOURCE_FIRST_FINDING_ID_OR_SCOPE")
        refs = row["sentence_ids"]
        if len(set(refs)) != len(refs) or not set(refs) <= set(sentences):
            raise ProbeError("SOURCE_FIRST_SENTENCE_NOT_READ")
        if any(sentences[key]["job_id"] != row["job_id"] for key in refs):
            raise ProbeError("SOURCE_FIRST_SENTENCE_WRONG_JOB")
        if len({sentences[key]["snapshot_id"] for key in refs}) > 1:
            raise ProbeError("SOURCE_FIRST_MIXED_VERSIONS")
        if row["state"] in {"stated", "explicitly_denied"} and not refs:
            raise ProbeError("SOURCE_FIRST_POSITIVE_OR_DENIAL_NEEDS_SOURCE")
        if row["state"] in {"not_disclosed", "unresolved"} and refs:
            raise ProbeError("SOURCE_FIRST_UNKNOWN_IS_NOT_QUOTED_FACT")
        if row["state"] == "not_disclosed" and row["job_id"] not in full:
            raise ProbeError("SOURCE_FIRST_NOT_DISCLOSED_NEEDS_FULL_READ")
        if len(set(row["supersedes"])) != len(row["supersedes"]):
            raise ProbeError("SOURCE_FIRST_INVALID_REVISION")
        for identity in row["supersedes"]:
            old = known.get(identity)
            if (
                not old
                or not old["active"]
                or (old["job_id"], old["facet"]) != (row["job_id"], row["facet"])
            ):
                raise ProbeError("SOURCE_FIRST_INVALID_REVISION")
            if old["state"] in {"stated", "explicitly_denied"} and row["state"] in {
                "not_disclosed",
                "unresolved",
            }:
                raise ProbeError("SOURCE_FIRST_UNKNOWN_CANNOT_REPLACE_DISCLOSED")
            known[identity] = {**old, "active": False, "superseded_by": row["id"]}
        row.update(
            active=True,
            citations=[sentences[key] for key in refs],
            evidence_ids=list(dict.fromkeys(sentences[key]["evidence_id"] for key in refs)),
        )
        known[row["id"]] = row
    active = [row for row in known.values() if row["active"]]
    for row in active:
        if row["state"] in {"not_disclosed", "unresolved"} and any(
            (other["job_id"], other["facet"]) == (row["job_id"], row["facet"])
            and other["state"] in {"stated", "explicitly_denied"}
            for other in active
        ):
            raise ProbeError("SOURCE_FIRST_UNKNOWN_CONFLICTS_WITH_DISCLOSED")
    return list(known.values())


def check_answer(answer, findings, evidence, required_jobs):
    active = {row["id"]: row for row in findings if row["active"]}
    missing = [
        {"job_id": job, "facet": facet}
        for job in sorted(required_jobs)
        for facet in sorted(REQUIRED_FACETS)
        if not any(row["job_id"] == job and row["facet"] == facet for row in active.values())
    ]
    issues = []
    for index, claim in enumerate(answer.claims):
        linked = [active.get(key) for key in claim.finding_ids]
        if any(row is None for row in linked):
            issues.append({"index": index, "reason": "finding_missing_or_superseded"})
            continue
        if any(row["state"] in {"not_disclosed", "unresolved"} for row in linked):
            issues.append({"index": index, "reason": "unknown_cannot_support_exclusionary_claim"})
            continue
        sources = {key for row in linked for key in row["evidence_ids"]}
        jobs = {row["job_id"] for row in linked}
        if set(claim.evidence_ids) != sources or any(
            evidence.get(key, {}).get("job_id") not in jobs for key in claim.evidence_ids
        ):
            issues.append({"index": index, "reason": "claim_sources_differ_from_findings"})
        if len(jobs) > 1 and (
            claim.basis != "synthesis" or len({row["facet"] for row in linked}) != 1
        ):
            issues.append(
                {"index": index, "reason": "comparison_needs_same_facet_each_side_synthesis"}
            )
    return {
        "missing_source_facets": missing,
        "claim_finding_issues": issues,
        "binding_passed": not missing and not issues,
        "semantic_approval": False,
    }


def review_findings(findings):
    """匿名审核也必须能看完整活动梳理，不能只审核被挑选的自由结论。"""
    return [
        {
            "id": row["id"],
            "job_id": row["job_id"],
            "facet": row["facet"],
            "facet_label": FACETS[row["facet"]],
            "state": row["state"],
            "state_label": STATES[row["state"]],
            "reason": row["reason"],
            "citations": [
                {
                    key: cite.get(key)
                    for key in (
                        "evidence_id",
                        "job_id",
                        "snapshot_id",
                        "start",
                        "end",
                        "text",
                        "context",
                    )
                }
                for cite in row["citations"]
            ],
        }
        for row in findings
        if row["active"]
    ]
