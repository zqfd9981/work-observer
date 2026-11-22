"""A saved multi-intent answer must remain searchable and readable beyond flat claims."""

from copy import deepcopy

from work_observer.research.investigation_memory import recall
from work_observer.research.learning import LearningNotebook


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
