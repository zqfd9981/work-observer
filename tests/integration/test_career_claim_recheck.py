"""A numbered claim recheck retains full old wording and rereads current raw material."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_question_materials import QuestionMaterialModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade

CLAIM_END = "末尾限定：只解释局部样例，生产验收权仍未知。"
LONG_CLAIM = "🧪" * 1100 + CLAIM_END


class ClaimRecheckModel(QuestionMaterialModel):
    async def turn(self, history):
        context = json.loads(history[1]["content"])
        continued = context["project_context"]["career_evidence"].get("continued_discussion")
        if continued:
            details = continued["claim_details_to_recheck"]
            assert [row["position"] for row in details] == list(range(1, 25))
            assert details[-1] == {"position": 24, "text": LONG_CLAIM, "category": "task",
                                   "basis": "inference", "requirement": "unspecified"}
            assert all("evidence_ids" not in row for row in details)
            assert all("quote" not in row and "id" not in row
                       for row in continued["source_references_to_reread"])
            assert "第 24 条判断" in context["question"]
        messages, call = await super().turn(history)
        if call["name"] == "finish_research":
            args = json.loads(call["arguments"])
            if not continued:
                evidence_ids = args["claims"][0]["evidence_ids"]
                args["claims"] = [{
                    "category": "task", "basis": "inference", "requirement": "unspecified",
                    "text": (f"合成第 {index + 1} 条解释：" + "局部样例需要按实际条件核对。" * 65)
                    if index < 23 else LONG_CLAIM,
                    "evidence_ids": evidence_ids,
                } for index in range(24)]
            else:
                assert len(args["claims"]) == 2  # Both chosen raw documents were freshly read.
                args["claims"] = [{
                    "category": "task", "basis": "synthesis", "requirement": "unspecified",
                    "text": "合成查证：两份材料分别描述局部样例和新增超时条件；"
                            "第24条解释需要保留适用条件，生产验收权仍未知。",
                    "evidence_ids": [key for row in args["claims"] for key in row["evidence_ids"]],
                }]
            call["arguments"] = json.dumps(args)
        return messages, call


def test_recheck_late_long_claim_uses_chosen_old_discussion_and_fresh_sources(tmp_path):
    database = tmp_path / "claim-recheck.db"
    upgrade(database)
    model = ClaimRecheckModel()
    with TestClient(create_app(
        Settings(database_path=database, raw_directory=tmp_path / "raw"),
        model=model, reports_dir=tmp_path / "reports", checkpoint_path=tmp_path / "runs.db",
    ), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, payload):
            response = client.post(path, headers=auth, json=payload)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = post("/api/career", {
            "title": "合成单条判断查证", "goal": "核对边界和反例",
            "first_question": "局部样例能说明什么？",
            "material_title": "合成判断查证原说明",
            "material_text": "虚构说明：检查局部输入输出并记录差异。生产验收权未说明。",
        })
        identity, question = goal["id"], goal["questions"][0]
        base = "/api/career/" + identity
        original = run_stage(client, identity, auth, "ask", question_id=question["id"],
                             question=question["question"])["results"][0]
        assert original["result"]["status"] == "completed", original["result"].get("stop_reason")
        saved = deepcopy(original["result"])
        assert len(saved["claims"]) == 24 and saved["claims"][-1]["text"] == LONG_CLAIM
        updated = post(base + "/materials", {
            "title": "合成判断查证补充条件",
            "text": "虚构补充：超时输入需要单独记录，正常输入输出一致不能证明超时恢复。",
        })
        ids = [row["id"] for row in updated["materials"]]
        before = deepcopy(updated)
        reviewed = run_stage(client, identity, auth, "ask", source_step_id=original["step_id"],
                             question_id=question["id"], material_ids=ids, inherit_focus=False,
                             question="请只核对原研究第 24 条判断，回读两份原文，保留末尾限定。")
        result = reviewed["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert result["model_calls"] == 2
        assert {row["public_document_id"] for row in result["evidence"]} == set(ids)
        old_ids = {row["id"] for row in saved["evidence"]}
        # A reread of the same literal range keeps its locator; the added source is new.
        assert {row["id"] for row in result["evidence"]} > old_ids
        retained = next(row for row in reviewed["results"] if row["step_id"] == original["step_id"])
        assert retained["result"]["claims"] == saved["claims"]
        assert retained["result"]["evidence"] == saved["evidence"]
        assert reviewed["questions"] == before["questions"]
        assert reviewed["insights"] == before["insights"]
        assert reviewed["materials"] == before["materials"]
