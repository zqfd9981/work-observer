"""Choose work originals, build their relation map, and continue with the same sources."""

import json
import re

from starlette.testclient import TestClient
from test_career_material_comparison import MaterialComparisonModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

MATERIALS = [
    ("合成地图：业务核对", "核对退款请求与回填账本", "差异清单"),
    ("合成地图：执行平台", "维护异步回填执行器与超时追踪", "执行记录和故障说明"),
]


class MaterialMapModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}
        self.followup = MaterialComparisonModel()

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        if context["project_context"]["career_action"] != "map":
            self.followup.tools = self.tools
            return await self.followup.turn(history)
        selected = [row["document_id"] for row in personal["selected_materials"]]
        assert len(selected) == 2
        assert not personal.get("stories") and not personal.get("learning_notes")
        assert not context.get("application_background")
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_archived_documents", {"reads": [
                {"document_id": key, "start": 0} for key in selected
            ]}
        else:
            evidence = outputs[0]["evidence"]
            claims, groups, relations = [], [], []
            for key in selected:
                source = next(row for row in evidence if row["public_document_id"] == key)
                parts = re.search(r"任务：(.+?)。交付：(.+?)。", source["quote"])
                task, deliverable = parts.groups()
                index = len(claims)
                claims.extend({"category": category, "basis": "direct", "text": text,
                               "requirement": "unspecified", "evidence_ids": [source["id"]]}
                              for category, text in [("task", task), ("deliverable", deliverable)])
                groups.append({"name": source["title"], "problem": "核对该说明中的工作对象与产出。",
                               "tasks": task, "deliverables": deliverable,
                               "claim_indices": [index, index + 1], "basis": "inference",
                               "boundary": "只按各自说明连接，不能合并责任或外推生产。",
                               "next_check": "验收权和实际分工仍需核实。"})
                relations.append({"source_claim_index": index, "target_claim_index": index + 1,
                                  "predicate": "produces", "basis": "inference",
                                  "rationale": "同一份工作说明分别列出了任务与交付物。",
                                  "transfer_limit": "共用回填字样不证明由同一个人负责。"})
            name, args = "finish_research", {"claims": claims,
                "gaps": ["验收权和实际分工仍未知；这些是用户提供的合成说明。"],
                "work_map": {"version": "work-map-v3-work-relations",
                    "scope_note": "两份合成资料的工作关系示例，未选JD，不证明岗位资格或个人能力。",
                    "work_types": groups, "work_relations": relations,
                    "comparisons": [{"relation_indices": [0, 1], "basis": "inference",
                        "common_ground": "都涉及回填工作，但处理对象不同。",
                        "differences": "一侧核对账本并交付差异清单，"
                        "另一侧维护执行器并交付运行记录。",
                        "transfer_conditions": "需要分别核对业务口径与运行条件，不能只凭名称迁移。",
                        "unknowns": ["验收权和实际分工仍未知。"]}],
                    "unknowns": ["用户说明未独立核实，验收权仍未知。"]}, "revisions": []}
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_selected_work_materials_form_a_map_and_continue_with_original_scope(tmp_path):
    database = tmp_path / "material-map.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MaterialMapModel()
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def save(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成：所选资料画地图", "goal": "看清工作线与交付差异",
                    "background": "个人背景不用于本轮工作地图。", "resume_text": "合成个人简历。"})
        identity = goal["id"]
        base = "/api/career/" + identity
        materials = []
        for title, task, deliverable in MATERIALS:
            data = save(base + "/materials", {"title": title,
                        "text": f"任务：{task}。交付：{deliverable}。验收权仍未知。"})
            materials.append(data["materials"][-1]["id"])
        for index in range(22):
            save(base + "/materials", {"title": f"其他合成说明{index}", "text": "其他背景。"})
        custom = "对照所选业务核对和执行平台的任务、交付物与迁移前提。末尾关注：验收权仍未知。"
        question = save(base + "/questions", {"question": "这两条工作线怎样产生不同的交付物？",
                        "material_ids": materials, "state": "answered",
                        "conclusion": "先保留两条工作线，验收权仍未知。"})["questions"][0]
        mapped = run_stage(client, identity, auth, "map", question_id=question["id"],
                           question=custom)["results"][0]
        result = mapped["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert mapped["material_ids"] == materials and mapped["user_question"] == custom
        assert mapped["question_id"] == question["id"]
        assert client.get(base).json()["questions"][0] == question
        assert custom in model.contexts[0]["question"]
        assert len(result["work_map"]["work_relations"]) == 2
        for relation in result["work_map"]["work_relations"]:
            left, right = [result["claims"][index] for index in relation["claim_indices"]]
            assert left["category"] == "task" and right["category"] == "deliverable"
            assert left["evidence_ids"] == right["evidence_ids"]
        assert result["work_map"]["comparisons"][0]["claim_indices"] == [0, 1, 2, 3]
        assert goal["resume"]["document_id"] not in result["scope"]["archived_public_ids"]
        calls = len(model.contexts)
        invalid = client.post(base + "/prepare", headers=auth, json={"kind": "map",
                              "material_ids": [materials[0], goal["resume"]["document_id"]]})
        assert invalid.status_code == 422 and len(model.contexts) == calls
        followup = run_stage(client, identity, auth, "ask", source_step_id=mapped["step_id"],
                             question="核对两条工作线的边界，不能只因都写回填就合并责任。")
        latest = followup["results"][0]
        assert latest["result"]["status"] == "completed"
        assert latest["material_ids"] == materials
        assert set(row["public_document_id"] for row in latest["result"]["evidence"]) == set(
            materials)
