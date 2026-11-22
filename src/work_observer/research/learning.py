"""Recall personal understanding for the current question without adopting it as fact."""

import json
from copy import deepcopy

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.service import _tokens
from work_observer.reports.cognition import work_map_search_parts
from work_observer.research.investigation_memory import record_task_context, research_context
from work_observer.retrieval.enhanced import validated_terms
from work_observer.text_match import match_text

CALCULATION_FIELDS = ("local_experiments", "cohort_experiments", "threshold_experiments")
CALCULATION_NOTICE = (
    "来源讨论当时运行的完整本地计算输入与输出，不表示本轮已经重新执行。"
    "构造案例、参照标签与指定代价不等于业务事实；改变条件后须重新计算并核对原文。"
    "保留整次讨论的计算记录，不表示每项计算都支持本份认识或每条旧判断。"
)


def calculation_records(result):
    context = result.get("career_learning_context", {})
    return {key: deepcopy(context[key]) for key in CALCULATION_FIELDS if context.get(key)}


def relation_learning_notes(notes, step_id, index=None, *, active_only=False):
    related = {
        row["id"]: {row["source_relation_index"]} for row in notes
        if row.get("source_step_id") == step_id
        and type(row.get("source_relation_index")) is int
        and (index is None or row["source_relation_index"] == index)
    }
    changed = True
    while changed:
        changed = False
        for row in notes:
            previous = related.get(row.get("replaces_insight_id"), set())
            combined = related.get(row["id"], set()) | previous
            if combined and combined != related.get(row["id"]):
                related[row["id"]] = combined
                changed = True
    return [{**deepcopy(row), "related_relation_indices": sorted(related[row["id"]])}
            for row in notes if row["id"] in related
            and (not active_only or row.get("use_for_research", True))]


def inquiry_children(career, question_id):
    return [{
        **{key: deepcopy(row.get(key)) for key in (
            "id", "question", "state", "source_step_id", "source_gap_index",
            "conclusion_step_id", "updated_at", "created_at",
        )},
        "has_user_conclusion": bool(row.get("conclusion", "").strip()),
    } for row in career.get("questions", []) if row.get("parent_question_id") == question_id]


def inquiry_unknown_origin(project, question, store):
    index = question.get("source_gap_index")
    if type(index) is not int or index < 0:
        return None
    step = next((row for row in project.get("steps", [])
                 if row["id"] == question.get("source_step_id")), {})
    run = store.get(step["run_id"]) if step.get("run_id") else {}
    result = (run or {}).get("result") or {}
    if (not run or run.get("state") == "invalidated" or result.get("status") != "completed"
            or index >= len(result.get("gaps", []))):
        return None
    return {
        "step_id": step["id"], "index": index, "text": result["gaps"][index],
        "notice": "这是原研究记录的未知，不是已成立事实；本次需回读原文查证。",
    }


def work_relation_record(owner, study, result, index, current):
    relation = result["work_map"]["work_relations"][index]
    claims = result.get("claims", [])
    linked = [{"index": n, **claims[n]} for n in relation["claim_indices"]
              if 0 <= n < len(claims)]
    refs = {key for claim in linked for key in claim["evidence_ids"]}
    return deepcopy({
        "key": f"{owner['id']}:{study['step_id']}:{index}",
        "project_id": owner["id"], "project_title": owner["title"],
        "step_id": study["step_id"], "relation_index": index,
        "question_id": study.get("question_id"),
        "question": study.get("user_question") or "工作地图研究",
        "recorded_at": study["created_at"], "current": current,
        "research_cutoff": result["created_at"],
        "scope_note": result["work_map"].get("scope_note", ""),
        "scope": result.get("scope", {}), "relation": relation, "claims": linked,
        "evidence": [row for row in result.get("evidence", []) if row["id"] in refs],
        "unknowns": result["work_map"].get("unknowns", []),
    })


def experiment_answer_origin(career, task):
    source = next((row for row in career.get("runs", [])
                   if row["step_id"] == task.get("source_step_id")), None)
    if source and source["kind"] == "plan":
        source = next((row for row in career.get("runs", [])
                       if row["step_id"] == source.get("source_step_id")), None)
    if not source or source["kind"] != "answer":
        return None
    return {
        "step_id": source["step_id"], "original_question": source.get("interview_question"),
        "user_answer": source.get("answer"), "answer_document_id": source.get("answer_document_id"),
        "notice": "验证计划所针对的完整个人解释；不是实际观察或原文证据。"
                  "可读取该step_id的历史反馈，再按本轮范围回查原文。",
    }


def experiment_claim_origin(project, task, store):
    index = task.get("source_claim_index")
    if index is None:
        return None
    step = next((row for row in project.get("steps", [])
                 if row["id"] == task.get("source_step_id")), {})
    run = store.get(step["run_id"]) if step.get("run_id") else {}
    if not run or run.get("state") == "invalidated":
        return None
    result = run.get("result") or {}
    claims = result.get("claims", [])
    if index >= len(claims):
        return None
    claim = claims[index]
    return {
        "step_id": step["id"], "claim_index": index, "claim": deepcopy(claim),
        "evidence": [deepcopy(row) for row in result.get("evidence", [])
                     if row["id"] in claim.get("evidence_ids", [])],
        "notice": "实验所针对的历史Agent判断及当时引用；不是本次实际观察或新证据。"
                  "验证可支持、挑战或保留未知；需按当前范围回读原文，不自动采用旧判断。",
    }


def experiment_relation_origin(project, task, store):
    index = task.get("source_relation_index")
    if index is None:
        return None
    step = next((row for row in project.get("steps", [])
                 if row["id"] == task.get("source_step_id")), {})
    run = store.get(step["run_id"]) if step.get("run_id") else {}
    result = (run or {}).get("result") or {}
    relations = (result.get("work_map") or {}).get("work_relations", [])
    if not run or run.get("state") == "invalidated" or not 0 <= index < len(relations):
        return None
    study = next((row for row in project.get("career", {}).get("runs", [])
                  if row["step_id"] == task.get("source_step_id")), None)
    if not study:
        return None
    return {
        **work_relation_record(project, study, result, index, False),
        "notice": "实验所针对的历史工作关系及当时引用；连接理由和迁移限制保留完整。"
                  "它是待验证解释，不是本次观察或新证据，仍需回查原文与实际条件。",
    }


def experiment_template_origin(project, task, store):
    if not task.get("source_experiment_id"):
        return None
    step = next((row for row in project.get("steps", [])
                 if row["id"] == task.get("source_step_id")), {})
    if not step.get("run_id"):
        return None
    run = store.get(step["run_id"]) or {}
    if run.get("state") == "invalidated":
        return None
    reads = (run.get("result") or {}).get("career_learning_context", {}).get("read_other_goals", [])
    origin = next((row for row in reads if row["kind"] == "experiment"
                   and row["record_id"] == task["source_experiment_id"]), None)
    if not origin:
        return None
    copied = deepcopy(origin)
    copied["memory"].pop("template_origin", None)
    copied["notice"] = (
        "来源讨论当时读取的旧设计与用户观察，只供核对这份新计划的起点。"
        "日志范围标记属于当时状态；本轮可读范围仍以fixed_scope为准。"
        "旧观察不是这项新实验的结果，不能因借用设计而声称已经执行或验证。"
    )
    return copied


def learning_family(notes, identity):
    links = {row["id"]: set() for row in notes}
    for row in notes:
        if (parent := row.get("replaces_insight_id")) in links:
            links[row["id"]].add(parent)
            links[parent].add(row["id"])
    seen, pending = set(), [identity] if identity in links else []
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            pending.extend(links[current] - seen)
    return [row for row in notes if row["id"] in seen]


def learning_inquiry_links(career, note):
    """Find inquiry connections from existing records; an explicit scope takes precedence."""
    questions = {row["id"]: row for row in career.get("questions", [])}
    notes = {row["id"]: row for row in career.get("insights", [])}
    runs = {row["step_id"]: row for row in career.get("runs", [])}
    tasks = {row["id"]: row for row in career.get("tasks", [])}
    links, seen, current = {}, set(), note
    while current and current.get("id") not in seen:
        seen.add(current.get("id"))
        source = runs.get(current.get("source_step_id"), {})
        task = tasks.get(current.get("task_id"), {})
        explicit = current.get("question_id")
        candidates = [(explicit, "question")] if explicit else [
            (task.get("question_id"), "experiment"),
            (source.get("question_id"), "discussion"),
            *((row["question_id"], "synthesis")
              for row in source.get("synthesis_sources", [])),
        ]
        for identity, via in candidates:
            if identity in questions and identity not in links:
                links[identity] = {
                    "question_id": identity, "question": questions[identity]["question"],
                    "via": via, "inherited": current is not note,
                    "source_note_id": current.get("id"),
                    "source_step_id": current.get("source_step_id"),
                }
        if explicit or task.get("question_id") or source.get("question_id"):
            break
        current = notes.get(current.get("replaces_insight_id"))
    return list(links.values())


class LearningNotebook:
    """Read this goal's personal notes and saved experiment records."""

    def __init__(self, project_reader, store, selected_note_id=None, counter_note_id=None,
                 *, selected_note_ids=None, project_lister=None):
        self.project_reader = project_reader
        self.store = store
        self.selected_note_id = selected_note_id
        self.counter_note_id = counter_note_id
        self.selected_note_ids = selected_note_ids or []
        self.project_lister = project_lister

    def _other_goals(self):
        identity = self.project_reader()["id"]
        return [row for row in (self.project_lister() if self.project_lister else [])
                if row["id"] != identity and row.get("career")]

    def search_other_goal_memory(self, terms, offset=0):
        if terms != []:
            terms = validated_terms(terms)
        if type(offset) is not int or offset < 0:
            raise ProbeError("INVALID_MEMORY_OFFSET")
        ranked, total = [], 0
        for project in self._other_goals():
            notebook = LearningNotebook(lambda project=project: project, self.store)
            for kind, search, field, id_key in (
                ("insight", notebook.search, "notes", "id"),
                ("research", notebook.search_research_history, "research", "step_id"),
                ("experiment", notebook.search_experiments, "experiments", "id"),
                ("inquiry", notebook.search_inquiries, "inquiries", "id"),
            ):
                page_offset = 0
                while True:
                    page = search(terms, page_offset)
                    if page_offset == 0:
                        total += page["matching_count"]
                    for row in page[field]:
                        ranked.append({
                            "project_id": project["id"], "project_title": project["title"],
                            "kind": kind, "record_id": row[id_key],
                            "recorded_at": row["recorded_at"],
                            "matched_terms": row["matched_terms"], "preview": row,
                        })
                    if page["next_offset"] is None or page["next_offset"] >= offset + 6:
                        break
                    page_offset = page["next_offset"]
        ranked.sort(key=lambda row: (len(row["matched_terms"]), row["recorded_at"],
                                    row["record_id"]), reverse=True)
        return {
            "memories": ranked[offset:offset + 6], "matching_count": total, "offset": offset,
            "next_offset": offset + 6 if offset + 6 < total else None,
            "notice": "其他求职目标中选用的认识、已完成研究、实验和调查笔记的关键词预览。"
                      "新旧顺序不表示正确性，需read_other_goal_memory读完整内容与原场景。"
                      "实验计划、预期和实际观察分别保留；失败或完成状态都不证明个人能力。"
                      "不改变选用状态，不复制记录，不把其他目标的原文加入本轮范围。",
        }

    def read_other_goal_memory(self, project_id, kind, record_id):
        project = next((row for row in self._other_goals() if row["id"] == project_id), None)
        if not project or kind not in {"insight", "research", "experiment", "inquiry"}:
            raise ProbeError("OTHER_GOAL_MEMORY_NOT_AVAILABLE")
        notebook = LearningNotebook(lambda: project, self.store)
        if kind == "insight":
            memory = notebook.read(record_id)["note"]
        elif kind == "experiment":
            memory = notebook.read_experiments([record_id])["experiments"][0]
        elif kind == "inquiry":
            memory = notebook.read_inquiry(record_id)["inquiry"]
        else:
            memory = notebook.read_research_history(record_id)["research"]
        return {
            "project_id": project_id, "project_title": project["title"],
            "project_goal": project["goal"], "kind": kind, "record_id": record_id,
            "memory": memory,
            "notice": "其他目标中本次读取的完整旧记录。先比较业务对象、分工、交付和适用条件，"
                      "判断是否值得迁移，不把旧解释当作当前岗位事实或个人能力。"
                      "实验预期不等于执行；reported_observation仅是用户保存的观察，"
                      "读取不会重跑实验或核实日志。"
                      "旧资料只供定位；本轮仍按fixed_scope读取原文，不扩展选岗、资料或采用状态。",
        }

    def _available(self):
        project = self.project_reader()
        notes = project.get("career", {}).get("insights", [])
        historical = {row["id"] for identity in (
            self.selected_note_id, self.counter_note_id, *self.selected_note_ids)
                      for row in learning_family(notes, identity)}
        return project, [
            row for row in notes if row.get("use_for_research", True) or row["id"] in historical
        ]

    def search(self, terms, offset=0):
        if terms != []:
            terms = validated_terms(terms)
        if type(offset) is not int or offset < 0:
            raise ProbeError("INVALID_LEARNING_OFFSET")
        project, notes = self._available()
        ranked = []
        for row in notes:
            step = next((item for item in project.get("steps", [])
                         if item["id"] == row.get("source_step_id")), {})
            run = self.store.get(step["run_id"]) if step.get("run_id") else {}
            calculations = calculation_records((run or {}).get("result") or {}) if (
                run or {}
            ).get("state") != "invalidated" else {}
            text = match_text(
                "\n".join(
                    row.get(key, "")
                    for key in ("previous_view", "observation", "current_view", "open_question")
                )
                + "\n" + (row.get("source_passage") or {}).get("title", "")
                + "\n" + (row.get("source_passage") or {}).get("quote", "")
                + "\n" + json.dumps(row.get("source_passages", []), ensure_ascii=False)
                + "\n" + json.dumps(calculations, ensure_ascii=False)
            )
            hits = [term for term in terms if match_text(term) in text]
            if hits or not terms:
                ranked.append(
                    (len(hits), row.get("updated_at") or row["created_at"], row["id"], row, hits)
                )
        ranked.sort(key=lambda row: row[:3], reverse=True)
        page = ranked[offset : offset + 6]
        return {
            "notes": [
                {
                    "id": row["id"],
                    "current_view_preview": row["current_view"][:160],
                    "preview_is_partial": len(row["current_view"]) > 160,
                    "use_for_research": row.get("use_for_research", True),
                    "replaces_insight_id": row.get("replaces_insight_id"),
                    "recorded_at": row.get("updated_at") or row["created_at"],
                    "matched_terms": hits,
                }
                for *_, row, hits in page
            ],
            "available_count": len(notes),
            "matching_count": len(ranked),
            "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(ranked) else None,
            "notice": "关键词召回的用户理解预览，可能省略末尾限制；需read_learning_note读全文。"
            "已搁置记录只在用户点选的认识脉络内开放，检索与读取不会恢复选用。",
        }

    def read(self, note_id):
        project, notes = self._available()
        row = next((row for row in notes if row["id"] == note_id), None)
        if row is None:
            raise ProbeError("LEARNING_NOTE_NOT_AVAILABLE")
        return {
            "note": learning_record(row, project, self.store),
            "notice": "这是本次读取时保存的用户理解，不是已核实的事实或本轮原文证据。"
            "旧引用只供定位，形成判断仍须读取当前可用原文；不改变记录或选用状态。",
        }

    def search_experiments(self, terms, offset=0, question_id=""):
        if terms != []:
            terms = validated_terms(terms)
        if type(offset) is not int or offset < 0:
            raise ProbeError("INVALID_EXPERIMENT_OFFSET")
        project = self.project_reader()
        career = project.get("career", {})
        if question_id and not any(row["id"] == question_id
                                   for row in career.get("questions", [])):
            raise ProbeError("EXPERIMENT_INQUIRY_NOT_AVAILABLE")
        ranked = []
        for row in career.get("tasks", []):
            if question_id and row.get("question_id") != question_id:
                continue
            original_answer = experiment_answer_origin(career, row) or {}
            original_claim = experiment_claim_origin(project, row, self.store) or {}
            original_relation = experiment_relation_origin(project, row, self.store) or {}
            text = match_text("\n".join(row.get(key, "") for key in (
                "title", "task_or_ability", "deliverable", "completion_check",
                "hypothesis", "outcome", "design_change", "artifact", "comparison_conditions",
            )) + "\n" + "\n".join(
                value for case in row.get("comparison_rows", []) for value in case.values()
            ) + "\n" + (original_answer.get("original_question") or "")
                + "\n" + (original_answer.get("user_answer") or "")
                + "\n" + original_claim.get("claim", {}).get("text", "")
                + "\n" + ((row.get("feedback_origin") or {}).get("gap") or "")
                + "\n" + json.dumps(original_relation, ensure_ascii=False))
            hits = [term for term in terms if match_text(term) in text]
            if hits or not terms:
                ranked.append((len(hits), row.get("updated_at") or row["created_at"],
                               row["id"], row, hits))
        ranked.sort(key=lambda row: row[:3], reverse=True)
        page = ranked[offset:offset + 6]
        return {
            "experiments": [{
                "id": row["id"], "title": row["title"],
                "question_id": row.get("question_id"), "state": row["state"],
                "has_reported_observation": bool(row.get("outcome", "").strip()) or any(
                    case.get("observed", "").strip() for case in row.get("comparison_rows", [])
                ),
                "observation_preview": row.get("outcome", "")[:180],
                "preview_is_partial": len(row.get("outcome", "")) > 180,
                "previous_task_id": row.get("previous_task_id"),
                "created_at": row["created_at"],
                "recorded_at": row.get("updated_at") or row["created_at"],
                "matched_terms": hits,
            } for *_, row, hits in page],
            "matching_count": len(ranked), "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(ranked) else None,
            "notice": "本目标的用户实验记录目录，不是验证结果。"
            "预期与计划不等于实际观察；用read_experiments读取完整设计、观察和产物定位。",
        }

    def search_inquiries(self, terms, offset=0):
        if terms != []:
            terms = validated_terms(terms)
        if type(offset) is not int or offset < 0:
            raise ProbeError("INVALID_INQUIRY_OFFSET")
        ranked = []
        for row in self.project_reader().get("career", {}).get("questions", []):
            fields = {key: row.get(key, "") for key in (
                "question", "why_matters", "next_evidence", "conclusion",
                "hypothesis_a", "hypothesis_b",
            )}
            for index, origin in enumerate((row.get("carried_understanding") or {}).get(
                "learning_notes", [],
            )):
                fields[f"starting_note_{index}"] = "\n".join(
                    origin["note"].get(key, "") for key in (
                        "previous_view", "reported_observation", "current_user_view",
                        "open_question",
                    )
                )
            for index, passage in enumerate([
                row.get("source_passage"), *row.get("evidence_passages", []),
            ]):
                if passage:
                    fields[f"passage_{index}"] = "\n".join(passage.get(key, "") for key in (
                        "title", "quote", "user_note", "target_view",
                    ))
                    if note := passage.get("conversation_note"):
                        fields[f"conversation_{index}"] = "\n".join(note.get(key, "") for key in (
                            "asked_question", "speaker", "context", "said_when", "limits",
                        )) + "\n" + (note.get("target_job") or {}).get("label", "")
            hits = [term for term in terms
                    if any(match_text(term) in match_text(value) for value in fields.values())]
            if terms and not hits:
                continue
            ranked.append((len(hits), row.get("updated_at") or row["created_at"], row["id"], {
                "id": row["id"], "question_preview": row["question"][:160],
                "preview_is_partial": len(row["question"]) > 160,
                "state": row["state"], "parent_question_id": row.get("parent_question_id"),
                "evidence_passage_count": len(row.get("evidence_passages", [])),
                "recorded_at": row.get("updated_at") or row["created_at"],
                "matched_terms": hits,
                "matched_fields": [key for key, value in fields.items()
                                   if any(match_text(term) in match_text(value) for term in terms)],
            }))
        ranked.sort(key=lambda row: row[:3], reverse=True)
        page = ranked[offset:offset + 6]
        return {
            "inquiries": [row[3] for row in page], "matching_count": len(ranked),
            "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(ranked) else None,
            "notice": "本目标保存的调查问题目录，包括尚未研究和暂不研究的记录。"
            "关键词也检索摘录与用户标注；预览不是全文或原文证据，用read_inquiry读取。"
            "状态只代表用户整理方式，读取不会改变研究焦点或恢复暂不研究的问题。",
        }

    def read_inquiry(self, question_id):
        project = self.project_reader()
        career = project.get("career", {})
        row = next((row for row in career.get("questions", [])
                    if row["id"] == question_id), None)
        if row is None:
            raise ProbeError("INQUIRY_NOT_AVAILABLE")
        record = {key: deepcopy(row.get(key)) for key in (
            "id", "question", "why_matters", "next_evidence", "state", "conclusion",
            "hypothesis_a", "hypothesis_b", "parent_question_id", "source_step_id",
            "conclusion_step_id", "source_passage", "evidence_passages", "material_ids",
            "selected_job_ids", "carried_understanding", "reused_from", "created_at", "updated_at",
            "source_insight_id", "source_gap_index",
        )}
        origin = next((item for item in career.get("insights", [])
                       if item["id"] == row.get("source_insight_id")), None)
        if origin:
            record["origin_learning_note"] = learning_record(origin, project, self.store)
        record["evidence_passages"] = record["evidence_passages"] or []
        record["child_question_ids"] = [item["id"] for item in career.get("questions", [])
                                        if item.get("parent_question_id") == question_id]
        record["child_inquiries"] = inquiry_children(career, question_id)
        record["origin_unknown"] = inquiry_unknown_origin(project, row, self.store)
        record["linked_experiment_ids"] = [item["id"] for item in career.get("tasks", [])
                                           if item.get("question_id") == question_id]
        record["linked_research_step_ids"] = [item["step_id"] for item in career.get("runs", [])
                                               if item.get("question_id") == question_id]
        return {
            "inquiry": record,
            "notice": "本次读取时的完整用户调查记录，包括两种解释、原文摘录及标注。"
            "用户结论和supports/challenges/conditions标注均是待核判断，不代表原文已经支持或推翻解释。"
            "摘录不能代替上下文；按正文定位读取本轮可用原文，再引用本轮证据ID。"
            "保留旧原句、反例和限制，不自动恢复已移出资料，不修改问题、焦点或研究状态。",
        }

    def read_experiments(self, experiment_ids):
        if (not isinstance(experiment_ids, list) or not 1 <= len(experiment_ids) <= 6
                or any(not isinstance(key, str) for key in experiment_ids)
                or len(set(experiment_ids)) != len(experiment_ids)):
            raise ProbeError("INVALID_EXPERIMENT_SELECTION")
        project = self.project_reader()
        career = project.get("career", {})
        tasks = {row["id"]: row for row in career.get("tasks", [])}
        if not set(experiment_ids) <= tasks.keys():
            raise ProbeError("EXPERIMENT_NOT_AVAILABLE")
        questions = {row["id"]: row for row in career.get("questions", [])}
        records = []
        for key in experiment_ids:
            row = tasks[key]
            inquiry = questions.get(row.get("question_id"), {})
            records.append({
                "id": key, "title": row["title"], "question_id": row.get("question_id"),
                "inquiry_question": inquiry.get("question"),
                "task_or_ability": row["task_or_ability"],
                "planned_deliverable": row["deliverable"],
                "proposed_check": row["completion_check"], "state": row["state"],
                "purpose": row.get("purpose"),
                "prior_expectation": row.get("hypothesis", ""),
                "reported_observation": row.get("outcome", ""),
                "comparison_conditions": row.get("comparison_conditions", ""),
                "comparison_rows": deepcopy(row.get("comparison_rows", [])),
                "design_change": row.get("design_change", ""),
                "previous_task_id": row.get("previous_task_id"),
                "source_step_id": row.get("source_step_id"),
                "target_requirement": row.get("target_requirement"),
                "answer_to_verify": experiment_answer_origin(career, row),
                "feedback_to_verify": deepcopy(row.get("feedback_origin")),
                "note_to_verify": deepcopy(row.get("retrieval_note_origin")),
                "claim_to_verify": experiment_claim_origin(project, row, self.store),
                "relation_to_verify": experiment_relation_origin(project, row, self.store),
                "task_to_verify": record_task_context(project, row, self.store),
                "template_origin": experiment_template_origin(project, row, self.store),
                "origin": row.get("origin", "research"),
                "reused_from_goal": (row.get("reused_from") or {}).get("project_title"),
                "artifact": row.get("artifact", ""),
                "artifact_document": {
                    "document_id": row["artifact_document_id"],
                    "title": row.get("artifact_title") or row["title"],
                    "available_in_goal": row["artifact_document_id"] in project.get(
                        "public_document_ids", []
                    ),
                } if row.get("artifact_document_id") else None,
                "recorded_at": row.get("updated_at") or row["created_at"],
                "created_at": row["created_at"],
            })
        return {
            "experiments": records,
            "notice": "用户保存的完整实验设计与观察，不是独立运行或能力认证。"
            "即使state为done，也可能记录失败。产物定位不表示已经读取原文；"
            "本目标仍保留的产物可按返回的document_id读取；"
            "未保留的产物只能作为旧定位，不能假装已核对。保留条件、反例与未知。",
        }

    def reading_evidence(self, *, exclude_run_id=None):
        """Only source positions actually retained by this goal's research runs."""
        project = self.project_reader()
        steps = {row["id"]: row for row in project.get("steps", [])}
        records = []
        for entry in project.get("career", {}).get("runs", []):
            run_id = steps.get(entry["step_id"], {}).get("run_id")
            if not run_id or run_id == exclude_run_id:
                continue
            result = self.store.get(run_id).get("result") or {}
            records.extend({key: source.get(key) for key in (
                "public_document_id", "job_id", "snapshot_id", "start", "end", "evidence_kind",
            )} for source in result.get("evidence", []))
        return records

    def _research_history(self):
        project = self.project_reader()
        steps = {row["id"]: row for row in project.get("steps", [])}
        records = []
        for entry in project.get("career", {}).get("runs", []):
            step = steps.get(entry["step_id"], {})
            if not step.get("run_id") or step.get("state") == "abandoned":
                continue
            run = self.store.get(step["run_id"])
            result = run.get("result") or {}
            if (run["state"] == "invalidated" or result.get("status") != "completed"
                    or (result.get("business_review") or {}).get("status") == "rejected"):
                continue
            records.append((entry, result))
        return records

    def search_research_history(self, terms, offset=0):
        if terms != []:
            terms = validated_terms(terms)
        if type(offset) is not int or offset < 0:
            raise ProbeError("INVALID_RESEARCH_HISTORY_OFFSET")
        ranked = []
        for entry, result in self._research_history():
            question = entry.get("user_question") or entry.get("interview_question") or ""
            claims = result.get("claims", [])
            parts = work_map_search_parts(result.get("work_map") or {})
            calculations = calculation_records(result)
            investigation = research_context(result) or {}
            text = match_text("\n".join([
                question, *(row["text"] for row in claims), *result.get("gaps", []),
                *(value for part in parts for value in part["fields"].values()),
                json.dumps(calculations, ensure_ascii=False),
                json.dumps(investigation, ensure_ascii=False),
            ]))
            hits = [term for term in terms if match_text(term) in text]
            if terms and not hits:
                continue
            matches = [index for index, claim in enumerate(claims)
                       if not terms or any(match_text(term) in match_text(claim["text"])
                                           for term in terms)]
            map_matches = []
            for part in parts:
                fields = [key for key, value in part["fields"].items()
                          if not terms or any(match_text(term) in match_text(value)
                                              for term in terms)]
                if fields:
                    map_matches.append({
                        "section": part["section"], "index": part["index"],
                        "matched_fields": fields, "basis": part.get("basis"),
                        "fields_preview": {key: value[:180]
                                           for key, value in part["fields"].items()},
                        "preview_is_partial": any(len(value) > 180
                                                  for value in part["fields"].values()),
                    })
            ranked.append((len(hits), entry["created_at"], entry["step_id"], {
                "step_id": entry["step_id"], "kind": entry["kind"], "question": question,
                "question_id": entry.get("question_id"), "recorded_at": entry["created_at"],
                "claim_previews": [{
                    "position": index + 1, "text_preview": claims[index]["text"][:180],
                    "preview_is_partial": len(claims[index]["text"]) > 180,
                    "basis": claims[index].get("basis"),
                    "requirement": claims[index].get("requirement"),
                } for index in matches[:3]],
                "matching_claim_count": len(matches), "matched_terms": hits,
                "map_previews": map_matches[:3], "map_match_count": len(map_matches),
                "investigation_previews": [{
                    "task_index": outcome["task_index"], "status": outcome["status"],
                    "answer_preview": outcome["answer"][:180],
                    "preview_is_partial": len(outcome["answer"]) > 180,
                } for outcome in investigation.get("outcomes") or []
                    if not terms or any(match_text(term) in match_text(outcome["answer"])
                                        for term in terms)][:3],
                **({"calculation_count": sum(len(rows) for rows in calculations.values())}
                   if calculations else {}),
            }))
        ranked.sort(key=lambda row: row[:3], reverse=True)
        page = ranked[offset:offset + 6]
        return {
            "research": [row[3] for row in page], "matching_count": len(ranked),
            "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(ranked) else None,
            "notice": "本目标已完成研究的关键词预览，包含工作地图的关系、理由、迁移限制和未知。"
            "预览可能省略末尾条件，不能当作完整内容、新证据或已确认的结论。"
            "先read_research_history读取完整判断与限定，再回读本轮可用原文。",
        }

    def read_research_history(self, step_id):
        found = next(((entry, result) for entry, result in self._research_history()
                      if entry["step_id"] == step_id), None)
        if not found:
            raise ProbeError("RESEARCH_HISTORY_NOT_AVAILABLE")
        entry, result = found
        references = {row["id"]: {key: deepcopy(row[key]) for key in (
            "title", "job_id", "document_id", "snapshot_id", "public_document_id",
            "start", "end", "evidence_kind", "historical_cutoffs",
        ) if row.get(key) is not None} for row in result.get("evidence", [])}
        for source in result.get("evidence", []):
            if source.get("job_id"):
                references[source["id"]]["as_of"] = (source.get("historical_cutoffs") or [
                    result.get("created_at") or entry["created_at"],
                ])[0]
        record = {
            "step_id": entry["step_id"], "kind": entry["kind"],
            "question": entry.get("user_question") or entry.get("interview_question") or "",
            "question_id": entry.get("question_id"), "recorded_at": entry["created_at"],
            "scope_then": deepcopy(result.get("scope")),
            "inquiry_at_start": deepcopy(result.get("career_learning_context", {}).get(
                "inquiry_at_start",
            )),
            "claim_details_to_recheck": [{
                "position": index + 1,
                **{key: claim.get(key) for key in ("text", "category", "basis", "requirement")},
                "source_references_to_reread": [references[key]
                                                for key in claim.get("evidence_ids", [])
                                                if key in references],
            } for index, claim in enumerate(result.get("claims", []))],
            "work_map_then": deepcopy(result.get("work_map")),
            "investigation_then": research_context(result),
            "unknowns_then": list(result.get("gaps", [])),
            "source_references_to_reread": list(references.values()),
        }
        if entry.get("answer"):
            record["user_reported_answer"] = entry["answer"]
            record["answer_document_id"] = entry.get("answer_document_id")
        learning = result.get("career_learning_context") or {}
        notes_then = [learning.get("selected_note"), learning.get("origin_learning_note"),
                      *learning.get("selected_notes", [])]
        record["learning_notes_then"] = list({row["id"]: {
            key: deepcopy(row.get(key)) for key in (
                "id", "task_id", "question_id", "previous_view", "reported_observation",
                "current_user_view", "open_question", "use_for_research", "recorded_at",
            )
        } for row in notes_then if row}.values())
        if learning.get("retrieval_review"):
            record["retrieval_review_then"] = deepcopy(learning["retrieval_review"])
        if learning.get("feedback_origin"):
            record["feedback_origin"] = deepcopy(learning["feedback_origin"])
        if result.get("application_plan"):
            plan = deepcopy(result["application_plan"])
            for action in plan["actions"]:
                action["source_references_to_reread"] = [references[key]
                                                        for key in action.pop("evidence_ids", [])
                                                        if key in references]
            record["application_plan_then"] = plan
        if calculations := calculation_records(result):
            record["local_calculations"] = calculations
            record["local_calculation_notice"] = CALCULATION_NOTICE
        if focus := result.get("career_learning_context", {}).get("claim_to_review"):
            record["claim_to_review"] = deepcopy(focus)
        if comparison := result.get("career_learning_context", {}).get("understanding_comparison"):
            record["understanding_comparison"] = deepcopy(comparison)
        current_notes = relation_learning_notes(
            self.project_reader().get("career", {}).get("insights", []), step_id,
            active_only=True,
        )
        if current_notes:
            record["current_relation_notes"] = current_notes
        return {
            "research": record,
            "notice": "完整旧分析，只供重新核对；原范围、判断性质和末尾限定仍需保留。"
            "旧来源仅用于定位，不提供旧引用ID，须本轮读取原文后再引用。"
            "JD定位保留historical_cutoffs和as_of，用read_historical_job读取并核对snapshot_id；"
            "当前JD不能代替旧版本。当前范围以fixed_scope为准，已移出或其他目标的资料不自动恢复。"
            "current_relation_notes列当前选用的用户认识，包括明确接替原关系笔记的新理解；"
            "related_relation_indices是本地图work_relations从0开始的序号。"
            "接替记录可能参考其他资料，保留各自来源，不表示原图已修改或新解释已证实。"
            "user_reported_answer与learning_notes_then保留当时原回答与明确带入的个人认识，"
            "仍是自述和待检验理解；不以现在编辑的认识替换。retrieval_review_then只是当时"
            "带入的运行线索，未在本轮重跑，不能作为新的原文证据。"
            "application_plan_then是当时的建议与尚未执行的预期，引用改为原文定位；"
            "feedback_origin保留它明确针对的反馈与未知，不表示该未知已经解决。"
            "计划不等于实际结果，旧研究不能证明当前事实或个人能力，不修改原记录。",
        }


def recall_learning_notes(career, step, goal, *, limit=3):
    runs = {row["step_id"]: row for row in career.get("runs", [])}
    entry = runs.get(step["id"], {})
    previous = runs.get(entry.get("source_step_id"), {})
    source_steps = set()
    source = entry.get("source_step_id")
    while source and source not in source_steps:
        source_steps.add(source)
        source = runs.get(source, {}).get("source_step_id")
    notes_by_id = {note["id"]: note for note in career.get("insights", [])}
    inquiry_id, task_id = step.get("career_question_id"), step.get("career_task_id")
    inquiry = next((row for row in career.get("questions", []) if row["id"] == inquiry_id), {})
    task = next((row for row in career.get("tasks", []) if row["id"] == task_id), {})
    story = next(
        (row for row in career.get("stories", []) if row["id"] == step.get("career_story_id")), {}
    )
    selected_note = next(
        (row for row in career.get("insights", []) if row["id"] == step.get("career_insight_id")),
        {},
    )
    family = {
        row["id"] for row in learning_family(career.get("insights", []), selected_note.get("id"))
    }
    focused_query = "\n".join(
        str(value or "")
        for value in (
            entry.get("user_question"),
            entry.get("hypothesis_a"),
            entry.get("hypothesis_b"),
            entry.get("interview_question"),
            entry.get("requirement_text"),
            previous.get("user_question"),
            inquiry.get("question"),
            task.get("title"),
            task.get("task_or_ability"),
            story.get("title"),
        )
    ).strip()
    query_tokens = _tokens(focused_query or goal)
    ranked = []
    for index, note in enumerate(career.get("insights", [])):
        if not note.get("use_for_research", True):
            continue
        linked = bool(
            task_id
            and note.get("task_id") == task_id
            or inquiry_id
            and inquiry_id in {link["question_id"] for link in learning_inquiry_links(career, note)}
        )
        revision = note["id"] in family and note["id"] != selected_note.get("id")
        origin, visited, source_linked = note, set(), False
        while origin and origin["id"] not in visited:
            visited.add(origin["id"])
            if origin.get("source_step_id") in source_steps:
                source_linked = True
                break
            origin = notes_by_id.get(origin.get("replaces_insight_id"))
        text = "\n".join(
            note.get(key, "")
            for key in ("previous_view", "observation", "current_view", "open_question")
        )
        matches = sorted(query_tokens & _tokens(text))
        reason = (
            "same_discussion"
            if source_linked
            else "belief_revision"
            if revision
            else "same_inquiry_or_experiment"
            if linked
            else "keyword"
            if matches
            else "recent"
        )
        ranked.append(
            (
                2 if source_linked else int(linked or revision),
                len(matches),
                note.get("updated_at") or note["created_at"],
                index,
                note,
                {"id": note["id"], "reason": reason, "matched_terms": matches},
            )
        )
    ranked.sort(key=lambda row: row[:4], reverse=True)
    relevant = [row for row in ranked if row[0] or row[1]]
    chosen = (relevant if focused_query or relevant else ranked)[:limit]
    return [row[4] for row in chosen], {
        "eligible_count": len(ranked),
        "omitted_count": max(0, len(ranked) - len(chosen)),
        "selections": [row[5] for row in chosen],
    }


def learning_record(row, record, store):
    note = {
        "id": row["id"],
        "replaces_insight_id": row.get("replaces_insight_id"),
        "task_id": row.get("task_id"),
        "question_id": row.get("question_id"),
        "source_step_id": row.get("source_step_id"),
        "source_task_index": row.get("source_task_index"),
        "source_investigation_task": record_task_context(record, row, store),
        "previous_view": row["previous_view"],
        "source_passage": deepcopy(row.get("source_passage")),
        "source_passages": deepcopy(row.get("source_passages", [])),
        "source_locators": [*([deepcopy(row["source_passage"])]
                              if row.get("source_passage") else []),
                            *deepcopy(row.get("source_passages", []))],
        "reported_observation": row["observation"],
        "current_user_view": row["current_view"],
        "open_question": row["open_question"],
        "use_for_research": row.get("use_for_research", True),
        "notice": "用户自己的理解与疑问，不是已验证的事实；保留原话中的限制。",
        "recorded_at": row.get("updated_at") or row["created_at"],
    }
    inquiry = next((item for item in record.get("career", {}).get("questions", [])
                    if item["id"] == row.get("question_id")), None)
    experiment = next((item for item in record.get("career", {}).get("tasks", [])
                       if item["id"] == row.get("task_id")), None)
    if experiment:
        note["linked_experiment"] = deepcopy(experiment)
        for key, origin in {
            "claim_to_verify": experiment_claim_origin(record, experiment, store),
            "relation_to_verify": experiment_relation_origin(record, experiment, store),
            "task_to_verify": record_task_context(record, experiment, store),
            "template_origin": experiment_template_origin(record, experiment, store),
        }.items():
            if origin:
                note["linked_experiment"][key] = origin
        note["experiment_notice"] = (
            "读取时当前保存的实验设计与观察，不代表已独立验证；完成状态也不证明能力或因果。"
            "artifact_document_id只供定位，本轮仍需读取可用原文；不自动恢复已移出的材料。"
        )
    if inquiry:
        note["inquiry_question"] = inquiry["question"]
        note["inquiry_notice"] = "关联问题的当前表述，只供定位；不改变这份认识的原话或采用状态。"
        if (inquiry.get("carried_understanding") or {}).get("learning_notes"):
            note["source_understanding_comparison"] = deepcopy(inquiry["carried_understanding"])
    links = learning_inquiry_links(record.get("career", {}), row)
    note["inquiry_links"] = links
    if links:
        note["inquiry_links_notice"] = (
            "关联线索来自明确选定的问题、实验、综合讨论或被接替认识；"
            "不是对所有问题的适用证明。继承关联时先核对新认识缩窄了哪些条件，"
            "不能恢复被搁置的旧认识或把新认识外推到原来的全部范围。"
        )
    index = row.get("source_claim_index")
    if index is not None or links or row.get("source_step_id"):
        source_step = next(
            (item for item in record["steps"] if item["id"] == row.get("source_step_id")),
            None,
        )
        run = (
            store.get(source_step["run_id"]) if source_step and source_step.get("run_id") else None
        )
        result = (run or {}).get("result") or {}
        if (run or {}).get("state") == "invalidated":
            result = {}
        if focus := result.get("career_learning_context", {}).get("claim_to_review"):
            note["source_claim_review"] = deepcopy(focus)
        if comparison := result.get("career_learning_context", {}).get("understanding_comparison"):
            note["source_understanding_comparison"] = deepcopy(comparison)
        claims = result.get("claims", [])
        selected = [claims[index]] if index is not None and 0 <= index < len(claims) else (
            claims if (links or row.get("source_step_id")) and index is None else []
        )
        if (relation_index := row.get("source_relation_index")) is not None:
            selected = []
            relations = (result.get("work_map") or {}).get("work_relations", [])
            entry = next((item for item in record.get("career", {}).get("runs", [])
                          if item["step_id"] == row.get("source_step_id")), None)
            if entry and 0 <= relation_index < len(relations):
                note["source_relation_index"] = relation_index
                note["source_relation"] = work_relation_record(
                    record, entry, result, relation_index, False,
                )
                note["source_relation_notice"] = (
                    "来源地图中明确选定的原关系，保留当时的连接理由、迁移限制与引用。"
                    "这是历史Agent解释，用户的新认识也不是已核实事实，仍需回读原文与验证。"
                )
                selected = [claims[n] for n in relations[relation_index]["claim_indices"]
                            if 0 <= n < len(claims)]
        if task := note.get("source_investigation_task"):
            selected = task["claims"]
            note["source_locators"].extend(deepcopy(task["evidence"]))
        if calculations := calculation_records(result):
            note["source_calculations"] = calculations
            note["source_calculation_notice"] = CALCULATION_NOTICE
        if selected:
            context = result.get("career_learning_context", {})
            if context.get("inquiry_at_start"):
                note["source_inquiry"] = deepcopy(context["inquiry_at_start"])
                note["source_inquiry_notice"] = (
                    "来源讨论开始时的调查目的、用户解释与待核条件，不是现在的问题内容。"
                    "用户目的、经历自述与取舍不等于岗位事实或能力证明，"
                    "也不能不经核对就沿用为当前场景的偏好或结论。"
                )
            if context.get("selected_experiments"):
                note["source_experiments"] = deepcopy(context["selected_experiments"])
                note["source_experiments_notice"] = (
                    "这份认识参考的来源讨论启动时选定的完整实验输入，不是实验当前内容。"
                    "预期、计划和用户记录的观察分别保留；不是本轮新证据或独立验证，"
                    "仍需按本轮范围读取产物原文并核对适用条件。"
                )
            inputs = [
                *context.get("notes", []),
                *[item for item in (context.get("selected_note"), context.get("counter_note"),
                                   context.get("origin_learning_note")) if item],
                *context.get("selected_notes", []), *context.get("read_notes", []),
                *[{**item["memory"], "origin_project_id": item["project_id"],
                   "origin_project_title": item["project_title"]}
                  for item in context.get("read_other_goals", []) if item["kind"] == "insight"],
            ]
            if inputs:
                note["source_personal_inputs"] = [
                    {key: item.get(key) for key in (
                        "id", "previous_view", "reported_observation", "current_user_view",
                        "open_question", "use_for_research", "source_step_id", "question_id",
                        "origin_project_id", "origin_project_title",
                    )} for item in {
                        (item.get("origin_project_id"), item["id"]): item for item in inputs
                    }.values()
                ]
                note["source_personal_inputs_notice"] = (
                    "当时来源讨论带入或读取的个人观点与限定，不是新证据，"
                    "也不表示本份认识逐字继承全部观点。保留当时内容和选用状态，"
                    "不自动采用或恢复搁置记录，其他目标的认识需核对原场景。"
                )
            note["source_scope"] = result.get("scope")
            note["source_work_map"] = result.get("work_map")
            details = [{key: claim[key] for key in ("text", "category", "basis", "requirement")}
                       for claim in selected]
            if index is not None:
                note["original_analysis"] = details[0]
            else:
                note["source_discussion"] = {
                    "claims_to_recheck": details,
                    "unknowns_then": result.get("gaps", []),
                    "notice": "个人认识参考的原关系及其支撑判断，不表示采用旧解释。"
                    if relation_index is not None
                    else "个人认识参考的整次讨论，不是对某一条判断的逐字采用。",
                }
            references = {key for claim in selected for key in claim["evidence_ids"]}
            note["source_locators"] += [
                {
                    key: evidence[key]
                    for key in (
                        "job_id",
                        "public_document_id",
                        "snapshot_id",
                        "document_id",
                        "historical_cutoffs",
                        "start",
                        "end",
                        "quote",
                        "title",
                        "evidence_kind",
                    )
                    if key in evidence
                }
                for evidence in result.get("evidence", [])
                if evidence["id"] in references
            ]
            note["source_notice"] = (
                "这是形成用户认识时所选的旧分析与原文定位线索，不是当前事实或新证据。"
                "source_scope保留当时的资料范围，不能自动当作本轮选岗；"
                "source_work_map中的关系及迁移限定仍需重新核对。"
                "重查时应读取本轮可用原文，保留原分析的限定，不把旧引用编号用于新回答。"
            )
    return note
