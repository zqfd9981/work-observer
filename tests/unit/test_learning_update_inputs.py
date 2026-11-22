"""A new personal understanding retains the full old inputs of its source discussion."""

from copy import deepcopy

from work_observer.research.learning import learning_record


def test_updated_understanding_retains_local_reads_and_cross_goal_views_with_origin():
    local = {"id": "local", "previous_view": "原先理解", "reported_observation": "观察",
             "current_user_view": "开头带入的旧理解", "open_question": "未知",
             "use_for_research": True}
    later = {**local, "current_user_view": "本轮稍后读取的完整理解。" * 70 + "末尾条件仍保留。"}
    cross = {**local, "id": "cross", "current_user_view": "另一个场景的完整限定。" * 70,
             "use_for_research": False}
    result = {"claims": [{"text": "新资料描述交付对象。", "category": "task",
                          "basis": "inference", "requirement": "unspecified", "evidence_ids": []}],
              "evidence": [], "gaps": ["权限未知"], "career_learning_context": {
                  "notes": [local], "selected_note": local, "read_notes": [later],
                  "read_other_goals": [{"project_id": "source-goal", "project_title": "原工作场景",
                                        "kind": "insight", "memory": cross}],
              }}
    note = {"id": "new-note", "previous_view": "需要核对旧理解。", "observation": "本轮观察。",
            "current_view": "用户自行写的新理解。", "open_question": "权限仍未知。",
            "source_step_id": "current-study", "created_at": "2026-11-22T00:00:00Z"}
    project = {"steps": [{"id": "current-study", "run_id": "run"}], "career": {"runs": []}}
    store = type("Store", (), {"get": lambda self, identity: {
        "state": "completed", "result": result,
    }})()
    before = deepcopy(result)
    saved = learning_record(note, project, store)
    inputs = saved["source_personal_inputs"]
    assert len(inputs) == 2
    assert inputs[0]["current_user_view"] == later["current_user_view"]
    assert inputs[1]["current_user_view"] == cross["current_user_view"]
    assert inputs[1]["origin_project_id"] == "source-goal"
    assert inputs[1]["origin_project_title"] == "原工作场景"
    assert inputs[1]["use_for_research"] is False
    inputs[0]["current_user_view"] = "只改变返回对象。"
    assert result == before
