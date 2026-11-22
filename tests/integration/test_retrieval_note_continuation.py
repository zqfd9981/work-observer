"""A saved user understanding can be tested again without a model or implicit adoption."""

import re

from starlette.testclient import TestClient
from test_adaptive_investigation import workspace

from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore


def test_note_replay_keeps_full_thought_and_original_inputs_then_records_explicit_revision(
    tmp_path, monkeypatch,
):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Replaying a local experiment must not call a model")

    monkeypatch.setattr(ModelClient, "turn", forbidden)
    with TestClient(workspace(tmp_path, None), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": "合成复验岗位" + str(i), "company": "合成公司" + str(i),
            "description": text, "data_kind": "synthetic",
        })["job_id"] for i, text in enumerate([
            "负责端云同步与记忆管理。", "负责知识库检索与重排。",
        ])]
        created = post("/api/career", {
            "title": "合成认识复验", "goal": "用已有原文反驳或限定自己的查询解释", "job_ids": jobs,
            "first_question": "没有检索到，是否就说明岗位没有这项工作？",
            "material_title": "合成工作说明", "material_text": "端云同步应保留上下文条件。",
        })
        goal, document = created["id"], created["materials"][0]["id"]
        base = "/api/career/" + goal
        inputs = {"baseline": {"terms": ["RAG"]}, "candidate": {"terms": ["端云同步"]},
                  "job_ids": jobs[:1], "document_ids": [document],
                  "expected_job_ids": jobs[:1], "expected_document_ids": [document],
                  "question_id": created["focus_question_id"], "save": True}
        parent = post(base + "/experiments/retrieval", inputs)
        parent_task = parent["career"]["tasks"][-1]
        note_data = {
            "task_id": parent_task["id"], "question_id": created["focus_question_id"],
            "previous_view": "只要有RAG这个词就能找到全部相关工作。",
            "observation": "原表达未返回同步原文；改写后返回了两份原文。",
            "current_view": "词面返回受表达和片段上限影响，未独立验证语义。🤔" * 45
                            + "末尾限定：只讨论这个小样本，不推断岗位没有这项工作。",
            "open_question": "减少返回片段后，会遗漏哪份预期原文？未返回是否仍能支持原判断？",
        }
        note = post(base + "/insights", note_data)["insights"][-1]
        post(base + "/insights/" + note["id"] + "/use", {"use_for_research": False})
        before = client.get(base).json()
        replay_inputs = {**inputs, "previous_task_id": parent_task["id"],
                         "source_insight_id": note["id"], "hypothesis": note["current_view"],
                         "top_k": 1}
        preview = post(base + "/experiments/retrieval", {**replay_inputs, "save": False})
        assert client.get(base).json() == before
        saved = post(base + "/experiments/retrieval", replay_inputs)
        task = saved["career"]["tasks"][-1]
        snapshot = saved["experiment"]["note_origin"]
        assert snapshot["current_view"] == note_data["current_view"]
        assert snapshot["observation"] == note_data["observation"]
        assert snapshot["open_question"] == note_data["open_question"]
        assert not snapshot["use_for_research"]
        assert snapshot["id"] == note["id"] and snapshot["task_id"] == parent_task["id"]
        assert preview["experiment"]["note_origin"] == snapshot
        assert task["retrieval_note_origin"] == snapshot
        assert task["hypothesis"] == note_data["current_view"]
        assert task["previous_task_id"] == parent_task["id"]
        assert saved["experiment"]["input"] == {**parent["experiment"]["input"], "top_k": 1}
        assert saved["career"]["insights"] == before["insights"]
        artifact = client.get("/api/public-documents/" + task["artifact_document_id"]).json()[
            "text"
        ]
        assert note_data["current_view"] in artifact

        edited_data = {**note_data, "current_view": "后来编辑的理解，不能替换旧运行时的认识。"}
        changed = client.patch(base + "/insights/" + note["id"], headers=auth, json=edited_data)
        assert changed.status_code == 200, changed.text
        loaded = client.get(base + "/tasks/" + task["id"] + "/retrieval-inputs").json()
        assert loaded["previous"]["note_origin"] == snapshot
        assert client.get("/api/public-documents/" + task["artifact_document_id"]).json()[
            "text"
        ] == artifact
        prepared = post(base + "/prepare", {"kind": "reflect", "task_id": task["id"]})
        project = client.get("/api/projects/" + goal).json()
        step = next(row for row in project["steps"] if row["id"] == prepared["step_id"])
        assert step["career_retrieval_review"]["note_origin"] == snapshot
        assert step["job_ids"] == jobs[:1]
        assert client.delete(base + "/steps/" + step["id"], headers=auth).status_code == 200
        store = ResearchStore(tmp_path / "checkpoints.db",
                              namespace=str((tmp_path / "adaptive.db").resolve()))
        try:
            read = LearningNotebook(lambda: project, store).read_experiments([task["id"]])[
                "experiments"
            ][0]
            assert read["note_to_verify"] == snapshot
        finally:
            store.close()
        later = post(base + "/experiments/retrieval", {
            **replay_inputs, "previous_task_id": task["id"], "save": False,
        })
        assert later["experiment"]["note_origin"]["current_view"] == edited_data["current_view"]
        unrelated = post(base + "/insights", {
            "previous_view": "另一解释", "observation": "无关联实验", "current_view": "其他未知。",
        })["insights"][-1]
        invalid = client.post(base + "/experiments/retrieval", headers=auth, json={
            **replay_inputs, "source_insight_id": unrelated["id"],
        })
        assert invalid.status_code == 422
        # Preparing the new thought is explicit; running retrieval never rewrites the old note.
        revised = post(base + "/insights", {
            "task_id": task["id"], "question_id": task["question_id"],
            "replaces_insight_id": note["id"], "previous_view": snapshot["current_view"],
            "observation": task["outcome"],
            "current_view": "返回片段变少会漏掉部分预期原文，不能据此说岗位没有这项工作。",
            "open_question": snapshot["open_question"],
        })
        assert revised["insights"][-1]["replaces_insight_id"] == note["id"]
        assert revised["insights"][0]["current_view"] == edited_data["current_view"]
        assert not revised["insights"][0]["use_for_research"]
        assert revised["usage"]["calls"] == 0
