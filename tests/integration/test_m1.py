"""隔离数据库的 M1 故障与数据测试；模拟来源不作为真实平台连通证据。"""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager

import pytest
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from work_observer.collection.contracts import Capture, WatchsetSpec
from work_observer.collection.service import collect
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.recruitment import M0ReplaySource
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import migration_config, upgrade
from work_observer.storage.models import (
    CollectionRun,
    Company,
    Job,
    JobObservation,
    JobSnapshot,
    SourceDocument,
    TaskRun,
)
from work_observer.storage.repository import Repository

STAMP = "2026-11-17T09:00:00+00:00"


def job(identity="simulated-1", **overrides):
    return {
        "job_id": identity,
        "security_id": "simulated-access",
        "lid": "simulated-context",
        "title": "模拟岗位",
        "company": "模拟公司",
        "city": "上海",
        "salary": "20-30K",
        **overrides,
    }


def capture(body, tool="boss_search", arguments=None, stamp=STAMP):
    return Capture(
        raw={
            "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}],
            "isError": False,
        },
        request={"tool": tool, "arguments": arguments or {}},
        observed_at=stamp,
        provenance={"origin": "simulated_test_only"},
    )


class SimulatedSource:
    """只运行于 pytest 临时目录。"""

    mode = "live"

    def __init__(self, jobs=None, pages=None, details=None, repository=None, stamp=STAMP):
        self.pages = pages or {
            1: {
                "ok": True,
                "data": jobs if jobs is not None else [job()],
                "pagination": {"page": 1, "has_more": False},
            }
        }
        self.details = details or {}
        self.calls = []
        self.repository = repository
        self.stamp = stamp

    @asynccontextmanager
    async def open(self):
        yield self

    def no_open_database_transaction(self):
        if self.repository:
            assert self.repository.engine.pool.checkedout() == 0

    async def search(self, spec, page):
        self.no_open_database_transaction()
        self.calls.append(("list", page))
        result = self.pages[page]
        if isinstance(result, Exception):
            raise result
        return capture(
            result,
            arguments={"query": spec.query, "city": spec.city, "page": page},
            stamp=self.stamp,
        )

    async def detail(self, item):
        self.no_open_database_transaction()
        self.calls.append(("detail", item["job_id"]))
        result = self.details.get(
            item["job_id"],
            {
                "ok": True,
                "data": {
                    **item,
                    "city": "",
                    "description": "模拟岗位职责，仅供数据流程验证。",
                },
            },
        )
        if isinstance(result, Exception):
            raise result
        return capture(
            result,
            "boss_detail",
            {"job_id": item["job_id"], "security_id": item["security_id"]},
            stamp=self.stamp,
        )


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test.db"
    upgrade(db)
    repository = Repository(db)
    archive = RawArchive(tmp_path / "raw", secrets=["test-api-secret"])
    yield repository, archive
    repository.close()


def run(store, source, **settings):
    repository, archive = store
    source.repository = repository
    return asyncio.run(
        collect(
            repository,
            archive,
            source,
            "test-watchset",
            WatchsetSpec(
                query="Agent",
                city="上海",
                **settings,
            ),
        )
    )


def test_two_runs_reuse_jobs_snapshots_but_keep_observations_and_documents(store):
    repository, _ = store
    source = SimulatedSource(jobs=[job("a"), job("b")])
    first = run(store, source)
    second = run(store, source)
    assert first["status"] == second["status"] == "success"
    assert first["stats"]["jobs_new"] == 2
    assert second["stats"]["jobs_new"] == second["stats"]["snapshots_new"] == 0
    counts = repository.counts()
    assert counts == {
        "companies": 2,
        "watchsets": 1,
        "task_runs": 2,
        "collection_runs": 2,
        "jobs": 2,
        "job_snapshots": 4,
        "job_observations": 8,
        "source_documents": 6,
    }
    with Session(repository.engine) as session:
        documents = session.scalars(select(SourceDocument)).all()
        assert len({d.path for d in documents}) == 3
        for doc in documents:
            from pathlib import Path

            assert hashlib.sha256(Path(doc.path).read_bytes()).hexdigest() == doc.sha256
        assert (
            session.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.first_observed_at == STAMP,
                    Job.last_observed_at == STAMP,
                )
            )
            == 2
        )


def test_rotated_access_and_recruiter_activity_do_not_create_content_versions(store):
    repository, _ = store
    run(store, SimulatedSource())
    run(
        store,
        SimulatedSource(
            jobs=[
                job(
                    security_id="new-access",
                    lid="new-context",
                    boss_active="刚刚活跃",
                    greeted=True,
                    match_score=99,
                )
            ]
        ),
    )
    assert repository.counts()["job_snapshots"] == 2
    with Session(repository.engine) as session:
        handles = session.scalars(
            select(JobObservation.access_context).where(
                JobObservation.kind == "list",
            )
        ).all()
        assert {h["security_id"] for h in handles} == {"simulated-access", "new-access"}
        for payload in session.scalars(select(JobSnapshot.payload)):
            assert (
                not {"security_id", "lid", "greeted", "boss_active", "match_score"} & payload.keys()
            )


def test_detail_change_and_return_to_prior_content_preserves_history(store):
    repository, _ = store
    run(store, SimulatedSource())
    changed = {"ok": True, "data": {**job(), "city": "", "description": "模拟的新增职责。"}}
    run(store, SimulatedSource(details={"simulated-1": changed}))
    run(store, SimulatedSource())
    assert repository.counts()["jobs"] == 1
    assert repository.counts()["job_snapshots"] == 3
    with Session(repository.engine) as session:
        detail_observations = session.scalars(
            select(JobObservation)
            .where(
                JobObservation.kind == "detail",
            )
            .order_by(JobObservation.processed_at)
        ).all()
        assert detail_observations[0].snapshot_id == detail_observations[2].snapshot_id
        assert detail_observations[0].snapshot_id != detail_observations[1].snapshot_id


def test_same_title_different_ids_remain_separate(store):
    run(store, SimulatedSource(jobs=[job("one"), job("two")]))
    assert store[0].counts()["jobs"] == 2


def test_duplicate_ids_in_one_page_have_one_observation(store):
    result = run(store, SimulatedSource(jobs=[job(), job()]))
    assert result["stats"]["list_records_received"] == 2
    assert result["stats"]["list_observations"] == 1
    assert result["stats"]["details_received"] == 1
    assert store[0].counts()["jobs"] == 1


def test_detail_empty_city_does_not_replace_list_city(store):
    run(store, SimulatedSource())
    item = store[0].jobs()[0]
    assert item["list"]["city"] == "上海"
    assert item["detail"]["city"] == ""
    assert item["list_document_id"] != item["detail_document_id"]


def test_later_failed_page_keeps_prior_page_and_unknown_failed_count(store):
    source = SimulatedSource(
        pages={
            1: {"ok": True, "data": [job()], "pagination": {"page": 1, "has_more": True}},
            2: {"ok": False, "data": None, "error": {"code": "NETWORK_ERROR"}},
        }
    )
    result = run(store, source, page_limit=3, request_limit=5)
    assert result["status"] == "partial"
    assert result["stats"]["pages_succeeded"] == 1
    assert store[0].counts()["jobs"] == 1
    assert result["coverage"]["pages"][1]["count"] is None
    assert source.calls == [("list", 1), ("list", 2)]


@pytest.mark.parametrize(
    "code,status",
    [
        ("AUTH_REQUIRED", "needs_auth"),
        ("BROWSER_SESSION_NOT_FOUND", "needs_auth"),
        ("ENVIRONMENT_RISK", "partial"),
        ("RATE_LIMITED", "partial"),
    ],
)
def test_detail_auth_risk_and_limit_stop_without_retry(store, code, status):
    source = SimulatedSource(jobs=[job("a"), job("b")], details={"a": ProbeError(code)})
    result = run(store, source)
    assert result["status"] == status
    assert source.calls == [("list", 1), ("detail", "a")]
    assert result["coverage"]["details"][0]["count"] is None
    assert store[0].counts()["jobs"] == 2


def test_partial_detail_failure_keeps_success_and_its_raw_document(store):
    source = SimulatedSource(
        jobs=[job("a"), job("b")],
        details={
            "b": {"ok": False, "data": None, "error": {"code": "JOB_NOT_FOUND"}},
        },
    )
    result = run(store, source)
    assert result["status"] == "partial"
    assert result["stats"]["details_received"] == 1
    assert store[0].counts()["source_documents"] == 3
    assert store[0].counts()["job_snapshots"] == 3


def test_explicit_empty_success_is_different_from_page_failure(store):
    empty = run(store, SimulatedSource(jobs=[]))
    failed = run(store, SimulatedSource(pages={1: ProbeError("NETWORK_ERROR")}))
    assert empty["status"] == "success"
    assert empty["coverage"]["pages"][0]["count"] == 0
    assert failed["status"] == "failed"
    assert failed["coverage"]["pages"][0]["count"] is None


def test_invalid_row_rolls_back_the_whole_page_but_keeps_raw(store):
    result = run(store, SimulatedSource(jobs=[job(), {"title": "缺失身份的模拟数据"}]))
    assert result["status"] == "failed"
    assert result["issues"][0]["code"] == "INVALID_SOURCE_SCHEMA"
    assert store[0].counts()["jobs"] == 0
    assert store[0].counts()["source_documents"] == 1


@pytest.mark.parametrize(
    "detail,code",
    [
        ({**job(), "description": ""}, "MISSING_DETAIL_DESCRIPTION"),
        ({**job("another"), "description": "模拟正文"}, "DETAIL_ID_MISMATCH"),
    ],
)
def test_incomplete_or_wrong_identity_detail_is_not_saved_as_valid(store, detail, code):
    result = run(store, SimulatedSource(details={"simulated-1": {"ok": True, "data": detail}}))
    assert result["status"] == "partial"
    assert result["issues"][0]["code"] == code
    assert store[0].counts()["job_snapshots"] == 1


def test_budget_bounds_requests_and_reports_finite_coverage(store):
    source = SimulatedSource(jobs=[job("a"), job("b")])
    result = run(store, source, request_limit=1)
    assert len(source.calls) == 1
    assert result["stats"]["requests_attempted"] == 1
    assert result["coverage"]["details_limited"] is True
    assert result["stop_reason"] == "request_limit"


def test_watchset_config_versions_are_immutable(store):
    one = run(store, SimulatedSource())
    same = run(store, SimulatedSource())
    changed = run(store, SimulatedSource(), detail_limit=0)
    assert one["watchset_version"] == same["watchset_version"] == 1
    assert changed["watchset_version"] == 2
    assert store[0].counts()["watchsets"] == 2


def test_replay_cannot_mix_with_live_database(store):
    run(store, SimulatedSource())
    replay = SimulatedSource()
    replay.mode = "replay"
    with pytest.raises(ProbeError, match="LIVE_AND_REPLAY_DATABASES_MUST_BE_SEPARATE"):
        run(store, replay)
    assert store[0].counts()["collection_runs"] == 1


def test_archive_detects_corruption_and_never_overwrites_it(store):
    from pathlib import Path

    archive = store[1]
    path, _ = archive.save({"示例": "原始数据"})
    Path(path).write_bytes(b"tampered")
    with pytest.raises(ProbeError, match="ARCHIVE_CORRUPTED"):
        archive.save({"示例": "原始数据"})
    assert Path(path).read_bytes() == b"tampered"


def test_raw_document_redaction_and_database_foreign_keys(store):
    source = SimulatedSource(jobs=[job(description="test-api-secret")])
    run(store, source)
    with Session(store[0].engine) as session:
        snapshot = session.scalar(select(JobSnapshot).where(JobSnapshot.kind == "list"))
        assert snapshot.payload["description"] == "[REDACTED]"
        with pytest.raises(IntegrityError):
            session.add(
                JobSnapshot(
                    id="bad",
                    job_id="missing",
                    kind="detail",
                    content_version="v",
                    content_sha256="x",
                    payload={},
                    first_document_id="missing",
                    created_at=STAMP,
                )
            )
            session.flush()


def test_initial_migration_is_repeatable_and_matches_models(store):
    with store[0].engine.begin() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.check(config)
    assert store[0].counts()["jobs"] == 0


def test_task_status_matches_collection_status(store):
    result = run(store, SimulatedSource(pages={1: ProbeError("AUTH_REQUIRED")}))
    with Session(store[0].engine) as session:
        task = session.get(TaskRun, result["id"])
        collection = session.get(CollectionRun, result["id"])
        assert task.status == collection.status == "needs_auth"
        assert task.finished_at == collection.finished_at


def test_mid_page_failure_rolls_back_business_rows_and_retains_raw(store, monkeypatch):
    repository, _ = store
    original = repository._observe

    def observe(session, run_id, source, item, *args):
        if item["job_id"] == "b":
            raise RuntimeError("simulated mid-page failure")
        return original(session, run_id, source, item, *args)

    monkeypatch.setattr(repository, "_observe", observe)
    result = run(store, SimulatedSource(jobs=[job("a"), job("b")]))
    assert result["status"] == "failed"
    assert repository.counts()["jobs"] == repository.counts()["job_snapshots"] == 0
    assert repository.counts()["job_observations"] == 0
    assert repository.counts()["source_documents"] == 1


def test_history_retains_both_observations_but_reuses_snapshots(store):
    run(store, SimulatedSource())
    run(store, SimulatedSource(stamp="2026-11-17T10:00:00+00:00"))
    history = store[0].history(store[0].jobs()[0]["id"])
    assert len(history) == 4
    assert len({row["snapshot_id"] for row in history}) == 2
    assert len({row["run_id"] for row in history}) == 2
    assert len({row["observed_at"] for row in history}) == 2
    assert "simulated-access" not in json.dumps(history)


def test_collection_cli_and_read_commands_do_not_print_platform_handles(
    store, monkeypatch, tmp_path
):
    from typer.testing import CliRunner

    from work_observer import cli
    from work_observer.config import MCPConfig, Settings
    from work_observer.connectors import recruitment

    settings = Settings(database_path=tmp_path / "test.db", raw_directory=tmp_path / "cli-raw")
    monkeypatch.setattr(cli.Settings, "load", lambda _: settings)
    monkeypatch.setattr(Settings, "load_mcp", lambda _: MCPConfig(command="unused"))
    monkeypatch.setattr(recruitment, "MCPSource", lambda _: SimulatedSource())
    watchsets = tmp_path / "watchsets.toml"
    watchsets.write_text('[watchsets.ai-dev]\nquery="Agent"\ncity="Shanghai"\n')
    runner = CliRunner()
    result = runner.invoke(cli.app, ["collect", "--watchsets", str(watchsets)])
    assert result.exit_code == 0, result.stdout
    assert "simulated-access" not in result.stdout
    assert "simulated-1" not in result.stdout
    identity = store[0].jobs()[0]["id"]
    for args in [
        ["jobs"],
        ["runs"],
        ["db-stats"],
        ["job", "--id", identity],
        ["history", "--job-id", identity],
    ]:
        result = runner.invoke(cli.app, args)
        assert result.exit_code == 0, result.stdout
        assert "simulated-access" not in result.stdout


def write_mock_m0_bundle(path):
    """临时测试材料，不能复制到真实数据目录或用作验收数据。"""
    path.mkdir()
    listing = capture({"ok": True, "data": [job()], "pagination": {"page": 1, "has_more": False}})
    request = {"tool": "boss_search", "arguments": {"query": "Agent", "city": "上海", "page": 1}}
    payloads = {"mcp.search.json": listing.raw, "mcp.search.request.json": request}
    hashes = {}
    for name, payload in payloads.items():
        data = json.dumps(payload).encode()
        (path / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    (path / "report.json").write_text(
        json.dumps(
            {
                "milestone": "M0",
                "real_calls_only": True,
                "finished_at": STAMP,
                "checks": {"recruitment": {"status": "passed"}},
                "evidence_sha256": hashes,
            }
        )
    )


def test_m0_replay_hash_mismatch_is_rejected_before_processing(tmp_path):
    path = tmp_path / "mock-m0"
    write_mock_m0_bundle(path)
    (path / "mcp.search.json").write_text("{}")
    with pytest.raises(ProbeError, match="REPLAY_HASH_MISMATCH"):
        M0ReplaySource(path)


def test_replay_keeps_original_time_and_cannot_invent_unrecorded_pages(store, tmp_path):
    path = tmp_path / "mock-m0"
    write_mock_m0_bundle(path)
    source = M0ReplaySource(path)
    result = run(store, source, detail_limit=0)
    assert result["mode"] == "replay"
    assert result["stats"]["remote_tool_calls"] == 0
    assert store[0].jobs()[0]["last_observed_at"] == STAMP
    with pytest.raises(ProbeError, match="REPLAY_QUERY_NOT_RECORDED"):
        asyncio.run(source.search(WatchsetSpec(query="Agent", city="上海"), 2))


def test_current_job_has_queryable_fields_and_does_not_export_access(store):
    run(
        store,
        SimulatedSource(
            jobs=[
                job(
                    salary="28-55K·15薪",
                    experience="3-5年",
                    education="本科",
                    skills=["Python"],
                    welfare=["双休"],
                    source_company_id="company-1",
                    source_published_at="2026-11-16T10:00:00+08:00",
                    job_url="https://www.zhipin.com/job_detail/example.html?securityId=simulated-access",
                )
            ]
        ),
    )
    result = store[0].jobs()[0]
    current = result["current"]
    assert current["salary_min"] == "28000.00"
    assert current["salary_max"] == "55000.00"
    assert current["salary_unit"] == "month" and current["salary_months"] == 15
    assert current["experience_min_years"] == "3.0"
    assert current["education_level"] == "本科"
    assert current["source_skills"] == ["Python"]
    assert current["city"] == "上海" and current["description_text"]
    assert current["source_published_at"] == "2026-11-16T02:00:00+00:00"
    assert current["job_url"] == "https://www.zhipin.com/job_detail/example.html"
    assert current["status"] == "unknown"
    assert current["detail_state"] == "detail"
    assert result["company_profile"]["identity_status"] == "source_id"
    assert "simulated-access" not in json.dumps(result)


def test_companies_use_source_identity_and_do_not_merge_same_names(store):
    run(
        store,
        SimulatedSource(
            jobs=[
                job("a", source_company_id="same-company"),
                job("b", source_company_id="same-company"),
                job("c"),
                job("d"),
            ]
        ),
        detail_limit=0,
    )
    assert store[0].counts()["companies"] == 3
    with Session(store[0].engine) as session:
        rows = {j.source_job_id: j for j in session.scalars(select(Job))}
        assert rows["a"].company_id == rows["b"].company_id
        assert rows["c"].company_id != rows["d"].company_id
        assert session.get(Company, rows["c"].company_id).identity_status == "unverified"


def test_http_completion_upgrades_provisional_company_without_replacing_its_id(store):
    run(store, SimulatedSource(jobs=[job("a")]), detail_limit=0)
    with Session(store[0].engine) as session:
        previous = session.scalar(select(Job)).company_id
    run(
        store,
        SimulatedSource(jobs=[job("a", source_company_id="verified-company")]),
        detail_limit=0,
    )
    with Session(store[0].engine) as session:
        stored = session.scalar(select(Job))
        company = session.get(Company, stored.company_id)
        assert stored.company_id == previous
        assert company.identity_status == "source_id"
        assert company.source_company_id == "verified-company"
        assert session.scalar(select(func.count()).select_from(Company)) == 1
    spec = WatchsetSpec(query="Agent", city="上海", detail_limit=1, request_limit=1)
    batch = store[0].begin_run(
        "http-completion", spec, "live", kind="detail_completion", transport="http"
    )
    store[0].start_step(batch, "details", 1, "a")
    with Session(store[0].engine) as session:
        current = session.get(CollectionRun, batch)
        assert current.kind == "detail_completion" and current.transport == "http"
        assert current.stats["remote_tool_calls"] == 0
        assert current.stats["http_request_attempts"] == 1


def test_later_list_preserves_body_and_old_response_cannot_overwrite_current(store):
    run(store, SimulatedSource(jobs=[job("a", skills=["Python"])]))
    newer = "2026-11-18T09:00:00+00:00"
    run(
        store,
        SimulatedSource(jobs=[job("a", title="新标题", salary="面议")], stamp=newer),
        detail_limit=0,
    )
    run(store, SimulatedSource(jobs=[job("a", title="旧标题", salary="5-10K")]), detail_limit=0)
    current = store[0].jobs()[0]["current"]
    assert current["title"] == "新标题" and current["salary_raw"] == "面议"
    assert current["salary_min"] is None and current["salary_max"] is None
    assert current["description_text"] and current["source_skills"] == ["Python"]
    assert current["last_seen_in_search_at"] == newer
    assert current["source_published_at"] is None


def test_status_requires_explicit_text_and_access_parameters_stay_paired(store):
    run(
        store,
        SimulatedSource(jobs=[job("a", source_status_raw={"invalidStatus": True})]),
        detail_limit=0,
    )
    assert store[0].jobs()[0]["current"]["status"] == "unknown"
    later = "2026-11-18T09:00:00+00:00"
    item = job("a", source_status_raw={"jobStatusDesc": "职位已关闭"}, security_id="new-access")
    item.pop("lid")
    run(store, SimulatedSource(jobs=[item], stamp=later), detail_limit=0)
    with Session(store[0].engine) as session:
        stored = session.scalar(select(Job))
        assert stored.status == "closed" and stored.status_observed_at == later
        assert stored.first_closed_observed_at == later
        assert stored.access_context == {"security_id": "new-access"}


def test_new_migration_backfills_legacy_rows_without_losing_history(tmp_path):
    import sqlite3

    from work_observer.storage.database import engine_for

    path = tmp_path / "legacy.db"
    engine = engine_for(path)
    with engine.begin() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "d3cff3ef944a")
    engine.dispose()
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO watchsets VALUES (?,?,?,?,?,?)", ("w", "legacy", 1, "hash", "{}", STAMP)
        )
        db.execute(
            "INSERT INTO task_runs VALUES (?,?,?,?,?)", ("r", "collection", "success", STAMP, STAMP)
        )
        db.execute(
            "INSERT INTO collection_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "r",
                "w",
                "live",
                "success",
                STAMP,
                STAMP,
                "{}",
                "{}",
                "[]",
                None,
            ),
        )
        db.execute("INSERT INTO jobs VALUES (?,?,?,?,?)", ("j", "boss", "legacy-job", STAMP, STAMP))
        db.execute(
            "INSERT INTO source_documents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "d",
                "r",
                "detail",
                1,
                "legacy-job",
                "{}",
                '{"origin":"live"}',
                "local-legacy.json",
                "hash",
                STAMP,
                STAMP,
            ),
        )
        payload = {
            "title": "旧岗位",
            "company": "旧公司",
            "salary": "20-30K",
            "description": "旧正文",
        }
        db.execute(
            "INSERT INTO job_snapshots VALUES (?,?,?,?,?,?,?,?)",
            (
                "s",
                "j",
                "detail",
                "job-content-v1",
                "content-hash",
                json.dumps(payload),
                "d",
                STAMP,
            ),
        )
        db.execute(
            "INSERT INTO job_observations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "o",
                "r",
                "j",
                "s",
                "d",
                "detail",
                1,
                None,
                '{"security_id":"old-access","lid":"old-lid"}',
                STAMP,
                STAMP,
            ),
        )
    upgrade(path)
    upgrade(path)
    repository = Repository(path)
    try:
        current = repository.job("j")["current"]
        assert current["title"] == "旧岗位" and current["description_text"] == "旧正文"
        assert current["salary_min"] == "20000.00"
        assert current["source_published_at"] is None
        assert repository.counts()["job_snapshots"] == repository.counts()["job_observations"] == 1
        with Session(repository.engine) as session:
            assert session.get(Job, "j").access_context["lid"] == "old-lid"
            assert session.get(JobObservation, "o").snapshot_id == "s"
            assert session.scalar(select(Company)).identity_status == "unverified"
        with repository.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        repository.close()
