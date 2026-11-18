"""合成资料验证领域更新分离和个人记忆遗忘，不作为真实趋势证据。"""

import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from work_observer.analysis.profiles import ProfileService
from work_observer.api.updates import update_routes
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.memory.service import MemoryService
from work_observer.reports.domain_updates import DomainUpdateService
from work_observer.reports.inbox import InboxService
from work_observer.research.projects import ProjectService
from work_observer.research.store import ResearchStore
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def updates(tmp_path):
    path = tmp_path / "updates.db"
    upgrade(path)
    repository = Repository(path)
    store = ResearchStore(tmp_path / "checkpoints.db", str(path))
    archive = RawArchive(tmp_path / "raw")

    def add(identity, text="Python业务应用", **kwargs):
        return import_jd(
            repository,
            archive,
            ManualJD(
                title="合成岗位",
                company="合成公司",
                external_id=identity,
                description=text,
                data_kind="synthetic",
                **kwargs,
            ),
        )["job_id"]

    yield DomainUpdateService(store, repository), add
    store.close()
    repository.close()


def test_repeated_capture_does_not_manufacture_change_or_trend(updates):
    service, add = updates
    add("one")
    add("two")
    add("three", "Java业务应用")
    a = service.capture("前面板", terms=["Python"])
    b = service.capture("后面板", terms=["Python"])
    report = service.compare(a["id"], b["id"])
    assert a["statistics"] == [{"term": "Python", "literal_jobs": 2, "denominator": 3}]
    assert report["content_changes"] == report["metadata_changes"] == []
    assert report["sample_changes"]["added_job_ids"] == []
    assert report["method_changes"]["domain_definitions_changed"] is False
    assert report["trend_status"] == "insufficient_comparable_time_series"
    assert any("关系变化保持未知" in gap for gap in report["gaps"])
    assert service.compare(a["id"], b["id"])["id"] == report["id"]
    assert len(service.list()["reports"]) == 1


def test_content_sample_and_scope_changes_are_separate(updates):
    service, add = updates
    one = add("one", city="上海")
    a = service.capture("原始", job_ids=[one], terms=["Python"])
    add("one", "Java业务应用", city="北京")
    two = add("two")
    b = service.capture("变更", job_ids=[one, two], terms=["Python"])
    report = service.compare(a["id"], b["id"])
    assert len(report["content_changes"]) == 1
    assert "Python" in report["content_changes"][0]["description_diff"]
    assert report["metadata_changes"][0]["fields"][0]["name"] == "city"
    assert report["sample_changes"]["added_job_ids"] == [two]
    assert report["sample_changes"]["scope_rule_changed"]
    assert not report["statistics"]["comparable"]


def test_domain_version_change_is_method_change_not_source_change(updates):
    service, add = updates
    add("one")
    knowledge = DomainKnowledgeService(service.repository)
    domain = knowledge.propose_domain("application", "合成应用", "合成定义")
    knowledge.review_domain(domain["id"], "accept", "合成审核")
    a = service.capture("定义一")
    next_domain = knowledge.propose_domain(
        "application", "合成应用", "合成新定义", previous_id=domain["id"], change_kind="revise"
    )
    knowledge.review_domain(next_domain["id"], "accept", "合成修订")
    b = service.capture("定义二")
    report = service.compare(a["id"], b["id"])
    assert report["method_changes"]["domain_definitions_changed"]
    assert report["content_changes"] == []
    assert not report["statistics"]["comparable"]


def test_metadata_only_change_does_not_count_as_body_change(updates):
    service, add = updates
    add("one", "固定的合成正文", city="上海")
    a = service.capture("城市前")
    add("one", "固定的合成正文", city="北京")
    b = service.capture("城市后")
    report = service.compare(a["id"], b["id"])
    assert report["content_changes"] == []
    assert report["metadata_changes"][0]["fields"] == [
        {"name": "city", "before": "上海", "after": "北京"}
    ]


def test_explicit_personal_goals_changed_without_guessing_missing_fields(updates):
    service, add = updates
    one = add("one", city="上海")
    profile = ProfileService(service.repository)
    profile.save_preferences(
        {"cities": ["上海"], "employment_types": ["全职"], "desired_tasks": ["Python", "Go"]}
    )
    a = service.capture("目标一", include_personal=True)
    impact = next(row for row in a["jobs"] if row["job_id"] == one)["personal_impact"]
    assert impact["state"] == "unknown"
    assert (
        next(reason for reason in impact["reasons"] if reason["condition"] == "用工形式")["state"]
        == "unknown"
    )
    assert (
        next(reason for reason in impact["reasons"] if reason["condition"].endswith("Go"))["state"]
        == "unknown"
    )
    profile.save_preferences({"cities": ["北京"]})
    b = service.capture("目标二", include_personal=True)
    report = service.compare(a["id"], b["id"])
    assert report["personal_impact"]["goal_changed"]
    assert report["personal_impact"]["explicit_goals"]["structured"]["cities"] == ["北京"]
    assert report["personal_impact"]["jobs"][0]["after"]["state"] == "excluded"


def test_forget_scrubs_captures_reports_notifications_and_rejects_revival(updates):
    service, add = updates
    add("one")
    memory = MemoryService(service.repository)
    preference = memory.create("preference", "合成私有目标说明")
    a = service.capture("目标前", include_personal=True)
    b = service.capture("目标后", include_personal=True)
    report = service.compare(a["id"], b["id"])
    first = service.followup(report["id"], "合成私有补查")
    second = service.followup(report["id"], "合成私有补查")
    assert first["notification"]["id"] == second["notification"]["id"]
    forgotten = memory.forget(preference["id"])
    invalidated = service.invalidate([], forgotten["forgotten_memory_ids"])
    assert set(invalidated["invalidated_capture_ids"]) == {a["id"], b["id"]}
    assert invalidated["invalidated_update_report_ids"] == [report["id"]]
    repeated = service.invalidate([], forgotten["forgotten_memory_ids"])
    assert set(repeated["invalidated_capture_ids"]) == {a["id"], b["id"]}
    assert repeated["invalidated_update_report_ids"] == [report["id"]]
    with pytest.raises(ProbeError, match="UPDATE_MEMORY_FORGOTTEN"):
        service.report(report["id"])
    with pytest.raises(ProbeError, match="UPDATE_MEMORY_FORGOTTEN"):
        service._write("domain_update_captures", {**a, "id": "new"})
    assert "私有补查" not in str(InboxService(service.repository).list())
    with service.store.lock:
        for table in ("domain_update_captures", "domain_update_reports"):
            assert "私有目标" not in str(
                service.store.db.execute(f"select record from {table}").fetchall()
            )


def test_followup_project_retries_are_idempotent_and_never_execute_model(updates):
    service, add = updates
    one = add("one")
    a, b = service.capture("面板一"), service.capture("面板二")
    report = service.compare(a["id"], b["id"])
    projects = ProjectService(service.store)
    for _ in range(2):
        followup = service.followup(report["id"], "核对合成观察差异")
        project = projects.create(
            "核对领域观察变化",
            followup["question"],
            followup["job_ids"],
            source_key="domain-update:" + report["id"],
        )
        project = projects.add(
            project["id"],
            followup["question"],
            revision=project["revision"],
            key="domain-update:" + report["id"] + ":followup",
        )
    assert len(projects.list()) == 1
    assert len(project["steps"]) == 1
    assert project["job_ids"] == [one]
    assert service.store.list() == []
    assert len(InboxService(service.repository).list()) == 1


def test_http_capture_compare_followup_and_no_file_or_budget_controls(updates):
    service, add = updates
    add("one")
    running = {"busy": False}

    async def read_body(request):
        return await request.json()

    async def invalid(request, error):
        return JSONResponse({"error_code": "INVALID_INPUT"}, 422)

    app = Starlette(
        routes=update_routes(
            repository=lambda: service.repository,
            store=lambda: service.store,
            response=JSONResponse,
            read_json=read_body,
            busy=lambda: running["busy"],
        ),
        exception_handlers={ValidationError: invalid},
    )
    with TestClient(app) as client:
        first = client.post(
            "/api/updates/captures", json={"title": "HTTP面板一", "terms": ["Python"]}
        )
        second = client.post(
            "/api/updates/captures", json={"title": "HTTP面板二", "terms": ["Python"]}
        )
        assert first.status_code == second.status_code == 201
        pair = {"before_id": first.json()["id"], "after_id": second.json()["id"]}
        report = client.post("/api/updates/compare", json=pair)
        assert report.status_code == 201
        identity = report.json()["id"]
        assert client.get("/api/updates/reports/" + identity).json()["content_changes"] == []
        assert client.post("/api/updates/compare", json=pair).json()["id"] == identity
        for _ in range(2):
            response = client.post(
                "/api/updates/reports/" + identity + "/followup", json={"note": "HTTP合成核实问题"}
            )
            assert response.status_code == 201
        assert len(InboxService(service.repository).list()) == 1
        assert len(client.get("/api/updates").json()["captures"]) == 2
        assert (
            client.post(
                "/api/updates/captures", json={"title": "拒绝任意路径", "path": "C:/other.db"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/updates/captures", json={"title": "拒绝改预算", "max_calls": 1000}
            ).status_code
            == 422
        )
        running["busy"] = True
        assert client.post("/api/updates/captures", json={"title": "等待"}).status_code == 409
        assert service.store.list() == []
