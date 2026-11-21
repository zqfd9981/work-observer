"""Recall personal understanding for the current question without adopting it as fact."""

from work_observer.memory.service import _tokens


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
