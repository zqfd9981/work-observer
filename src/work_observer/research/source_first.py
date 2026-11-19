"""受限来源分项试验；精确定位和结构检查不等于语义审核通过。"""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from work_observer.connectors.mcp_probe import ProbeError

VERSION = "source-first-v9"
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
    "task_independence": "特定任务的独立能力",
    "team_collaboration": "团队及跨团队协作",
    "execution_safety": "系统执行与隔离安全",
}
ACTORS = {
    "job_holder": "岗位任职者",
    "human_operator": "人工操作者",
    "team": "团队",
    "system": "系统",
    "agent": "智能体",
    "unspecified": "主体未明确",
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
独立排查链路等特定任务能力用task_independence，不等于端到端独立交付independent_delivery。
团队需求对齐用team_collaboration，不等于人工审批或接管human_control；沙箱隔离用execution_safety，
不证明人工审批/接管human_control或生产发布权限release_authority。
actor只按原文主体登记，不把Agent执行改为岗位本人执行。
保留完整角色原话及作用对象，不用统一的“独立/负责”抹平范围。改正误类可以用新ID搬到正确维度，
须明确supersedes和理由并保留原记录的全部原文分句；主体登记错误也可按此合同直接纠正，
不必绕行其他维度。新旧都必须是已知记录，同岗位、来源身份不变，不能直接擦成未知。
搬完再核对原维度是否未披露。
最终每条自由claim只声明bindings，每项为finding_id和明确选用的sentence_ids。
只绑定活动的明示/明示否定finding，程序据选中分句及标题上下文导出实际引用，不要求引用无关分句。
同一unit跨原文片段时必须选全已显示部分且完整已读；不截去条件、否定或“优先”再概括。
可将本次回答明确引用的活动not_disclosed/unresolved的ID列在unknown_finding_ids，作为独立未知事项。
未列入该字段的未知仍保留在完整分项记录中，不代表已经回答或没有缺口。
未知finding单独展示，不能用来支撑“没有开发职责”等肯定的排除性结论；具体待核实事项另列gaps。
跨岗自由判断逐侧绑定实际使用的原文finding，用basis=synthesis或inference，不能标direct。
可解释业务、任务、责任、能力与工具的多维关系；不同维度只作多维分析，不表示同口径单维可比。
相同facet也不自动证明对象、范围或强度可比；多维归纳、因果解释与比较均仍须语义核对。
自由综合仍是待核分析，不能覆盖旁边已登记的正面原文动作；绑定检查不证明概括语义正确。
完成前检查每个有正文岗位的work_task、personal_coding_share、independent_delivery、release_authority、
runtime_role、human_control这六个维度。没有披露的分别记录，不把未知合成否定全部职责。
本试验仅使用固定本地JD，公开资料研究继续使用standard方法。所有登记、纠错和回答占原调用预算。
source_view是已读evidence的紧凑分句索引：来源身份按每条evidence_id回查，原文和完整性标记不变。
引用选项和可用工具随实际阅读与登记更新；只有已保存的已知分项才能用于自由判断，选项合法仍非语义通过。
登记六维不等于回答问题。完成前回看原问题的每项交付要求；招聘方核实问题、例外和案例准备等
若被要求须明确回答，具体问句或资料缺口可写gaps，不因未知分项已登记就省略。
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
    "task_independence",
    "team_collaboration",
    "execution_safety",
]
State = Literal["stated", "explicitly_denied", "not_disclosed", "unresolved"]
Actor = Literal["job_holder", "human_operator", "team", "system", "agent", "unspecified"]
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
    actor: Actor = "unspecified"
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
    bindings: list["ClaimBinding"] = Field(default_factory=list, max_length=12)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    finding_ids: list[str] = Field(default_factory=list, max_length=12)
    sentence_citations: list[dict] = Field(default_factory=list, max_length=96)


class ClaimBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    finding_id: str = Field(pattern=r"^F[1-9][0-9]{0,2}$")
    sentence_ids: list[str] = Field(min_length=1, max_length=8)


class SourceAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    claims: list[SourceClaim] = Field(min_length=1, max_length=24)
    gaps: list[str] = Field(max_length=12)
    unknown_finding_ids: list[str] = Field(default_factory=list, max_length=160)


def _strict_schema(schema):
    """Program defaults support old fixtures; actual strict tools require every exposed field."""
    if isinstance(schema, dict):
        schema.pop("default", None)
        if schema.get("type") == "object":
            schema["required"] = list(schema.get("properties", {}))
            schema["additionalProperties"] = False
        for value in schema.values():
            _strict_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            _strict_schema(value)
    return schema


def tools(base, *, scope_jobs=None, views=None, findings=None):
    selected = deepcopy(base)
    schema = SourceAnswer.model_json_schema()
    claim_schema = schema["$defs"]["SourceClaim"]
    for internal in ("evidence_ids", "finding_ids", "sentence_citations"):
        claim_schema["properties"].pop(internal)
    schema = _strict_schema(schema)
    selected[-1]["parameters"] = {"type": "object", **schema}
    selected[-1]["description"] = (
        "提交原问题要求的完整回答，不能用来源分项旁列代替资格分级、案例建议或招聘方核实问题等明确交付。"
        "未能完成的交付须在gaps具体说明。每条模型分析用bindings明确选择活动已知finding的完整已读分句；"
        "未知ID单列unknown_finding_ids。跨岗用synthesis或inference，多维关系仍需语义核对。"
        "程序派生引用，不能自动证明语义正确，也不会改写判断文字。"
    )
    schema = _strict_schema(FindingsInput.model_json_schema())
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
    if scope_jobs:
        # An exact enum constrains provider output; the engine still independently
        # enforces the fixed scope. Never fuzzy-match or repair a mistyped ID.
        allowed = sorted(set(scope_jobs))
        for definition in selected:
            if definition["name"] in {"read_job", "read_source_window"}:
                definition["parameters"]["properties"]["job_id"]["enum"] = allowed.copy()
            elif definition["name"] == "record_source_findings":
                definition["parameters"]["$defs"]["SourceFinding"]["properties"]["job_id"][
                    "enum"
                ] = allowed.copy()
    if views is not None and findings is not None:
        # Choices come from actual read receipts and accepted records only. The
        # engine still validates job, version, exact text and units. Availability
        # and enum membership do not establish semantic support.
        read_ids = sorted(sentence_index(views))
        active = {row["id"]: row for row in findings if row["active"]}
        known = {key: row for key, row in active.items() if row["state"] not in _UNKNOWN}
        unknown = sorted(set(active) - set(known))
        selected = [
            definition
            for definition in selected
            if not (
                (definition["name"] == "record_source_findings" and not read_ids)
                or (definition["name"] == "finish_research" and not known)
            )
        ]
        for definition in selected:
            schema = definition["parameters"]
            if definition["name"] == "record_source_findings":
                fields = schema["$defs"]["SourceFinding"]["properties"]
                fields["sentence_ids"]["items"]["enum"] = read_ids
                if active:
                    fields["supersedes"]["items"]["enum"] = sorted(active)
                else:
                    fields["supersedes"]["maxItems"] = 0
            elif definition["name"] == "finish_research":
                binding = schema["$defs"]["ClaimBinding"]["properties"]
                binding["finding_id"]["enum"] = sorted(known)
                binding["sentence_ids"]["items"]["enum"] = sorted(
                    {identity for row in known.values() for identity in row["sentence_ids"]}
                )
                unknown_field = schema["properties"]["unknown_finding_ids"]
                if unknown:
                    unknown_field["items"]["enum"] = unknown
                else:
                    unknown_field["maxItems"] = 0
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
    known = {row["id"]: deepcopy(row) for row in previous}
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
            if not old or not old["active"] or old["job_id"] != row["job_id"]:
                raise ProbeError("SOURCE_FIRST_INVALID_REVISION")
            if old["state"] in {"stated", "explicitly_denied"} and row["state"] in {
                "not_disclosed",
                "unresolved",
            }:
                raise ProbeError("SOURCE_FIRST_UNKNOWN_CANNOT_REPLACE_DISCLOSED")
            classification_changed = (
                old["facet"] != row["facet"] or old.get("actor", "unspecified") != row["actor"]
            )
            if classification_changed and not (
                old["state"] in {"stated", "explicitly_denied"}
                and row["state"] in {"stated", "explicitly_denied"}
                and set(old["sentence_ids"]) <= set(refs)
                and all(
                    any(
                        current["sentence_id"] == original["sentence_id"]
                        and all(
                            current.get(key) == original.get(key)
                            for key in (
                                "job_id",
                                "snapshot_id",
                                "start",
                                "end",
                                "text",
                                "document_id",
                                "document_sha256",
                                "content_sha256",
                            )
                        )
                        for current in (sentences[key] for key in refs)
                    )
                    for original in old["citations"]
                )
            ):
                raise ProbeError("SOURCE_FIRST_RECLASSIFICATION_MUST_PRESERVE_SOURCE")
            known[identity] = {**old, "active": False, "superseded_by": row["id"]}
        row.update(
            active=True,
            citations=[deepcopy(sentences[key]) for key in refs],
            evidence_ids=list(dict.fromkeys(sentences[key]["evidence_id"] for key in refs)),
        )
        if refs:
            row["source_quote_check"] = source_quote_check(row["citations"])
        known[row["id"]] = row
    active = [row for row in known.values() if row["active"]]
    for row in active:
        if row["state"] in {"not_disclosed", "unresolved"} and any(
            (other["job_id"], other["facet"], other.get("actor", "unspecified"))
            == (row["job_id"], row["facet"], row.get("actor", "unspecified"))
            and other["state"] in {"stated", "explicitly_denied"}
            for other in active
        ):
            raise ProbeError("SOURCE_FIRST_UNKNOWN_CONFLICTS_WITH_DISCLOSED")
    return list(known.values())


_SOURCE_IDENTITY = ("job_id", "snapshot_id", "document_id", "document_sha256", "content_sha256")
_UNKNOWN = {"not_disclosed", "unresolved"}


def _span_evidence(span, citation, evidence):
    """Verify exact text and context against actually read, identical-source ranges."""
    primary = evidence.get(span.get("evidence_id"))
    if primary is None:
        return [], "sentence_evidence_not_read"
    for key in _SOURCE_IDENTITY:
        expected = citation.get(key)
        if span.get(key) is not None and span[key] != expected:
            return [], "sentence_source_identity_mismatch"
        if expected is not None and primary.get(key) != expected:
            return [], "sentence_source_identity_mismatch"
        if key in {"document_sha256", "content_sha256"} and expected is None and primary.get(key):
            return [], "sentence_source_hash_unverifiable"
    start, end, text = span.get("start"), span.get("end"), span.get("text")
    if not (
        type(start) is int
        and type(end) is int
        and 0 <= start < end
        and isinstance(text, str)
        and len(text) == end - start
    ):
        return [], "sentence_range_or_text_invalid"
    actual, used = {}, []
    for key, row in sorted(evidence.items(), key=lambda pair: (pair[1].get("start", -1), pair[0])):
        if any(row.get(field) != primary.get(field) for field in _SOURCE_IDENTITY):
            continue
        left, right, quote = row.get("start"), row.get("end"), row.get("quote")
        if not (
            type(left) is int
            and type(right) is int
            and isinstance(quote, str)
            and 0 <= left < right
            and len(quote) == right - left
        ):
            continue
        overlap_start, overlap_end = max(start, left), min(end, right)
        if overlap_start >= overlap_end:
            continue
        used.append(key)
        for position in range(overlap_start, overlap_end):
            character = quote[position - left]
            if position in actual and actual[position] != character:
                return [], "read_evidence_text_conflict"
            actual[position] = character
    if len(actual) != end - start:
        return [], "sentence_or_context_not_fully_covered"
    if "".join(actual[position] for position in range(start, end)) != text:
        return [], "sentence_text_differs_from_read_evidence"
    return used, None


def _unit_issues(selected, all_citations, *, legacy=False):
    issues = []
    for citation in selected:
        unit = citation.get("unit_id")
        if not unit:
            if not legacy or any(
                citation.get(key)
                for key in (
                    "read_boundary_start",
                    "read_boundary_end",
                    "evidence_boundary_start",
                    "evidence_boundary_end",
                )
            ):
                issues.append("sentence_unit_unverifiable")
            continue
        if not citation.get("unit_complete_read") or not citation.get("unit_all_parts_shown"):
            issues.append("sentence_unit_not_completely_read_or_shown")
            continue
        start, end = citation.get("unit_start"), citation.get("unit_end")
        if not (type(start) is int and type(end) is int and 0 <= start < end):
            issues.append("sentence_unit_invalid_range")
            continue
        pieces = [row for row in selected if row.get("unit_id") == unit]
        expected = {row["sentence_id"] for row in all_citations if row.get("unit_id") == unit}
        if not expected <= {row["sentence_id"] for row in pieces}:
            issues.append("sentence_unit_requires_all_parts")
            continue
        cursor = start
        for row in sorted(pieces, key=lambda row: (row["start"], row["end"])):
            if (
                row.get("unit_start") != start
                or row.get("unit_end") != end
                or row["start"] > cursor
            ):
                break
            cursor = max(cursor, row["end"])
        if cursor != end:
            issues.append("sentence_unit_requires_all_parts")
    return list(dict.fromkeys(issues))


def source_quote_check(citations):
    """Check only the positions of cited units, not truth, support or qualification strength."""
    if not citations or any(not row.get("unit_id") for row in citations):
        return {
            "status": "unverified",
            "issues": ["unit_metadata_missing"],
            "semantic_approval": False,
        }
    issues = []
    for row in citations:
        if row.get("unit_complete_read") is not True or row.get("unit_all_parts_shown") is not True:
            issues.append("sentence_unit_not_completely_read_or_shown")
            continue
        start, end = row.get("unit_start"), row.get("unit_end")
        if not (type(start) is int and type(end) is int and 0 <= start < end):
            issues.append("sentence_unit_invalid_range")
            continue
        parts = [part for part in citations if part["unit_id"] == row["unit_id"]]
        if any(
            not (
                type(part.get("start")) is int
                and type(part.get("end")) is int
                and 0 <= part["start"] < part["end"]
            )
            for part in parts
        ):
            issues.append("sentence_unit_invalid_range")
            continue
        cursor = start
        for part in sorted(parts, key=lambda part: (part["start"], part["end"])):
            if (
                part.get("unit_start") != start
                or part.get("unit_end") != end
                or part["start"] > cursor
            ):
                cursor = -1
                break
            cursor = max(cursor, part["end"])
        if cursor != end:
            issues.append("sentence_unit_requires_all_parts")
    return {
        "status": "incomplete" if issues else "covered",
        "issues": list(dict.fromkeys(issues)),
        "semantic_approval": False,
    }


def unit_repair_options(answer, findings, evidence, issues):
    """Describe literal missing unit pieces; never repair a finding or a claim.

    A full read unit may span multiple Catalog evidence chunks. Selecting more
    pieces in a claim cannot add pieces absent from the registered finding.
    Only offer exact current units whose registered anchors still match the
    original source identity, text and offsets. No fuzzy lookup or fresh read.
    """
    from work_observer.research.source_views import build_source_views

    unit_problems = [row for row in issues if row.get("reason", "").startswith("sentence_unit_")]
    if not unit_problems:
        return None
    current = sentence_index(build_source_views(list(evidence.values())))
    active = {row["id"]: row for row in findings if row["active"]}
    repairs, seen = [], set()
    for problem in unit_problems:
        index, identity = problem.get("index"), problem.get("finding_id")
        row = active.get(identity)
        if not row or type(index) is not int or not 0 <= index < len(answer.claims):
            continue
        claim = answer.claims[index]
        selected = (
            [
                ref
                for binding in claim.bindings
                if binding.finding_id == identity
                for ref in binding.sentence_ids
            ]
            if claim.bindings
            else row["sentence_ids"]
        )
        for citation in row["citations"]:
            unit = citation.get("unit_id")
            if citation["sentence_id"] not in selected or (index, identity, unit) in seen:
                continue
            seen.add((index, identity, unit))
            anchors = [part for part in row["citations"] if part.get("unit_id") == unit]
            if not _unit_issues(
                [part for part in anchors if part["sentence_id"] in selected],
                anchors,
                legacy=not claim.bindings,
            ):
                continue
            parts = [part for part in current.values() if unit and part.get("unit_id") == unit]
            matched = all(
                any(
                    part["sentence_id"] == anchor["sentence_id"]
                    and all(
                        part.get(key) == anchor.get(key)
                        for key in (*_SOURCE_IDENTITY, "text", "start", "end")
                    )
                    for part in parts
                )
                for anchor in anchors
            )
            if not matched:
                parts = []
            available = [
                part["sentence_id"] for part in sorted(parts, key=lambda part: part["start"])
            ]
            complete = bool(parts) and all(
                part.get("unit_complete_read") and part.get("unit_all_parts_shown")
                for part in parts
            )
            registered = {part["sentence_id"] for part in anchors}
            missing = [ref for ref in available if ref not in registered]
            stale_completeness = not all(
                part.get("unit_complete_read") and part.get("unit_all_parts_shown")
                for part in anchors
            )
            action = (
                "verify_source_and_read_coverage"
                if not complete
                else "verify_reference_limit"
                if len(available) > 8
                else "revise_finding_then_bind_full_unit"
                if missing or stale_completeness
                else "bind_full_registered_unit"
            )
            repairs.append(
                dict(
                    index=index,
                    finding_id=identity,
                    unit_id=unit,
                    job_id=row["job_id"],
                    snapshot_id=citation.get("snapshot_id"),
                    available_unit_sentence_ids=available,
                    missing_from_finding=missing,
                    missing_from_selection=[ref for ref in available if ref not in selected],
                    current_unit_fully_read_and_shown=complete,
                    action=action,
                )
            )
    if not repairs:
        return None
    return dict(
        items=repairs[:20],
        truncated=len(repairs) > 20,
        semantic_approval=False,
        notice="若分句缺在已登记分项中，仅改终稿bindings无法补齐："
        "须用新finding ID、supersedes和理由明确修订，"
        "再绑定完整单元；若分项已有全单元，只补终稿选择。先核对来源及完整阅读，不能删去限定或自动当作语义通过。"
        "程序未修改任何分项、判断或预算。",
    )


def resolve_answer(answer, findings, evidence):
    """Resolve declared sentence selections on a deep copy; never edit prose or infer support."""
    answer = SourceAnswer.model_validate(answer).model_copy(deep=True)
    active = {row["id"]: row for row in findings if row["active"]}
    issues = []
    for index, claim in enumerate(answer.claims):
        legacy = not claim.bindings
        bindings = [(binding.finding_id, binding.sentence_ids) for binding in claim.bindings]
        if legacy:
            bindings = [(identity, None) for identity in claim.finding_ids]
        identity_list = [identity for identity, _ in bindings]
        if not bindings or len(identity_list) != len(set(identity_list)):
            issues.append({"index": index, "reason": "finding_ids_missing_or_duplicate"})
        derived_sources, derived_citations = [], []
        for identity, selected_ids in bindings:
            row = active.get(identity)
            if row is None:
                issues.append(
                    {
                        "index": index,
                        "reason": "finding_missing_or_superseded",
                        "finding_id": identity,
                    }
                )
                continue
            if row["state"] in _UNKNOWN:
                issues.append(
                    {
                        "index": index,
                        "reason": "unknown_findings_belong_in_unknown_section",
                        "finding_id": identity,
                        "move_to_unknown_finding_ids": [identity],
                    }
                )
                continue
            available = {cite["sentence_id"]: cite for cite in row["citations"]}
            selected_ids = list(available) if legacy else selected_ids
            if (
                not selected_ids
                or len(selected_ids) != len(set(selected_ids))
                or not set(selected_ids) <= set(available)
            ):
                issues.append(
                    {
                        "index": index,
                        "reason": "binding_sentences_not_in_finding",
                        "finding_id": identity,
                        "sentence_ids": selected_ids,
                        "available_sentence_ids": list(available),
                    }
                )
                continue
            selected = [available[key] for key in selected_ids]
            for reason in _unit_issues(selected, row["citations"], legacy=legacy):
                issues.append(
                    {
                        "index": index,
                        "reason": reason,
                        "finding_id": identity,
                        "sentence_ids": selected_ids,
                    }
                )
            for citation in selected:
                if citation.get("job_id") != row["job_id"]:
                    issues.append(
                        {
                            "index": index,
                            "reason": "finding_sentence_wrong_job",
                            "finding_id": identity,
                        }
                    )
                    continue
                for span in [citation, *citation.get("context", [])]:
                    used, problem = _span_evidence(span, citation, evidence)
                    if problem:
                        issues.append(
                            {
                                "index": index,
                                "reason": problem,
                                "finding_id": identity,
                                "sentence_id": citation["sentence_id"],
                                "is_context": span is not citation,
                            }
                        )
                    derived_sources.extend(used)
                derived_citations.append(
                    {
                        **deepcopy(citation),
                        "finding_id": identity,
                        "facet": row["facet"],
                        "actor": row.get("actor", "unspecified"),
                    }
                )
        derived_sources = list(dict.fromkeys(derived_sources))
        if legacy and not any(
            identity in active and active[identity]["state"] in _UNKNOWN
            for identity in identity_list
        ):
            expected = {
                key
                for identity in identity_list
                if identity in active
                for key in active[identity].get("evidence_ids", [])
            }
            expected.update(derived_sources)
            if set(claim.evidence_ids) != expected:
                issues.append(
                    {
                        "index": index,
                        "reason": "claim_sources_differ_from_findings",
                        "expected_evidence_ids": sorted(expected),
                        "actual_evidence_ids": claim.evidence_ids,
                        "missing_evidence_ids": sorted(expected - set(claim.evidence_ids)),
                        "extra_evidence_ids": sorted(set(claim.evidence_ids) - expected),
                    }
                )
        elif not legacy:
            claim.finding_ids = identity_list
            claim.evidence_ids = derived_sources
        claim.sentence_citations = derived_citations
        if len(claim.evidence_ids) > 10:
            issues.append({"index": index, "reason": "resolved_evidence_limit"})
    return answer, issues


def check_answer(answer, findings, evidence, required_jobs):
    answer, issues = resolve_answer(answer, findings, evidence)
    active = {row["id"]: row for row in findings if row["active"]}
    missing = [
        {"job_id": job, "facet": facet}
        for job in sorted(required_jobs)
        for facet in sorted(REQUIRED_FACETS)
        if not any(row["job_id"] == job and row["facet"] == facet for row in active.values())
    ]
    analysis_notes = []
    for index, claim in enumerate(answer.claims):
        linked = [active.get(key) for key in claim.finding_ids]
        if any(row is None for row in linked):
            continue
        if any(row["state"] in _UNKNOWN for row in linked):
            continue
        jobs = {row["job_id"] for row in linked}
        if len(jobs) > 1:
            if claim.basis == "direct":
                issues.append(
                    {"index": index, "reason": "multi_job_direct_claim_requires_analysis"}
                )
            if len({row["facet"] for row in linked}) != 1:
                analysis_notes.append(
                    {
                        "index": index,
                        "sides": [
                            {
                                "finding_id": row["id"],
                                "job_id": row["job_id"],
                                "facet": row["facet"],
                                "actor": row.get("actor", "unspecified"),
                            }
                            for row in linked
                        ],
                        "notice": "多维分析，不表示同口径单维可比；仍须语义核对",
                    }
                )
    unknown_issues = []
    if len(answer.unknown_finding_ids) != len(set(answer.unknown_finding_ids)):
        unknown_issues.append({"reason": "duplicate_unknown_finding_ids"})
    for identity in answer.unknown_finding_ids:
        row = active.get(identity)
        if not row or row["state"] not in _UNKNOWN:
            unknown_issues.append(
                {
                    "finding_id": identity,
                    "reason": "unknown_section_requires_active_unknown_finding",
                }
            )
    all_unknown = [identity for identity, row in active.items() if row["state"] in _UNKNOWN]
    return {
        "missing_source_facets": missing,
        "claim_finding_issues": issues,
        "analysis_notes": analysis_notes,
        "unknown_finding_issues": unknown_issues,
        "available_unknown_finding_ids": all_unknown,
        "missing_unknown_finding_ids": [
            key for key in all_unknown if key not in answer.unknown_finding_ids
        ],
        "binding_passed": not missing and not issues and not unknown_issues,
        "semantic_approval": False,
    }


def _review_finding(row):
    result = {
        "id": row["id"],
        "job_id": row["job_id"],
        "facet": row["facet"],
        "facet_label": FACETS[row["facet"]],
        "state": row["state"],
        "state_label": STATES[row["state"]],
        "reason": row["reason"],
        "citations": [
            {
                key: deepcopy(cite.get(key))
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
    if "actor" in row:
        result.update(actor=row["actor"], actor_label=ACTORS[row["actor"]])
    if "source_quote_check" in row:
        result["source_quote_check"] = deepcopy(row["source_quote_check"])
    return result


def review_findings(findings):
    """Keep legacy packet fields; include quote checks only when explicitly recorded."""
    return [_review_finding(row) for row in findings if row["active"]]


def review_finding_history(findings):
    """Only v2 has a revision-history appendix; never add empty fields to v1 blind packets."""
    return [
        {
            **_review_finding(row),
            "active": False,
            "supersedes": list(row.get("supersedes", [])),
            "superseded_by": row.get("superseded_by"),
        }
        for row in findings
        if "actor" in row and not row["active"]
    ]
