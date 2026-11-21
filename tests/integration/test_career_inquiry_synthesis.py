"""Synthesize selected inquiries while reading current originals, with a local model substitute."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


class InquirySynthesisModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        scope = context["fixed_scope"]
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        evidence = [row for output in outputs for row in output.get("evidence", [])]
        documents = [
            row
            for row in scope.get("public_document_titles", [])
            if row["title"].startswith("合成综合原资料") or "综合实验日志" in row["title"]
        ]
        if not outputs:
            if len(scope["jobs"]) > 1:
                name, args = (
                    "read_jobs",
                    {"reads": [{"job_id": job["id"], "start": 0} for job in scope["jobs"]]},
                )
            else:
                name, args = "read_job", {"job_id": scope["jobs"][0]["id"], "start": 0}
        elif documents and not any(row.get("public_document_id") for row in evidence):
            if len(documents) == 1:
                name, args = (
                    "read_archived_document",
                    {
                        "document_id": documents[0]["id"],
                        "start": 0,
                    },
                )
            else:
                name, args = (
                    "read_archived_documents",
                    {
                        "reads": [{"document_id": row["id"], "start": 0} for row in documents],
                    },
                )
        else:
            bundle = context["project_context"]["career_evidence"].get("synthesis_inquiries")
            text = (
                "合成综合判断：接口失败记录与业务验收是不同观察；商科更佳仅是所指岗位的加分项，"
                "不能从练习通过推出个人拥有生产验收权。"
                if bundle
                else "合成历史判断：仅描述局部样例。"
                + "保留原任务和适用范围。" * 95
                + "末尾限定：不能证明生产验收权。"
            )
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "synthesis",
                            "requirement": "unspecified",
                            "text": text,
                            "evidence_ids": [row["id"] for row in evidence],
                        }
                    ],
                    "gaps": ["实际验收分工与练习之外的适用范围仍未知。"],
                },
            )
            if not bundle and len(scope["jobs"]) == 1 and scope["jobs"][0]["title"].endswith("1"):
                args["claims"] = [
                    {
                        "category": "ability",
                        "basis": "direct",
                        "requirement": "preferred",
                        "text": "原岗位写明商科背景更佳，属于加分条件。",
                        "evidence_ids": [row["id"] for row in evidence if row.get("job_id")],
                    }
                ]
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_synthesize_inquiries_reads_originals_and_keeps_the_chosen_history(tmp_path):
    database = tmp_path / "synthesis.db"
    upgrade(database)
    model = InquirySynthesisModel()
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model,
            reports_dir=tmp_path / "reports",
            checkpoint_path=tmp_path / "research.db",
        ),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        jobs = [
            post(
                "/api/import",
                {
                    "title": "合成综合调查岗位" + str(index),
                    "company": "合成团队",
                    "data_kind": "synthetic",
                    "description": text,
                },
            )["job_id"]
            for index, text in enumerate(
                [
                    "负责工具接口接入和失败记录；生产验收权未说明。",
                    "参与业务验证，商科背景更佳。",
                ]
            )
        ]
        identity = post(
            "/api/career",
            {
                "title": "合成：从多个调查建立整体理解",
                "goal": "连接工作、资格和实验观察",
                "job_ids": jobs,
            },
        )["id"]
        base = "/api/career/" + identity
        questions, sources, documents = [], [], []
        for index, title in enumerate(["接口验证能证明什么？", "商科更佳与工作有什么关系？"]):
            saved = post(
                base + "/questions",
                {
                    "question": title,
                    "state": "open",
                    "selected_job_ids": [jobs[index]],
                    "conclusion": "这是个人理解。"
                    + "保留当前条件。" * 130
                    + "最终限定：尚无业务验收依据。",
                },
            )
            question = saved["questions"][-1]
            questions.append(question)
            material = post(
                base + "/materials",
                {
                    "title": "合成综合原资料" + str(index),
                    "text": "合成工作记录："
                    + (
                        "只检查接口输入输出。" if index == 0 else "商业理解是加分，不等于必备资格。"
                    ),
                },
            )["materials"][-1]
            documents.append(material["id"])
            answer = run_stage(
                client,
                identity,
                auth,
                "ask",
                question_id=question["id"],
                question=title,
                material_id=material["id"],
            )["results"][0]
            assert answer["result"]["status"] == "completed", json.dumps(
                {
                    k: v
                    for k, v in answer["result"].items()
                    if k in ("error", "message", "gaps", "stop_reason", "trace", "model_calls")
                },
                ensure_ascii=False,
            )
            sources.append(answer["step_id"])
        task = post(
            base + "/experiments",
            {
                "title": "合成综合实验",
                "question_id": questions[0]["id"],
                "task_or_ability": "接口超时验证",
                "deliverable": "输入输出日志",
                "completion_check": "比较超时和重试",
                "hypothesis": "预期重试可避免失败，这还不是结果。",
            },
        )["tasks"][-1]
        changed = client.patch(
            base + "/tasks/" + task["id"],
            headers=auth,
            json={
                "state": "done",
                "outcome": "用户报告：重试仍失败。"
                + "保留原样本。" * 180
                + "末尾观察：未运行真实业务验收。",
                "artifact": "本地合成日志",
                "artifact_title": "综合实验日志",
                "artifact_text": "合成日志：timeout -> retry -> timeout。",
            },
        )
        assert changed.status_code == 200, changed.text
        artifact = changed.json()["tasks"][-1]["artifact_document_id"]
        post(
            base + "/experiments",
            {
                "title": "合成尚未执行的后续",
                "question_id": questions[1]["id"],
                "task_or_ability": "验证迁移条件",
                "deliverable": "对照记录",
                "completion_check": "保留反例",
                "hypothesis": "尚待实施，不能算观察。",
            },
        )
        post(
            base + "/insights",
            {
                "question_id": questions[0]["id"],
                "source_step_id": sources[0],
                "previous_view": "原先过度外推。",
                "observation": "合成局部练习出现失败。",
                "current_view": "个人认识。"
                + "仅按已有记录理解。" * 130
                + "末尾认识限定：不证明验收权限。",
                "open_question": "谁实际做验收？",
            },
        )
        for index in range(21):
            post(base + "/materials", {"title": "其他合成材料" + str(index), "text": "无关说明。"})
        before = deepcopy(client.get(base).json()["questions"])
        bundle = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="把两项调查连起来解释。",
            synthesis_question_ids=[row["id"] for row in questions],
        )["results"][0]
        assert bundle["result"]["status"] == "completed", json.dumps(
            {
                k: v
                for k, v in bundle["result"].items()
                if k in ("error", "message", "gaps", "stop_reason", "trace", "model_calls")
            },
            ensure_ascii=False,
        )
        assert bundle["result"]["model_calls"] == 3
        assert bundle["question_id"] is None
        assert [row["step_id"] for row in bundle["synthesis_sources"]] == sources
        assert {row["job_id"] for row in bundle["result"]["evidence"] if row.get("job_id")} == set(
            jobs
        )
        read_documents = {row.get("public_document_id") for row in bundle["result"]["evidence"]}
        assert {*documents, artifact} <= read_documents
        selected = model.contexts[-1]["project_context"]["career_evidence"]["synthesis_inquiries"]
        assert len(selected) == 2
        assert selected[0]["inquiry"]["conclusion"].endswith("尚无业务验收依据。")
        assert selected[0]["discussion"]["claims_to_recheck"][0]["text"].endswith(
            "不能证明生产验收权。"
        )
        assert len(selected[0]["discussion"]["claims_to_recheck"][0]["text"]) > 1000
        assert "evidence_ids" not in selected[0]["discussion"]["claims_to_recheck"][0]
        assert selected[1]["discussion"]["claims_to_recheck"][0]["requirement"] == "preferred"
        assert selected[1]["discussion"]["claims_to_recheck"][0]["basis"] == "direct"
        assert selected[0]["experiments"][0]["outcome"].endswith("未运行真实业务验收。")
        assert selected[1]["experiments"][0]["state"] == "planned"
        assert not selected[1]["experiments"][0]["outcome"]
        assert selected[0]["learning_notes"][0]["current_user_view"].endswith("不证明验收权限。")
        newer = run_stage(
            client, identity, auth, "ask", question_id=questions[0]["id"], question="单项后续研究"
        )["results"][0]
        assert newer["step_id"] != sources[0]
        continued = run_stage(
            client,
            identity,
            auth,
            "ask",
            source_step_id=bundle["step_id"],
            question="接着这组调查核对共同盲区。",
            inherit_focus=False,
        )["results"][0]
        assert continued["result"]["status"] == "completed"
        assert continued["synthesis_sources"] == bundle["synthesis_sources"]
        chosen = model.contexts[-1]["project_context"]["career_evidence"]["synthesis_inquiries"]
        assert [item["discussion"]["step_id"] for item in chosen] == sources
        assert client.get(base).json()["questions"] == before
        first_run = next(
            row["run_id"]
            for row in client.get(base).json()["results"]
            if row["step_id"] == sources[0]
        )
        store = ResearchStore(tmp_path / "research.db", str(database.resolve()))
        store.invalidate_runs([first_run])
        store.close()
        resumed = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="重核仍保留的资料与个人观察。",
            source_step_id=bundle["step_id"],
            inherit_focus=False,
        )["results"][0]
        assert resumed["result"]["status"] == "completed"
        remaining = model.contexts[-1]["project_context"]["career_evidence"]["synthesis_inquiries"]
        assert remaining[0]["discussion"] is None and remaining[0]["discussion_unavailable"]
        note = remaining[0]["learning_notes"][0]
        assert note["current_user_view"].endswith("不证明验收权限。")
        assert "source_discussion" not in note and "source_locators" not in note
        extra_questions = [
            post(
                base + "/questions",
                {
                    "question": title,
                    "state": "open",
                },
            )["questions"][-1]
            for title in ("谁决定业务验收？", "失败样例如何迁移到新任务？")
        ]
        identities = [row["id"] for row in [*questions, *extra_questions]]
        expanded = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="综合四个问题的联系和未知。",
            synthesis_question_ids=identities,
        )["results"][0]
        assert expanded["result"]["status"] == "completed"
        context = model.contexts[-1]["project_context"]["career_evidence"]["synthesis_inquiries"]
        assert [item["inquiry"]["id"] for item in context] == identities
        assert all(item["discussion"] is None for item in context[2:])
        removed = client.delete(base + "/materials/" + documents[0], headers=auth)
        assert removed.status_code == 200, removed.text
        limited = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="只按当前还可用的资料重核。",
            synthesis_question_ids=identities,
        )["results"][0]
        assert limited["result"]["status"] == "completed"
        assert documents[0] not in limited["document_ids"]
        assert not any(
            row.get("public_document_id") == documents[0] for row in limited["result"]["evidence"]
        )
        for ids in ([questions[0]["id"]] * 2, [questions[0]["id"], "f" * 32]):
            response = client.post(
                base + "/prepare",
                headers=auth,
                json={
                    "kind": "ask",
                    "question": "无效选择",
                    "synthesis_question_ids": ids,
                },
            )
            assert response.status_code == 422
