"""A saved multi-intent answer must remain searchable and readable beyond flat claims."""

from copy import deepcopy

from work_observer.research.investigation_memory import interview_context, interview_origin, recall
from work_observer.research.learning import LearningNotebook


def test_identical_interview_questions_keep_the_selected_task_and_its_read_locators():
    question = "如何说明失败处理与验证边界？"
    result = {"status": "completed", "interview_questions": [question, question], "claims": [
        {"text": "合成任务A", "category": "task", "evidence_ids": ["a"]},
        {"text": "合成任务B", "category": "task", "evidence_ids": ["b"]},
    ], "evidence": [
        {"id": key, "quote": "旧引用不能当本轮新证据", "job_id": key, "snapshot_id": "version",
         "start": 0, "end": 12} for key in ("a", "b")
    ], "investigation": {"tasks": [
        {"intent": "interview", "question": "工作A的失败处理"},
        {"intent": "interview", "question": "工作B的验证边界"},
    ], "outcomes": [
        {"task_index": i, "status": "answered", "answer": "历史解释，不是标准答案。",
         "questions": [question], "claim_indices": [i]} for i in range(2)
    ]}}
    origin = interview_origin(result, "root", 1)
    assert origin["task_index"] == 1 and origin["question_index"] == 1
    assert interview_origin(result, "root", True) is None
    changed = deepcopy(result)
    changed["interview_questions"] = ["另一道题？", question]
    assert interview_origin(changed, "root", 1) is None

    class Store:
        state = "completed"

        def get(self, identity):
            assert identity == "root-run"
            return {"state": self.state, "result": deepcopy(result)}

    store = Store()
    project = {"steps": [{"id": "root", "run_id": "root-run"}]}
    context = interview_context(project, origin, store)
    assert context["available"] and context["task"]["question"] == "工作B的验证边界"
    assert {row["job_id"] for row in context["source_references_to_reread"]} == {"b"}
    assert "旧引用不能当本轮新证据" not in str(context)
    assert "evidence_ids" not in context["claim_details_to_recheck"][0]
    store.state = "invalidated"
    unavailable = interview_context(project, origin, store)
    assert not unavailable["available"] and "task" not in unavailable
    assert unavailable["task_index"] == 1


def test_nested_answer_is_recalled_with_full_final_condition_and_original_scope():
    answer = "双写对账：" + "先记录同一输入的两个结果。" * 40 + "末尾限制：尚未证明生产一致性。"
    investigation = {
        "original_question": "为什么会出现两个结果？", "objective": "解释异常并提出验证。",
        "constraints": [{"field": "city", "value": "上海", "source_text": "只看上海"}],
        "effective_scope": {"job_ids": ["original-job"], "public_document_ids": []},
        "tasks": [{"intent": "verify", "question": "两个结果来自哪里？",
                   "completion": "区分观察与因果。", "missing_source_keys": ["missing-side"]}],
        "outcomes": [{"task_index": 0, "status": "partial", "answer": answer,
                      "claim_indices": [], "questions": []}],
        "missing_context": ["另一侧日志尚未提供。"],
        "memory_recall": {"records": [{"record_id": "older-preview"}]},
    }
    result = {"status": "completed", "claims": [], "gaps": ["尚未完成验证。"],
              "evidence": [], "scope": {"jobs": [{"id": "original-job"}]},
              "investigation": investigation}
    project = {"id": "goal", "steps": [{"id": "step", "run_id": "run"}], "career": {
        "runs": [{"step_id": "step", "kind": "ask", "user_question": "两个结果？",
                  "created_at": "2026-11-23T00:00:00Z"}], "insights": [],
    }}

    class Store:
        def get(self, _identity):
            return {"state": "completed", "result": deepcopy(result)}

    notebook = LearningNotebook(lambda: deepcopy(project), Store())
    found = notebook.search_research_history(["双写对账"])
    assert found["matching_count"] == 1
    preview = found["research"][0]["investigation_previews"][0]
    assert preview["preview_is_partial"] and "末尾限制" not in preview["answer_preview"]
    full = notebook.read_research_history("step")["research"]
    context = full["investigation_then"]
    assert context["outcomes"][0]["answer"] == answer
    assert context["constraints"] == investigation["constraints"]
    assert context["effective_scope"] == investigation["effective_scope"]
    assert context["tasks"][0]["missing_source_keys"] == ["missing-side"]
    assert "memory_recall" not in context  # Do not recursively promote previews into old knowledge.
    assert "evidence" not in full
    recalled = recall(notebook, {"tasks": [{"attempts": [{"terms": ["双写对账"]}]}]})
    assert recalled["records"][0]["read_arguments"] == {"step_id": "step"}
    assert recalled["records"][0]["derived"]
