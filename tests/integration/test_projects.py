"""多轮持久会话及调查调度：合成来源与模型仅证明机制。"""

import asyncio
import json
import re
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from work_observer.api.projects import plan_project
from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.lifecycle import forget_personal
from work_observer.memory.service import MemoryService
from work_observer.research.projects import ProjectService, execute_project
from work_observer.research.store import ResearchStore
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


class EvidenceModel:
    def __init__(self):
        self.contexts = []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        outputs = [
            json.loads(h["output"]) for h in history if h.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = "query_jobs", {}
        elif not any(o.get("evidence") for o in outputs):
            name, args = "read_job", {"job_id": outputs[0]["jobs"][0]["id"]}
        else:
            ev = next(o["evidence"] for o in outputs if o.get("evidence"))
            name, args = (
                "finish_research",
                dict(
                    claims=[
                        dict(
                            category="task",
                            basis="direct",
                            requirement="unspecified",
                            text="合成岗位负责Python接口开发",
                            evidence_ids=[ev[0]["id"]],
                        )
                    ],
                    gaps=[],
                ),
            )
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(len(history))
        )
        return [call], call


@pytest.fixture
def setup(tmp_path):
    db = tmp_path / "app.db"
    upgrade(db)
    repo = Repository(db)
    jd = import_jd(
        repo,
        RawArchive(tmp_path / "raw", []),
        ManualJD(
            title="合成项目岗位",
            company="合成公司",
            external_id="project-test",
            description="负责 Python 接口开发",
            data_kind="synthetic",
        ),
    )
    store = ResearchStore(tmp_path / "checkpoints.db", str(db.resolve()))
    yield repo, store, jd["job_id"]
    store.close()
    repo.close()


def test_research_hub_lists_progress_and_renames_without_changing_the_research(setup):
    repo, store, job = setup
    service = ProjectService(store)
    project = service.create("待命名研究", "理解接口任务", [job], public_document_ids=[])
    project = service.add(
        project["id"], "接口工作由谁验收？", revision=project["revision"], offline=True
    )
    with TestClient(
        create_app(
            Settings(
                database_path=Path(repo.engine.url.database),
                raw_directory=Path(repo.engine.url.database).parent / "raw",
            )
        ),
        base_url="http://127.0.0.1",
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        listed = client.get("/api/projects").json()[0]
        assert listed["step_count"] == 1 and listed["last_question"] == "接口工作由谁验收？"
        assert listed["job_count"] == 1 and listed["document_count"] == 0
        renamed = client.post(
            f"/api/projects/{project['id']}/title",
            headers={"X-WO-Token": token},
            json={"revision": project["revision"], "title": "接口工作与验收分工"},
        )
        assert renamed.status_code == 200, renamed.text
        current = service.get(project["id"])
        assert current["title"] == "接口工作与验收分工"
        for key in ("goal", "job_ids", "public_document_ids", "scope_version", "steps", "budget"):
            assert current[key] == project[key]
        assert client.get("/api/projects").json()[0]["title"] == current["title"]


def test_collected_claim_is_available_in_the_next_question_of_the_same_research(setup):
    repo, store, job = setup
    service = ProjectService(store)
    project = service.create("合成收藏接续", "理解Python接口任务", [job], max_calls=6, max_rounds=2)
    project = service.add(
        project["id"],
        "Python接口任务是什么？",
        revision=project["revision"],
        max_calls=3,
        timeout=30,
    )
    project = asyncio.run(
        execute_project(
            service, project["id"], repo, Settings(), model=EvidenceModel(), max_steps=1
        )
    )
    run_id = project["steps"][0]["run_id"]
    with TestClient(
        create_app(
            Settings(
                database_path=Path(repo.engine.url.database),
                raw_directory=Path(repo.engine.url.database).parent / "raw",
            )
        ),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        saved = client.post(
            "/api/memories",
            headers=auth,
            json={
                "kind": "knowledge",
                "source_run_id": run_id,
                "claim_index": 0,
                "scope": "project",
                "project_id": project["id"],
            },
        )
        assert saved.status_code == 201, saved.text
        accepted = client.post(f"/api/memories/{saved.json()['id']}/activate", headers=auth)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "active"
    project = service.get(project["id"])
    service.add(
        project["id"],
        "继续解释Python接口任务",
        revision=project["revision"],
        max_calls=3,
        timeout=30,
    )
    model = EvidenceModel()
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=model, max_steps=1)
    )
    assert any(row["id"] == saved.json()["id"] for row in model.contexts[0]["memory_context"])
    assert store.get(project["steps"][-1]["run_id"])["result"]["status"] == "completed"


def test_three_stage_persistent_work_waits_for_review_then_synthesizes(setup):
    repo, store, job_id = setup
    service = ProjectService(store)
    project = plan_project(service, service.create("机制验证", "Python开发职责", [job_id]))
    model = EvidenceModel()
    result = asyncio.run(execute_project(service, project["id"], repo, Settings(), model=model))
    assert [s["state"] for s in result["steps"]] == ["waiting_review", "waiting_review", "queued"]
    assert service.usage(result)["calls"] == 6
    for step in result["steps"][:2]:
        result = service.review(
            result["id"],
            step["id"],
            revision=result["revision"],
            action="accept",
            note="合成原文核对测试",
        )
    result = asyncio.run(execute_project(service, project["id"], repo, Settings(), model=model))
    assert result["steps"][-1]["state"] == "waiting_review"
    context = model.contexts[-1]["project_context"]
    assert len(context["previous_findings"]) == 2
    assert all("derived_claims" in p for p in context["previous_findings"])
    assert service.usage(result)["reserved_calls"] == 30


def test_revision_scope_replan_and_budget_do_not_expand(setup):
    _, store, job_id = setup
    service = ProjectService(store)
    p = service.create("预算", "Python", [job_id], max_calls=10)
    p = service.add(p["id"], "Python职责", revision=p["revision"])
    first = service.claim(p["id"])
    service.finish(p["id"], first["id"], state="failed")
    p = service.get(p["id"])
    p = service.add(p["id"], "再次调查", revision=p["revision"])
    assert service.claim(p["id"]) is None
    assert service.get(p["id"])["stop_reason"] == "project_budget_exhausted"
    p = service.get(p["id"])
    p = service.revise(p["id"], revision=p["revision"], goal="修订范围", job_ids=[job_id])
    assert p["scope_version"] == 2 and p["steps"][-1]["state"] == "waiting_review"
    with pytest.raises(ProbeError, match="STEP_SCOPE_CHANGED_REPLAN"):
        service.review(
            p["id"], p["steps"][-1]["id"], revision=p["revision"], action="accept", note="不外推"
        )
    with pytest.raises(ProbeError, match="PROJECT_CHANGED_REFRESH"):
        service.add(p["id"], "旧窗口", revision=1)


def test_source_key_is_idempotent_and_revised_scope_rejects_reuse(setup):
    _, store, job_id = setup
    service = ProjectService(store)
    args = ("来源报告", "核对Python", [job_id])
    first = plan_project(service, service.create(*args, source_key="report:stable"), offline=True)
    again = plan_project(service, service.create(*args, source_key="report:stable"), offline=True)
    assert first["id"] == again["id"] and len(again["steps"]) == 3
    revised = service.revise(
        first["id"], revision=again["revision"], goal="另一个目标", job_ids=[job_id]
    )
    with pytest.raises(ProbeError, match="PROJECT_SOURCE_KEY_CONFLICT"):
        service.create(*args, source_key="report:stable")
    assert service.get(first["id"])["scope_version"] == revised["scope_version"] == 2


def test_new_project_recall_then_forgetting_clears_project_and_downstream(setup):
    repo, store, job_id = setup
    memory = MemoryService(repo)
    preference = memory.create("preference", "个人敏感偏好Python", subject="work_goal")
    service = ProjectService(store)
    p = service.create("独立新会话", "Python研究", [job_id])
    p = service.add(p["id"], "Python职责", revision=p["revision"])
    model = EvidenceModel()
    p = asyncio.run(execute_project(service, p["id"], repo, Settings(), model=model))
    assert model.contexts[-1]["memory_context"][0]["id"] == preference["id"]
    result = store.get(p["steps"][0]["run_id"])["result"]
    claim = result["claims"][0]
    derived = memory.create(
        "knowledge", claim["text"], evidence=result["evidence"], source_run_id=result["run_id"]
    )
    memory.activate(derived["id"])
    forgotten = forget_personal(repo, store, preference["id"])
    assert p["steps"][0]["run_id"] in forgotten["affected_run_ids"]
    assert service.get(p["id"])["state"] == "invalidated"
    assert not service.get(p["id"])["turns"]
    assert store.get(p["steps"][0]["run_id"])["result"] is None
    assert not memory.recall("Python", [job_id])
    assert repo.job(job_id)["current"]["description_text"] == "负责 Python 接口开发"


def test_changed_preference_drops_prior_findings_and_scoped_memory(setup):
    repo, store, job_id = setup
    memory = MemoryService(repo)
    preference = memory.create("preference", "Python", subject="goal")
    service = ProjectService(store)
    p = service.create("原会话", "Python", [job_id])
    p = service.add(p["id"], "Python职责", revision=p["revision"])
    p = asyncio.run(execute_project(service, p["id"], repo, Settings(), model=EvidenceModel()))
    memory.revise(preference["id"], "Java")
    p = service.add(
        p["id"],
        "Python还有哪些要求",
        revision=p["revision"],
        reply_to_step_id=p["steps"][0]["id"],
    )
    model = EvidenceModel()
    asyncio.run(execute_project(service, p["id"], repo, Settings(), model=model))
    assert model.contexts[-1]["project_context"]["previous_findings"] == []
    assert model.contexts[-1]["project_context"]["reply_to"]["findings_included"] is False
    assert [m["content"] for m in model.contexts[-1]["memory_context"]] == ["Java"]


@pytest.mark.parametrize("with_background", [False, True])
def test_explicit_short_followup_keeps_unreviewed_context_without_accepting_it(
    setup, with_background
):
    repo, store, job_id = setup
    service = ProjectService(store)
    project = service.create("持续提问", "Python工作", [job_id], max_calls=12)
    background = None
    if with_background:
        background = MemoryService(repo).create(
            "preference", "Python工作研究", scope="project", project_id=project["id"]
        )
    project = service.add(
        project["id"], "Python接口职责", revision=project["revision"], max_calls=4
    )
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=EvidenceModel())
    )
    first = project["steps"][0]
    project = service.add(
        project["id"],
        "为什么？",
        revision=project["revision"],
        max_calls=4,
        reply_to_step_id=first["id"],
    )
    # Reconstruct the service from persisted state, without a review action.
    service = ProjectService(store)
    model = EvidenceModel()
    project = asyncio.run(execute_project(service, project["id"], repo, Settings(), model=model))
    context = model.contexts[0]["project_context"]
    assert context["reply_to"]["step_id"] == first["id"]
    assert context["reply_to"]["findings_included"] is True
    assert context["previous_findings"][0]["run_id"] == first["run_id"]
    assert context["previous_findings"][0]["review_state"] == "waiting_review"
    assert all(s["state"] == "waiting_review" and not s["depends_on"] for s in project["steps"])
    assert service.usage(project)["calls"] == 6
    if background:
        result = store.get(project["steps"][-1]["run_id"])["result"]
        assert result["context_memory_used"][0]["id"] == background["id"]


@pytest.mark.parametrize("keep_original", [True, False])
def test_explicit_followup_respects_original_scope_after_material_changes(setup, keep_original):
    repo, store, job_id = setup
    service = ProjectService(store)
    project = service.create("补充后追问", "Python工作", [job_id])
    project = service.add(project["id"], "Python接口职责", revision=project["revision"])
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=EvidenceModel())
    )
    first = project["steps"][0]
    other = import_jd(
        repo,
        RawArchive(Path(repo.engine.url.database).parent / "extra-raw"),
        ManualJD(
            title="合成补充材料", company="合成", description="Java开发", data_kind="synthetic"
        ),
    )["job_id"]
    project = service.revise(
        project["id"],
        revision=project["revision"],
        goal=project["goal"],
        job_ids=[job_id, other] if keep_original else [other],
    )
    project = service.add(
        project["id"],
        "还有呢？",
        revision=project["revision"],
        reply_to_step_id=first["id"],
    )
    context = service.context(project["id"], project["steps"][-1], repo)
    assert context["scope_version"] == 2
    assert context["reply_to"]["source_scope_version"] == 1
    assert context["reply_to"]["findings_included"] is False
    assert context["previous_findings"] == []
    if keep_original:
        assert context["reply_to"]["historical_findings_included"]
        assert context["historical_reply"]["run_id"] == first["run_id"]
        assert context["historical_reply"]["reason"] == "project_scope_changed"
        assert context["historical_reply"]["source_scope_version"] == 1
    else:
        assert "historical_reply" not in context
    assert service.get(project["id"])["steps"][0]["job_ids"] == [job_id]


def test_reply_cannot_reference_other_project_or_unfinished_step(setup):
    _, store, job_id = setup
    service = ProjectService(store)
    project = service.create("回复校验", "Python", [job_id])
    project = service.add(project["id"], "待调查", revision=project["revision"])
    for identity, error in (
        ("f" * 32, "INVALID_STEP_REPLY"),
        (project["steps"][0]["id"], "STEP_REPLY_NOT_READY"),
    ):
        with pytest.raises(ProbeError, match=error):
            service.add(
                project["id"], "为什么？", revision=project["revision"], reply_to_step_id=identity
            )
    assert len(service.get(project["id"])["steps"]) == 1


def test_restart_recovery_does_not_consume_and_http_followup(tmp_path):
    settings = Settings(database_path=tmp_path / "app.db", raw_directory=tmp_path / "raw")
    upgrade(settings.database_path)
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        headers = {"X-WO-Token": token}
        job_id = client.post(
            "/api/import",
            headers=headers,
            json=dict(
                title="合成", company="合成", description="Python合成", data_kind="synthetic"
            ),
        ).json()["job_id"]
        p = client.post(
            "/api/projects",
            headers=headers,
            json=dict(title="持久", goal="Python", job_ids=[job_id]),
        ).json()
        p = client.post(
            f"/api/projects/{p['id']}/steps",
            headers=headers,
            json=dict(
                revision=p["revision"],
                question="Python",
                offline=True,
                approach="work_map",
                coverage_mode="question",
            ),
        ).json()
        assert client.post(f"/api/projects/{p['id']}/run", headers=headers).status_code == 202
        for _ in range(100):
            detail = client.get(f"/api/projects/{p['id']}").json()
            if not detail["worker_running"]:
                break
            time.sleep(0.01)
        assert detail["steps"][0]["state"] == "waiting_material"
        assert detail["steps"][0]["approach"] == "work_map"
        assert detail["steps"][0]["result"]["coverage_mode"] == "question"
        assert "work_map" not in detail["steps"][0]["result"]
        assert detail["usage"]["calls"] == 0
        saved = client.post(
            f"/api/research/{detail['steps'][0]['run_id']}/save",
            headers=headers,
        ).json()
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        headers = {"X-WO-Token": token}
        detail = client.get(f"/api/projects/{p['id']}").json()
        assert detail["steps"][0]["result"]["status"] == "evidence_only"
        assert detail["steps"][0]["result"]["report_id"] == saved["report_id"]
        assert not detail["worker_running"]
        schema = client.get("/api/openapi.json").json()
        assert "/api/projects/{id}/steps/{step_id}/review" in schema["paths"]
        followup = client.post(
            f"/api/projects/{p['id']}/steps",
            headers=headers,
            json=dict(
                revision=detail["revision"],
                question="为什么？",
                offline=True,
                reply_to_step_id=detail["steps"][0]["id"],
            ),
        )
        assert followup.status_code == 201
        assert followup.json()["steps"][-1]["reply_to_step_id"] == detail["steps"][0]["id"]
        queued = client.get(f"/api/projects/{p['id']}").json()
        assert queued["ready_step_ids"] == [queued["steps"][-1]["id"]]
