"""The map Agent's own follow-up stays in the same question-driven research."""
import asyncio
import json

from test_cognition_research import MapModel
from test_source_first_research import source_workspace as source_workspace

from work_observer.config import Settings
from work_observer.research.projects import ProjectService, execute_project


class MapWithFollowup(MapModel):
    def __init__(self):
        super().__init__()
        self.proposed = False

    async def turn(self, history):
        outputs, call = await super().turn(history)
        if call["name"] == "finish_research" and not self.proposed:
            self.proposed = True
            call.update(name="propose_investigation", arguments=json.dumps({
                "question": "合成检查接口交付的责任边界",
                "kind": "counterexample", "completion": "按原文核对个人与团队分工",
                "evidence_needed": "岗位原文中的协作和交付表述",
            }))
        return outputs, call


def test_map_followup_inherits_output_scope_and_reply_without_a_new_project(source_workspace):
    repo, store, jobs = source_workspace
    service = ProjectService(store)
    project = service.create("合成领域认识", "接口工作地图", jobs,
                             max_calls=16, max_seconds=360, max_rounds=3)
    project = service.add(project["id"], "合成建立工作地图", revision=project["revision"],
                          approach="work_map", coverage_mode="question", max_calls=6, timeout=120)
    project = asyncio.run(execute_project(service, project["id"], repo, Settings(),
                                          model=MapWithFollowup(), max_steps=2))
    first, second = project["steps"]
    assert second["approach"] == "work_map" and second["coverage_mode"] == "question"
    assert second["reply_to_step_id"] == first["id"]
    assert second["kind"] == "counterexample"
    assert all(step["state"] == "waiting_review" for step in project["steps"])
    result = store.get(second["run_id"])["result"]
    assert result["status"] == "completed" and result["work_map"]
    assert result["continued_from"] == [first["run_id"]]
    assert len(service.list()) == 1
    assert service.usage(project)["reserved_calls"] == 14
