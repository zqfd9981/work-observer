"""Home return points reflect explicit saved work, without truth or progress scores."""

from copy import deepcopy

from work_observer.research.resume import resume_items


def test_resume_uses_actual_observations_and_explicit_note_links_without_mutation():
    project = {
        "steps": [
            {"id": "paused", "state": "interrupted", "updated_at": "2026-11-03"},
            {"id": "ended", "state": "abandoned"},
        ],
        "career": {
            "runs": [
                {"step_id": "paused", "created_at": "2026-11-01", "user_question": "原问题"},
                {"step_id": "ended", "created_at": "2026-11-09"},
                {"step_id": "missing", "created_at": "2026-11-10"},
            ],
            "tasks": [
                {
                    "id": "already-noted",
                    "title": "已复盘",
                    "outcome": "失败记录",
                    "created_at": "01",
                },
                {
                    "id": "condition-only",
                    "title": "只有条件观察",
                    "outcome": "",
                    "created_at": "02",
                    "comparison_rows": [{"observed": "合成反例，未能验收。"}],
                },
                {
                    "id": "empty-done",
                    "title": "只有完成状态",
                    "state": "done",
                    "created_at": "03",
                    "outcome": "",
                    "completion_check": "尚需记录实际结果",
                },
            ],
            "insights": [
                {
                    "id": "noted",
                    "task_id": "already-noted",
                    "current_view": "旧理解",
                    "open_question": "仍有未知",
                    "created_at": "01",
                },
                {
                    "id": "parked",
                    "use_for_research": False,
                    "current_view": "搁置观点",
                    "open_question": "不自动推进",
                    "created_at": "99",
                },
            ],
            "questions": [
                {"id": "focus", "state": "open", "question": "关注的问题", "created_at": "01"},
                {"id": "newer", "state": "open", "question": "较新问题", "created_at": "02"},
                {"id": "answered", "state": "answered", "question": "已记结论", "created_at": "99"},
                {"id": "parked-q", "state": "parked", "question": "暂停调查", "created_at": "99"},
            ],
            "focus_question_id": "focus",
        },
    }
    before = deepcopy(project)
    items = {row["category"]: row for row in resume_items(project)}
    assert items["research"]["record_id"] == "paused"
    assert items["research"]["updated_at"] == "2026-11-03"
    assert items["observation"]["record_id"] == "condition-only"
    assert items["observation"]["body"] == "合成反例，未能验收。"
    assert items["experiment"]["record_id"] == "empty-done"
    assert items["understanding"]["record_id"] == "noted"
    assert items["question"]["record_id"] == "focus"
    assert "当前关注" in items["question"]["reason"]
    assert project == before
    project["career"]["focus_question_id"] = "parked-q"
    assert (
        next(row for row in resume_items(project) if row["category"] == "question")["record_id"]
        == "newer"
    )


def test_empty_work_has_no_invented_return_point():
    assert resume_items({"career": {}, "steps": []}) == []


def test_overall_summary_does_not_hide_a_negative_condition_observation():
    task = {
        "id": "sample",
        "title": "合成条件对照",
        "outcome": "整体记录已保存。",
        "comparison_rows": [{"condition": "改变验收权限", "observed": "合成反例：没有完成闭环。"}],
    }
    item = resume_items({"career": {"tasks": [task]}})[0]
    assert item["category"] == "observation"
    assert "整体记录已保存。" in item["body"]
    assert "改变验收权限：合成反例：没有完成闭环。" in item["body"]
