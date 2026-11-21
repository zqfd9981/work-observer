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


class LearningNotebook:
    """Read current personal notes; only an explicitly focused family opens shelved history."""

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
        source = runs.get(note.get("source_step_id"), {})
        note_task = next(
            (row for row in career.get("tasks", []) if row["id"] == note.get("task_id")), {}
        )
        linked = bool(
            task_id
            and note.get("task_id") == task_id
            or inquiry_id
            and inquiry_id in {source.get("question_id"), note_task.get("question_id")}
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
        "source_step_id": row.get("source_step_id"),
        "previous_view": row["previous_view"],
        "reported_observation": row["observation"],
        "current_user_view": row["current_view"],
        "open_question": row["open_question"],
        "use_for_research": row.get("use_for_research", True),
        "notice": "用户自己的理解与疑问，不是已验证的事实；保留原话中的限制。",
        "recorded_at": row.get("updated_at") or row["created_at"],
    }
    if (index := row.get("source_claim_index")) is not None:
        source_step = next(
            (item for item in record["steps"] if item["id"] == row.get("source_step_id")),
            None,
        )
        run = (
            store.get(source_step["run_id"]) if source_step and source_step.get("run_id") else None
        )
        result = (run or {}).get("result") or {}
        claims = result.get("claims", [])
        if 0 <= index < len(claims):
            claim = claims[index]
            note["original_analysis"] = {
                key: claim[key] for key in ("text", "category", "basis", "requirement")
            }
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
                if evidence["id"] in claim["evidence_ids"]
            ]
            note["source_notice"] = (
                "这是形成用户认识时所选的旧分析与原文定位线索，不是当前事实或新证据。"
                "重查时应读取本轮可用原文，保留原分析的限定，不把旧引用编号用于新回答。"
            )
    return note
