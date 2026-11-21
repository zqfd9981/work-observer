"""Bring explicitly selected inquiries into one source-based investigation."""

from work_observer.research.learning import learning_record, recall_learning_notes


def synthesis_inquiries(record, store, selections):
    career = record["career"]
    questions = {row["id"]: row for row in career.get("questions", [])}
    steps = {row["id"]: row for row in record["steps"]}
    result = []
    for selection in selections:
        question = questions.get(selection["question_id"])
        if not question:
            continue
        previous_step = steps.get(selection.get("step_id"), {})
        run = store.get(previous_step["run_id"]) if previous_step.get("run_id") else {}
        previous = (run or {}).get("result") or {}
        available = previous.get("status") == "completed" and run.get("state") != "invalidated"
        discussion = None
        if available:
            discussion = {
                "step_id": previous_step["id"],
                "source_cutoff": previous.get("created_at"),
                "scope": previous.get("scope"),
                "same_goal_scope": previous_step["scope_version"] == record["scope_version"],
                "claims_to_recheck": [
                    {key: claim.get(key) for key in ("text", "category", "basis", "requirement")}
                    for claim in previous.get("claims", [])
                ],
                "work_map": previous.get("work_map"),
                "unresolved_then": previous.get("gaps", []),
                "source_references_to_reread": [
                    {
                        key: source.get(key)
                        for key in (
                            "title",
                            "evidence_kind",
                            "job_id",
                            "public_document_id",
                            "document_id",
                            "snapshot_id",
                            "historical_cutoffs",
                            "start",
                            "end",
                        )
                    }
                    for source in previous.get("evidence", [])
                ],
            }
        tasks = [row for row in career["tasks"] if row.get("question_id") == question["id"]]
        tasks.sort(key=lambda row: row.get("updated_at") or row["created_at"], reverse=True)
        notes, recall = recall_learning_notes(
            career,
            {"id": "", "career_question_id": question["id"]},
            record["goal"],
        )
        task_ids = {row["id"] for row in tasks}
        source_steps = {
            row["step_id"] for row in career["runs"] if row.get("question_id") == question["id"]
        }
        notes = [
            row
            for row in notes
            if row.get("question_id") == question["id"]
            or row.get("task_id") in task_ids
            or row.get("source_step_id") in source_steps
        ]
        result.append(
            {
                "inquiry": question,
                "discussion": discussion,
                "discussion_unavailable": bool(selection.get("step_id") and not available),
                "experiments": [
                    {
                        **{
                            key: task.get(key)
                            for key in (
                                "id",
                                "title",
                                "task_or_ability",
                                "deliverable",
                                "completion_check",
                                "hypothesis",
                                "state",
                                "outcome",
                                "design_change",
                                "previous_task_id",
                                "created_at",
                                "updated_at",
                            )
                        },
                        "artifact_document": {
                            "document_id": task["artifact_document_id"],
                            "title": task.get("artifact_title"),
                        }
                        if task.get("artifact_document_id")
                        else None,
                    }
                    for task in tasks[:3]
                ],
                "omitted_experiments": max(0, len(tasks) - 3),
                "learning_notes": [learning_record(row, record, store) for row in notes],
                "learning_recall": recall,
            }
        )
    return result
