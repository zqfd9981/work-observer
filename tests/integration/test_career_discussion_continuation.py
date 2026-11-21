"""Continue an exact long discussion with its map and proposed work, then read current sources."""

import json
import re
import time
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_inquiry_synthesis import InquirySynthesisModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


class DiscussionContinuationModel(InquirySynthesisModel):
    def __init__(self):
        super().__init__()
        self.originals = 0
        self.expected_source = None

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        continued = context["project_context"]["career_evidence"].get("continued_discussion")
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        evidence = [row for output in outputs for row in output.get("evidence", [])]
        if continued is None:
            messages, call = await super().turn(history)
            if call["name"] == "finish_research":
                self.originals += 1
                args = json.loads(call["arguments"])
                job = next(row for row in evidence if row.get("job_id"))
                args["claims"].extend(
                    [
                        {
                            "category": "ability",
                            "basis": "direct",
                            "requirement": "preferred",
                            "text": "合成旧JD写明商科背景更佳，属于加分条件。",
                            "evidence_ids": [job["id"]],
                        },
                        {
                            "category": "task",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "负责Python接口样例验证。",
                            "evidence_ids": [job["id"]],
                        },
                        {
                            "category": "tool",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "原文提到Python。",
                            "evidence_ids": [job["id"]],
                        },
                    ]
                )
                args["work_map"] = {
                    "version": "work-map-v3-work-relations",
                    "scope_note": f"合成原讨论{self.originals}的地图。",
                    "work_types": [
                        {
                            "name": "合成局部样例工作",
                            "problem": "解释局部输入输出，不能代替业务验收。",
                            "tasks": "构造接口验证样例。",
                            "deliverables": "样例与失败记录。",
                            "claim_indices": [0, 2],
                            "basis": "inference",
                            "boundary": "未说明个人拥有生产审批权。",
                            "next_check": "核对实际分工。",
                        }
                    ],
                    "work_relations": [
                        {
                            "source_claim_index": 3,
                            "target_claim_index": 2,
                            "predicate": "supports",
                            "basis": "inference",
                            "rationale": "Python可构造接口样例，实际场景仍需验证。",
                            "transfer_limit": "保留局部条件。" * 60
                            + "末尾地图限定：未验证生产并发。",
                        }
                    ],
                    "comparisons": [],
                    "unknowns": ["真实业务验收仍未知。"],
                }
                if context["project_context"]["career_action"] == "map":
                    args["revisions"] = []
                else:
                    args.pop("work_map")
                if context.get("application_background"):
                    args["application_plan"] = {
                        "background_memory_id": context["application_background"]["memory_id"],
                        "actions": [
                            {
                                "title": "合成局部样例练习",
                                "task_or_ability": "接口样例验证",
                                "deliverable": "正常和超时样例日志",
                                "hypothesis": "预期存在可重复观察，尚未实施。",
                                "completion_check": "保留原样本与反例。" * 50
                                + "末尾检查：不以样例通过证明生产验收权限。",
                                "evidence_ids": [row["id"] for row in evidence],
                                "assumptions": ["仅使用合成本地输入。"],
                            }
                        ],
                        "open_questions": ["实际业务验证口径仍需核实。"],
                    }
                call["arguments"] = json.dumps(args)
            return messages, call
        self.contexts.append(context)
        if self.expected_source:
            assert continued["step_id"] == self.expected_source
        if not continued.get("unavailable"):
            assert len(continued["claim_details_to_recheck"][0]["text"]) > 1000
            assert continued["claim_details_to_recheck"][0]["text"].endswith("不能证明生产验收权。")
            assert continued["claim_details_to_recheck"][1]["requirement"] == "preferred"
            assert all("evidence_ids" not in row for row in continued["claim_details_to_recheck"])
            if continued.get("work_map"):
                assert continued["work_map"]["work_relations"][0]["transfer_limit"].endswith(
                    "未验证生产并发。"
                )
            if continued.get("application_plan"):
                assert continued["application_plan"]["actions"][0]["completion_check"].endswith(
                    "生产验收权限。"
                )
                assert "evidence_ids" not in continued["application_plan"]["actions"][0]
        scope = context["fixed_scope"]
        documents = [
            row
            for row in scope.get("public_document_titles", [])
            if row["title"].startswith("合成综合原资料续问")
        ]
        if not outputs:
            if len(scope["jobs"]) == 1:
                name, args = "read_job", {"job_id": scope["jobs"][0]["id"], "start": 0}
            else:
                name, args = (
                    "read_jobs",
                    {"reads": [{"job_id": row["id"], "start": 0} for row in scope["jobs"]]},
                )
        elif documents and not any(row.get("public_document_id") for row in evidence):
            name, args = "read_archived_document", {"document_id": documents[0]["id"], "start": 0}
        else:
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "responsibility",
                            "basis": "synthesis",
                            "requirement": "unspecified",
                            "text": "合成续问：按本轮原文解释工具接入与失败记录，"
                            "实际验收分工仍未知。",
                            "evidence_ids": [row["id"] for row in evidence],
                        }
                    ],
                    "gaps": ["旧补充原文不在当前目录中，无法重核相关旧解释。"]
                    if not documents
                    else ["旧解释与实验建议仍需按实际任务条件核对。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_continue_chosen_discussion_preserves_full_context_and_current_scope(tmp_path):
    database, checkpoint = tmp_path / "continuation.db", tmp_path / "research.db"
    upgrade(database)
    model = DiscussionContinuationModel()
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

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        jobs = [
            post(
                "/api/import",
                {
                    "title": "合成完整续问岗位" + str(index),
                    "company": "合成团队",
                    "data_kind": "synthetic",
                    "description": text,
                },
            )["job_id"]
            for index, text in enumerate(
                [
                    "负责Python接口样例验证，交付失败记录；商科背景更佳，生产审批权未说明。",
                    "负责工具接入和失败记录，实际业务验收分工未说明。",
                ]
            )
        ]
        identity = post(
            "/api/career",
            {
                "title": "合成：长讨论继续追问",
                "goal": "解释边界并核对旧建议",
                "job_ids": jobs,
                "background": "虚构背景：只做过本地样例，没有生产业务验收经历。",
            },
        )["id"]
        base = "/api/career/" + identity
        document = post(
            base + "/materials",
            {
                "title": "合成综合原资料续问",
                "text": "合成工作记录：只记录局部输入输出，不证明生产业务验收。",
            },
        )["materials"][-1]
        first = run_stage(
            client,
            identity,
            auth,
            "map",
            question="保留完整工作解释与建议。",
            selected_job_ids=[jobs[0]],
            material_id=document["id"],
        )["results"][0]
        assert first["result"]["status"] == "completed", json.dumps(
            {key: first["result"].get(key) for key in ("stop_reason", "trace", "model_calls")},
            ensure_ascii=False,
        )
        original = deepcopy(first["result"])
        later = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="另一份较新的完整讨论。",
            selected_job_ids=[jobs[0]],
            material_id=document["id"],
        )["results"][0]
        assert later["result"]["status"] == "completed"
        assert later["result"].get("work_map") != original["work_map"]
        question = post(
            base + "/questions",
            {
                "question": "按另一岗位重新核对适用范围",
                "state": "open",
                "conclusion": "验收范围仍未知。",
                "selected_job_ids": [jobs[1]],
            },
        )["questions"][-1]
        model.expected_source = first["step_id"]
        extras = {
            "question_id": question["id"],
            "source_step_id": first["step_id"],
            "selected_job_ids": [jobs[1]],
            "inherit_focus": False,
        }
        continued = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="这些解释与旧建议在本轮范围中还成立吗？",
            **extras,
        )["results"][0]
        assert continued["result"]["status"] == "completed"
        assert continued["result"]["model_calls"] == 3
        context = model.contexts[-1]
        saved = context["project_context"]["career_evidence"]["continued_discussion"]
        assert saved["work_map"] == original["work_map"]
        assert saved["unresolved_then"] == original["gaps"]
        assert saved["scope"] == original["scope"]
        assert saved["selected_job_ids"] == [jobs[0]]
        assert {row["id"] for row in context["fixed_scope"]["jobs"]} == {jobs[1]}
        assert all(
            "quote" not in row and "id" not in row for row in saved["source_references_to_reread"]
        )
        assert any(
            row["public_document_id"] == document["id"]
            for row in saved["source_references_to_reread"]
        )
        assert {row["job_id"] for row in continued["result"]["evidence"] if row.get("job_id")} == {
            jobs[1]
        }
        assert continued["result"]["claims"][0]["requirement"] == "unspecified"
        model.expected_source = later["step_id"]
        plan_followup = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="解释这份旧实验设计的检查条件。",
            **{**extras, "source_step_id": later["step_id"]},
        )["results"][0]
        assert plan_followup["result"]["status"] == "completed"
        plan_context = model.contexts[-1]["project_context"]["career_evidence"][
            "continued_discussion"
        ]
        assert (
            plan_context["application_plan"]["actions"][0]["completion_check"]
            == (later["result"]["application_plan"]["actions"][0]["completion_check"])
        )
        model.expected_source = first["step_id"]
        client.delete(base + "/materials/" + document["id"], headers=auth)
        limited = run_stage(
            client, identity, auth, "ask", question="仅按当前可用原文核对。", **extras
        )["results"][0]
        assert limited["result"]["status"] == "completed"
        assert limited["result"]["model_calls"] == 2
        assert document["id"] not in limited["document_ids"]
        pending = post(
            base + "/prepare", {"kind": "ask", "question": "当前资料仍可独立查证。", **extras}
        )
        retained = next(row for row in client.get(base).json()["results"]
                        if row["step_id"] == first["step_id"])["result"]
        assert retained["claims"] == original["claims"]
        assert retained["work_map"] == original["work_map"]
        store = ResearchStore(checkpoint, str(database.resolve()))
        store.invalidate_runs([first["run_id"]])
        store.close()
        post("/api/projects/" + identity + "/run", {"step_id": pending["step_id"]})
        for _ in range(200):
            data = client.get(base).json()
            row = next(row for row in data["results"] if row["step_id"] == pending["step_id"])
            if not data["running"] and row["result"]:
                break
            time.sleep(0.01)
        assert row["result"]["status"] == "completed"
        cleared = model.contexts[-1]["project_context"]["career_evidence"]["continued_discussion"]
        assert cleared == {"step_id": first["step_id"], "unavailable": True}
        assert data["questions"][0] == question
        assert (
            next(row for row in data["results"] if row["step_id"] == later["step_id"])["result"][
                "claims"
            ]
            == later["result"]["claims"]
        )
        # Existing stored proposals retain their original citations; only model context strips IDs.
        source_run = ResearchStore(checkpoint, str(database.resolve()))
        assert (
            source_run.get(later["run_id"])["result"]["application_plan"]
            == later["result"]["application_plan"]
        )
        assert source_run.get(first["run_id"])["result"] is None
        source_run.close()
