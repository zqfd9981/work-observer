"""Compare two complete personal views without adopting either as an established fact."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class NoteComparisonModel(CareerModel):
    """The local script reads the second view's source before returning a qualified comparison."""

    async def turn(self, history):
        outputs, call = await super().turn(history)
        personal = json.loads(history[1]["content"])["project_context"]["career_evidence"]
        counter = personal.get("counter_experiment")
        if call["name"] == "finish_research" and counter and counter.get("artifact_document"):
            evidence = [
                item
                for row in history
                if row.get("type") == "function_call_output"
                for item in json.loads(row["output"]).get("evidence", [])
            ]
            document_id = counter["artifact_document"]["document_id"]
            if not any(item.get("public_document_id") == document_id for item in evidence):
                call = {
                    "type": "function_call",
                    "name": "read_archived_document",
                    "arguments": json.dumps({"document_id": document_id, "start": 0}),
                    "call_id": str(len(history)),
                }
                return [call], call
            arguments = json.loads(call["arguments"])
            sources = [item for item in evidence if item.get("evidence_kind") == "work_material"]
            arguments["claims"] = [
                {
                    "category": "task",
                    "basis": "synthesis",
                    "requirement": "unspecified",
                    "text": (
                        "两份用户记录分别描述单线程超时和并发正常响应，"
                        "条件不同，不能据此判定同一原因。"
                    ),
                    "evidence_ids": list(dict.fromkeys(item["id"] for item in sources)),
                }
            ]
            arguments["gaps"] = ["两条理解并不必然互斥；仍需固定请求标识和并发条件。"]
            arguments["application_plan"] = None
            call["arguments"] = json.dumps(arguments)
        return outputs, call


def test_two_full_views_sources_and_followup_survive_without_reactivating_shelved_notes(tmp_path):
    database = tmp_path / "two-views.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = NoteComparisonModel()
    with TestClient(
        create_app(settings, model=model, reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        job = post(
            "/api/import",
            {
                "title": "合成认识对照岗位",
                "company": "合成团队",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
                "data_kind": "synthetic",
            },
        )["job_id"]

        def goal(title):
            return post(
                "/api/career",
                {
                    "title": title,
                    "goal": "理解记录之间的差异",
                    "job_ids": [job],
                    "background": "本地虚构练习。",
                },
            )["id"]

        identity = goal("合成两条完整认识的对照")
        base = f"/api/career/{identity}"

        def experiment(title, observation):
            task = post(
                base + "/experiments",
                {
                    "title": title,
                    "task_or_ability": "核对失败条件",
                    "deliverable": "运行记录",
                    "completion_check": "保留未知",
                },
            )["tasks"][-1]
            response = client.patch(
                base + "/tasks/" + task["id"],
                headers=auth,
                json={
                    "state": "done",
                    "outcome": observation,
                    "artifact_text": observation,
                },
            )
            assert response.status_code == 200, response.text
            return response.json()["tasks"][-1]

        task_a = experiment("合成记录A", "合成记录：单线程超时之后重复写入，尚未核对正常响应。")
        task_b = experiment("合成记录B", "合成记录：并发正常响应也重复写入，尚未固定请求标识。")
        views = []
        for label, task, condition in (
            ("A", task_a, "只观察单线程超时，不能覆盖并发。"),
            ("B", task_b, "只观察并发正常响应，尚未固定请求标识。"),
        ):
            text = ("合成历史理解" + label + "。") * 90 + "末尾限定：" + condition
            note = post(
                base + "/insights",
                {
                    "previous_view": "原因尚不清楚。",
                    "observation": task["outcome"],
                    "current_view": text,
                    "open_question": "需要对照适用条件，不直接断定矛盾。",
                    "task_id": task["id"],
                },
            )["insights"][-1]
            post(base + "/insights/" + note["id"] + "/use", {"use_for_research": False})
            views.append(note)
        other = goal("合成另一个目标")
        foreign = post(
            f"/api/career/{other}/insights",
            {
                "previous_view": "旧理解。",
                "observation": "合成观察。",
                "current_view": "另一目标的理解。",
            },
        )["insights"][0]
        args = {
            "kind": "challenge",
            "insight_id": views[0]["id"],
            "counter_insight_id": views[1]["id"],
            "hypothesis_a": "核对所选完整认识A。",
            "hypothesis_b": "核对所选完整认识B。",
        }
        for changes in (
            {"counter_insight_id": views[0]["id"]},
            {"counter_insight_id": foreign["id"]},
            {"kind": "role"},
        ):
            assert (
                client.post(base + "/prepare", headers=auth, json={**args, **changes}).status_code
                == 422
            )
        before = client.get(base).json()["insights"]
        result = run_stage(client, identity, auth, **args)["results"][0]
        assert result["result"]["status"] == "completed", result["result"].get("stop_reason")
        personal = model.contexts[-1]["project_context"]["career_evidence"]
        assert personal["selected_learning_note"]["current_user_view"] == views[0]["current_view"]
        assert (
            personal["selected_counter_learning_note"]["current_user_view"]
            == views[1]["current_view"]
        )
        assert personal["counter_experiment"]["reported_observation"] == task_b["outcome"]
        sources = {row.get("public_document_id") for row in result["result"]["evidence"]}
        assert {task_a["artifact_document_id"], task_b["artifact_document_id"]} <= sources
        snapshot = result["result"]["career_learning_context"]
        assert snapshot["counter_note"]["current_user_view"] == views[1]["current_view"]
        assert not snapshot["counter_note"]["use_for_research"]
        followed = run_stage(
            client,
            identity,
            auth,
            "ask",
            source_step_id=result["step_id"],
            question="它们是否只是适用条件不同？",
        )["results"][0]
        assert followed["counter_insight_id"] == views[1]["id"]
        assert followed["insight_id"] == views[0]["id"]
        assert followed["result"]["career_learning_context"]["counter_note"]["id"] == views[1]["id"]
        assert client.get(base).json()["insights"] == before
