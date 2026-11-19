"""Synthetic project continuity and rejection propagation; not human research evidence."""

import asyncio
import json
from pathlib import Path

from test_cognition_research import MapModel
from test_source_first_research import source_workspace as source_workspace
from typer.testing import CliRunner

from work_observer.cli import app
from work_observer.config import Settings
from work_observer.memory.service import MemoryService
from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import DIMENSIONS
from work_observer.reports.results import audit_result, render
from work_observer.research.projects import ProjectService, execute_project
from work_observer.research.store import ResearchStore


class RevisionModel(MapModel):
    async def turn(self, history):
        outputs, call = await super().turn(history)
        if call["name"] == "finish_research":
            context = json.loads(history[1]["content"])["project_context"]
            if context["previous_findings"]:
                previous = context["previous_findings"][0]
                arguments = json.loads(call["arguments"])
                arguments["revisions"] = [
                    {
                        "previous_run_id": previous["run_id"],
                        "previous_claim_index": previous["derived_claims"][0][
                            "previous_claim_index"
                        ],
                        "decision": "retain",
                        "trigger": "recheck",
                        "new_claim_indices": [0],
                        "evidence_ids": arguments["claims"][0]["evidence_ids"],
                        "reason": "合成重读支持任务描述，不扩大独立责任",
                    }
                ]
                call["arguments"] = json.dumps(arguments)
        return outputs, call


def test_cli_saves_explicit_map_step_without_running_a_model(
    source_workspace, tmp_path, monkeypatch
):
    repo, store, jobs = source_workspace
    monkeypatch.setattr(
        Settings,
        "load",
        classmethod(
            lambda cls, *a, **kw: Settings(
                database_path=Path(repo.engine.url.database), raw_directory=tmp_path / "raw"
            )
        ),
    )
    service = ProjectService(store)
    project = service.create("合成CLI延续", "接口与责任", jobs)
    path = tmp_path / "ask.json"
    path.write_text(
        json.dumps(
            {
                "revision": project["revision"],
                "question": "继续核对接口",
                "approach": "work_map",
                "offline": True,
            }
        ),
        encoding="utf-8",
    )
    response = CliRunner().invoke(
        app,
        [
            "product",
            "projects",
            "ask",
            "--id",
            project["id"],
            "--db",
            str(repo.engine.url.database),
            "--file",
            str(path),
        ],
    )
    assert response.exit_code == 0, response.output
    step = service.get(project["id"])["steps"][0]
    assert step["approach"] == "work_map" and step["offline"] and step["run_id"] is None


def test_reopened_project_retains_provisional_judgement_and_rejection_invalidates_downstream(
    source_workspace,
):
    repo, store, jobs = source_workspace
    service = ProjectService(store)
    project = service.create(
        "合成认识延续", "接口任务与责任边界", jobs, max_calls=10, max_seconds=360, max_rounds=3
    )
    project = service.add(
        project["id"],
        "合成接口任务与责任",
        revision=project["revision"],
        approach="work_map",
        max_calls=5,
    )
    project = asyncio.run(
        execute_project(
            service, project["id"], repo, Settings(), model=RevisionModel(), max_steps=1
        )
    )
    first = store.get(project["steps"][0]["run_id"])["result"]
    assert project["steps"][0]["state"] == "waiting_review"
    path, namespace = store.path, store.namespace
    store.close()
    reopened = ResearchStore(path, namespace)
    repo.bind_research_store(reopened)
    try:
        service = ProjectService(reopened)
        project = service.get(project["id"])
        project = service.add(
            project["id"],
            "重读合成接口任务，检查独立责任边界",
            revision=project["revision"],
            approach="work_map",
            max_calls=5,
        )
        project = asyncio.run(
            execute_project(
                service, project["id"], repo, Settings(), model=RevisionModel(), max_steps=1
            )
        )
        second = reopened.get(project["steps"][1]["run_id"])["result"]
        revision = second["cognition_revisions"][0]
        assert second["continued_from"] == [first["run_id"]]
        assert revision["previous_review_state"] == "waiting_review"
        assert revision["previous_statement"] == first["claims"][0]["text"]
        assert revision["evidence_relation"] == "reread"
        assert "重读原材料" in render(second)
        assert service.usage(project)["calls"] == 8
        assert service.usage(project)["reserved_calls"] == 10
        quality = QualityReviewService(reopened, repo)
        memory = MemoryService(repo)
        candidate = memory.create(
            "knowledge",
            "合成接口任务待复用",
            source_run_id=first["run_id"],
            evidence=first["evidence"],
            scope="project",
            project_id=project["id"],
            origin="agent",
        )
        memory.activate(candidate["id"])
        packet = quality.packet(first["run_id"])
        quality.submit(
            first["run_id"],
            {
                "result_sha256": packet["result_sha256"],
                "reviewer": "合成辅助拒绝",
                "reviewer_kind": "agent_assisted",
                "decision": "reject",
                "note": "合成失效机制核对",
                "dimensions": {key: {"rating": "fail", "reason": "合成测试"} for key in DIMENSIONS},
                "claim_reviews": [
                    {"index": i, "support": "unknown", "requirement": "unknown", "note": "合成测试"}
                    for i in range(len(packet["claims"]))
                ],
            },
        )
        assert audit_result(second, repo)["stale_dependencies"]
        assert not memory.validity(candidate["id"])["eligible"]
        assert next(r for r in memory.list() if r["id"] == candidate["id"])["status"] == "active"
        project = service.add(
            project["id"],
            "继续检查合成接口任务",
            revision=project["revision"],
            reply_to_step_id=project["steps"][0]["id"],
            approach="work_map",
            offline=True,
        )
        context = service.context(project["id"], project["steps"][-1], repo)
        assert context["previous_findings"] == []
        assert context["reply_to"]["findings_included"] is False
        assert context["excluded_prior_findings"] == [
            {"run_id": first["run_id"], "reason": "quality_rejected"}
        ]
    finally:
        reopened.close()
