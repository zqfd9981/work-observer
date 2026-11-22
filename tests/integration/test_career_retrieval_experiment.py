"""Actual isolated retrieval; user expectations are not semantic ground truth."""

import json
import re

from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace
from test_investigation_interview_flow import InterviewFlowModel

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


def test_interview_feedback_can_lead_to_query_execution_note_and_next_validation(tmp_path):
    model = InterviewFlowModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        jobs = [client.post("/api/import", headers=auth, json={
            "title": "合成工作线" + str(i), "company": "合成公司" + str(i),
            "description": text, "data_kind": "synthetic",
        }).json()["job_id"] for i, text in enumerate([
            "负责知识库检索与重排。", "负责端云同步与记忆管理。",
        ])]
        model.jobs = jobs
        for i, task in enumerate(model.planner.plan["tasks"]):
            task["source_job_ids"] = [jobs[i]]
        goal = client.post("/api/career", headers=auth, json={
            "title": "合成反馈后验证", "goal": "用实际原文检验查询解释", "job_ids": jobs,
        }).json()["id"]
        base = f"/api/career/{goal}"

        def run(values):
            prepared = client.post(base + "/prepare", headers=auth, json=values)
            assert prepared.status_code == 201, prepared.text
            step = prepared.json()["step_id"]
            client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row
            return row

        root = run({"kind": "ask", "adaptive": True, "question": "分别准备两种工作的面试问题。"})
        answer = "我只完成本地构造输入，尚未验证真实端云同步。"
        feedback = run({"kind": "answer", "source_step_id": root["step_id"],
                        "question_index": 1, "answer": answer})
        calls = len(model.contexts)
        inputs = {"source_step_id": feedback["step_id"], "job_ids": jobs,
                  "baseline": {"terms": ["重排"]}, "candidate": {"terms": ["端云同步"]},
                  "expected_job_ids": [jobs[1]], "save": True}
        rejected = client.post(base + "/experiments/retrieval", headers=auth,
                               json={**inputs, "source_step_id": root["step_id"]})
        assert rejected.status_code == 422
        response = client.post(base + "/experiments/retrieval", headers=auth, json=inputs)
        assert response.status_code == 201, response.text
        saved = response.json()
        experiment = next(row for row in saved["career"]["tasks"] if row["id"] == saved["task_id"])
        assert experiment["source_step_id"] == feedback["step_id"]
        assert experiment["purpose"] == "understanding_check"
        carried = client.get(base + "/tasks/" + experiment["id"] + "/retrieval-inputs")
        assert carried.json()["previous"]["source_step_id"] == feedback["step_id"]
        continued = client.post(base + "/experiments/retrieval", headers=auth, json={
            **inputs, "previous_task_id": experiment["id"],
        })
        assert continued.status_code == 201, continued.text
        continued_task = next(row for row in continued.json()["career"]["tasks"]
                              if row["id"] == continued.json()["task_id"])
        assert continued_task["source_step_id"] == feedback["step_id"]
        assert continued_task["previous_task_id"] == experiment["id"]
        note = client.post(base + "/insights", headers=auth, json={
            "task_id": experiment["id"], "source_step_id": feedback["step_id"],
            "previous_view": answer, "observation": "我用两组查询核对了本地返回。",
            "current_view": "这组资料需要区分查询主题，尚不能推断自己的实际端云能力。",
            "open_question": "加入新的反例原文后，是否仍能区分？",
        })
        assert note.status_code == 201, note.text
        follow = client.post(base + "/experiments", headers=auth, json={
            "previous_task_id": experiment["id"], "title": "加入反例再检查",
            "task_or_ability": "区分检索与相关性", "deliverable": "反例输入与输出记录",
            "completion_check": "逐项核对额外返回。", "design_change": "改变对照原文。",
        })
        assert follow.status_code == 201, follow.text
        next_task = follow.json()["tasks"][-1]
        assert next_task["source_step_id"] == feedback["step_id"]
        assert next_task["state"] == "planned" and not next_task["outcome"]
        project = client.get("/api/projects/" + goal).json()
        store = ResearchStore(tmp_path / "checkpoints.db",
                              namespace=str((tmp_path / "adaptive.db").resolve()))
        try:
            record = LearningNotebook(lambda: project, store).read_experiments([next_task["id"]])[
                "experiments"
            ][0]
            assert record["answer_to_verify"]["user_answer"] == answer
            assert record["answer_to_verify"]["step_id"] == feedback["step_id"]
        finally:
            store.close()
        assert len(model.contexts) == calls


def test_local_queries_compare_sources_and_save_real_output_without_model(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("This exercise must not call a model")

    monkeypatch.setattr(ModelClient, "turn", forbidden)
    path = tmp_path / "retrieval.db"
    upgrade(path)
    texts = [
        "Agent平台开发，维护业务接口。", "端云同步记忆。" * 180, "端云同步记忆，其他目标原文。",
    ]
    app = create_app(Settings(database_path=path, raw_directory=tmp_path / "raw"))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        jobs = [client.post("/api/import", headers=auth, json={
            "title": "合成检索样本" + str(i), "company": "合成公司" + str(i),
            "description": text, "data_kind": "synthetic", "external_id": f"retrieval-original-{i}",
        }).json()["job_id"] for i, text in enumerate(texts)]
        document_text = "合成工作说明：端云同步记忆要保留上下文条件。"
        goal = client.post("/api/career", headers=auth, json={
            "title": "合成召回对照", "goal": "解释查询表达如何影响召回", "job_ids": jobs[:2],
            "first_question": "泛词能否代替具体工作要求？", "material_title": "合成工作说明",
            "material_text": document_text,
        }).json()
        identity, qid = goal["id"], goal["focus_question_id"]
        document = goal["materials"][0]["id"]
        base = f"/api/career/{identity}"
        endpoint = base + "/experiments/retrieval"
        inputs = {"baseline": {"terms": ["Agent"]},
                  "candidate": {"terms": ["记忆"], "required_terms": ["端云同步"]},
                  "job_ids": jobs[:2], "document_ids": [document],
                  "expected_job_ids": [jobs[1]], "expected_document_ids": [document],
                  "top_k": 3, "question_id": qid, "hypothesis": "主题限定可能减少泛词干扰。"}
        preview = client.post(endpoint, headers=auth, json=inputs)
        assert preview.status_code == 200, preview.text
        result = preview.json()["experiment"]
        first, second = result["runs"]
        assert first["metrics"]["source_recall"] == first["metrics"]["source_precision"] == 0
        assert second["metrics"]["source_recall"] == second["metrics"]["source_precision"] == 1
        assert len(second["evidence"]) == 3 and second["metrics"]["returned_sources"] == 2
        assert {check["reason"] for check in first["missing_source_checks"]} == {
            "query_expression_missing",
        }
        assert not second["missing_source_checks"]
        for evidence in second["evidence"]:
            original = document_text if evidence["public_document_id"] else texts[1]
            assert evidence["quote"] == original[evidence["start"] : evidence["end"]]
        assert {source["key"] for source in result["sources"]} == {
            "job:" + key for key in jobs[:2]
        } | {"document:" + document}
        assert all(source.get("content_sha256") for source in result["sources"])
        before = client.get(base).json()
        assert not before["tasks"] and before["usage"]["calls"] == 0

        rejected = client.post(endpoint, headers=auth, json={**inputs, "job_ids": jobs})
        assert rejected.status_code == 422 and not client.get(base).json()["tasks"]
        for changed in ({"expected_job_ids": [jobs[0]], "job_ids": [jobs[1]]},
                        {"document_ids": ["f" * 32], "expected_document_ids": []},
                        {"expected_job_ids": [], "expected_document_ids": []}):
            rejected = client.post(endpoint, headers=auth, json={**inputs, **changed})
            assert rejected.status_code == 422

        negative = client.post(endpoint, headers=auth, json={
            **inputs, "expectation": "none", "expected_job_ids": [], "expected_document_ids": [],
            "baseline": {"terms": ["无此工作条件"]}, "candidate": {"terms": ["Agent"]},
        }).json()["experiment"]["runs"]
        assert negative[0]["metrics"]["correct_no_match"] is True
        assert negative[0]["metrics"]["source_precision"] is None
        assert negative[1]["metrics"]["correct_no_match"] is False
        assert all(run["metrics"]["source_recall"] is None for run in negative)
        saved = client.post(endpoint, headers=auth, json={**inputs, "save": True})
        assert saved.status_code == 201, saved.text
        data = saved.json()
        task = next(row for row in data["career"]["tasks"] if row["id"] == data["task_id"])
        assert task["question_id"] == qid and task["state"] == "done"
        assert len(task["comparison_rows"]) == 2
        assert all(row["observed"] for row in task["comparison_rows"])
        assert task["hypothesis"] == inputs["hypothesis"]
        assert data["career"]["usage"]["calls"] == 0
        document = client.get("/api/public-documents/" + task["artifact_document_id"])
        original = document.json()["text"]
        assert "本机实际运行记录" in original and "不是答案准确率" in original
        encoded = data["experiment"]["artifact_text"].split("\n\n", 1)[1]
        assert json.loads(encoded)["input"]["expected_job_ids"] == [jobs[1]]
        assert not client.get(base).json()["insights"]  # No automatic adoption of conclusions.
        parent_id = task["id"]
        before_task = client.get("/api/projects/" + identity).json()["career"]["tasks"][0]
        loaded = client.get(base + "/tasks/" + parent_id + "/retrieval-inputs")
        assert loaded.status_code == 200, loaded.text
        assert loaded.json()["input"]["candidate"] == inputs["candidate"]
        assert loaded.json()["previous"]["task_id"] == parent_id
        assert len(client.get(base).json()["tasks"]) == 1
        unchanged = client.post(
            endpoint, headers=auth, json={**inputs, "previous_task_id": parent_id},
        )
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["experiment"]["previous_comparison"]["changed_conditions"] == []
        child = client.post(endpoint, headers=auth, json={
            **inputs, "previous_task_id": parent_id, "top_k": 1, "save": True,
        })
        assert child.status_code == 201, child.text
        child_result = child.json()["experiment"]
        assert child_result["previous_comparison"]["changed_conditions"] == ["片段上限"]
        assert child_result["runs"][1]["metrics"]["source_recall"] == 0.5
        compared = child_result["previous_comparison"]["return_comparison"][1]["sources"]
        dropped = [row for row in compared if row["before"]["returned"]
                   and not row["after"]["returned"]]
        assert len(dropped) == 1
        assert dropped[0]["before"]["in_corpus"] and dropped[0]["after"]["in_corpus"]
        assert dropped[0]["before"]["expected"] and dropped[0]["after"]["expected"]
        checks = child_result["runs"][1]["missing_source_checks"]
        assert len(checks) == 1 and checks[0]["reason"] == "outside_returned_limit"
        assert checks[0]["evidence"]["quote"] and not checks[0]["counted_in_metrics"]
        assert checks[0]["source_key"] not in child_result["runs"][1]["returned_source_keys"]
        assert len(child_result["runs"][1]["evidence"]) == 1
        child_task = next(row for row in child.json()["career"]["tasks"]
                          if row["id"] == child.json()["task_id"])
        assert child_task["previous_task_id"] == parent_id
        assert "片段上限" in child_task["design_change"]
        assert child_task["question_id"] == qid and child_task["state"] == "done"
        parent_after = client.get("/api/projects/" + identity).json()["career"]["tasks"][0]
        assert parent_after == before_task
        assert client.get("/api/public-documents/" + task["artifact_document_id"]).json()[
            "text"
        ] == original
        edited_rows = [{**row, "observed": "用户后来补记的解释，不是原始运行输出。"}
                       for row in task["comparison_rows"]]
        edited = client.patch(base + "/tasks/" + parent_id, headers=auth, json={
            "state": "done", "outcome": task["outcome"], "comparison_rows": edited_rows,
        })
        assert edited.status_code == 200, edited.text
        archived_rows = client.get(base + "/tasks/" + parent_id + "/retrieval-inputs").json()[
            "previous"
        ]["comparison_rows"]
        assert archived_rows == data["experiment"]["comparison_rows"]

        relabel = client.post(endpoint, headers=auth, json={
            **inputs, "previous_task_id": parent_id, "expected_job_ids": [],
        }).json()["experiment"]
        assert relabel["previous_comparison"]["changed_conditions"] == ["预期相关标签"]
        assert relabel["runs"][1]["metrics"]["source_precision"] == 0.5
        relabelled = next(row for row in relabel["previous_comparison"]["return_comparison"][1][
            "sources"
        ] if row["source_key"] == "job:" + jobs[1])
        assert relabelled["before"]["expected"] and not relabelled["after"]["expected"]
        assert relabelled["before"]["returned"] and relabelled["after"]["returned"]
        updated = client.post("/api/import", headers=auth, json={
            "title": "合成检索样本1", "company": "合成公司1", "external_id": "retrieval-original-1",
            "description": texts[1] + "新增业务条件：同步策略待验证。", "data_kind": "synthetic",
        })
        assert updated.json()["job_id"] == jobs[1]
        newer_source = client.post(endpoint, headers=auth, json={
            **inputs, "previous_task_id": parent_id,
        }).json()["experiment"]
        assert newer_source["previous_comparison"]["changed_conditions"] == ["原文内容"]
        assert next(row for row in newer_source["previous_comparison"]["return_comparison"][1][
            "sources"
        ] if row["source_key"] == "job:" + jobs[1])["content_changed"]
        document_id = inputs["document_ids"][0]
        assert client.delete(base + "/materials/" + document_id, headers=auth).status_code == 200
        missing = client.get(base + "/tasks/" + parent_id + "/retrieval-inputs")
        assert missing.status_code == 200
        assert missing.json()["input"]["document_ids"] == [document_id]  # No implicit relabelling.
        assert client.post(endpoint, headers=auth, json={
            **inputs, "previous_task_id": parent_id,
        }).status_code == 422  # Reading an old experiment never restores removed originals.
        narrowed = client.post(endpoint, headers=auth, json={
            **inputs, "previous_task_id": parent_id,
            "document_ids": [], "expected_document_ids": [],
        })
        assert narrowed.status_code == 200, narrowed.text
        assert {"对照资料", "预期相关标签"} <= set(narrowed.json()["experiment"][
            "previous_comparison"
        ]["changed_conditions"])
        removed_source = next(row for row in narrowed.json()["experiment"]["previous_comparison"][
            "return_comparison"
        ][1]["sources"] if row["source_key"] == "document:" + document_id)
        assert removed_source["before"]["in_corpus"] and not removed_source["after"]["in_corpus"]
        assert client.get(base).json()["usage"]["calls"] == 0
        other = client.post("/api/career", headers=auth, json={
            "title": "合成另一个目标", "goal": "不混入其他目标的实验记录",
        }).json()["id"]
        foreign = client.get(f"/api/career/{other}/tasks/{parent_id}/retrieval-inputs")
        assert foreign.status_code == 422
