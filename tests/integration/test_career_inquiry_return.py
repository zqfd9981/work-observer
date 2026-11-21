"""Review the parent using one chosen child's complete answer and newly read originals."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class InquiryReturnModel(ModelClient):
    def __init__(self):
        self.contexts = []
        self.last_usage = {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        inquiry = context["project_context"]["career_evidence"]["selected_inquiry"]
        returned = inquiry.get("followup_to_recheck")
        if returned:
            assert returned["asked_then"] == "核对样例验证与最终验收的分工。"
            assert returned["claim_details_to_recheck"][-1]["text"].endswith(
                "仅加分；跨团队决定权未披露。"
            )
            assert returned["claim_details_to_recheck"][-1]["requirement"] == "preferred"
            assert (
                returned["unresolved_then"][-1] == "需另行询问最终验收者，不能由样例推定个人权限。"
            )
            assert "不能证明生产职责" in inquiry["conclusion"]
            assert returned["source_cutoff"]
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        evidence = [row for output in outputs for row in output.get("evidence", [])]
        document = next(
            row
            for row in context["fixed_scope"]["public_document_titles"]
            if row["title"] == "合成后续验收样本"
        )
        if not outputs:
            jobs = context["fixed_scope"]["jobs"]
            if len(jobs) > 1:
                name, args = (
                    "read_jobs",
                    {"reads": [{"job_id": row["id"], "start": 0} for row in jobs]},
                )
            else:
                name, args = "read_job", {"job_id": jobs[0]["id"], "start": 0}
        elif not any(row.get("public_document_id") == document["id"] for row in evidence):
            name, args = "read_archived_document", {"document_id": document["id"], "start": 0}
        else:
            claim = (
                (
                    "合成样本只支持提供验证样例；"
                    + "保留条件和适用对象。" * 110
                    + "商科背景仅加分；跨团队决定权未披露。"
                )
                if not returned
                else "原判断应保留局部样例限制；现有材料仍不能核实生产验收决定权。"
            )
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "text": claim,
                            "category": "ability" if not returned else "responsibility",
                            "basis": "synthesis",
                            "requirement": "preferred" if not returned else "unspecified",
                            "evidence_ids": [row["id"] for row in evidence],
                        }
                    ],
                    "gaps": ["需另行询问最终验收者，不能由样例推定个人权限。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_chosen_followup_returns_with_full_conditions_scope_and_actual_sources(tmp_path):
    database = tmp_path / "return-inquiry.db"
    upgrade(database)
    model = InquiryReturnModel()
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
                    "title": f"合成调查回查岗位{i}",
                    "company": "合成团队",
                    "data_kind": "synthetic",
                    "description": "参与接口样例验证，提供验证记录。商科背景更佳。"
                    "生产验收决定权未披露。",
                },
            )["job_id"]
            for i in range(2)
        ]
        goal = post(
            "/api/career",
            {
                "title": "合成：把后续查证带回原问题",
                "goal": "修正对工作责任的理解",
                "job_ids": jobs,
            },
        )
        api = "/api/career/" + goal["id"]
        source_text = "合成样本：本地验证记录可供协作方参考，不代表取得跨团队生产验收权。"
        document = post(api + "/materials", {"title": "合成后续验收样本", "text": source_text})[
            "materials"
        ][0]
        parent = post(
            api + "/questions",
            {
                "question": "提供验证记录是否等于负责最终验收？",
                "state": "answered",
                "conclusion": "用户原判断：局部样例不能证明生产职责；验收边界仍需核实。",
                "next_evidence": "需要能区分参与验证与最终决定权的分工材料。",
            },
        )["questions"][0]
        child = post(
            api + "/questions",
            {
                "question": "核对样例验证与最终验收的分工。",
                "parent_question_id": parent["id"],
                "selected_job_ids": [jobs[1]],
            },
        )["questions"][-1]
        chosen = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question=child["question"],
            question_id=child["id"],
            material_id=document["id"],
        )["results"][0]
        assert chosen["result"]["status"] == "completed"
        assert len(chosen["result"]["claims"][0]["text"]) > 1000
        # A later answer to the same question must not silently replace the user's chosen answer.
        run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question="较新的另一种提问。",
            question_id=child["id"],
            material_id=document["id"],
        )
        child_data = {
            "question": child["question"],
            "state": "answered",
            "conclusion": "用户暂记：只看过样例；跨团队职责未知。",
        }
        post(api + "/questions/" + child["id"], child_data, "patch")
        for index in range(21):
            post(api + "/materials", {"title": f"无关后续资料{index}", "text": "无关合成说明。"})
        before = deepcopy(client.get(api).json()["questions"])
        reviewed = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=parent["id"],
            source_step_id=chosen["step_id"],
            selected_job_ids=[],
            question="请把选定的后续查证带回原问题，回读原文再说明哪些需要修订。",
        )
        row = reviewed["results"][0]
        assert row["question_id"] == parent["id"] and row["source_step_id"] == chosen["step_id"]
        assert row["result"]["status"] == "completed" and row["result"]["model_calls"] == 3
        context = model.contexts[-1]
        returned = context["project_context"]["career_evidence"]["selected_inquiry"][
            "followup_to_recheck"
        ]
        assert returned["step_id"] == chosen["step_id"] and returned["question_id"] == child["id"]
        assert returned["user_conclusion"] == child_data["conclusion"]
        assert returned["selected_job_ids"] == [jobs[1]]
        assert (
            returned["claim_details_to_recheck"][0]["text"] == chosen["result"]["claims"][0]["text"]
        )
        assert {job["id"] for job in context["fixed_scope"]["jobs"]} == set(jobs)
        assert any(
            ref["public_document_id"] == document["id"]
            for ref in returned["source_references_to_reread"]
        )
        assert document["id"] in row["document_ids"] and row["omitted_documents"]
        assert any(
            source.get("public_document_id") == document["id"] and source["quote"] == source_text
            for source in row["result"]["evidence"]
        )
        assert not any(
            source["id"] in {parent["id"], child["id"], chosen["step_id"]}
            for source in row["result"]["evidence"]
        )
        assert client.get(api).json()["questions"] == before
        calls = len(model.contexts)
        saved = post(
            api + "/questions/" + parent["id"],
            {
                "question": parent["question"],
                "state": "answered",
                "conclusion": "用户复核后保留局部样例限制，实际验收分工仍待补证。",
                "conclusion_step_id": row["step_id"],
            },
            "patch",
        )
        assert len(model.contexts) == calls
        assert saved["questions"][0]["conclusion_step_id"] == row["step_id"]
        assert saved["questions"][1] == before[1]
        original = next(item for item in saved["results"] if item["step_id"] == chosen["step_id"])
        assert original["result"]["claims"] == chosen["result"]["claims"]
