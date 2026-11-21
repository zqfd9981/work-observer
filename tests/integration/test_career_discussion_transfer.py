"""Reuse one historical discussion as a new inquiry, with current sources read separately."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_map_comparison import MapComparisonModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


class DiscussionTransferModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        career = context["project_context"]["career_evidence"]
        carried = (career.get("selected_inquiry") or {}).get("carried_understanding")
        scope = context["fixed_scope"]
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        evidence = [item for output in outputs for item in output.get("evidence", [])]
        if carried:
            assert len(carried["research_claims"][-1]["text"]) > 1000
            assert carried["research_claims"][-1]["text"].endswith("不证明个人拥有生产验收权。")
            assert carried["research_claims"][0]["requirement"] == "preferred"
            assert all("evidence_ids" not in claim for claim in carried["research_claims"])
            assert {job["id"] for job in scope["jobs"]}.isdisjoint(
                job["id"] for job in carried["source_jobs"]
            )
        document = next(
            (row for row in scope.get("public_document_titles", [])
             if row["title"] == "合成旧讨论原资料"),
            None,
        )
        if not outputs:
            name, args = "read_job", {"job_id": scope["jobs"][0]["id"], "start": 0}
        elif document and not any(
            row.get("public_document_id") == document["id"] for row in evidence
        ):
            name, args = "read_archived_document", {"document_id": document["id"], "start": 0}
        else:
            if not carried:
                job = next(row for row in evidence if row.get("job_id"))
                claims = [
                    {
                        "category": "ability",
                        "basis": "direct",
                        "requirement": "preferred",
                        "text": "合成原JD写明商科背景更佳，属于加分条件。",
                        "evidence_ids": [job["id"]],
                    },
                    {
                        "category": "business",
                        "basis": "inference",
                        "requirement": "unspecified",
                        "text": "合成资料仅描述局部样例检查。"
                        + "保留原任务和样本范围。" * 95
                        + "末尾限定：不证明个人拥有生产验收权。",
                        "evidence_ids": [row["id"] for row in evidence],
                    },
                ]
            else:
                claims = [
                    {
                        "category": "responsibility",
                        "basis": "synthesis",
                        "requirement": "unspecified",
                        "text": "当前合成JD描述工具接入与失败记录；实际验收决定权仍未知。",
                        "evidence_ids": [row["id"] for row in evidence],
                    }
                ]
            name, args = (
                "finish_research",
                {
                    "claims": claims,
                    "gaps": ["实际验收仍需核实；加分条件只按所指原岗位理解，不能自动迁移。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_discussion_reuse_preserves_full_qualifiers_and_explicit_source_choice(tmp_path):
    database, checkpoint = tmp_path / "discussion-transfer.db", tmp_path / "research.db"
    upgrade(database)
    model = DiscussionTransferModel()
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model,
            reports_dir=tmp_path / "reports",
            checkpoint_path=checkpoint,
        ),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, values, status=201):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code == status, response.text
            return response.json()

        old_job, new_job = [
            post(
                "/api/import",
                {
                    "title": "合成讨论迁移" + title,
                    "company": "合成团队",
                    "data_kind": "synthetic",
                    "description": description,
                },
            )["job_id"]
            for title, description in [
                ("原岗位", "参与接口验证，交付样例记录。商科背景更佳。生产验收权未说明。"),
                ("新岗位", "负责工具接入和失败记录，实际验收决定权未说明。"),
            ]
        ]
        source = post(
            "/api/career",
            {"title": "合成旧讨论目标", "goal": "核对样例验证的边界", "job_ids": [old_job]},
        )
        source_api = "/api/career/" + source["id"]
        text = "合成资料：样例检查记录可供协作参考；未证明拥有生产验收决定权。"
        document = post(source_api + "/materials", {"title": "合成旧讨论原资料", "text": text})[
            "materials"
        ][0]
        original = run_stage(
            client,
            source["id"],
            auth,
            "ask",
            question="合成讨论迁移：样例检查能证明什么？",
            material_id=document["id"],
        )["results"][0]
        assert original["result"]["status"] == "completed"
        old_claims = deepcopy(original["result"]["claims"])
        target = post(
            "/api/career", {"title": "合成新目标", "goal": "重新核对迁移条件", "job_ids": [new_job]}
        )
        target_api = "/api/career/" + target["id"]
        calls = len(model.contexts)
        payload = {
            "source_project_id": source["id"],
            "kind": "discussion",
            "record_id": original["step_id"],
        }
        copied = post(target_api + "/reuse", payload, 200)
        assert len(model.contexts) == calls
        question = copied["questions"][0]
        carried = question["carried_understanding"]
        assert question["state"] == "open" and not question["conclusion"]
        assert question["source_step_id"] is None and question["conclusion_step_id"] is None
        assert question["selected_job_ids"] == [] and not copied["document_ids"]
        assert carried["research_claims"] == [
            {key: claim[key] for key in ("text", "category", "basis", "requirement")}
            for claim in old_claims
        ]
        assert carried["research_gaps"] == original["result"]["gaps"]
        assert carried["research_review_status"] == "unreviewed"
        assert any(
            ref["public_document_id"] == document["id"] for ref in carried["source_references"]
        )
        assert all("quote" not in ref for ref in carried["source_references"])
        assert len(post(target_api + "/reuse", payload, 200)["questions"]) == 1
        first = run_stage(
            client,
            target["id"],
            auth,
            "ask",
            question_id=question["id"],
            question=question["question"],
        )["results"][0]
        assert first["result"]["status"] == "completed" and first["result"]["model_calls"] == 2
        assert {row["job_id"] for row in first["result"]["evidence"]} == {new_job}
        post(target_api + "/materials/attach", {"document_id": document["id"]}, 200)
        for index in range(21):
            post(
                target_api + "/materials",
                {"title": f"无关讨论迁移资料{index}", "text": "无关合成说明。"},
            )
        second = run_stage(
            client,
            target["id"],
            auth,
            "ask",
            question_id=question["id"],
            question=question["question"],
        )["results"][0]
        assert second["result"]["status"] == "completed" and second["result"]["model_calls"] == 3
        assert document["id"] in second["document_ids"] and second["omitted_documents"]
        assert any(
            row.get("public_document_id") == document["id"] and row["quote"] == text
            for row in second["result"]["evidence"]
        )
        assert all(claim["requirement"] == "unspecified" for claim in second["result"]["claims"])
        assert client.get(target_api).json()["questions"][0] == question
        saved_source = client.get(source_api).json()
        assert saved_source["results"][0]["result"]["claims"] == old_claims
        assert client.get("/api/public-documents/" + document["id"]).json()["text"] == text
        pending = post(source_api + "/prepare", {"kind": "ask", "question": "尚未执行的合成讨论"})
        response = client.post(
            target_api + "/reuse", headers=auth, json={**payload, "record_id": pending["step_id"]}
        )
        assert response.status_code == 422
        client.delete(source_api + "/steps/" + pending["step_id"], headers=auth)
        # A cleared source cannot be copied into another destination.
        store = ResearchStore(checkpoint, str(database.resolve()))
        store.invalidate_runs([original["run_id"]])
        store.close()
        another = post("/api/career", {"title": "合成待核实目标", "goal": "不恢复已清除研究"})
        response = client.post(
            "/api/career/" + another["id"] + "/reuse", headers=auth, json=payload
        )
        assert response.status_code == 422
        assert not client.get("/api/career/" + another["id"]).json()["questions"]


def test_discussion_transfer_keeps_map_relations_and_current_reading_scope(tmp_path):
    database = tmp_path / "map-transfer.db"
    upgrade(database)
    model = MapComparisonModel()
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model, reports_dir=tmp_path / "reports",
        ), base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        job = post("/api/import", {
            "title": "合成地图迁移岗位", "company": "合成团队", "data_kind": "synthetic",
            "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
        })["job_id"]
        source = post("/api/career", {
            "title": "合成旧地图", "goal": "理解任务关系", "job_ids": [job],
        })
        original = run_stage(client, source["id"], auth, "map")["results"][0]
        old_map = deepcopy(original["result"]["work_map"])
        assert old_map["work_relations"][0]["transfer_limit"].endswith("未验证生产并发。")
        target = post("/api/career", {
            "title": "合成地图迁移目标", "goal": "重新核对工作关系", "job_ids": [job],
        })
        calls = len(model.contexts)
        copied = post("/api/career/" + target["id"] + "/reuse", {
            "source_project_id": source["id"], "kind": "discussion",
            "record_id": original["step_id"],
        })
        assert len(model.contexts) == calls
        question = copied["questions"][0]
        assert question["carried_understanding"]["work_map"] == old_map
        followup = run_stage(
            client, target["id"], auth, "ask", question_id=question["id"],
            question="核对旧地图的迁移限制",
        )["results"][0]
        assert followup["result"]["status"] == "completed"
        selected = model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"]
        assert selected["carried_understanding"]["work_map"] == old_map
        assert all(evidence["job_id"] == job for evidence in followup["result"]["evidence"])
        saved = client.get("/api/career/" + source["id"]).json()
        assert saved["results"][0]["result"]["work_map"] == old_map
