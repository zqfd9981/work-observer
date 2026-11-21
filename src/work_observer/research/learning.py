"""Recall personal understanding for the current question without adopting it as fact."""

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.service import _tokens
from work_observer.retrieval.enhanced import validated_terms
from work_observer.text_match import match_text


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

    def __init__(self, project_reader, store, selected_note_id=None, counter_note_id=None):
        self.project_reader = project_reader
        self.store = store
        self.selected_note_id = selected_note_id
        self.counter_note_id = counter_note_id

    def _available(self):
        project = self.project_reader()
        notes = project.get("career", {}).get("insights", [])
        historical = {row["id"] for identity in (self.selected_note_id, self.counter_note_id)
                      for row in learning_family(notes, identity)}
        return project, [
            row for row in notes if row.get("use_for_research", True) or row["id"] in historical
        ]

    def search(self, terms, offset=0):
        if terms != []:
            terms = validated_terms(terms)
        if type(offset) is not int or offset < 0:
            raise ProbeError("INVALID_LEARNING_OFFSET")
        _, notes = self._available()
        ranked = []
        for row in notes:
            text = match_text(
                "\n".join(
                    row.get(key, "")
                    for key in ("previous_view", "observation", "current_view", "open_question")
                )
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

    def source_document_ids(self):
        """The attached source library, independent of the short opening catalog."""
        return list(dict.fromkeys(self.project_reader().get("public_document_ids", [])))

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
            text = match_text("\n".join(row.get(key, "") for key in (
                "title", "task_or_ability", "deliverable", "completion_check",
                "hypothesis", "outcome", "design_change", "artifact",
            )))
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
                "has_reported_observation": bool(row.get("outcome", "").strip()),
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
                "prior_expectation": row.get("hypothesis", ""),
                "reported_observation": row.get("outcome", ""),
                "design_change": row.get("design_change", ""),
                "previous_task_id": row.get("previous_task_id"),
                "source_step_id": row.get("source_step_id"),
                "target_requirement": row.get("target_requirement"),
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


def recall_learning_notes(career, step, goal, *, limit=3):
    runs = {row["step_id"]: row for row in career.get("runs", [])}
    entry = runs.get(step["id"], {})
    previous = runs.get(entry.get("source_step_id"), {})
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
        text = "\n".join(
            note.get(key, "")
            for key in ("previous_view", "observation", "current_view", "open_question")
        )
        matches = sorted(query_tokens & _tokens(text))
        reason = (
            "belief_revision"
            if revision
            else "same_inquiry_or_experiment"
            if linked
            else "keyword"
            if matches
            else "recent"
        )
        ranked.append(
            (
                linked or revision,
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
        "previous_view": row["previous_view"],
        "reported_observation": row["observation"],
        "current_user_view": row["current_view"],
        "open_question": row["open_question"],
        "use_for_research": row.get("use_for_research", True),
        "notice": "用户自己的理解与疑问，不是已验证的事实；保留原话中的限制。",
        "recorded_at": row.get("updated_at") or row["created_at"],
    }
    inquiry = next((item for item in record.get("career", {}).get("questions", [])
                    if item["id"] == row.get("question_id")), None)
    if inquiry:
        note["inquiry_question"] = inquiry["question"]
        note["inquiry_notice"] = "关联问题的当前表述，只供定位；不改变这份认识的原话或采用状态。"
    links = learning_inquiry_links(record.get("career", {}), row)
    note["inquiry_links"] = links
    if links:
        note["inquiry_links_notice"] = (
            "关联线索来自明确选定的问题、实验、综合讨论或被接替认识；"
            "不是对所有问题的适用证明。继承关联时先核对新认识缩窄了哪些条件，"
            "不能恢复被搁置的旧认识或把新认识外推到原来的全部范围。"
        )
    index = row.get("source_claim_index")
    if index is not None or links:
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
        claims = result.get("claims", [])
        selected = [claims[index]] if index is not None and 0 <= index < len(claims) else (
            claims if links and index is None else []
        )
        if selected:
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
                    "notice": "个人认识参考的整次讨论，不是对某一条判断的逐字采用。",
                }
            references = {key for claim in selected for key in claim["evidence_ids"]}
            note["source_locators"] = [
                {
                    key: evidence[key]
                    for key in (
                        "job_id",
                        "public_document_id",
                        "snapshot_id",
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
