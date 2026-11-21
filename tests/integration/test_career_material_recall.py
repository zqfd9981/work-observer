"""A specific question can bring an older saved original back into a bounded investigation."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class MaterialRecallModel(ModelClient):
    """Local scripted reader: use existing archive search and full-text reading tools."""

    def __init__(self):
        self.tools, self.contexts = [], []
        self.last_usage = {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        if context["project_context"]["career_action"] != "ask":
            return await CareerModel.turn(self, history)
        self.contexts.append(context)
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, arguments = "query_jobs", {}
        elif len(outputs) == 1:
            name, arguments = (
                "read_job",
                {"job_id": context["fixed_scope"]["jobs"][0]["id"], "start": None},
            )
        elif len(outputs) == 2:
            name, arguments = "search_archived_sources", {"terms": ["回填幂等键"]}
        elif len(outputs) == 3:
            old = next(row for row in outputs[-1]["evidence"] if row.get("public_document_id"))
            self.read_id = old["public_document_id"]
            name, arguments = "read_archived_document", {"document_id": self.read_id, "start": 0}
        else:
            assert "不代表生产可用" in "".join(row["quote"] for row in outputs[-1]["evidence"])
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "business",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "这份合成资料只描述局部样例，不代表生产可用。",
                            "evidence_ids": [outputs[-1]["evidence"][0]["citation_key"]],
                        }
                    ],
                    "gaps": ["用户提供的材料不是独立评测，仍需核对实际条件。"],
                    "application_plan": None,
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": str(len(history)),
        }
        return [call], call


def test_question_recalls_an_old_source_without_manual_selection_or_scope_growth(tmp_path):
    database = tmp_path / "material-recall.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MaterialRecallModel()
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
                "title": "合成资料回查岗位",
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
                    "goal": "理解工作记录",
                    "job_ids": [job],
                    "background": "本地虚构练习。",
                },
            )["id"]

        identity = goal("合成按问题找回旧笔记")
        base = f"/api/career/{identity}"
        body = "合成材料：回填幂等键需要与业务请求标识一起记录。只描述局部样例，不代表生产可用。"
        old = post(base + "/materials", {"title": "合成早期业务笔记", "text": body})["materials"][0]
        for index in range(22):
            post(
                base + "/materials",
                {
                    "title": "合成近期其他资料" + str(index),
                    "text": "合成界面与视觉排版记录，与业务回填无关。",
                },
            )
        other = goal("合成不在本轮范围的目标")
        foreign = post(
            f"/api/career/{other}/materials", {"title": "回填幂等键核对条件", "text": body}
        )["materials"][0]
        before = client.get(base).json()
        assert old["id"] not in before["document_ids"][-20:]
        assert not model.contexts
        researched = run_stage(
            client, identity, auth, "ask", question="回填幂等键需要核对哪些条件？"
        )
        result = researched["results"][0]
        assert result["result"]["status"] == "completed", result["result"].get("stop_reason")
        assert result["result"]["model_calls"] == 5
        assert result["material_id"] is None and model.read_id == old["id"]
        assert old["id"] in result["document_ids"] and len(result["document_ids"]) == 20
        assert foreign["id"] not in result["document_ids"]
        assert any(
            row.get("public_document_id") == old["id"] for row in result["result"]["evidence"]
        )
        assert client.get(base).json()["document_ids"] == before["document_ids"]
        calls = client.get(base).json()["usage"]["calls"]

        # Explicit choices stay in the working set alongside keyword-based recall.
        latest = before["materials"][-1]["id"]
        prepared = post(
            base + "/prepare",
            {
                "kind": "ask",
                "question": "回填幂等键有哪些条件？",
                "material_id": latest,
                "offline": True,
            },
        )
        scope = client.get(base).json()["results"][0]["document_ids"]
        assert {old["id"], latest} <= set(scope)
        assert (
            client.delete(base + "/steps/" + prepared["step_id"], headers=auth).status_code == 200
        )
        resume = client.patch(
            base + "/resume",
            headers=auth,
            json={
                "title": "合成个人简历",
                "text": "回填幂等键核对条件，仅为用户自述。",
            },
        ).json()["resume"]
        prepared = post(
            base + "/prepare", {"kind": "role", "question": "回填幂等键核对条件", "offline": True}
        )
        assert resume["document_id"] not in client.get(base).json()["results"][0]["document_ids"]
        assert (
            client.delete(base + "/steps/" + prepared["step_id"], headers=auth).status_code == 200
        )
        removed = client.delete(base + "/materials/" + old["id"], headers=auth)
        assert removed.status_code == 200
        prepared = post(
            base + "/prepare",
            {"kind": "ask", "question": "回填幂等键需要核对哪些条件？", "offline": True},
        )
        assert old["id"] not in client.get(base).json()["results"][0]["document_ids"]
        assert client.get(base).json()["usage"]["calls"] == calls
