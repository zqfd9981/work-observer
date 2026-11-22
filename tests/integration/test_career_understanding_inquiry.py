"""Two saved views become an open inquiry without treating either as a new finding."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.collection.contracts import now
from work_observer.config import Settings
from work_observer.research.historical_sources import read
from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


class ComparisonModel(CareerModel):
    async def turn(self, history):
        context = json.loads(history[1]["content"])
        inquiry = (
            context.get("project_context", {})
            .get("career_evidence", {})
            .get(
                "selected_inquiry",
            )
            or {}
        )
        carried = inquiry.get("carried_understanding") or {}
        if carried.get("learning_notes"):
            outputs = [row for row in history if row.get("type") == "function_call_output"]
            references = list(
                {
                    (row["job_id"], row["as_of"]): row for row in carried["source_references"]
                }.values()
            )
            if len(outputs) < len(references):
                self.contexts.append(context)
                source = references[len(outputs)]
                call = {
                    "type": "function_call",
                    "name": "read_historical_job",
                    "arguments": json.dumps(
                        {"job_id": source["job_id"], "as_of": source["as_of"], "start": 0}
                    ),
                    "call_id": str(len(history)),
                }
                return [call], call
        return await super().turn(history)


def test_two_notes_keep_full_origins_and_reread_sources_without_changing_old_goals(tmp_path):
    database = tmp_path / "understanding.db"
    upgrade(database)
    model = ComparisonModel()
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model,
            checkpoint_path=tmp_path / "runs.db",
            reports_dir=tmp_path / "reports",
        ),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(
                r'name="wo-token" content="([^"]+)"',
                client.get("/").text,
            )[1]
        }

        def save(path, values, method="POST"):
            response = client.request(method, path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        originals, references = [], []
        for index in range(2):
            job = save(
                "/api/import",
                {
                    "title": f"合成岗位{index}",
                    "company": "合成团队",
                    "data_kind": "synthetic",
                    "description": "必须掌握Python接口测试。只做局部失败样例，生产验收权限未说明。",
                },
            )["job_id"]
            goal = save(
                "/api/career",
                {
                    "title": f"合成认识{index}",
                    "goal": "区分样例验证与生产责任。",
                    "job_ids": [job],
                },
            )
            source = run_stage(client, goal["id"], auth, "role")["results"][0]
            note_values = {
                "source_step_id": source["step_id"],
                "source_claim_index": 0,
                "previous_view": "原先把测试能力理解为生产责任。",
                "observation": f"实际观察{index}：只读到局部任务说明。",
                "current_view": "完整条件🤔" * 100 + f"末尾限定{index}：只适用于当前样例。",
                "open_question": f"未决问题{index}：谁验收生产交付？",
            }
            updated = save(f"/api/career/{goal['id']}/insights", note_values)
            note = updated["insights"][-1]
            if index == 0:
                updated = save(
                    f"/api/career/{goal['id']}/insights/{note['id']}/use",
                    {
                        "use_for_research": False,
                    },
                )
                note = updated["insights"][-1]
            originals.append(updated)
            references.append({"project_id": goal["id"], "note_id": note["id"]})
        calls = len(model.contexts)
        request = {
            "notes": references,
            "question": "两种解释的差异是否来自任务范围不同？",
            "why_matters": "我想区分真实交付与局部练习。",
            "next_evidence": "分别核实验收人和失败样例。",
        }
        endpoint = "/api/career/understanding/inquiry"
        invalid = client.post(
            endpoint, headers=auth, json={**request, "notes": [references[0]] * 2}
        )
        assert invalid.status_code == 422
        forged = client.post(
            endpoint,
            headers=auth,
            json={
                **request,
                "notes": [{**references[0], "current_view": "伪造旧认识"}, references[1]],
            },
        )
        assert forged.status_code == 422
        paired = save(endpoint, request)
        inquiry = paired["questions"][0]
        carried = deepcopy(inquiry["carried_understanding"])
        assert not paired["results"] and not paired["insights"] and not paired["tasks"]
        assert inquiry["state"] == "open" and not inquiry["conclusion"]
        assert not inquiry["hypothesis_a"] and not inquiry["hypothesis_b"]
        assert paired["focus_question_id"] == inquiry["id"]
        assert len(carried["learning_notes"]) == 2 and not carried["skipped_sources"]
        assert len(paired["jobs"]) == 2 and len(model.contexts) == calls
        for origin, original in zip(carried["learning_notes"], originals, strict=True):
            note = original["insights"][-1]
            assert origin["note"]["current_user_view"] == note["current_view"]
            assert origin["note"]["use_for_research"] == note["use_for_research"]
            assert origin["note"]["open_question"] == note["open_question"]
            assert origin["note"]["source_locators"][0]["document_id"]
            assert origin["note"]["source_locators"][0]["available_for_recheck"]
            assert client.get("/api/career/" + original["id"]).json() == original
        project = client.get("/api/projects/" + paired["id"]).json()
        store = ResearchStore(tmp_path / "runs.db", namespace=str(database.resolve()))
        notebook = LearningNotebook(lambda: project, store)
        assert notebook.read_inquiry(inquiry["id"])["inquiry"]["carried_understanding"] == carried
        assert notebook.search_inquiries(["末尾限定0"])["matching_count"] == 1
        found = client.get(f"/api/career/{paired['id']}/search?q=末尾限定0&scope=goal").json()
        assert any(row["id"] == inquiry["id"] for row in found["records"])
        # Later editing the old note does not rewrite the saved starting point.
        old = originals[0]["insights"][-1]
        save(
            f"/api/career/{originals[0]['id']}/insights/{old['id']}",
            {
                **{
                    key: old.get(key)
                    for key in (
                        "previous_view",
                        "observation",
                        "open_question",
                        "source_step_id",
                        "source_claim_index",
                    )
                },
                "current_view": "原目标后来修改了理解。",
            },
            method="PATCH",
        )
        offline = run_stage(
            client,
            paired["id"],
            auth,
            "ask",
            question_id=inquiry["id"],
            question="先回读共同问题的原文。",
            offline=True,
        )
        result = offline["results"][0]["result"]
        assert result["status"] == "evidence_only" and len(model.contexts) == calls
        assert result["career_learning_context"]["understanding_comparison"] == carried
        assert offline["questions"] == paired["questions"] and not offline["insights"]
        # This is a local scripted substitute, with no provider or network calls.
        studied = run_stage(
            client,
            paired["id"],
            auth,
            "ask",
            question_id=inquiry["id"],
            question="分别回读两边的历史原文，再核对任务范围。",
        )
        checked = studied["results"][0]
        assert checked["result"]["status"] == "completed"
        assert checked["result"]["career_learning_context"]["understanding_comparison"] == carried
        assert {row["job_id"] for row in checked["result"]["evidence"]} == {
            row["id"] for row in paired["jobs"]
        }
        project = client.get("/api/projects/" + paired["id"]).json()
        notebook = LearningNotebook(lambda: project, store)
        history = notebook.read_research_history(checked["step_id"])
        assert history["research"]["understanding_comparison"] == carried
        reflection = save(
            f"/api/career/{paired['id']}/insights",
            {
                "question_id": inquiry["id"],
                "previous_view": "原先尚不能区分两种场景。",
                "observation": "先把原文与旧认识分别保留。",
                "current_view": "继续核对任务范围，暂不合并旧认识。",
                "open_question": "需要验收记录。",
            },
        )["insights"][-1]
        project = client.get("/api/projects/" + paired["id"]).json()
        memory = LearningNotebook(lambda: project, store).read(reflection["id"])["note"]
        assert memory["source_understanding_comparison"] == carried
        chained = save(
            endpoint,
            {
                **request,
                "notes": [
                    {"project_id": paired["id"], "note_id": reflection["id"]},
                    references[1],
                ],
                "include_sources": False,
            },
        )
        bare = save(endpoint, {**request, "include_sources": False})
        assert not bare["jobs"] and not bare["document_ids"] and not bare["results"]
        assert not bare["questions"][0]["carried_understanding"]["include_sources"]
        assert (
            bare["questions"][0]["carried_understanding"]["learning_notes"][0]["note"][
                "current_user_view"
            ]
            == "原目标后来修改了理解。"
        )
        # A manually excerpted old JD has no job_id; resolve its exact saved version.
        original_source = originals[0]["results"][0]["result"]["evidence"][0]
        old_job = originals[0]["jobs"][0]["id"]
        save(
            f"/api/career/{originals[0]['id']}/jobs/{old_job}/observations",
            {
                "description": "合成新岗位正文：改为原型讨论，旧失败样例不再沿用。",
                "data_kind": "synthetic",
            },
        )
        excerpt_note = save(
            f"/api/career/{originals[0]['id']}/insights",
            {
                "previous_view": "按旧原文理解任务。",
                "observation": "保留旧版的完整限定。",
                "current_view": "旧样例还需回读当时的原文。",
                "open_question": "哪些条件已改变？",
                "source_passages": [
                    {
                        key: original_source[key]
                        for key in (
                            "document_id",
                            "snapshot_id",
                            "start",
                            "end",
                        )
                    }
                ],
            },
        )["insights"][-1]
        excerpt_pair = save(
            endpoint,
            {
                **request,
                "notes": [
                    {"project_id": originals[0]["id"], "note_id": excerpt_note["id"]},
                    references[1],
                ],
            },
        )
        locators = excerpt_pair["questions"][0]["carried_understanding"]["source_references"]
        locator = next(row for row in locators if row["job_id"] == old_job)
        repository = Repository(database)
        try:
            historical = read(repository, old_job, locator["as_of"], 0, {old_job}, now())
            assert historical["status"] == "read"
            assert {row["snapshot_id"] for row in historical["evidence"]} == {
                original_source["snapshot_id"],
            }
        finally:
            repository.close()
        # A zero-run copy still contains personal material and follows source forgetting.
        forgotten = client.delete("/api/projects/" + originals[0]["id"], headers=auth)
        assert forgotten.status_code == 200, forgotten.text
        assert {paired["id"], bare["id"], chained["id"]} <= set(
            forgotten.json()["affected_project_ids"],
        )
        assert "末尾限定0" not in json.dumps(client.get("/api/projects/" + paired["id"]).json())
