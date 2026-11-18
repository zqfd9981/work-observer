"""完整CLI链路隔离验收：合成资料、离线或明确模拟模型，所有网络入口禁止。"""

import base64
import json
from copy import deepcopy

import pytest
from typer.testing import CliRunner

from work_observer.cli import app
from work_observer.config import Settings
from work_observer.research.agent import finalize
from work_observer.research.store import ResearchStore
from work_observer.retrieval.enhanced import DEFAULT_ALIASES


@pytest.fixture
def cli_product(tmp_path, monkeypatch):
    root = tmp_path / "demo"
    config = tmp_path / "mcp.toml"
    connector = tmp_path / "connector"
    connector.mkdir()
    pause = connector / "cdp_risk_lock.json"
    pause.write_text('{"synthetic_pause":true}', encoding="utf-8")
    config.write_text(
        'command="never-run"\nargs=["--data-dir",' + json.dumps(str(connector)) + "]",
        encoding="utf-8",
    )
    settings = Settings(
        database_path=root / "app.db", raw_directory=root / "raw", mcp_config=config
    )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls, *args, **kwargs: settings))
    calls = []

    def no_network(*args, **kwargs):
        calls.append("forbidden-network")
        raise AssertionError("隔离CLI验收不能访问平台、公开服务或实际模型")

    monkeypatch.setattr("httpx.AsyncClient", no_network)
    monkeypatch.setattr("work_observer.connectors.mcp_probe.connect", no_network)
    monkeypatch.setattr("work_observer.connectors.recruitment.connect", no_network)
    runner = CliRunner()

    def invoke(*arguments, code=0, parse=True):
        arguments = [str(value) for value in arguments]
        result = runner.invoke(app, arguments)
        assert result.exit_code == code, (result.stdout, result.exception)
        return json.loads(result.stdout) if parse else result.stdout

    assert invoke("demo-init", "--directory", root)["jobs"] == 4
    yield invoke, root, settings, pause
    assert calls == []


def input_file(root, name, data):
    path = root / (name + ".json")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_cli_csv_and_reviewed_image_import_and_forget(cli_product):
    invoke, root, _, _ = cli_product
    csv = root / "batch.csv"
    csv.write_text(
        "title,company,description,external_id,data_kind\n合成CSV,合成,合成正文Python,cli-csv,synthetic\n缺正文,合成,,,synthetic\n",
        encoding="utf-8-sig",
    )
    preview = invoke("import-csv", csv)
    assert len(preview["rows"]) == 2 and preview["rows"][0]["valid"]
    assert invoke("jobs")["counts"]["scope_total"] == 4
    saved = invoke("import-csv", csv, "--commit")
    assert saved["imported"] == saved["failed"] == 1
    again = invoke("import-csv", csv, "--commit")
    assert again["rows"][0]["stats"]["jobs_new"] == 0
    image = root / "synthetic.png"
    image.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8WQAAAAASUVORK5CYII="
        )
    )
    archived = invoke("import-image", image, "--data-kind", "synthetic")
    assert archived["model_calls"] == 0 and archived["status"] == "archived_only"
    draft = input_file(
        root,
        "image-reviewed",
        {
            "title": "合成原图核对",
            "company": "合成",
            "description": "合成图手工转录Python",
            "data_kind": "synthetic",
            "import_asset_id": archived["asset"]["id"],
            "ocr_reviewed": True,
        },
    )
    imported = invoke("import-jd", "--file", draft)
    job = invoke("job", "--id", imported["job_id"])
    assert job["provenance"]["description_text"]["input_kind"] == "image_manual_review"
    missing = invoke("import-image", image, "--data-kind", "synthetic", "--allow-model")
    assert missing["status"] == "failed" and missing["error_code"] == "MODEL_CONFIG_MISSING"
    assert missing["model_calls"] == 0
    memory = invoke("memory-add", "preference", "合成待忘记偏好")
    forgotten = invoke("memory-change", memory["id"], "forget", "--reports-dir", root / "reports")
    assert memory["id"] in forgotten["forgotten_memory_ids"]
    assert "合成待忘记偏好" not in json.dumps(invoke("memories", "--history"), ensure_ascii=False)


def test_demo_to_offline_research_history_stats_match_inbox_and_restore(cli_product):
    invoke, root, _, _ = cli_product
    jobs = invoke("jobs")
    assert jobs["counts"]["scope_total"] == jobs["counts"]["candidate_details"] == 4
    app_job = next(job for job in jobs["jobs"] if "应用工程师" in job["title"])
    raw_history = invoke("history", "--job-id", app_job["id"])
    assert len(raw_history) == 2 and all(item["data_kind"] == "synthetic" for item in raw_history)
    diff = invoke("compare-history", app_job["id"])
    assert (
        diff["status"] == "compared"
        and diff["before"]["snapshot_id"] != diff["after"]["snapshot_id"]
    )
    assert "线上评测集" in diff["description_diff"]
    invoke(
        "research",
        "--question",
        "合成样例有哪些可核对的任务？",
        "--offline",
        "--save",
        "--reports-dir",
        root / "reports",
        parse=False,
    )
    saved_runs = invoke("research-runs")
    assert saved_runs[0]["status"] == "evidence_only"
    run_id = saved_runs[0]["id"]
    report = invoke("research-run", run_id)
    assert report["result"]["model_calls"] == 0 and not report["result"]["claims"]
    assert report["saved"]["report_id"]
    retrieved = invoke("product", "retrieval", "run", "--term", "Python")
    assert retrieved["matching_jobs"] == 3
    stats_file = input_file(root, "scope", {"filters": {"city": "上海", "salary_min": 20000}})
    stats = invoke("product", "statistics", "run", "--term", "Python", "--file", stats_file)
    assert stats["sample"]["scope_total"] == 4 and stats["sample"]["denominator"] == 1
    assert stats["sample"]["matched"] == 1 and stats["sample"]["unknown"] == 2
    assert stats["statistics"][0]["literal_jobs"] == 1
    assert stats["statistics"][0]["unknown_scope_literal_jobs"] == 1
    earliest = min(raw_history, key=lambda item: item["processed_at"])
    cutoff = input_file(
        root, "historical-scope", {"job_ids": [app_job["id"]], "as_of": earliest["processed_at"]}
    )
    old = invoke("product", "retrieval", "run", "--term", "Python", "--file", cutoff)
    assert old["evidence"][0]["snapshot_id"] == earliest["snapshot_id"]
    conditions = input_file(root, "conditions", {"cities": ["上海"], "salary_min": 20000})
    assert invoke("product", "match", "save", "--file", conditions)["version"] == 1
    matches = invoke("product", "match", "run")
    assert matches["counts"] == {"matched": 1, "unknown": 2, "excluded": 1}
    followup = invoke("product", "inbox", "followup", "--text", "任务由谁验收？", "--id", run_id)
    assert followup in invoke("product", "inbox", "unread")
    assert invoke("product", "inbox", "read", "--id", followup["id"])["state"] == "read"
    assert invoke("product", "inbox", "resolve", "--id", followup["id"])["state"] == "resolved"
    status = invoke("status")
    assert status["network_checks"] == 0 and status["source"]["state"] == "paused"
    bundle, restored = root.parent / "backup", root.parent / "restored"
    assert invoke("backup", bundle, "--reports-dir", root / "reports")["verified_files"] > 1
    assert invoke("restore", bundle, restored)["status"] == "restored_to_new_directory"
    assert invoke("jobs", "--db", restored / "app.db")["counts"]["scope_total"] == 4
    assert (
        invoke("research-run", run_id, "--db", restored / "app.db")["result"]["status"]
        == "evidence_only"
    )


def test_cli_watchset_schedule_worker_pause_and_retry_are_bounded(cli_product):
    invoke, root, _, pause = cli_product
    original_pause = pause.read_bytes()
    definition = input_file(
        root, "watchset", {"name": "合成观察配置", "spec": {"query": "Agent", "city": "上海"}}
    )
    watchset = invoke("product", "watchsets", "save", "--file", definition)
    assert invoke("product", "watchsets", "list")
    schedule_file = input_file(
        root, "schedule", {"watchset_id": watchset["id"], "hour": 0, "minute": 0}
    )
    schedule = invoke("product", "schedules", "save", "--file", schedule_file)
    assert schedule["enabled"] is False
    assert not invoke("worker", "--once")["scheduled"]
    input_file(
        root,
        "schedule",
        {
            "watchset_id": watchset["id"],
            "schedule_id": schedule["id"],
            "hour": 0,
            "minute": 0,
            "enabled": True,
        },
    )
    invoke("product", "schedules", "save", "--file", schedule_file)
    queued = invoke("product", "schedules", "tick")["scheduled"][0]
    blocked = invoke("worker", "--once")["executed"][0]
    assert blocked["id"] == queued["id"] and blocked["state"] == "blocked"
    assert blocked["error_code"] == "SOURCE_PAUSED_USE_LOCAL_DATA" and blocked["result_id"] is None
    assert not invoke("worker", "--once")["executed"]
    assert len(invoke("product", "tasks", "list")) == 1
    invoke("product", "tasks", "retry", "--id", blocked["id"])
    retried = invoke("product", "tasks", "run", "--id", blocked["id"])
    assert retried["state"] == "blocked" and retried["attempts"] == 2
    rejected = invoke("product", "tasks", "retry", "--id", blocked["id"], code=1)
    assert rejected["error_code"] == "TASK_RETRY_LIMIT"
    assert pause.read_bytes() == original_pause
    assert invoke("db-stats")["collection_runs"] == 5  # 只有demo导入批次，没有网络执行批次。


def test_cli_fixed_strategy_evaluation_activation_and_rollback(cli_product):
    invoke, root, _, _ = cli_product
    definition = input_file(root, "strategy", {"name": "合成别名评测", "aliases": DEFAULT_ALIASES})
    candidate = invoke("product", "strategies", "create", "--file", definition)
    assert (
        invoke("product", "strategies", "activate", "--id", candidate["id"], code=1)["error_code"]
        == "STRATEGY_EVALUATION_NOT_ACCEPTED"
    )
    tested = invoke("product", "strategies", "evaluate", "--id", candidate["id"])
    assert (
        tested["status"] == "accepted" and tested["contract"]["data_mode"] == "synthetic_test_only"
    )
    assert (
        invoke("product", "strategies", "activate", "--id", candidate["id"])["status"] == "active"
    )
    assert invoke("product", "strategies", "monitor")["status"] == "passed"
    rolled = invoke("product", "strategies", "rollback", "--text", "合成验收显式回退")
    assert rolled["rolled_back"] == candidate["id"] and rolled["active"]["id"] == "literal-v1"
    assert invoke("product", "strategies", "list")["active_config"] == {"aliases": {}}


def test_cli_partial_profile_review_knowledge_validation_and_forgotten_backup(
    cli_product, monkeypatch
):
    invoke, root, _, _ = cli_product
    job_id = invoke("jobs")["jobs"][0]["id"]
    offline = invoke("product", "profiles", "analyze", "--id", job_id, "--offline")
    assert offline["status"] == "evidence_only" and not offline["result"]["domains"]
    seed = deepcopy(offline["result"])
    evidence = seed["evidence"][0]
    seed.update(
        status="completed",
        mode="model",
        model_calls=3,
        claims=[
            {
                "category": "task",
                "basis": "direct",
                "requirement": "unspecified",
                "text": evidence["quote"],
                "evidence_ids": [evidence["id"]],
            }
        ],
    )
    finalize(seed)

    async def simulated_research(*args, **kwargs):
        return deepcopy(seed)

    class InvalidSupplement:
        async def turn(self, history):
            return [], {
                "name": "finish_profile",
                "arguments": json.dumps(
                    {
                        "domains": [
                            {
                                "domain": "business_application",
                                "rationale": "模拟故意伪造引用",
                                "evidence_ids": ["forged"],
                            }
                        ],
                        "interview_questions": ["任务如何验收？"],
                    }
                ),
            }

    monkeypatch.setattr("work_observer.analysis.profiles.research", simulated_research)
    monkeypatch.setattr(
        "work_observer.analysis.profiles.ModelClient", lambda settings: InvalidSupplement()
    )
    partial = invoke("product", "profiles", "analyze", "--id", job_id)
    assert partial["status"] == "partial" and not partial["result"]["domains"]
    completion = next(
        check for check in partial["result"]["review"]["checks"] if check["name"] == "完成状态"
    )
    assert completion["passed"] is False and completion["detail"] == "partial"
    assert invoke("product", "profiles", "analyze", "--id", job_id)["id"] != partial["id"]
    assert (
        invoke("memory-add", "knowledge", "伪造无来源知识", code=1)["error_code"]
        == "MEMORY_EVIDENCE_REQUIRED"
    )
    store = ResearchStore(root / "checkpoints.db", str(root / "app.db"))
    run = store.create({"question": "明确模拟的研究记录"})
    forged = deepcopy(seed)
    forged["evidence"][0]["quote"] = "不能伪造原文"
    store.save(run["id"], result=forged, state="finished")
    store.close()
    assert invoke("memory-propose", run["id"], 0, code=1)["error_code"] == "INVALID_MEMORY_EVIDENCE"
    store = ResearchStore(root / "checkpoints.db", str(root / "app.db"))
    store.save(run["id"], result=seed)
    used = seed["memory_used"][0]["id"]
    store.invalidate_memories([used])
    assert store.get(run["id"])["state"] == "invalidated"
    store.close()
    bundle, restored = root.parent / "forgotten-backup", root.parent / "forgotten-restored"
    invoke("backup", bundle, "--reports-dir", root / "reports")
    invoke("restore", bundle, restored)
    assert invoke("research-run", run["id"], "--db", restored / "app.db")["state"] == "invalidated"
