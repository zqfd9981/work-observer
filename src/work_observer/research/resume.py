"""Concrete return points derived from saved work, without executing research."""


def resume_items(project):
    career = project["career"]
    notes = career.get("insights", [])
    tasks = career.get("tasks", [])
    steps = {row["id"]: row for row in project.get("steps", [])}
    items = []

    def add(category, kind, row, title, body, reason, *, identity=None):
        items.append({
            "category": category, "kind": kind, "record_id": identity or row["id"],
            "title": title, "body": body, "reason": reason,
            "updated_at": row.get("updated_at") or row.get("created_at", ""),
            "question_id": row.get("question_id"),
        })

    for entry in career.get("runs", []):
        step = steps.get(entry["step_id"], {})
        if step.get("state") in {"queued", "running", "interrupted", "failed", "waiting_material"}:
            add("research", "discussion", {**entry, "updated_at": step.get("updated_at")
                                           or entry.get("created_at", "")},
                entry.get("user_question") or entry.get("interview_question") or "未完成的研究记录",
                "", "这轮仍保留未完成状态，先回看已有进度与原文，再决定下一步。",
                identity=entry["step_id"])
    for task in tasks:
        observations = [
            (row.get("condition", "").strip() + "：" if row.get("condition", "").strip() else "")
            + row["observed"].strip()
            for row in task.get("comparison_rows", []) if row.get("observed", "").strip()
        ]
        outcome = task.get("outcome", "").strip()
        if outcome or observations:
            if not any(note.get("task_id") == task["id"] for note in notes):
                add("observation", "task", task, task["title"],
                    "\n\n".join([value for value in [outcome, *observations] if value]),
                    "已有用户记录的观察，尚无直接关联这项实验的个人认识记录。")
        else:
            add("experiment", "task", task, task["title"],
                task.get("hypothesis") or task.get("completion_check", ""),
                "已有实验设计与状态，还没有保存实际观察；可先查看计划与检查方式。")
    for note in notes:
        if note.get("use_for_research", True) and note.get("open_question", "").strip():
            add("understanding", "understanding", note, note["current_view"], note["open_question"],
                "这份选用中的个人认识保留了待核条件，可回看来源与相关研究。")
    for question in career.get("questions", []):
        if question["state"] == "open":
            add("question", "investigate", question, question["question"],
                question.get("next_evidence", ""), "这条调查仍开放，可沿保存的问题与资料继续查证。")

    # One recent return point per category keeps the home page concise.
    recent = {}
    for item in sorted(items, key=lambda row: (row["updated_at"], row["record_id"]), reverse=True):
        recent.setdefault(item["category"], item)
    focus = next((item for item in items if item["category"] == "question"
                  and item["record_id"] == career.get("focus_question_id")), None)
    if focus:
        focus["reason"] = "这是你当前关注的开放调查，可沿保存的问题与资料继续查证。"
        recent["question"] = focus
    return list(recent.values())
