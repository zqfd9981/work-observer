"""Apply model-extracted, user-grounded job constraints inside an already frozen scope."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from work_observer.retrieval.enhanced import RetrievalService
from work_observer.text_match import match_text

ConstraintField = Literal["city", "company", "role", "source"]


class ScopeConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    field: ConstraintField
    value: str = Field(min_length=1, max_length=160)
    source_text: str = Field(min_length=1, max_length=300)


class ScopeRelease(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    field: ConstraintField
    source_text: str = Field(min_length=1, max_length=300)


def narrow(repository, constraints, releases, *, original_question, scope, as_of,
           inherited=()):
    active = {row["field"]: dict(row) for row in inherited}
    seen = set()
    for release in releases:
        if match_text(release.source_text) not in match_text(original_question):
            raise ValueError("放宽范围须保留本次用户原话。")
        active.pop(release.field, None)
    for constraint in constraints:
        if constraint.field in seen:
            raise ValueError("每种范围条件只保留一个明确值；多个对象使用任务的来源选择。")
        seen.add(constraint.field)
        row = constraint.model_dump()
        # Unchanged conditions may come from the explicitly selected old discussion.
        if active.get(constraint.field) == row:
            continue
        if match_text(constraint.source_text) not in match_text(original_question):
            raise ValueError("范围条件须回链本次用户原话，不能从模型查询或背景猜测。")
        if (constraint.field != "source"
                and match_text(constraint.value) not in match_text(constraint.source_text)):
            raise ValueError("城市、公司或岗位名称须保留用户原话中的名称。")
        if constraint.field == "source" and constraint.value not in {"boss", "manual"}:
            raise ValueError("岗位来源仅支持boss或manual；其他来源在缺口中说明。")
        if constraint.field == "source":
            names = {"boss": ["boss", "直聘"], "manual": ["manual", "手工", "手动", "导入"]}
            if not any(name in match_text(constraint.source_text)
                       for name in names[constraint.value]):
                raise ValueError("岗位来源须对应用户原话中明确提及的平台或导入方式。")
        active[constraint.field] = row
    jobs = [row["id"] for row in scope["jobs"]]
    unknown, excluded = [], []
    if active:
        records, _, _ = RetrievalService(repository, alias_groups={})._records(
            scope["filters"], jobs, as_of,
        )
        jobs = []
        fields = {"city": "city", "company": "company_name_raw", "role": "title",
                  "source": "source"}
        for row in records:
            states = []
            for constraint in active.values():
                value = row["record"].get(fields[constraint["field"]])
                states.append("unknown" if not value else "matched" if (
                    match_text(constraint["value"]) in match_text(str(value))
                ) else "excluded")
            if row["state"] == "excluded" or "excluded" in states:
                excluded.append(row["job_id"])
            elif "unknown" in states or row["state"] == "unknown":
                unknown.append(row["job_id"])
            else:
                jobs.append(row["job_id"])
    return {
        "constraints": list(active.values()),
        "released_constraints": [row.model_dump() for row in releases],
        "effective_scope": {
            "job_ids": jobs,
            "public_document_ids": [] if "source" in active else scope["archived_public_ids"],
            "as_of": as_of,
        },
        "scope_unknown_job_ids": unknown, "scope_excluded_job_ids": excluded,
        "scope_notice": "条件只在本轮已选资料内缩小范围，不从全库扩充岗位。"
        "字段未知单列，不当作已符合条件；归档时间不是岗位发布时间。",
    }
