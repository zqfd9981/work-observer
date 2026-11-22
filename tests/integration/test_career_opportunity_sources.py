"""A personal opportunity reflection retains multiple exact raw references."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


class OpportunitySourceModel(ModelClient):
    def __init__(self):
        self.last_usage = {}
        self.contexts = []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        note = context["project_context"]["career_evidence"]["selected_learning_note"]
        assert len(note["source_passages"]) == len(note["source_locators"]) == 2
        assert note["source_passages"][0]["start"] == 0
        assert note["source_passages"][1]["quote"].endswith("尾部条件：不代表正式承诺。")
        ids = [row["public_document_id"] for row in note["source_locators"]]
        assert set(ids) <= set(context["fixed_scope"]["archived_public_ids"])
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = (
                "read_archived_documents",
                {
                    "reads": [{"document_id": key, "start": 0} for key in ids],
                },
            )
        else:
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "inference",
                            "requirement": "unspecified",
                            "text": "两份合成记录的工作情境不同，个人偏好还需结合实际任务比例核实；"
                            "沟通记录不能代替团队正式承诺。",
                            "evidence_ids": [row["id"] for row in outputs[0]["evidence"]],
                        }
                    ],
                    "gaps": ["真实工作比例、交付权限和个人适应性仍未知。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_multi_source_reflection_persists_searches_and_freshly_reads_each_source(tmp_path):
    database = tmp_path / "opportunity-sources.db"
    upgrade(database)
    model = OpportunitySourceModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, model=model, reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成机会复盘", "goal": "以原文核对个人取舍"})
        base = "/api/career/" + goal["id"]
        texts = [
            "合成甲🧠\r\n持续编码与测试，真实任务比例未说明。",
            "合成乙🧠\r\n用户沟通转述：参与需求核对，编码比例未知。尾部条件：不代表正式承诺。",
        ]
        references = []
        for index, text in enumerate(texts):
            material = save(
                base + "/materials",
                {
                    "title": "合成取舍出处" + str(index),
                    "text": text,
                },
            )["materials"][-1]
            references.append({"public_document_id": material["id"], "start": 0, "end": len(text)})
        question = save(base + "/questions", {"question": "怎样保留编码，同时理解用户问题？"})[
            "questions"
        ][-1]
        before = client.get(base).json()
        values = {
            "question_id": question["id"],
            "source_passages": references,
            "previous_view": "个人希望持续编码，也能理解业务问题。",
            "observation": "对合成甲有兴趣，对合成乙的实际任务比例仍不清楚。",
            "current_view": "个人取舍需要核实工作比例，不能把沟通回复当作正式承诺。",
            "open_question": "分别向两个团队核实日常任务如何分配。",
        }
        for invalid in [[{**references[0], "end": len(texts[0]) + 1}], references * 4]:
            rejected = client.post(
                base + "/insights", headers=auth, json={**values, "source_passages": invalid}
            )
            assert rejected.status_code == 422
        assert client.get(base).json() == before and not model.contexts
        saved = save(base + "/insights", values)
        note = saved["insights"][-1]
        originals = note["source_passages"]
        assert [row["quote"] for row in originals] == texts
        assert saved["results"] == before["results"] and saved["usage"] == before["usage"]
        edited = save(
            base + "/insights/" + note["id"],
            {
                **values,
                "current_view": "更看重具体工作比例，仍保留两侧未知。",
            },
            "patch",
        )["insights"][-1]
        assert edited["source_passages"] == originals
        project = client.get("/api/projects/" + goal["id"]).json()
        store = ResearchStore(tmp_path / "checkpoints.db", namespace=str(database.resolve()))
        notebook = LearningNotebook(lambda: project, store)
        assert notebook.search(["合成取舍出处1"])["matching_count"] == 1
        memory = notebook.read(note["id"])["note"]
        assert memory["source_passages"] == originals and memory["source_locators"] == originals
        assert all("evidence_ids" not in row for row in memory["source_locators"])
        hits = client.get(base + "/search", params={"q": "合成取舍出处1"}).json()
        assert any(row["id"] == note["id"] for row in hits["records"])
        checked = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=question["id"],
            insight_id=note["id"],
            question="按两侧出处重查个人取舍的条件。",
        )
        result = checked["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert len(result["evidence"]) == 2
        assert result["career_learning_context"]["selected_note"]["source_passages"] == originals
        assert len(model.contexts) == 2
        assert client.get(base).json()["insights"][-1] == edited
