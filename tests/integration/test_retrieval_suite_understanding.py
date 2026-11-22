"""A case-specific understanding can be explicitly replayed without rewriting its past."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace

from work_observer.research.agent import ModelClient
from work_observer.research.learning import learning_record
from work_observer.research.store import ResearchStore


class UnderstandingReplayModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}
        self.expected_note = None
        self.case_missing = False

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        review = personal["retrieval_review"]
        assert {row["id"] for row in context["fixed_scope"]["jobs"]} == set(self.jobs)
        assert set(context["fixed_scope"]["archived_public_ids"]) == self.documents
        if self.expected_note:
            assert review["note_origin"] == self.expected_note
            original = review["note_origin"]["source_case"]
            assert original["name"] == "端云负例" and original["artifact_document_id"]
            assert original["runs"][1]["unexpected_source_keys"] == ["job:" + self.jobs[1]]
            assert (original["name"] not in [row["name"] for row in review["input"]["cases"]]
                    ) == self.case_missing
        else:
            selected = personal["selected_retrieval_case"]
            assert selected["name"] == "端云负例" and len(selected["runs"]) == 2
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_archived_documents", {
                "reads": [{"document_id": key, "start": 0} for key in sorted(self.documents)],
            }
        elif len(outputs) == 1:
            name, args = "read_job", {"job_id": self.jobs[1], "start": 0}
        else:
            evidence = outputs[-1]["evidence"][0]
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "direct", "requirement": "unspecified",
                            "text": evidence["quote"], "evidence_ids": [evidence["citation_key"]]}],
                "gaps": ["原样例已改名，仍不能把新样例无返回视为原认识已通过验证。"
                         if self.case_missing else "额外来源的标签还需核对，语义效果仍未验证。"],
            }
            schema = next(tool for tool in self.tools if tool["name"] == name)["parameters"]
            if "application_plan" in schema["properties"]:
                args["application_plan"] = None
            if "revisions" in schema["properties"]:
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_parked_case_understanding_replays_full_text_and_keeps_unmatched_case_unknown(tmp_path):
    model = UnderstandingReplayModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": "合成认识复验岗位" + str(i), "company": "合成团队" + str(i),
            "description": text, "data_kind": "synthetic",
        })["job_id"] for i, text in enumerate([
            "负责检索召回，建设评估集并核对失败样本。", "负责端云同步记忆，维护上下文。",
            "这是同目标中未选入本次评估的其他任务原文。",
        ])]
        goal = post("/api/career", {
            "title": "合成样例认识复验", "goal": "把失败观察带回个人理解", "job_ids": jobs,
            "first_question": "返回的来源越多是否就代表更好？",
            "material_title": "不应混入的材料", "material_text": "另一条工作线的说明。",
        })
        base = "/api/career/" + goal["id"]

        def run(values):
            step = post(base + "/prepare", values)
            post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
            return row

        values = {"job_ids": jobs[:2], "question_id": goal["focus_question_id"], "cases": [
            {"name": "评估职责", "baseline": {"terms": ["查无表达甲"]},
             "candidate": {"terms": ["评估集"]}, "expected_job_ids": jobs[:1]},
            {"name": "端云负例", "baseline": {"terms": ["查无表达乙"]},
             "candidate": {"terms": ["端云同步"]}, "expectation": "none"},
        ]}
        initial = post(base + "/experiments/retrieval-suite", {**values, "save": True})
        parent = initial["career"]["tasks"][-1]
        model.jobs, model.documents = jobs[:2], {parent["artifact_document_id"]}
        discussed = run({"kind": "ask", "task_id": parent["id"],
                         "retrieval_case_name": "端云负例", "question": "为何额外返回不等于更好？"})
        note_data = {
            "task_id": parent["id"], "source_step_id": discussed["step_id"],
            "question_id": goal["focus_question_id"], "previous_view": "返回越多就越好。",
            "observation": "构造负例的宽泛查询返回了端云来源，标签还需原文核对。",
            "current_view": "增加词面返回可能同时增加额外来源，需要保留标签的适用条件。" * 40
            + "末尾限定：仍未验证语义相关性。",
            "open_question": "只在固定的本地原文上核对，标签不是独立结论。" * 25
            + "末尾未知：尚未进行语义评测。",
        }
        assert 1000 < len(note_data["current_view"]) <= 1500
        note = post(base + "/insights", note_data)["insights"][-1]
        post(base + "/insights/" + note["id"] + "/use", {"use_for_research": False})
        changed = deepcopy(values)
        changed["cases"][1]["candidate"] = {"terms": ["zz-no-matching-topic"]}
        replay = {**changed, "source_insight_id": note["id"], "previous_task_id": parent["id"],
                  "hypothesis": note_data["current_view"]}
        before = client.get(base).json()
        calls = len(model.contexts)
        preview = post(base + "/experiments/retrieval-suite", replay)
        saved = post(base + "/experiments/retrieval-suite", {**replay, "save": True})
        child = saved["career"]["tasks"][-1]
        snapshot = saved["experiment"]["note_origin"]
        assert snapshot == preview["experiment"]["note_origin"] == child["retrieval_note_origin"]
        assert snapshot["current_view"] == note_data["current_view"]
        assert snapshot["open_question"] == note_data["open_question"]
        assert not snapshot["use_for_research"] and len(model.contexts) == calls
        assert snapshot["source_case"]["step_id"] == discussed["step_id"]
        assert saved["career"]["insights"] == before["insights"]
        artifact = client.get("/api/public-documents/" + child["artifact_document_id"]).json()[
            "text"
        ]
        edited = client.patch(base + "/insights/" + note["id"], headers=auth, json={
            **note_data, "current_view": "后来编辑的认识，不能改写上次运行起点。",
        })
        assert edited.status_code == 200, edited.text
        loaded = client.get(base + "/tasks/" + child["id"] + "/retrieval-inputs").json()
        assert loaded["previous"]["note_origin"] == snapshot
        assert client.get("/api/public-documents/" + child["artifact_document_id"]).json()[
            "text"
        ] == artifact
        model.expected_note = snapshot
        model.documents = {parent["artifact_document_id"], child["artifact_document_id"]}
        reflected = run({"kind": "reflect", "task_id": child["id"]})
        assert reflected["result"]["career_learning_context"]["retrieval_review"][
            "note_origin"
        ] == snapshot
        changed["cases"][1]["name"] = "改名后的新负例"
        again = post(base + "/experiments/retrieval-suite", {
            **changed, "previous_task_id": child["id"], "source_insight_id": note["id"],
            "save": True,
        })
        grandchild = again["career"]["tasks"][-1]
        model.expected_note = again["experiment"]["note_origin"]
        assert model.expected_note["current_view"].startswith("后来编辑")
        assert model.expected_note["source_case"] == snapshot["source_case"]
        model.case_missing = True
        model.documents.add(grandchild["artifact_document_id"])
        reflected = run({"kind": "reflect", "task_id": grandchild["id"]})
        assert any("已改名" in gap for gap in reflected["result"]["gaps"])
        replacement = post(base + "/insights", {
            "task_id": grandchild["id"], "question_id": goal["focus_question_id"],
            "replaces_insight_id": note["id"], "source_step_id": None,
            "previous_view": model.expected_note["current_view"],
            "observation": "原负例已经改名，当前集合没有同名样例可作直接比较。",
            "current_view": "不能用另一条样例无返回证明旧认识成立，仍需固定原标签复验。",
            "open_question": "还缺原样例在同一条件下的记录。",
        })["insights"][-1]
        revised = post(base + "/experiments/retrieval-suite", {
            **changed, "previous_task_id": grandchild["id"],
            "source_insight_id": replacement["id"], "save": True,
        })
        revised_task = revised["career"]["tasks"][-1]
        model.expected_note = revised["experiment"]["note_origin"]
        assert model.expected_note["id"] == replacement["id"]
        assert model.expected_note["source_case"] == snapshot["source_case"]
        model.documents = {parent["artifact_document_id"], grandchild["artifact_document_id"],
                           revised_task["artifact_document_id"]}
        run({"kind": "reflect", "task_id": revised_task["id"]})
        project = client.get("/api/projects/" + goal["id"]).json()
        store = ResearchStore(tmp_path / "checkpoints.db",
                              namespace=str((tmp_path / "adaptive.db").resolve()))
        try:
            learned = learning_record(project["career"]["insights"][0], project, store)
            assert learned["source_retrieval_case"]["name"] == "端云负例"
            revised_note = learning_record(project["career"]["insights"][-1], project, store)
            assert revised_note["source_retrieval_case"] == snapshot["source_case"]
        finally:
            store.close()
        assert not client.get(base).json()["insights"][0]["use_for_research"]
        assert client.get(base).json()["questions"][0]["state"] == "open"
