"""Run learner-labelled cases locally, save failures and discuss the selected corpus."""

import json
import re
import sqlite3
from copy import deepcopy

from starlette.testclient import TestClient
from test_adaptive_investigation import ScriptedPlanner, brief, settled, workspace
from test_adaptive_investigation import task as investigation_task

from work_observer.research.agent import ModelClient


class SuiteDiscussionModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}
        self.planner = ScriptedPlanner(brief([investigation_task(
            terms=["上下文"], retry=["端云同步"], question="只核对记忆职责样例的标签与返回。",
        )]))

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        review = personal["retrieval_review"]
        assert review["available"] and len(review["input"]["cases"]) == 3
        if getattr(self, "expected_review_origin", None):
            assert review["review_origin"] == self.expected_review_origin
        assert len(review["runs"]) == 6
        expected_extra = getattr(self, "expected_extra", self.jobs[0])
        assert review["runs"][-1]["unexpected_source_keys"] == ["job:" + expected_extra]
        assert {row["id"] for row in context["fixed_scope"]["jobs"]} == set(self.jobs)
        documents = {self.artifact}
        if getattr(self, "parent_artifact", None):
            documents.add(self.parent_artifact)
            assert review["previous_suite_comparison"] == self.expected_comparison
        if getattr(self, "expected_case_name", None):
            selected = personal["selected_retrieval_case"]
            assert selected["name"] == self.expected_case_name
            assert len(selected["runs"]) == 2
            assert selected["input"]["expected_job_ids"] == self.jobs[:1]
            assert (selected["input"]["question"], selected["input"]["label_reason"]) == (
                self.expected_case_intent
            )
            assert selected["runs"][0]["unexpected_source_keys"] == ["job:" + self.jobs[1]]
        if personal.get("selected_story"):
            documents.add(personal["selected_story"]["document_id"])
        assert set(context["fixed_scope"]["archived_public_ids"]) == documents
        if any(tool["name"] == "plan_investigation" for tool in self.tools):
            self.planner.tools = self.tools
            self.planner.plan["tasks"][0]["source_job_ids"] = self.jobs[:]
            calls, raw = await self.planner.turn(history)
            if calls[0]["name"] == "finish_research":
                args = json.loads(calls[0]["arguments"])
                outputs = [json.loads(row["output"]) for row in history
                           if row.get("type") == "function_call_output"]
                evidence = next(row["evidence"] for row in outputs if row.get("engine"))
                for claim, source in zip(args["claims"], evidence, strict=True):
                    claim["text"] = source["quote"][:600]
                calls[0]["arguments"] = json.dumps(args)
            return calls, raw
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_archived_documents", {
                "reads": [{"document_id": key, "start": 0} for key in sorted(documents)],
            }
        elif len(outputs) == 1:
            name, args = "read_job", {"job_id": self.jobs[0], "start": 0}
        else:
            jd = outputs[-1]["evidence"][0]
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "direct", "requirement": "unspecified",
                            "text": jd["quote"], "evidence_ids": [jd["citation_key"]]}],
                "gaps": ["为何改写找回了更多来源，也可能同时产生额外返回？"],
            }
            schema = next(tool for tool in self.tools if tool["name"] == name)["parameters"]
            if "application_plan" in schema["properties"]:
                args["application_plan"] = None
            if "revisions" in schema["properties"]:
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_suite_keeps_case_failures_and_shared_scope_through_save_replay_and_interview(tmp_path):
    model = SuiteDiscussionModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        bodies = ["负责知识库检索，构造评估集和失败样本。",
                  "负责端云同步与记忆存储，使用KV管理上下文。",
                  "负责其他项目的任务与交付，未涉及本组检索问题。", "评估集与端云同步。"]
        jobs = [post("/api/import", {
            "title": "合成样例岗位" + str(i), "company": "合成团队" + str(i),
            "description": body, "data_kind": "synthetic",
        })["job_id"] for i, body in enumerate(bodies)]
        goal = post("/api/career", {
            "title": "合成小样本评估", "goal": "逐条核对标签和失败原因", "job_ids": jobs[:3],
            "first_question": "找回更多来源是否一定说明查询更好？",
            "material_title": "不应混入的其他说明", "material_text": "另一项目的材料。",
        })
        base = "/api/career/" + goal["id"]

        def case(name, baseline, candidate, expected=None):
            return {"name": name, "baseline": {"terms": [baseline]},
                    "candidate": {"terms": [candidate]},
                    "expectation": "sources" if expected else "none",
                    "expected_job_ids": expected or []}

        values = {"job_ids": jobs[:2], "top_k": 3, "question_id": goal["focus_question_id"],
                  "hypothesis": "更具体的表达可能找回职责，但也可能在负例上返回资料。",
                  "cases": [case("评估职责", "查无表达甲", "评估集", jobs[:1]),
                            case("记忆职责", "上下文", "端云同步", jobs[1:2]),
                            case("不应命中的问题", "查无表达乙", "评估集")]}
        question = "如何找到端云上下文管理的原始工作要求？\n" * 35 + "原问题末尾<保留>"
        reason = (
            "第二份原文明确提到端云同步与KV记忆，其他资料仍需逐条区分。\n" * 25 + "标签理由末尾"
        )
        values["cases"][1].update(question=question, label_reason=reason)
        preview = post(base + "/experiments/retrieval-suite", values)["experiment"]
        assert preview["input"]["cases"][1]["question"] == question
        assert preview["input"]["cases"][1]["label_reason"] == reason
        without_intent = deepcopy(values)
        without_intent["cases"][1].pop("question")
        without_intent["cases"][1].pop("label_reason")
        plain = post(base + "/experiments/retrieval-suite", without_intent)["experiment"]
        assert [run["metrics"] for run in plain["runs"]] == [
            run["metrics"] for run in preview["runs"]
        ]  # User intent explains the label; it never changes retrieval scoring.
        assert len(preview["runs"]) == 6 and len(preview["comparison_rows"]) == 6
        assert preview["totals"][0]["source_recall"] == 0.5
        assert preview["totals"][1]["source_recall"] == 1
        assert preview["totals"][1]["source_precision"] == 2 / 3
        assert [row["exact_label_matches"] for row in preview["totals"]] == [2, 2]
        assert preview["runs"][0]["missing_expected_source_keys"] == ["job:" + jobs[0]]
        assert preview["runs"][-1]["metrics"]["correct_no_match"] is False
        assert {row["job_id"] for row in preview["sources"]} == set(jobs[:2])
        assert not client.get(base).json()["tasks"] and not model.contexts
        for invalid in [
            {**values, "job_ids": [jobs[3]]},
            {**values, "cases": [values["cases"][0]] * 2},
            {**values, "top_k": True},
            {**values, "cases": [case("范围外标签", "甲", "乙", jobs[3:]),
                                  values["cases"][1]]},
        ]:
            rejected = client.post(base + "/experiments/retrieval-suite", headers=auth,
                                   json={**invalid, "save": True})
            assert rejected.status_code == 422, rejected.text
        assert not client.get(base).json()["tasks"]
        saved = post(base + "/experiments/retrieval-suite", {**values, "save": True})
        task = saved["career"]["tasks"][-1]
        assert task["state"] == "done" and task["local_experiment"] == "retrieval_suite"
        assert task["question_id"] == goal["focus_question_id"]
        assert len(task["comparison_rows"]) == 6 and task["outcome"]
        replay = client.get(base + "/tasks/" + task["id"] + "/retrieval-inputs").json()
        assert replay["record_kind"] == "retrieval_suite"
        assert replay["input"] == saved["experiment"]["input"]
        assert replay["input"]["cases"][1]["label_reason"] == reason
        model.jobs, model.artifact = jobs[:2], task["artifact_document_id"]
        for kind in ("reflect", "interview"):
            step = post(base + "/prepare", {"kind": kind, "task_id": task["id"]})
            post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
            discussed = settled(client, base)["results"][0]
            assert discussed["result"]["status"] == "completed", discussed["result"]
            assert len(discussed["result"]["career_learning_context"]["retrieval_review"][
                "runs"
            ]) == 6
        story = post(base + "/stories", {
            "title": "合成局部评估练习", "source_task_id": task["id"],
            "situation": "只使用本机的合成资料。", "action": "配置三条查询和使用者预期。",
            "result": "改写找回正例，也在负例中返回来源。",
            "limits": "这是本机词面检查，没有验证语义质量或生产效果。",
        })["stories"][-1]
        assert len(story["retrieval_source"]["runs"]) == 6
        step = post(base + "/prepare", {"kind": "interview", "story_id": story["id"]})
        post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
        discussed = settled(client, base)["results"][0]
        assert discussed["result"]["status"] == "completed", discussed["result"]
        before = deepcopy(client.get(base).json()["tasks"])
        rerun = post(base + "/experiments/retrieval-suite", {
            **values, "save": True, "previous_task_id": task["id"],
        })
        assert rerun["career"]["tasks"][-1]["previous_task_id"] == task["id"]
        assert rerun["career"]["tasks"][:-1] == before
        unchanged = rerun["experiment"]["previous_comparison"]
        assert not unchanged["shared_changed_conditions"]
        assert all(row["state"] == "matched" and not row["changed_conditions"]
                   for row in unchanged["cases"])
        revised = deepcopy(values)
        revised["top_k"] = 1
        revised["cases"][0]["baseline"] = {"terms": ["评估集"]}
        revised["cases"][1]["expected_job_ids"] = jobs[:1]
        revised["cases"][1]["question"] = "这次改问如何找到评估集建设职责？"
        revised["cases"][1]["label_reason"] = "改为第一份原文中的评估集职责，原问题与标签一起改变。"
        revised["cases"] = [revised["cases"][1], revised["cases"][0],
                            case("新增：端云负例", "端云同步", "端云同步")]
        changed = post(base + "/experiments/retrieval-suite", {
            **revised, "save": True, "previous_task_id": task["id"],
        })
        comparison = changed["experiment"]["previous_comparison"]
        assert comparison["shared_changed_conditions"] == ["片段上限"]
        cases = {row["name"]: row for row in comparison["cases"]}
        assert cases["新增：端云负例"]["before"] is None
        assert cases["不应命中的问题"]["after"] is None
        assert {row["state"] for row in cases.values()} == {"matched", "added", "removed"}
        assert "原查询" in cases["评估职责"]["changed_conditions"]
        assert "预期相关标签" in cases["记忆职责"]["changed_conditions"]
        assert "样例问题" in cases["记忆职责"]["changed_conditions"]
        assert "标签依据" in cases["记忆职责"]["changed_conditions"]
        assert cases["记忆职责"]["before"]["input"]["question"] == question
        assert cases["记忆职责"]["before"]["input"]["label_reason"] == reason
        assert cases["记忆职责"]["after"]["input"]["question"] == revised["cases"][0]["question"]
        returns = cases["评估职责"]["return_comparison"][0]["sources"]
        source = next(row for row in returns if row["source_key"] == "job:" + jobs[0])
        assert not source["before"]["returned"] and source["after"]["returned"]
        labels = cases["记忆职责"]["return_comparison"][0]["sources"]
        source = next(row for row in labels if row["source_key"] == "job:" + jobs[1])
        assert source["before"]["returned"] and source["after"]["returned"]
        assert source["before"]["expected"] and not source["after"]["expected"]
        changed_task = changed["career"]["tasks"][-1]
        assert changed_task["retrieval_suite_comparison"] == comparison
        assert "预期相关标签" in changed_task["design_change"]
        assert changed["career"]["tasks"][:-2] == before
        model.artifact, model.parent_artifact = changed_task["artifact_document_id"], model.artifact
        model.expected_comparison, model.expected_extra = comparison, jobs[1]
        step = post(base + "/prepare", {"kind": "reflect", "task_id": changed_task["id"]})
        post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
        discussed = settled(client, base)["results"][0]
        assert discussed["result"]["status"] == "completed", discussed["result"]
        assert discussed["result"]["career_learning_context"]["retrieval_review"][
            "previous_suite_comparison"
        ] == comparison
        for invalid in ("不存在的样例", ""):
            rejected = client.post(base + "/prepare", headers=auth, json={
                "kind": "ask", "task_id": changed_task["id"], "retrieval_case_name": invalid,
                "question": "只追问这一条。",
            })
            assert rejected.status_code == 422, rejected.text
        model.expected_case_name = "记忆职责"
        model.expected_case_intent = (
            revised["cases"][0]["question"], revised["cases"][0]["label_reason"],
        )
        step = post(base + "/prepare", {
            "kind": "ask", "task_id": changed_task["id"],
            "retrieval_case_name": model.expected_case_name,
            "question_id": goal["focus_question_id"], "selected_job_ids": jobs[:2],
            "inherit_focus": False, "material_ids": [],
            "adaptive": True,
            "question": "只核对这条样例：改变预期标签，为什么不能证明查询修复？",
        })
        post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
        focused = settled(client, base)["results"][0]
        assert focused["result"]["status"] == "completed", focused["result"]
        selected = focused["result"]["career_learning_context"]["retrieval_case"]
        assert selected["name"] == model.expected_case_name
        assert selected["input"]["question"] == revised["cases"][0]["question"]
        assert selected["input"]["label_reason"] == revised["cases"][0]["label_reason"]
        assert focused["retrieval_case_name"] == model.expected_case_name
        continued = post(base + "/prepare", {
            "kind": "ask", "source_step_id": focused["step_id"],
            "adaptive": True,
            "question": "如果保持原来的预期标签，应补哪项实际观察？",
        })
        post("/api/projects/" + goal["id"] + "/run", {"step_id": continued["step_id"]})
        discussed = settled(client, base)["results"][0]
        assert discussed["result"]["status"] == "completed", discussed["result"]
        assert discussed["result"]["career_learning_context"]["retrieval_case"] == selected
        model.expected_case_name = None
        # Continue from the diagnosis, retaining the specific old case and discussion.
        followup_values = deepcopy(revised)
        followup_values.update(previous_task_id=changed_task["id"],
                               review_step_id=discussed["step_id"])
        followup_values["cases"][0]["candidate"] = {"terms": ["评估集"]}
        calls, tasks_before = len(model.contexts), deepcopy(client.get(base).json()["tasks"])
        preview = post(base + "/experiments/retrieval-suite", followup_values)
        assert client.get(base).json()["tasks"] == tasks_before
        next_run = post(base + "/experiments/retrieval-suite", {**followup_values, "save": True})
        next_task = next_run["career"]["tasks"][-1]
        review_origin = next_run["experiment"]["review_origin"]
        assert len(model.contexts) == calls
        assert preview["experiment"]["review_origin"] == review_origin
        assert review_origin["step_id"] == discussed["step_id"]
        assert review_origin["source_case"] == selected
        assert next_task["retrieval_review_step_id"] == discussed["step_id"]
        assert next_task["question_id"] == changed_task["question_id"]
        assert next_run["career"]["tasks"][:-1] == tasks_before
        loaded = client.get(base + "/tasks/" + next_task["id"] + "/retrieval-inputs").json()
        assert loaded["previous"]["review_origin"] == review_origin
        assert loaded["previous"]["review_step_id"] == discussed["step_id"]
        assert loaded["input"]["cases"][0]["candidate"]["terms"] == ["评估集"]
        assert review_origin["source_case"]["input"]["candidate"]["terms"] == ["端云同步"]
        for overrides in ({"previous_task_id": None}, {"previous_task_id": task["id"]},
                          {"review_step_id": "f" * 32}):
            response = client.post(base + "/experiments/retrieval-suite", headers=auth, json={
                **followup_values, **overrides, "save": True,
            })
            assert response.status_code == 422, response.text
        assert len(client.get(base).json()["tasks"]) == len(tasks_before) + 1
        # An explicit replay can retain the same diagnosis through a subsequent run.
        again = post(base + "/experiments/retrieval-suite", {
            **followup_values, "previous_task_id": next_task["id"],
        })
        assert again["experiment"]["review_origin"] == review_origin
        old_artifact, old_parent, old_comparison = (
            model.artifact, model.parent_artifact, model.expected_comparison,
        )
        model.artifact = next_task["artifact_document_id"]
        model.parent_artifact = changed_task["artifact_document_id"]
        model.expected_comparison = next_run["experiment"]["previous_comparison"]
        model.expected_review_origin = review_origin
        step = post(base + "/prepare", {"kind": "reflect", "task_id": next_task["id"]})
        post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
        reflected = settled(client, base)["results"][0]
        assert reflected["result"]["status"] == "completed", reflected["result"].get("stop_reason")
        assert reflected["result"]["career_learning_context"]["retrieval_review"][
            "review_origin"
        ] == review_origin
        model.artifact, model.parent_artifact, model.expected_comparison = (
            old_artifact, old_parent, old_comparison,
        )
        model.expected_review_origin = None
        revised_story = post(base + "/stories", {
            "title": "合成评估复验经历", "source_task_id": changed_task["id"],
            "situation": "检查失败样例后重新运行。", "action": "修改查询和标签，并保留移除样例。",
            "result": "有一条原先漏回的来源重新返回；另一条只改变了预期标签。",
            "limits": "仍是小样本词面检索，不能从改标签证明修复。",
        })["stories"][-1]
        step = post(base + "/prepare", {"kind": "interview", "story_id": revised_story["id"]})
        post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
        discussed = settled(client, base)["results"][0]
        assert discussed["result"]["status"] == "completed", discussed["result"]
        document_id = goal["materials"][0]["id"]
        with sqlite3.connect(tmp_path / "adaptive.db") as connection:
            connection.execute("UPDATE public_documents SET text=? WHERE id=?",
                               ("模拟临时材料不完整，保留旧哈希用于完整性检查。", document_id))
        incomplete = post(base + "/experiments/retrieval-suite", {
            "job_ids": jobs[:1], "document_ids": [document_id],
            "cases": [case("空问题甲", "甲甲甲", "乙乙乙"),
                      case("空问题乙", "丙丙丙", "丁丁丁")],
        })["experiment"]
        assert not incomplete["corpus_complete"]
        assert all(row["exact_label_matches"] is None for row in incomplete["totals"])
        assert all(row["source_recall"] is None for row in incomplete["totals"])
        assert all(row["metrics"]["correct_no_match"] is None for row in incomplete["runs"])
