"""仅在隔离模拟资料上检查历史RAG、统计、评测与显式策略切换。"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.retrieval.enhanced import DEFAULT_ALIASES, RetrievalService
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.models import Job, JobObservation, JobSnapshot
from work_observer.storage.repository import Repository
from work_observer.tracking.evaluation import StrategyService


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "enhanced.db"
    upgrade(path)
    repository = Repository(path)
    archive = RawArchive(tmp_path / "raw")

    def add(identity="a", description="构建智能体的工具调用链", **kwargs):
        return import_jd(
            repository,
            archive,
            ManualJD(
                title="模拟岗位",
                company="模拟公司",
                external_id=identity,
                description=description,
                **kwargs,
            ),
        )["job_id"]

    yield repository, add
    repository.close()


def test_alias_retrieval_citations_are_exact_deduplicated_and_context_is_bounded(store):
    repo, add = store
    job = add()
    add()
    service = RetrievalService(repo, alias_groups=DEFAULT_ALIASES)
    assert not service.search(["Agent"], aliases=False)["evidence"]
    result = service.search(["Agent"], limit=1)
    assert result["matching_jobs"] == 1
    assert "智能体" in result["expanded_terms"]
    assert len(result["evidence"]) == 1
    evidence = result["evidence"][0]
    assert evidence["job_id"] == job
    with Session(repo.engine) as session:
        text = session.get(JobSnapshot, evidence["snapshot_id"]).payload["description"]
    assert text[evidence["start"] : evidence["end"]] == evidence["quote"]
    assert result["context_characters"] <= result["context_limit"] == 7000


def test_historical_scope_uses_old_fields_not_current_fields_or_later_imports(store):
    repo, add = store
    job = add(description="构建智能体", city="上海", salary="20-30K")
    with Session(repo.engine) as session:
        cutoff = session.scalar(select(JobObservation.processed_at))
    add(description="维护 Java 服务", city="北京", salary="40-50K")
    service = RetrievalService(repo, alias_groups=DEFAULT_ALIASES)
    assert service.search(["Agent"], filters={"city": "上海"})["evidence"] == []
    result = service.search(["Agent"], filters={"city": "上海"}, as_of=cutoff)
    assert result["sample"]["matched_details"] == 1
    assert result["evidence"][0]["quote"] == "构建智能体"
    assert result["evidence"][0]["job_id"] == job
    assert service.stats(["Java"], as_of=cutoff)["statistics"][0]["literal_jobs"] == 0
    assert service.stats(["Java"])["statistics"][0]["literal_jobs"] == 1
    # 即便后来观察被回填为较早来源时间，也不能越过本地处理截止点。
    with Session(repo.engine) as session, session.begin():
        rows = session.scalars(select(JobObservation).order_by(JobObservation.processed_at)).all()
        rows[-1].observed_at = rows[0].observed_at
    assert service.search(["Agent"], as_of=cutoff)["evidence"][0]["quote"] == "构建智能体"


def test_statistics_full_denominator_and_unknown_are_separate_from_top_k(store):
    repo, add = store
    add("a", "Python 必备", city="上海", salary="20-30K")
    add("b", "Python 加分", city="上海", salary="20-30K")
    add("c", "Java", city="上海", salary="20-30K")
    add("unknown", "Python", city="上海")
    add("outside", "Python", city="北京", salary="20-30K")
    service = RetrievalService(repo)
    result = service.stats(["Python"], filters={"city": "上海", "salary_min": 20000})
    assert result["sample"]["denominator"] == 3
    assert result["sample"]["unknown_details"] == 1
    assert result["sample"]["excluded"] == 1
    item = result["statistics"][0]
    assert item["literal_jobs"] == 2
    assert item["ratio"] == 2 / 3
    assert item["unknown_scope_literal_jobs"] == 1
    assert "非必备要求" in result["interpretation"]
    limited = service.search(["Python"], filters={"city": "上海", "salary_min": 20000}, limit=1)
    assert len(limited["evidence"]) == 1
    assert limited["sample"] == result["sample"]


def test_missing_details_remain_in_sample_without_becoming_requirements(store):
    repo, add = store
    job = add()
    # 模拟只有来源列表观察：不以修改当前字段制造历史事实。
    with Session(repo.engine) as session, session.begin():
        observation = session.scalar(select(JobObservation))
        snapshot = session.get(JobSnapshot, observation.snapshot_id)
        observation.kind = snapshot.kind = "list"
        snapshot.payload = {"title": "模拟", "company": "模拟公司", "skills": ["Agent"]}
        current = session.get(Job, job)
        current.description_text = None
        current.detail_state = "list_only"
    result = RetrievalService(repo).search(["Agent"])
    assert result["sample"]["matched_missing_details"] == 1
    assert result["evidence"] == []
    assert result["tag_only_hits"][0]["labels"] == ["Agent"]
    assert RetrievalService(repo).stats(["Agent"])["statistics"][0]["ratio"] is None


@pytest.mark.parametrize("as_of", ["2026-11-18", "bad", 123])
def test_historical_queries_require_explicit_timezone(store, as_of):
    with pytest.raises(ProbeError, match="INVALID_RETRIEVAL_TIME"):
        RetrievalService(store[0]).search(["Agent"], as_of=as_of)


def test_strategy_fixed_fixture_accepted_rejected_insufficient_activate_and_rollback(store):
    repo, _ = store
    service = StrategyService(repo)
    candidate = service.create("模拟别名候选", DEFAULT_ALIASES)
    evaluation = service.evaluate(candidate["id"])
    assert evaluation["status"] == "accepted"
    assert evaluation["metrics"]["candidate_recall"] == 1
    assert evaluation["metrics"]["baseline_recall"] == 2 / 6
    assert evaluation["metrics"]["external_calls"] == 0
    assert evaluation["metrics"]["data_mode"] == "synthetic_test_only"
    assert evaluation["metrics"]["source_version_guard"]
    assert service.activate(candidate["id"])["status"] == "active"
    assert service.active_config()["aliases"] == DEFAULT_ALIASES
    rollback = service.rollback("模拟回退，不宣称真实效果")
    assert rollback["rolled_back"] == candidate["id"]
    assert rollback["active"]["id"] == "literal-v1"
    assert [event["action"] for event in service.events()] == ["rolled_back", "activated"]
    poor = service.create("没有改善", {})
    assert service.evaluate(poor["id"])["status"] == "rejected"
    with pytest.raises(ProbeError, match="STRATEGY_REQUIRES_NEW_CANDIDATE"):
        service.activate(poor["id"])
    small = service.create("样本不足", DEFAULT_ALIASES)
    assert service.evaluate(small["id"], case_ids=["agent-alias"])["status"] == "insufficient"
    with pytest.raises(ProbeError, match="STRATEGY_EVALUATION_NOT_ACCEPTED"):
        service.activate(small["id"])
    assert len(service.experiments()) == 3


def test_activation_requires_current_baseline_and_production_uses_activated_config(store):
    repo, add = store
    add()
    retrieval = RetrievalService(repo)
    assert retrieval.search(["Agent"])["evidence"] == []
    service = StrategyService(repo)
    a = service.create("候选一", DEFAULT_ALIASES)
    b = service.create("候选二", DEFAULT_ALIASES)
    assert service.evaluate(a["id"])["status"] == "accepted"
    assert service.evaluate(b["id"])["status"] == "accepted"
    service.activate(a["id"])
    assert retrieval.search(["Agent"])["evidence"]
    with pytest.raises(ProbeError, match="STRATEGY_BASELINE_CHANGED_REEVALUATE"):
        service.activate(b["id"])
    # 与已启用同配置比较没有实际增益，不能再宣称改善。
    assert service.evaluate(b["id"])["status"] == "rejected"
    assert service.monitor()["status"] == "passed"
    service.rollback()
    assert retrieval.search(["Agent"])["evidence"] == []
    with pytest.raises(ProbeError, match="STRATEGY_REQUIRES_NEW_CANDIDATE"):
        service.activate(a["id"])


def test_critical_guard_monitor_automatically_rolls_back_and_retains_history(store, monkeypatch):
    service = StrategyService(store[0])
    candidate = service.create("候选", DEFAULT_ALIASES)
    evaluation = service.evaluate(candidate["id"])
    service.activate(candidate["id"])
    failed = {**evaluation["metrics"], "source_version_guard": False}
    monkeypatch.setattr(service, "_run", lambda *args: failed)
    result = service.monitor()
    assert result["status"] == "rolled_back"
    assert result["affected_strategy_ids"] == [candidate["id"]]
    assert result["active"]["id"] == "literal-v1"
    assert service.events()[0]["action"] == "automatic_rollback"
    assert len(service.experiments()) == 2
    assert (
        next(row for row in service.list() if row["id"] == candidate["id"])["status"]
        == "rolled_back"
    )


def test_long_literal_term_crossing_chunk_boundary_is_retrievable(store):
    repo, add = store
    add(description="前" * 695 + "Python" + "后" * 700)
    result = RetrievalService(repo).search(["Python"])
    assert result["matching_jobs"] == 1
    assert "Python" in result["evidence"][0]["quote"]


def test_strategy_does_not_accept_custom_cases_or_unbounded_config(store):
    service = StrategyService(store[0])
    with pytest.raises(ProbeError, match="INVALID_STRATEGY_ALIASES"):
        service.create("模拟", {"Agent": ["x"] * 9})
    candidate = service.create("模拟", {})
    with pytest.raises(ProbeError, match="INVALID_EVALUATION_CASES"):
        service.evaluate(candidate["id"], case_ids=["invented-answer"])
