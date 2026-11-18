"""MVP 机制验收：只用临时库/模拟模型，不冒充真实网站或模型连通。"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from work_observer import cli
from work_observer.collection.contracts import WatchsetSpec
from work_observer.config import MCPConfig, Settings
from work_observer.connectors.manual import ManualJD, import_jd, load_manual
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.source_status import require_source_available, source_status
from work_observer.reports.results import list_results, read_result, render, save_result
from work_observer.research.agent import ModelClient, research
from work_observer.retrieval.catalog import Catalog, Filters
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.models import Job, JobSnapshot
from work_observer.storage.repository import Repository


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "isolated.db"
    upgrade(path)
    repository = Repository(path)
    archive = RawArchive(tmp_path / "raw", ["test-secret"])
    yield repository, archive
    repository.close()


def add(store, external_id="a", **changes):
    return import_jd(
        *store,
        ManualJD(
            title="模拟 Agent 开发",
            company="模拟公司",
            city="上海",
            external_id=external_id,
            description=changes.pop(
                "description", "岗位职责：实现 RAG。必备 Python；加分 Docker。"
            ),
            **changes,
        ),
    )


def test_import_dedup_version_history_and_manual_provenance(store):
    first = add(store)
    again = add(store)
    assert first["job_id"] == again["job_id"]
    assert again["stats"]["jobs_new"] == again["stats"]["snapshots_new"] == 0
    assert again["stats"]["remote_tool_calls"] == 0
    changed = add(store, description="岗位职责：实现 Agent；必备 Python。")
    assert changed["job_id"] == first["job_id"]
    assert changed["stats"]["snapshots_new"] == 1
    assert store[0].counts()["job_snapshots"] == 2
    history = store[0].history(first["job_id"])
    assert len(history) == 3
    assert {item["response_origin"] for item in history} == {"manual"}
    job = store[0].job(first["job_id"])
    assert job["current"]["source_published_at"] is None
    assert job["current"]["status"] == "unknown"
    assert job["company_profile"]["identity_status"] == "unverified"
    ev = Catalog(store[0]).evidence(first["job_id"])[0]
    assert ev["mode"] == ev["response_origin"] == "manual"
    assert Catalog(store[0]).document(ev["document_id"])["integrity"] == "verified"


def test_content_identity_without_external_id_and_identity_conflict(store):
    jd = ManualJD(title="模拟", company="模拟", description="模拟正文")
    a = import_jd(*store, jd)
    assert import_jd(*store, jd)["job_id"] == a["job_id"]
    add(store)
    with pytest.raises(ProbeError, match="MANUAL_IDENTITY_CONFLICT"):
        import_jd(
            *store,
            ManualJD(title="另一个岗位", company="模拟", description="正文", external_id="a"),
        )


@pytest.mark.parametrize(
    "data",
    [
        {"description": "https://example.com/job"},
        {"description": " "},
        {"source_published_at": "2026-11-18"},
        {"security_id": "private"},
        {"job_url": "https://user:password@example.com/job"},
    ],
)
def test_import_rejects_missing_body_unknown_fields_and_ambiguous_time(data):
    with pytest.raises(ValidationError):
        ManualJD.model_validate(
            {"title": "模拟", "company": "模拟", "description": "模拟正文", **data}
        )


def test_text_json_import_clean_urls_and_secrets(store, tmp_path):
    text = tmp_path / "jd.txt"
    text.write_text("模拟正文 test-secret", encoding="utf-8")
    result = import_jd(*store, load_manual(text, title="模拟", company="模拟"))
    assert "test-secret" not in json.dumps(store[0].job(result["job_id"]))
    data = tmp_path / "jd.json"
    data.write_text(
        json.dumps(
            {
                "title": "模拟",
                "company": "模拟",
                "description": "正文",
                "job_url": "https://example.com/job?security_id=private&lid=private#private",
            }
        ),
        encoding="utf-8",
    )
    result = import_jd(*store, load_manual(data))
    assert store[0].job(result["job_id"])["current"]["job_url"] == "https://example.com/job"


def test_related_manual_data_does_not_overwrite_platform_record(store):
    first = add(store)
    original = store[0].job(first["job_id"])
    # 测试仅建立关联，不改变原记录或身份。
    second = add(store, "b", related_job_id=first["job_id"], description="补充正文")
    assert second["job_id"] != first["job_id"]
    after = store[0].job(first["job_id"])
    assert after["current"] == original["current"]
    assert after["detail"] == original["detail"]
    assert after["manual_supplements"] == [{"job_id": second["job_id"], "title": "模拟 Agent 开发"}]


def test_manual_mode_does_not_break_live_replay_isolation(store):
    add(store)
    live = store[0].begin_run("模拟", WatchsetSpec(query="模拟", city="模拟"), "live")
    store[0].finish(live, "success", "test", True, True)
    add(store, "b")
    with pytest.raises(ProbeError, match="LIVE_AND_REPLAY"):
        store[0].begin_run("模拟", WatchsetSpec(query="模拟", city="模拟"), "replay")


def test_sql_unknowns_salary_units_filters_and_statistics_before_pagination(store):
    add(store, "known", salary="20-30K", education="本科", experience="1-3年")
    add(store, "missing")
    add(store, "daily", salary="200-300元/天", education="硕士")
    catalog = Catalog(store[0])
    result = catalog.query(Filters(salary_min=25000), limit=1)
    assert result["counts"] == {
        "scope_total": 3,
        "matched": 1,
        "unknown": 2,
        "excluded": 0,
        "candidate_details": 3,
    }
    assert result["truncated"]
    result = catalog.query(Filters(education="本科", experience="1-3年"))
    assert (
        result["counts"]["matched"]
        == result["counts"]["unknown"]
        == result["counts"]["excluded"]
        == 1
    )
    assert catalog.query(Filters(company="' OR 1=1 --"))["counts"]["matched"] == 0
    assert catalog.query(Filters(company="%"))["counts"]["matched"] == 0
    assert catalog.query(Filters(city="北京"))["jobs"] == []


def test_missing_detail_and_keyword_unknown_are_not_misclassified(store):
    item = add(store)
    with Session(store[0].engine) as session, session.begin():
        job = session.get(Job, item["job_id"])
        job.description_text = None
        job.detail_state = "list_only"
    catalog = Catalog(store[0])
    assert catalog.query(Filters(keyword="Docker"))["counts"]["unknown"] == 1
    assert catalog.query(Filters(detail="detail"))["jobs"] == []
    assert catalog.evidence(item["job_id"]) == []
    with Session(store[0].engine) as session, session.begin():
        session.get(Job, item["job_id"]).source_skills = ["中文技能"]
    assert catalog.query(Filters(keyword="中文技能"))["counts"]["matched"] == 1


def test_search_snapshot_reference_scope_and_archive_integrity(store):
    first = add(store)
    second = add(store, "b", description="只使用 Java")
    catalog = Catalog(store[0])
    found = catalog.search(["Python"])
    assert found["matching_jobs"] == 1
    ev = found["evidence"][0]
    with Session(store[0].engine) as session:
        snapshot = session.get(JobSnapshot, ev["snapshot_id"])
        assert snapshot.payload["description"][ev["start"] : ev["end"]] == ev["quote"]
    assert catalog.search(["Python"], job_ids=[second["job_id"]])["evidence"] == []
    document = catalog.document(ev["document_id"])
    assert document["integrity"] == "verified"
    Path(document["path"]).write_text("changed", encoding="utf-8")
    assert catalog.document(ev["document_id"])["integrity"] == "missing_or_changed"
    assert ev["job_id"] == first["job_id"]


class SimulatedModel:
    def __init__(self, job_id, mode="good"):
        self.job_id = job_id
        self.mode = mode
        self.calls = 0

    async def turn(self, history):
        self.calls += 1
        if self.mode == "timeout":
            await asyncio.sleep(5)
        if self.calls == 1 or self.mode == "loop":
            name, arguments = "query_jobs", {}
        elif self.calls == 2:
            if self.mode == "search":
                name, arguments = "search_evidence", {"terms": ["Python", "RAG"]}
            else:
                name, arguments = (
                    "read_job",
                    {"job_id": self.job_id if self.mode != "escape" else "outside"},
                )
        else:
            evidence = json.loads(history[-1]["output"]).get("evidence", [])
            cite = "fabricated" if self.mode == "fake" else evidence[0]["id"]
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "ability",
                            "requirement": "required",
                            "text": "模拟判断：需 Python",
                            "evidence_ids": [cite],
                        }
                    ],
                    "gaps": [],
                },
            )
        call = {
            "type": "function_call",
            "call_id": str(self.calls),
            "name": name,
            "arguments": json.dumps(arguments),
        }
        return [call], call


def run_research(store, mode="good", **kwargs):
    first = add(store)
    return asyncio.run(
        research(
            store[0],
            "模拟问题",
            Settings(),
            job_ids=[first["job_id"]],
            model=SimulatedModel(first["job_id"], mode),
            **kwargs,
        )
    )


def test_agent_uses_tools_evidence_and_saved_result_is_frozen(store, tmp_path):
    result = run_research(store)
    assert result["status"] == "completed"
    assert result["model_calls"] == 3
    assert [t["tool"] for t in result["trace"]] == ["query_jobs", "read_job", "finish_research"]
    saved = save_result(result, tmp_path / "reports")
    add(store, description="改变正文后不改写已保存报告")
    restored = read_result(saved["report_id"], tmp_path / "reports")
    assert restored["evidence"] == result["evidence"]
    assert "Python" in render(restored)
    assert len(list_results(tmp_path / "reports")) == 1


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("escape", "RESEARCH_SCOPE_VIOLATION"),
        ("loop", "model_call_limit"),
        ("fake", "model_call_limit"),
        ("timeout", "TIMEOUT"),
    ],
)
def test_agent_limits_scope_citations_calls_and_time(store, mode, reason):
    result = run_research(store, mode, max_calls=3, timeout=0.01 if mode == "timeout" else 10)
    assert result["status"] != "completed"
    assert result["stop_reason"] == reason
    assert result["claims"] == []


def test_offline_and_model_unavailable_are_explicit(store):
    result = run_research(store, offline=True)
    assert result["status"] == "evidence_only" and result["model_calls"] == 0
    assert result["claims"] == []
    result = asyncio.run(research(store[0], "模拟问题", Settings()))
    assert result["stop_reason"] == "MODEL_CONFIG_MISSING"


def test_agent_search_loop_and_no_details_stop_without_model(store):
    result = run_research(store, "search")
    assert result["status"] == "completed"
    assert result["trace"][1]["tool"] == "search_evidence"
    with Session(store[0].engine) as session, session.begin():
        job = session.scalar(select(Job))
        job.description_text = None
        job.detail_state = "list_only"
    result = asyncio.run(research(store[0], "模拟问题", Settings()))
    assert result["status"] == "insufficient_evidence" and result["model_calls"] == 0


def test_source_pause_blocks_before_network_without_changing_lock(tmp_path, monkeypatch):
    lock = tmp_path / "cdp_risk_lock.json"
    lock.write_text('{"reason":"ENVIRONMENT_RISK","platform_code":37}', encoding="utf-8")
    config = MCPConfig(command="must-not-start", args=["--data-dir", str(tmp_path)])
    original = lock.read_bytes()
    assert source_status(config)["state"] == "paused"
    with pytest.raises(ProbeError, match="SOURCE_PAUSED_USE_LOCAL_DATA"):
        require_source_available(config)
    monkeypatch.setattr(Settings, "load_mcp", lambda _: config)
    result = CliRunner().invoke(cli.app, ["collect"])
    assert result.exit_code == 1 and "SOURCE_PAUSED" in result.stdout
    assert lock.read_bytes() == original


@pytest.mark.parametrize("api", ["responses", "chat-completions"])
def test_model_wire_formats_are_supported_without_logging_credentials(monkeypatch, api):
    requests = []

    def handler(request):
        data = json.loads(request.content)
        requests.append(data)
        if api == "responses":
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "name": "query_jobs",
                            "call_id": "1",
                            "arguments": "{}",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {"id": "1", "function": {"name": "query_jobs", "arguments": "{}"}}
                            ]
                        },
                    }
                ]
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    settings = Settings(
        model_base_url="https://example.com/v1",
        model_name="simulated",
        model_api_key="test-secret",
        model_api=api,
    )
    _, call = asyncio.run(ModelClient(settings).turn([{"role": "user", "content": "模拟"}]))
    assert call["name"] == "query_jobs"
    assert "test-secret" not in json.dumps(requests)


def test_cli_import_search_offline_report_and_private_output(store, tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / "isolated.db", raw_directory=tmp_path / "raw")
    monkeypatch.setattr(Settings, "load", lambda _: settings)
    file = tmp_path / "jd.txt"
    file.write_text("模拟：必备 Python，使用 RAG", encoding="utf-8")
    runner = CliRunner()
    args = ["import-jd", "--file", str(file), "--title", "模拟岗位", "--company", "模拟公司"]
    assert runner.invoke(cli.app, args).exit_code == 0
    assert runner.invoke(cli.app, args).exit_code == 0
    for args in [
        ["jobs"],
        ["companies", "--name", "模拟"],
        ["search", "--term", "Python"],
        [
            "research",
            "--question",
            "模拟",
            "--offline",
            "--save",
            "--reports-dir",
            str(tmp_path / "reports"),
        ],
    ]:
        result = runner.invoke(cli.app, args)
        assert result.exit_code == 0, result.stdout
        assert "security_id" not in result.stdout and "lid" not in result.stdout
    assert store[0].counts()["jobs"] == 1
    saved = list_results(tmp_path / "reports")[0]
    company_id = store[0].companies()[0]["id"]
    document_id = Catalog(store[0]).search(["Python"])["evidence"][0]["document_id"]
    for args in [
        ["company", "--id", company_id],
        ["source", "--id", document_id],
        ["report", "--id", saved["report_id"], "--reports-dir", str(tmp_path / "reports")],
    ]:
        result = runner.invoke(cli.app, args)
        assert result.exit_code == 0, result.stdout
