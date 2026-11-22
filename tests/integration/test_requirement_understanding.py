"""A saved understanding can revisit its JD work after the current role analysis changes."""

import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace
from test_requirement_interview import RequirementInterviewModel

from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore


def test_requirement_feedback_understanding_practice_and_revision_keep_the_original_work(tmp_path):
    model = RequirementInterviewModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": "合成认识回查岗位" + str(i), "company": "合成团队" + str(i),
            "description": text, "data_kind": "synthetic",
        })["job_id"] for i, text in enumerate([
            "职责：建设检索评估集，核对失败样本。", "职责：维护端云同步和上下文。",
            "其他工作：维护支付接口。",
        ])]
        goal = post("/api/career", {
            "title": "合成岗位认识回查", "goal": "从具体职责形成待检验的理解",
            "job_ids": jobs, "material_title": "无关资料", "material_text": "支付接口笔记。",
        })
        base = "/api/career/" + goal["id"]
        model.selected_job, model.records = jobs[0], []
        model.unrelated_document = goal["materials"][0]["id"]

        def run(data):
            step = post(base + "/prepare", data)
            post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
            return row

        run({"kind": "role"})
        requirement = client.get(base).json()["requirements"][0]
        questions = run({"kind": "interview", "requirement_key": requirement["key"]})
        feedback = run({"kind": "answer", "source_step_id": questions["step_id"],
                        "answer": "我只知道评估集这个词，还不清楚该怎样核对失败样本。"})
        frozen = deepcopy(feedback["result"]["career_learning_context"]["requirement"])
        for source in frozen["evidence"]:
            source.pop("id", None)
            source.pop("citation_key", None)
        values = {
            "source_step_id": feedback["step_id"], "previous_view": "只要有评估集就足够了。",
            "observation": "原文同时写了评估集建设与失败样本核对，尚未实际执行。",
            "current_view": "评估集与失败样本要在固定资料和标注条件下核对，仍需验证适用范围。" * 38
            + "末尾限定：尚未进行语义或生产效果验证。",
            "open_question": "词面返回与语义相关性需要分开，不能从数量推定质量。" * 25
            + "末尾未知：怎样记录标注分歧仍不清楚。",
        }
        assert 1000 < len(values["current_view"]) <= 1500
        note = post(base + "/insights", values)["insights"][-1]
        post(base + "/insights/" + note["id"] + "/use", {"use_for_research": False})
        post(base + "/stories", {"title": "不应混入的支付经历", "situation": "支付接口",
                                "action": "只检查本地响应", "result": "未验证业务效果"})
        unrelated = post(base + "/experiments", {
            "title": "不应混入的支付练习", "task_or_ability": "检查支付响应",
            "deliverable": "局部日志", "completion_check": "核对本地输出",
        })["tasks"][-1]
        changed = client.patch(base + "/tasks/" + unrelated["id"], headers=auth, json={
            "state": "done", "outcome": "只有支付接口的一条局部观察。",
        })
        assert changed.status_code == 200

        # The latest role card now points elsewhere; the saved thought still belongs to JD 0.
        model.selected_job = jobs[1]
        run({"kind": "role"})
        assert client.get(base).json()["requirements"][0]["key"] != requirement["key"]
        model.selected_job = jobs[0]
        quiz = run({"kind": "teachback", "insight_id": note["id"]})
        assert quiz["requirement_key"] == requirement["key"]
        assert quiz["result"]["scope"]["archived_public_ids"] == []
        saved = quiz["result"]["career_learning_context"]
        assert saved["requirement"] == frozen
        assert saved["selected_note"]["source_requirement"] == frozen
        assert saved["selected_note"]["current_user_view"] == values["current_view"]
        assert saved["selected_note"]["open_question"] == values["open_question"]
        assert not saved["selected_note"]["use_for_research"]
        answer = run({"kind": "answer", "source_step_id": quiz["step_id"],
                      "answer": "我会保留标注分歧，不把本地返回数量直接当作语义质量。"})
        followup = run({"kind": "followup", "source_step_id": answer["step_id"]})
        rechecked = run({"kind": "ask", "insight_id": note["id"],
                         "question": "回查这份已搁置的认识，哪些条件需要缩窄？"})
        for row in (answer, followup, rechecked):
            assert row["result"]["career_learning_context"]["requirement"] == frozen
        replacement = post(base + "/insights", {
            **values, "source_step_id": rechecked["step_id"], "replaces_insight_id": note["id"],
            "previous_view": values["current_view"],
            "current_view": "局部词面检查只能用于定位失败，仍需记录标签条件和分歧。",
        })["insights"][-1]
        revised = run({"kind": "teachback", "insight_id": replacement["id"]})
        assert revised["result"]["career_learning_context"]["requirement"] == frozen
        historical = next(row for row in client.get(base).json()["results"]
                          if row["step_id"] == quiz["step_id"])
        assert historical["result"]["career_learning_context"] == saved
        old = next(row for row in client.get(base).json()["insights"] if row["id"] == note["id"])
        assert not old["use_for_research"]

        # Choosing a different current JD explicitly must keep the new scope under user control.
        transfer = post(base + "/prepare", {
            "kind": "ask", "insight_id": replacement["id"], "inherit_focus": False,
            "selected_job_ids": jobs[1:2], "question": "这份理解能否用于上下文管理？",
        })
        project = client.get("/api/projects/" + goal["id"]).json()
        step = next(row for row in project["steps"] if row["id"] == transfer["step_id"])
        assert step["job_ids"] == jobs[1:2] and not step.get("career_requirement")
        store = ResearchStore(tmp_path / "checkpoints.db",
                              namespace=str((tmp_path / "adaptive.db").resolve()))
        try:
            notebook = LearningNotebook(lambda: project, store, selected_note_id=note["id"])
            original = notebook.read(note["id"])["note"]
            assert original["source_requirement"] == frozen
            assert all("id" not in source and "citation_key" not in source
                       for source in original["source_requirement"]["evidence"])
        finally:
            store.close()
