"""A follow-up inquiry keeps its parent's limits without adopting its conclusion as evidence."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class BranchInquiryModel(ModelClient):
    def __init__(self):
        self.last_usage = {}
        self.contexts = []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        inquiry = context["project_context"]["career_evidence"]["selected_inquiry"]
        parent = inquiry["parent_inquiry"]
        assert parent["id"] == inquiry["parent_question_id"]
        assert "生产验收权尚未核实" in parent["conclusion"]
        assert parent["next_evidence"].endswith("保留跨团队条件。")
        assert parent["hypothesis_a"] and parent["hypothesis_b"]
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        evidence = [row for output in outputs for row in output.get("evidence", [])]
        document = parent["source_passage"]["public_document_id"]
        allowed = {row["id"] for row in context["fixed_scope"]["public_document_titles"]}
        if not outputs:
            name, args = "read_job", {"job_id": context["fixed_scope"]["jobs"][0]["id"], "start": 0}
        elif document in allowed and not any(
            row.get("public_document_id") == document for row in evidence
        ):
            name, args = "read_archived_document", {"document_id": document, "start": 0}
        else:
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "text": "合成岗位写明参与样例验证，资料尚不能核实生产验收决定权。",
                            "category": "responsibility",
                            "basis": "synthesis",
                            "requirement": "unspecified",
                            "evidence_ids": [row["id"] for row in evidence],
                        }
                    ],
                    "gaps": ["需要向实际验收者核对分工；原问题和后续问题仍可能需要不同证据。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_branch_inherits_scope_and_rereads_parent_material_without_rewriting_parent(tmp_path):
    database = tmp_path / "branches.db"
    upgrade(database)
    model = BranchInquiryModel()
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model,
            reports_dir=tmp_path / "reports",
        ),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        jobs = [
            post(
                "/api/import",
                {
                    "title": f"合成分支调查岗位{i}",
                    "company": "合成团队",
                    "data_kind": "synthetic",
                    "description": "参与接口失败样例验证。交付样例记录；生产验收决定权未说明。",
                },
            )["job_id"]
            for i in range(2)
        ]
        goal = post(
            "/api/career",
            {
                "title": "合成：调查拆出后续问题",
                "goal": "核对验证任务和实际决定权",
                "job_ids": jobs,
            },
        )
        api = "/api/career/" + goal["id"]
        text = "合成业务记录：验证样例供协作方参考；跨团队生产上线仍需另行核实。"
        document = post(api + "/materials", {"title": "合成原调查资料", "text": text})["materials"][
            0
        ]
        conclusion = (
            "用户暂记：参与验证不等于拥有上线决定权。"
            + "保留适用范围。" * 180
            + "生产验收权尚未核实。"
        )
        parent_data = {
            "question": "参与样例验证意味着负责上线吗？",
            "state": "answered",
            "conclusion": conclusion,
            "next_evidence": "找实际验收分工；保留跨团队条件。",
            "hypothesis_a": "参与验证但只提供建议。",
            "hypothesis_b": "限定范围内也可能参与决定。",
            "selected_job_ids": [jobs[1]],
            "source_passage": {"public_document_id": document["id"], "start": 0, "end": len(text)},
        }
        parent = post(api + "/questions", parent_data)["questions"][0]
        child = post(
            api + "/questions",
            {
                "question": "哪些产物和沟通记录能区分提供建议与验收决定？",
                "parent_question_id": parent["id"],
            },
        )["questions"][-1]
        assert child["selected_job_ids"] == [jobs[1]] and not child["conclusion"]
        assert not model.contexts
        for i in range(21):
            post(api + "/materials", {"title": f"无关合成资料{i}", "text": "无关的本地合成背景。"})
        original_parent = deepcopy(client.get(api).json()["questions"][0])
        first = run_stage(
            client, goal["id"], auth, "ask", question_id=child["id"], question=child["question"]
        )["results"][0]
        assert first["result"]["status"] == "completed"
        assert first["result"]["model_calls"] == 3
        assert {row["id"] for row in model.contexts[-1]["fixed_scope"]["jobs"]} == {jobs[1]}
        parent_context = model.contexts[-1]["project_context"]["career_evidence"][
            "selected_inquiry"
        ]["parent_inquiry"]
        assert parent_context["conclusion"] == conclusion
        assert document["id"] in first["document_ids"] and first["omitted_documents"]
        evidence = first["result"]["evidence"]
        assert any(
            row.get("public_document_id") == document["id"] and row["quote"] == text
            for row in evidence
        )
        assert not any(row["id"] in {parent["id"], child["id"]} for row in evidence)
        saved = client.get(api).json()
        assert saved["questions"][0] == original_parent
        assert saved["questions"][1]["state"] == "open" and not saved["questions"][1]["conclusion"]
        # Editing an existing inquiry through a client that sends no parent keeps the saved link.
        edited = post(api + "/questions/" + child["id"], {"question": child["question"]}, "patch")
        assert edited["questions"][1]["parent_question_id"] == parent["id"]
        removed = client.delete(api + "/materials/" + document["id"], headers=auth)
        assert removed.status_code == 200, removed.text
        second = run_stage(
            client, goal["id"], auth, "ask", question_id=child["id"], question=child["question"]
        )["results"][0]
        assert second["result"]["status"] == "completed" and second["result"]["model_calls"] == 2
        assert document["id"] not in second["document_ids"]
        assert not any(
            row.get("public_document_id") == document["id"] for row in second["result"]["evidence"]
        )
        assert client.get(api).json()["questions"][0] == original_parent
        # Cross-workspace links and cycles cannot form a navigational dead end.
        foreign_goal = post("/api/career", {"title": "另一合成目标", "goal": "保持调查范围"})
        foreign = post(
            "/api/career/" + foreign_goal["id"] + "/questions", {"question": "另一个问题"}
        )["questions"][0]
        before = client.get(api).json()["questions"]
        for path, values, method in [
            (
                api + "/questions",
                {"question": "错误跨目标", "parent_question_id": foreign["id"]},
                "post",
            ),
            (
                api + "/questions/" + parent["id"],
                {"question": parent["question"], "parent_question_id": child["id"]},
                "patch",
            ),
        ]:
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code == 422, response.text
        assert client.get(api).json()["questions"] == before
