"""Evidence-linked proposals using an explicitly saved project background."""

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
    "原文只能支持为何针对该任务/能力，建议本身和验收方式是推断，不冒充企业既定要求。"
    "不把会用工具等同于具备能力；尊重用户自述限制，不猜测完成时间、授权或保证结果。"
    "未明确的资源、权限和前提列入assumptions或open_questions，不代替用户执行外部动作。"
)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    task_or_ability: str = Field(min_length=1, max_length=500)
    deliverable: str = Field(min_length=1, max_length=700)
    completion_check: str = Field(min_length=1, max_length=700)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)
    assumptions: list[str] = Field(max_length=4)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    background_memory_id: str
    actions: list[Action] = Field(min_length=1, max_length=3)
    open_questions: list[str] = Field(max_length=6)


def background(memories, project_id):
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
        ) or not all(data[key].strip() for key in ("background", "goal")):
            continue
        candidates.append({"memory_id": note["id"], "version": note["version"], **data})
    return candidates[0] if len(candidates) == 1 else None


def tools(base):
    result = deepcopy(base)
    schema = Plan.model_json_schema()
    finish = next(row for row in result if row["name"] == "finish_research")["parameters"]
    finish.setdefault("$defs", {}).update(schema.pop("$defs"))
    finish["properties"]["application_plan"] = {"anyOf": [schema, {"type": "null"}]}
    finish["required"].append("application_plan")
    return result


def contract():
    source = "\n".join(inspect.getsource(sys.modules[__name__]).splitlines())
    return {"version": VERSION, "sha256": hashlib.sha256(source.encode()).hexdigest()}


def validate(raw, evidence, memories, project_id):
    if raw is None:
        return None
    plan = Plan.model_validate(raw)
    context = background(memories, project_id)
    if context is None or plan.background_memory_id != context["memory_id"]:
        raise ValueError("行动建议必须绑定本项目本轮采用的唯一用户背景版本")
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
    }
