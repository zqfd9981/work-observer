"""A selected JD task drives local practice and stays available for evidence review."""

import json
import re

from starlette.testclient import TestClient
from test_adaptive_investigation import settled, workspace

from work_observer.research.agent import ModelClient


class RequirementPracticeModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}
        self.target = None

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        action = context["project_context"]["career_action"]
        personal = context["project_context"]["career_evidence"]
        jobs = {row["id"] for row in context["fixed_scope"]["jobs"]}
        if action == "evidence":
            selected = personal["selected_requirement"]
            assert selected["key"] == self.target["key"]
            assert selected["requirement"] == "unspecified"
            assert selected["records"][0]["id"] == self.proof_task
            assert jobs == {self.jobs[0]}
            assert self.proof_document in context["fixed_scope"]["archived_public_ids"]
            documents = {self.proof_document}
        elif action != "role":
            assert personal["selected_requirement"] == self.target
            assert jobs == set(self.jobs[:2])
            assert set(context["fixed_scope"]["archived_public_ids"]) == self.documents
            documents = self.documents
        else:
            documents = set()
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs and documents:
            name, args = "read_archived_documents", {
                "reads": [{"document_id": key, "start": 0} for key in sorted(documents)],
            }
        elif not outputs or len(outputs) == 1 and documents:
            name, args = "read_job", {"job_id": self.jobs[0], "start": 0}
        else:
            evidence = outputs[-1]["evidence"][0]
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "direct", "requirement": "unspecified",
                            "text": evidence["quote"], "evidence_ids": [evidence["citation_key"]]}],
                "gaps": ["如何区分本地词面观察与完整的评估集建设经验？"],
            }
            schema = next(tool for tool in self.tools if tool["name"] == name)["parameters"]
            if "application_plan" in schema["properties"]:
                args["application_plan"] = None
            if "revisions" in schema["properties"]:
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_jd_requirement_drives_single_and_suite_practice_then_explicit_evidence_review(tmp_path):
    model = RequirementPracticeModel()
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201, 202}, response.text
            return response.json()

        jobs = [post("/api/import", {
            "title": "合成要求关联岗位" + str(i), "company": "合成团队" + str(i),
            "description": text, "data_kind": "synthetic",
        })["job_id"] for i, text in enumerate([
            "职责：建设检索评估集，核对失败样本；本条没有列出任职资格。",
            "职责：维护端云同步记忆和上下文。", "本次未选入的其他项目工作资料。",
        ])]
        goal = post("/api/career", {
            "title": "合成从要求到评估练习", "goal": "为岗位准备可核对的练习材料", "job_ids": jobs,
            "material_title": "不应混入的其他材料", "material_text": "另一任务的局部说明。",
        })
        model.jobs = jobs
        base = "/api/career/" + goal["id"]

        def run(data):
            step = post(base + "/prepare", data)
            post("/api/projects/" + goal["id"] + "/run", {"step_id": step["step_id"]})
            row = settled(client, base)["results"][0]
            assert row["result"]["status"] == "completed", row["result"].get("stop_reason")
            return row

        run({"kind": "role"})
        requirement = client.get(base).json()["requirements"][0]
        key = requirement["key"]
        post(base + "/requirement-evidence", {
            "requirement_key": key, "records": [], "relevance": "先核对本地查询与标签。",
            "missing": "还缺标注规范与真实语义验证。",
        })
        single = {"job_ids": jobs[:2], "requirement_key": key,
                  "baseline": {"terms": ["查无表达"]}, "candidate": {"terms": ["评估集"]},
                  "expected_job_ids": jobs[:1]}
        values = {"job_ids": jobs[:2], "requirement_key": key, "cases": [
            {"name": "职责核对", "baseline": single["baseline"],
             "candidate": single["candidate"], "expected_job_ids": jobs[:1]},
            {"name": "构造负例", "baseline": {"terms": ["查无表达"]},
             "candidate": {"terms": ["端云同步"]}, "expectation": "none"},
        ]}
        calls = len(model.contexts)
        preview = post(base + "/experiments/retrieval-suite", values)
        saved = post(base + "/experiments/retrieval-suite", {**values, "save": True})
        parent = saved["career"]["tasks"][-1]
        target = parent["target_requirement"]
        assert target == preview["experiment"]["target_requirement"]
        assert target["key"] == key and target["requirement"] == "unspecified"
        assert target["category"] == "task" and target["evidence"] == requirement["evidence"]
        assert target["missing"] == "还缺标注规范与真实语义验证。"
        assert not saved["career"]["requirements"][0]["proof"]["records"]
        quick = post(base + "/experiments/retrieval", {**single, "save": True})
        quick_task = quick["career"]["tasks"][-1]
        assert quick["experiment"]["target_requirement"] == target
        assert quick_task["target_requirement"] == target and len(model.contexts) == calls
        for task in (parent, quick_task):
            replay = client.get(base + "/tasks/" + task["id"] + "/retrieval-inputs").json()
            assert replay["previous"]["target_requirement"] == target
        post(base + "/requirement-evidence", {
            "requirement_key": key, "records": [], "missing": "后来改写的缺口，不改动原练习方向。",
        })
        rerun = post(base + "/experiments/retrieval-suite", {
            **values, "previous_task_id": parent["id"], "save": True,
        })
        child = rerun["career"]["tasks"][-1]
        assert child["target_requirement"] == target
        quick_again = post(base + "/experiments/retrieval", {
            **single, "previous_task_id": quick_task["id"], "save": True,
        })
        assert quick_again["career"]["tasks"][-1]["target_requirement"] == target
        for endpoint, inputs in (("retrieval", single), ("retrieval-suite", values)):
            bad = client.post(base + "/experiments/" + endpoint, headers=auth,
                              json={**inputs, "requirement_key": "missing", "save": True})
            assert bad.status_code == 422
        model.target = target
        model.documents = {parent["artifact_document_id"], child["artifact_document_id"]}
        for kind in ("reflect", "interview"):
            run({"kind": kind, "task_id": child["id"]})
        post(base + "/requirement-evidence", {
            "requirement_key": key, "records": [{"kind": "task", "id": parent["id"]}],
            "relevance": "仅能讨论构造查询、用户标签和逐例核对方法。",
            "missing": "尚无独立标注、模型回答或生产评估证据。",
        })
        model.proof_task, model.proof_document = parent["id"], parent["artifact_document_id"]
        run({"kind": "evidence", "requirement_key": key})
        after = client.get(base).json()
        assert after["requirements"][0]["proof"]["missing"] == (
            "尚无独立标注、模型回答或生产评估证据。"
        )
        assert not after["stories"]
        assert next(row for row in after["tasks"] if row["id"] == parent["id"])[
            "target_requirement"
        ] == target
