"""Research starts with working material and can later connect to a target JD."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class MaterialWorkspaceModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        if context["fixed_scope"]["jobs"]:
            return await CareerModel.turn(self, history)
        self.contexts.append(context)
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            source = next(row for row in context["fixed_scope"]["public_document_titles"]
                          if row["title"].startswith("合成工作说明"))
            name, args = "read_archived_document", {"document_id": source["id"], "start": 0}
        else:
            ev = outputs[0]["evidence"][0]["id"]
            name, args = "finish_research", {
                "claims": [
                    {"category": category, "basis": "direct", "requirement": "unspecified",
                     "text": text, "evidence_ids": [ev]}
                    for category, text in (
                        ("task", "合成工作说明描述构造失败请求。"),
                        ("deliverable", "合成工作说明描述交付样例、日志和观察记录。"),
                    )
                ],
                "gaps": ["这不是招聘JD；生产运行与个人岗位责任仍未知。"],
                "application_plan": None,
            }
            project = context["project_context"]
            if project.get("previous_findings") or project.get("historical_reply"):
                args["revisions"] = []
            if project["career_action"] == "map":
                args.pop("application_plan")
                args["work_map"] = {
                    "version": "work-map-v3-work-relations",
                    "scope_note": "只解释用户提供的合成工作说明，不代表企业岗位或独立执行。",
                    "work_types": [], "comparisons": [],
                    "work_relations": [{"source_claim_index": 0, "target_claim_index": 1,
                                        "predicate": "produces", "basis": "inference",
                                        "rationale": "失败请求验证可留下样例与观察记录。",
                                        "transfer_limit": "只限合成说明，生产并发与招聘条件未知。",
                                        }],
                    "unknowns": ["真实业务验收与个人权限未说明。"],
                }
                args["revisions"] = []
            if project["career_action"] == "plan":
                args["application_plan"] = {
                    "background_memory_id": context["application_background"]["memory_id"],
                    "actions": [{"title": "合成请求观察练习", "task_or_ability": "理解失败验证",
                                 "deliverable": "样例和观察",
                                 "completion_check": "比较正常与失败输入",
                                 "hypothesis": "失败请求可能改变输出，仍需在本地样例中检查。",
                                 "evidence_ids": [ev], "assumptions": ["仅使用本地合成数据"]}],
                    "open_questions": ["不能据此证明招聘胜任或生产效果。"],
                }
        if name == "finish_research" and not context.get("application_background"):
            args.pop("application_plan", None)
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_material_first_workspace_researches_without_jobs_and_later_adds_jd(tmp_path):
    database = tmp_path / "material-start.db"
    upgrade(database)
    model = MaterialWorkspaceModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        shell = post("/api/career", {"title": "合成空白方向", "goal": "先整理问题"})
        response = client.post(f"/api/career/{shell['id']}/prepare", headers=auth,
                               json={"kind": "map"})
        assert response.status_code == 422 and not model.contexts
        original = "合成工作说明：构造失败请求，交付样例、日志和观察记录；生产并发未验证。"
        created = post("/api/career", {
            "title": "合成资料研究", "goal": "理解失败验证如何产生工作产物",
            "material_title": "合成工作说明", "material_text": original,
            "resume_text": "合成个人简历：仅用于个人应用，岗位理解不得读取。",
        })
        identity = created["id"]
        base = f"/api/career/{identity}"
        assert not created["jobs"] and created["materials"] and not model.contexts
        source = created["materials"][0]["id"]
        assert original in client.get("/api/public-documents/" + source).json()["text"]
        mapped = run_stage(client, identity, auth, "map")["results"][0]
        assert mapped["result"]["status"] == "completed", mapped["result"].get("stop_reason")
        assert mapped["materials_only"] and mapped["result"]["work_map"]["unknowns"]
        scope = model.contexts[-1]["fixed_scope"]
        assert not scope["jobs"] and len(scope["public_document_titles"]) == 1
        assert scope["public_document_titles"][0]["id"] == source
        assert not client.get(base).json()["requirements"]
        question = post(base + "/questions", {
            "question": "哪些工作关系仍未得到验证？", "source_step_id": mapped["step_id"],
        })["questions"][0]
        asked = run_stage(client, identity, auth, "ask", question=question["question"],
                          question_id=question["id"])
        assert asked["results"][0]["result"]["status"] == "completed", (
            asked["results"][0]["result"].get("stop_reason")
        )
        response = client.patch(base, headers=auth, json={
            "title": created["title"], "goal": created["goal"], "job_ids": [],
            "background": "只做本地合成请求练习，未有生产经验。",
        })
        assert response.status_code == 200, response.text
        planned = run_stage(client, identity, auth, "plan", question_id=question["id"])
        row = planned["results"][0]
        assert row["result"]["status"] == "completed"
        task = post(base + "/tasks", {"step_id": row["step_id"]})["tasks"][0]
        assert task["question_id"] == question["id"]
        job = post("/api/import", {
            "title": "合成目标岗位", "company": "合成团队", "data_kind": "synthetic",
            "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
        })["job_id"]
        response = client.patch(base, headers=auth, json={
            "title": created["title"], "goal": created["goal"], "job_ids": [job],
            "background": "只做本地合成请求练习，未有生产经验。",
        })
        assert response.status_code == 200, response.text
        linked = run_stage(client, identity, auth, "role")
        assert linked["requirements"] and not linked["results"][0]["materials_only"]
        assert linked["tasks"][0] == task and linked["questions"][0]["id"] == question["id"]
        old_map = next(row for row in linked["results"] if row["step_id"] == mapped["step_id"])
        assert old_map["materials_only"]
        assert old_map["result"]["work_map"] == mapped["result"]["work_map"]
