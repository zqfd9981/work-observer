"""Read-only lookup across retained runs; matches are leads, not accepted knowledge."""

import json

from pydantic import BaseModel, ConfigDict, Field

from work_observer.research.relevance import map_content
from work_observer.text_match import match_text


class HistoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(default="", max_length=200)
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


def _texts(row, names):
    for name in names:
        value = row.get(name, "")
        yield from value if isinstance(value, list) else [value]


def _fields(record):
    result = record.get("result") or {}
    question = (record.get("input") or {}).get("question") or result.get("question") or "研究记录"
    if not isinstance(question, str) or not question.strip():
        question = "研究记录"
    fields = [("question", question)]
    fields.extend(("claim", row.get("text", "")) for row in result.get("claims", []))
    work_map = result.get("work_map") or {}
    fields.extend(("work_map", text) for text in _texts(work_map, ("scope_note", "unknowns")))
    fields.extend(("work_map", text) for _, _, _, text in map_content(result))
    for revision in result.get("cognition_revisions", []):
        fields.extend(
            ("cognition_revision", text)
            for text in _texts(revision, ("previous_statement", "new_statements", "reason"))
        )
        for aspect in revision.get("aspects", []):
            fields.extend(
                ("cognition_revision", text)
                for text in _texts(aspect, ("previous_excerpt", "new_statements", "reason"))
            )
    plan = result.get("application_plan") or {}
    for action in plan.get("actions", []):
        fields.extend(
            ("application_plan", text)
            for text in _texts(
                action,
                ("title", "task_or_ability", "deliverable", "completion_check", "assumptions"),
            )
        )
    fields.extend(("application_plan", text) for text in plan.get("open_questions", []))
    fields.extend(("read_source", row.get("title", "")) for row in result.get("evidence", []))
    scope = result.get("scope") or {}
    for row in [*scope.get("jobs", []), *scope.get("public_document_titles", [])]:
        fields.append(("scope_source", row.get("title", "")))
    fields.extend(("gap", text) for text in result.get("gaps", []))
    return [(kind, text) for kind, text in fields if isinstance(text, str) and text.strip()]


def _excerpt(text, terms):
    folded = match_text(text)
    position = min((folded.find(term) for term in terms if term in folded), default=0)
    start = max(0, position - 60)
    return (
        ("…" if start else "")
        + text[start : start + 240]
        + ("…" if start + 240 < len(text) else "")
    )


def search_history(store, *, q="", limit=20, offset=0):
    query = HistoryQuery(q=q, limit=limit, offset=offset)
    terms = match_text(query.q).split()
    total, items = 0, []
    with store.lock:
        erased_projects = set()
        if store.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_projects'"
        ).fetchone():
            erased_projects = {
                identity
                for identity, encoded in store.db.execute(
                    "SELECT id,record FROM research_projects WHERE namespace=?", (store.namespace,)
                )
                if json.loads(encoded).get("state") == "invalidated"
            }
        rows = store.db.execute(
            "SELECT record FROM research_checkpoints WHERE namespace=? "
            "ORDER BY json_extract(record,'$.created_at') DESC,id DESC",
            (store.namespace,),
        )
        for (encoded,) in rows:
            record = json.loads(encoded)
            result = record.get("result") or {}
            project_id = (record.get("input") or {}).get("project_id") or result.get("project_id")
            if record.get("state") == "invalidated" or project_id in erased_projects:
                continue
            fields = _fields(record)
            searchable = match_text("\n".join(text for _, text in fields))
            if not all(term in searchable for term in terms):
                continue
            total += 1
            if not query.offset < total <= query.offset + query.limit:
                continue
            match = next(
                (
                    (kind, text)
                    for kind, text in fields
                    if any(t in match_text(text) for t in terms)
                ),
                None,
            )
            items.append(
                {
                    "id": record["id"],
                    "question": fields[0][1],
                    "created_at": record.get("created_at"),
                    "state": record.get("state"),
                    "status": result.get("status"),
                    "project_id": project_id,
                    "report_id": (record.get("saved") or {}).get("report_id"),
                    "match": {"field": match[0], "excerpt": _excerpt(match[1], terms)}
                    if match
                    else None,
                }
            )
    return {
        "query": query.q,
        "items": items,
        "total": total,
        "limit": query.limit,
        "offset": query.offset,
        "notice": (
            "搜索已保留的问题、判断、工作地图、认识修订、行动建议、缺口和资料标题；多个词同时匹配。"
            "范围含某资料不表示已读全文，历史匹配不表示结论已核对或仍有效。"
        ),
    }
