"""Use the existing sourced work map when a planned question needs relationship output."""

from copy import deepcopy
from types import SimpleNamespace

from work_observer.reports.cognition import ResearchWorkMap


def requested(investigation):
    return any(task.get("output") == "work_map" for task in (investigation or {}).get("tasks", []))


def tools(definitions, investigation):
    if not requested(investigation):
        return definitions
    from work_observer.research.cognition import VERSION

    definitions = deepcopy(definitions)
    schema = ResearchWorkMap.model_json_schema()

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
    schema["properties"]["version"]["enum"] = [VERSION]
    finish = next(row for row in definitions if row["name"] == "finish_research")["parameters"]
    finish.setdefault("$defs", {}).update(schema.pop("$defs", {}))
    finish["properties"]["work_map"] = {"anyOf": [schema, {"type": "null"}]}
    finish["required"].append("work_map")
    return definitions


def validate(raw, investigation, outcomes, claims, evidence):
    from work_observer.research.cognition import validate_map

    map_tasks = {index for index, task in enumerate(investigation["tasks"])
                 if task.get("output") == "work_map"}
    completed = [row for row in outcomes if row["task_index"] in map_tasks
                 and row["status"] == "answered"]
    if raw is None:
        if completed:
            raise ValueError("用户要求的工作关系尚未形成地图，请补充work_map或明确标为部分回答。")
        return None
    work_map = validate_map(
        SimpleNamespace(work_map=ResearchWorkMap.model_validate(raw), claims=claims), evidence,
    )
    covered = {index for row in [*work_map["work_types"], *work_map["work_relations"]]
               for index in row["claim_indices"]}
    for outcome in completed:
        if not outcome["claim_indices"] or not set(outcome["claim_indices"]) <= covered:
            raise ValueError("工作地图须包含对应分项的依据，不能用其他工作线的地图代替。")
    return work_map


POLICY = """
用户希望讲清业务问题、任务、交付物、责任、能力和工具之间的联系，或对照工作线时，
按实际问题选择tasks.output=work_map；只问一个具体事实时用explanation，不按出现某个词机械画图。
输出形式与意图分开：understand或compare等意图仍保留，work_map只表示关系解释需要结构化呈现。
选work_map后，finish_research会提供现有工作地图字段；不需要用户另开一次研究。
work_map用本轮claims的零起始序号定位关系两端，节点保留原判断全文、类别和资格性质。
先按业务场景、任务与交付对象区分工作线，再说明能力和工具怎样支撑工作。
同一JD、同名框架或相似工具不足以证明两项工作有产出关系，不把协作推为最终决定权。
正文写可深入专攻之一时，保留共同范围、分方向任务与资格，不画成一人全部承担。
只连接有依据的同一工作线；内部工具的任务不能接到产品孵化的产物，综合比较句不能替代单侧节点。
任职要求中的能力保留原文强度及必备/加分性质，关系requires不等同于招聘必备required。
关系写连接理由与适用边界；跨岗位比较需在comparisons选择两侧实际关系，
保留共同点、差异、迁移前提和未知；不是两份资料有引用就证明可迁移。
版本使用工具定义给出的现有版本；work_types可以为空，未知放unknowns，不凑满六类或关系条数。
没有足够原文时work_map可以为null，对应任务用partial或needs_context，明确缺什么。
地图仍是待核对分析，不能自动成为个人认识、实验结果或独立证据；不要求生成旧式逐句修订账本。
按问题用最少必要判断、分组与关系，不凑满字段上限。task_outcomes简要回应，详细连接放地图。
"""
