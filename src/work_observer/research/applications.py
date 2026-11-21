"""Evidence-linked experiments using saved goals and optional personal background."""

import hashlib
import inspect
import json
import sys
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field

VERSION = "application-actions-v1"
PREFIX = "个人应用背景（用户自述，结构化）：\n"
NOTICE = "以下为研究建议，产物和检查方式不是企业既定验收，也不表示已经执行或已具备岗位能力。"
POLICY = (
    "本轮提供application_background，来自用户明确保存的本项目背景，不是独立来源证据。"
    "用户要求应用、学习或项目建议时，在finish_research的application_plan中给最多3项有顺序的动作；"
    "其他问题或背景不足时填null，并在gaps写明需要澄清什么。不要虚构经历、投入或适配结论。"
    "每项说明针对的任务/能力、可交付产物和可实际检查的完成条件，引用本轮已读原文；"
    "实验类动作在hypothesis写明尚未验证的解释及适用条件，在completion_check写出"
    "可以支持、区分或挑战它的具体观察；完成作品不等于解释成立。非实验动作可将hypothesis留空。"
    "实验动作优先给2至4组可直接尝试的comparison_rows：condition说明改变的条件，"
    "input给具体可复制的合成输入或操作，expected写待验证的预期，不能填写实际结果。"
    "comparison_conditions说明建议保持不变的条件及未控制之处。优先只改变一个关键条件，"
    "包含有机会挑战原解释的案例；不为凑组数而捏造规则或企业数据。"
    "无法设计具体对照或非实验动作时comparison_rows填空数组，comparison_conditions可留空。"
    "原文只能支持为何针对该任务/能力，建议本身和验收方式是推断，不冒充企业既定要求。"
    "不把会用工具等同于具备能力；尊重用户自述限制，不猜测完成时间、授权或保证结果。"
    "未明确的资源、权限和前提列入assumptions或open_questions，不代替用户执行外部动作。"
)
LEARNING_POLICY = (
    "本轮application_background.purpose为understanding_check：用户只保存了研究目标，尚未提供个人背景。"
    "这足以设计资料理解验证，不足以判断个人适配、能力缺口或安排个人学习路线。"
    "围绕当前问题只给一个最小验证动作：使用可自行构造的合成案例、公开示例或现有资料，"
    "写清输入、待区分的解释、观察记录及什么结果会挑战原解释；不依赖企业权限或真实业务数据。"
    "有本轮原文依据时可填写application_plan，绑定该目标的memory_id；不要因个人背景为空"
    "就一律返回null。若资料本身不足以设计检查，返回null并明确缺少什么。"
    "个人经历、环境、时间与资源均按未知处理；实验尚未执行，不保证预期，也不代表岗位胜任。"
)


class ComparisonCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    condition: str = Field(min_length=1, max_length=300)
    input: str = Field(min_length=1, max_length=600)
    expected: str = Field(min_length=1, max_length=600)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    task_or_ability: str = Field(min_length=1, max_length=500)
    deliverable: str = Field(min_length=1, max_length=700)
    completion_check: str = Field(min_length=1, max_length=700)
    hypothesis: str = Field(default="", max_length=1500,
                            description="实验准备检验的解释与条件，尚未验证；非实验动作可留空。")
    evidence_ids: list[str] = Field(min_length=1, max_length=6)
    assumptions: list[str] = Field(max_length=4)
    comparison_conditions: str = Field(default="", max_length=1000)
    comparison_rows: list[ComparisonCase] = Field(default_factory=list, max_length=4)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    background_memory_id: str
    actions: list[Action] = Field(min_length=1, max_length=3)
    open_questions: list[str] = Field(max_length=6)


def background(memories, project_id, *, allow_learning=False):
    candidates = []
    for note in memories:
        if not (
            project_id
            and note.get("project_id") == project_id
            and note.get("scope") == "project"
            and note.get("kind") == "preference"
            and note.get("origin") == "user"
            and note.get("status") == "active"
        ):
            continue
        content = note.get("content", "")
        data = None
        if content.startswith(PREFIX):
            try:
                data = json.loads(content[len(PREFIX) :])
            except ValueError:
                continue
        elif content.startswith("个人应用背景（用户自述）：\n"):
            labels = ["已有经历或能力：", "\n本次目标：", "\n投入与限制："]
            if any(content.count(label) != 1 for label in labels):
                continue
            first, rest = content.split(labels[1])
            goal, constraints = rest.split(labels[2])
            data = {
                "background": first.split(labels[0])[1],
                "goal": goal,
                "constraints": "" if constraints == "未说明，不作假设" else constraints,
            }
        if not isinstance(data, dict) or set(data) != {"background", "goal", "constraints"}:
            continue
        if any(
            not isinstance(data[key], str) or len(data[key]) > limit
            for key, limit in (("background", 1500), ("goal", 1000), ("constraints", 500))
        ) or not data["goal"].strip() or not (data["background"].strip() or allow_learning):
            continue
        candidate = {"memory_id": note["id"], "version": note["version"], **data}
        if not data["background"].strip():
            candidate["purpose"] = "understanding_check"
        candidates.append(candidate)
    return candidates[0] if len(candidates) == 1 else None


def tools(base):
    result = deepcopy(base)
    schema = Plan.model_json_schema()
    finish = next(row for row in result if row["name"] == "finish_research")["parameters"]
    finish.setdefault("$defs", {}).update(schema.pop("$defs"))
    action = finish["$defs"]["Action"]
    action["required"] = list(action["properties"])
    for field in ("hypothesis", "comparison_conditions", "comparison_rows"):
        action["properties"][field].pop("default", None)
    finish["properties"]["application_plan"] = {"anyOf": [schema, {"type": "null"}]}
    finish["required"].append("application_plan")
    return result


def contract():
    source = "\n".join(inspect.getsource(sys.modules[__name__]).splitlines())
    return {"version": VERSION, "sha256": hashlib.sha256(source.encode()).hexdigest()}


def validate(raw, evidence, memories, project_id, *, allow_learning=False):
    if raw is None:
        return None
    plan = Plan.model_validate(raw)
    context = background(memories, project_id, allow_learning=allow_learning)
    if context is None or plan.background_memory_id != context["memory_id"]:
        raise ValueError("行动建议必须关联本项目本轮采用的目标与背景记录")
    aliases = {row.get("citation_key"): key for key, row in evidence.items()}
    for action in plan.actions:
        action.evidence_ids = list(
            dict.fromkeys(aliases.get(key, key) for key in action.evidence_ids)
        )
        if any(
            key not in evidence
            or not evidence[key].get("quote", "").strip()
            or not (evidence[key].get("snapshot_id") or evidence[key].get("public_document_id"))
            for key in action.evidence_ids
        ):
            raise ValueError("行动建议须引用本轮已读取的岗位或归档正文；搜索摘要不能替代原文")
    return {
        "version": VERSION,
        "background_memory_id": context["memory_id"],
        "background_version": context["version"],
        "goal": context["goal"],
        "constraints": context["constraints"],
        "actions": [row.model_dump() for row in plan.actions],
        "open_questions": plan.open_questions,
        "notice": NOTICE,
        **({"purpose": "understanding_check",
            "notice": ("这是围绕资料解释设计的验证，个人背景尚未提供。"
                       "尚未执行，不代表个人适配或岗位能力。")}
           if context.get("purpose") == "understanding_check" else {}),
    }
