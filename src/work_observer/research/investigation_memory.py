"""Reuse the investigation's rewritten queries to locate saved learning, as leads only."""

import json
from copy import deepcopy

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.text_match import match_text


def task_context(result, index):
    investigation = result.get("investigation") or {}
    tasks = investigation.get("tasks", [])
    if result.get("status") != "completed" or type(index) is not int or not 0 <= index < len(tasks):
        raise ValueError("请选择完整调查中的一个分项解释。")
    outcome = next((row for row in investigation.get("outcomes", [])
                    if row["task_index"] == index), None)
    if not outcome:
        raise ValueError("这项调查尚没有完整保存的回应。")
    claims = result.get("claims", [])
    selected = [{"claim_index": n, **deepcopy(claims[n])} for n in outcome["claim_indices"]
                if 0 <= n < len(claims)]
    cited = {key for claim in selected for key in claim.get("evidence_ids", [])}
    actions = (result.get("application_plan") or {}).get("actions", []) if (
        tasks[index]["intent"] == "practice"
        and sum(task["intent"] == "practice" for task in tasks) == 1
    ) else []
    cited.update(key for action in actions for key in action.get("evidence_ids", []))
    return {
        "task_index": index, "task": deepcopy(tasks[index]), "outcome": deepcopy(outcome),
        "constraints": deepcopy(investigation.get("constraints", [])),
        "effective_scope": deepcopy(investigation.get("effective_scope")),
        "missing_context": deepcopy(investigation.get("missing_context", [])),
        "claims": selected,
        "suggested_actions": deepcopy(actions),
        "evidence": [{**deepcopy(row), **({"as_of": (row.get("historical_cutoffs") or [
            result.get("created_at"),
        ])[0]} if row.get("job_id") else {})}
                     for row in result.get("evidence", []) if row["id"] in cited],
        "notice": "来源调查中这一项的历史解释、范围与原文，不是用户已经采用的认识或实验结果。",
    }


def record_task_context(project, record, store):
    index = record.get("source_task_index")
    if index is None:
        return None
    step = next((row for row in project.get("steps", [])
                 if row["id"] == record.get("source_step_id")), {})
    run = store.get(step["run_id"]) if step.get("run_id") else {}
    if not run or run.get("state") == "invalidated":
        return None
    try:
        return task_context(run.get("result") or {}, index)
    except ValueError:
        return None


def research_context(result):
    investigation = result.get("investigation")
    if not investigation:
        return None
    context = {key: deepcopy(investigation.get(key)) for key in (
        "original_question", "objective", "constraints", "effective_scope", "outcomes",
        "missing_context", "scope_unknown_job_ids", "scope_excluded_job_ids",
    )}
    context["tasks"] = [{key: deepcopy(task.get(key)) for key in (
        "intent", "output", "question", "completion", "source_job_ids", "source_document_ids",
        "required_source_keys", "source_coverage", "missing_source_keys", "retrieval_status",
    )} for task in investigation.get("tasks", [])]
    return context


def recall(notebook, investigation):
    per_task = []
    for index, task in enumerate(investigation["tasks"]):
        queries, seen = [], set()
        for attempt in reversed(task["attempts"]):
            terms = attempt.get("required_terms") or attempt["terms"]
            key = tuple(sorted(match_text(term) for term in terms))
            if key in seen:
                continue
            seen.add(key)
            queries.append({"terms": terms, "task_indices": [index]})
        per_task.append(queries)
    selected, positions = [], {}
    for rank in range(max(map(len, per_task), default=0)):
        for rows in per_task:
            if rank >= len(rows):
                continue
            query = rows[rank]
            key = tuple(sorted(match_text(term) for term in query["terms"]))
            if key in positions:
                selected[positions[key]]["task_indices"].extend(query["task_indices"])
            elif len(selected) < 3:
                positions[key] = len(selected)
                selected.append(query)
    for query in selected:
        query["task_indices"] = sorted(set(query["task_indices"]))
    categories = [
        ("understanding", notebook.search, "notes", "id", "read_learning_note", "note_id"),
        ("inquiry", notebook.search_inquiries, "inquiries", "id", "read_inquiry", "question_id"),
        ("research", notebook.search_research_history, "research", "step_id",
         "read_research_history", "step_id"),
        ("experiment", notebook.search_experiments, "experiments", "id",
         "read_experiments", "experiment_ids"),
    ]
    records, searches, errors = {}, [], []
    for query in selected:
        for kind, search, field, identity, read_tool, argument in categories:
            try:
                result = search(query["terms"], offset=0)
            except ProbeError:
                errors.append(kind)
                continue
            searches.append({"kind": kind, **query, "matching_count": result["matching_count"],
                             "next_offset": result.get("next_offset")})
            for rank, row in enumerate(result[field]):
                key = (kind, row[identity])
                item = records.setdefault(key, {
                    "kind": kind, "record_id": row[identity], "preview": row,
                    "read_tool": read_tool,
                    "read_arguments": {argument: [row[identity]] if kind == "experiment"
                                       else row[identity]},
                    "task_indices": [], "query_terms": [], "score": 0,
                    "derived": True, "independent_source": False,
                })
                item["score"] += 1 / (60 + rank)
                item["task_indices"] = sorted(set([*item["task_indices"], *query["task_indices"]]))
                item["query_terms"] = list(dict.fromkeys([*item["query_terms"], *query["terms"]]))
    ranked = sorted(records.values(), key=lambda row: (-row["score"], row["record_id"]))
    first, rest, kinds = [], [], set()
    for row in ranked:
        (rest if row["kind"] in kinds else first).append(row)
        kinds.add(row["kind"])
    packed, characters = [], 0
    for row in [*first, *rest]:
        size = len(json.dumps(row, ensure_ascii=False))
        if len(packed) >= 8 or characters + size > 5000:
            continue
        packed.append(row)
        characters += size
    return {
        "queries": selected, "searches": searches, "records": packed,
        "omitted_count": len(records) - len(packed), "context_characters": characters,
        "unavailable_kinds": sorted(set(errors)),
        "notice": "使用本轮已执行查询定位的旧认识、调查、研究与实验预览，不是原文证据或完整条件。"
        "先按read_tool读取完整记录，再回读本轮可用原文；不自动采用认识、恢复搁置项或扩大资料范围。"
        "这些记录可能来自不同岗位、时期或实验条件，跨场景联系仍待核对。",
    }
