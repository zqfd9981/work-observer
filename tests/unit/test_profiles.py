"""岗位画像/个人匹配机制使用隔离模拟资料；不冒充真实语义评测。"""

import asyncio
import json

import pytest

from work_observer.analysis.profiles import PersonalPreferences, ProfileService
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.memory.service import MemoryService
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def profile_store(tmp_path):
    path = tmp_path / "profile.db"
    upgrade(path)
    repository = Repository(path)
    archive = RawArchive(tmp_path / "raw", [])
    job_id = import_jd(
        repository,
        archive,
        ManualJD(
            title="模拟 Agent 开发",
            company="模拟公司",
            description="业务为客户服务；职责：开发 RAG 应用并交付服务接口，负责上线维护。"
            "必备 Python；加分 Docker。",
            city="上海",
            salary="20-30K",
            external_id="a",
        ),
    )["job_id"]
    from work_observer.knowledge.service import DomainKnowledgeService

    knowledge = DomainKnowledgeService(repository)
    definition = knowledge.propose_domain(
        "business_application", "合成应用交付", "开发业务应用与接口"
    )
    knowledge.review_domain(definition["id"], "accept", "合成机制定义，非真实语义验收")
    yield ProfileService(repository), repository, archive, job_id
    repository.close()


class ProfileModel:
    def __init__(self, job_id, evidence_id, *, invalid_domain=False):
        self.job_id, self.evidence_id, self.invalid_domain = job_id, evidence_id, invalid_domain
        self.calls = 0

    async def turn(self, history):
        self.calls += 1
        if self.calls == 1:
            name, arguments = "query_jobs", {}
        elif self.calls == 2:
            name, arguments = "read_job", {"job_id": self.job_id}
        elif self.calls == 3:
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": category,
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": text,
                            "evidence_ids": [self.evidence_id],
                        }
                        for category, text in (
                            ("business", "客户服务"),
                            ("task", "开发 RAG 应用"),
                            ("deliverable", "服务接口"),
                            ("responsibility", "上线维护"),
                            ("ability", "Python"),
                            ("tool", "Docker"),
                        )
                    ],
                    "gaps": ["实际合同主体待核实"],
                },
            )
        else:
            name, arguments = (
                "finish_profile",
                {
                    "domains": [
                        {
                            "domain": "business_application",
                            "rationale": "该岗位明确承担应用开发与接口交付",
                            "evidence_ids": [
                                "forged-evidence" if self.invalid_domain else self.evidence_id
                            ],
                        }
                    ],
                    "interview_questions": ["客户服务应用上线后由谁负责验收？"],
                },
            )
        call = {
            "type": "function_call",
            "call_id": str(self.calls),
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        }
        return [call], call


def analyze(store, **changes):
    service, repository, _, job_id = store
    model = changes.pop(
        "model", ProfileModel(job_id, Catalog(repository).evidence(job_id)[0]["id"])
    )
    return asyncio.run(
        service.analyze(job_id, Settings(model_name="simulated"), model=model, **changes)
    ), model


def test_optional_archive_reader_does_not_make_a_fresh_profile_cache_stale(profile_store, tmp_path):
    from work_observer.connectors.public_documents import PublicDocumentService

    service, repository, _, job_id = profile_store
    PublicDocumentService(repository, tmp_path / "materials").archive_text(
        "合成公司资料", "RAG接口开发与平台团队协作", "合成自述"
    )
    first, _ = analyze(profile_store)
    assert first["result"]["archived_sources_version"] == "archived-source-windows-v1"
    assert not first["stale"]
    again, unused = analyze(profile_store)
    assert again["cached"] and again["id"] == first["id"] and unused.calls == 0
    assert not service.get(job_id)["stale"]


def test_profile_method_switch_invalidates_cache_and_task_matching(profile_store):
    from work_observer.retrieval.enhanced import DEFAULT_ALIASES
    from work_observer.tracking.evaluation import StrategyService

    service, repository, _, job_id = profile_store
    first, _ = analyze(profile_store)
    strategies = StrategyService(repository)
    candidate = strategies.create("模拟切换", DEFAULT_ALIASES)
    assert strategies.evaluate(candidate["id"])["status"] == "accepted"
    strategies.activate(candidate["id"])
    stale = service.get(job_id)
    assert stale["stale"] and "检索策略" in stale["stale_reasons"][-1]
    matching = service.compare_personal(preferences={"desired_tasks": ["RAG"]})
    assert matching["counts"]["unknown"] == 1
    second, _ = analyze(profile_store)
    assert second["id"] != first["id"] and not second["stale"]
    strategies.rollback("模拟方法回退")
    assert service.get(job_id)["stale"]
    original, model = analyze(profile_store)
    assert original["cached"] and original["id"] == first["id"] and model.calls == 0


def test_profile_full_chain_candidates_cache_and_explicit_correction(profile_store):
    service, _, _, job_id = profile_store
    result, model = analyze(profile_store)
    assert result["status"] == "completed"
    assert not result["cached"] and not result["stale"]
    assert model.calls == result["result"]["model_calls"] == 4
    assert not result["result"]["missing_dimensions"]
    assert result["result"]["effective_domains"][0]["status"] == "candidate"
    assert result["result"]["groups"]["deliverable"][0]["text"] == "服务接口"
    again, unused = analyze(profile_store)
    assert again["id"] == result["id"] and again["cached"] and unused.calls == 0
    correction = service.set_domain_correction(
        job_id, ["configuration_delivery"], "实际交付以平台配置实施为主"
    )
    old = service.get(job_id)
    assert old["stale"]
    assert old["result"]["effective_domains"][0]["domain"] == "configuration_delivery"
    assert old["result"]["effective_domains"][0]["correction_id"] == correction["id"]
    corrected, _ = analyze(profile_store)
    assert corrected["id"] != result["id"] and not corrected["stale"]
    assert corrected["result"]["effective_domains"][0]["status"] == "user_corrected"
    assert len(service.list()) == 2


def test_profile_offline_and_invalid_domains_preserve_evidence_without_success(profile_store):
    service, repository, _, job_id = profile_store
    offline, model = analyze(profile_store, offline=True)
    assert offline["status"] == "evidence_only" and model.calls == 0
    assert offline["result"]["claims"] == offline["result"]["domains"] == []
    assert offline["result"]["evidence"]
    invalid_model = ProfileModel(
        job_id, Catalog(repository).evidence(job_id)[0]["id"], invalid_domain=True
    )
    failed, _ = analyze(profile_store, model=invalid_model)
    assert failed["status"] == "partial"
    assert failed["result"]["claims"] and not failed["result"]["domains"]
    assert not service.get(job_id)["stale"]


def test_profile_source_changes_mark_old_results_stale(profile_store):
    service, repository, archive, job_id = profile_store
    result, _ = analyze(profile_store)
    import_jd(
        repository,
        archive,
        ManualJD(
            title="模拟 Agent 开发",
            company="模拟公司",
            external_id="a",
            description="新职责：只整理资料。",
            city="上海",
            salary="20-30K",
        ),
    )
    assert service.get(job_id, result["id"])["stale"]
    assert "岗位正文版本已变化" in service.get(job_id)["stale_reasons"]


def test_personal_match_preserves_unknown_and_uses_complete_population(profile_store):
    service, repository, archive, job_id = profile_store
    other_id = import_jd(
        repository,
        archive,
        ManualJD(
            title="模拟其他工作",
            company="模拟公司",
            external_id="b",
            description="职责暂未明确",
            city="北京",
            salary="10-15K",
        ),
    )["job_id"]
    preferences = {"cities": ["上海"], "salary_min": 20000, "employment_types": ["full_time"]}
    matches = service.compare_personal(preferences=preferences, limit=1)
    assert matches["counts"] == {"matched": 0, "unknown": 1, "excluded": 1}
    assert matches["truncated"]
    all_matches = service.compare_personal(preferences=preferences)
    by_id = {item["id"]: item for item in all_matches["jobs"]}
    assert by_id[job_id]["match_status"] == "unknown"
    assert by_id[other_id]["match_status"] == "excluded"
    assert any(
        item["condition"] == "用工形式" and item["status"] == "unknown"
        for item in by_id[job_id]["reasons"]
    )


def test_task_match_only_current_evidenced_profile_and_saved_preferences(profile_store):
    service, repository, _, job_id = profile_store
    MemoryService(repository).create("preference", "希望工资100万，不限城市")
    assert service.compare_personal()["counts"]["matched"] == 1  # 自由文本不变硬筛选。
    assert (
        service.compare_personal(preferences={"desired_tasks": ["RAG"]})["counts"]["unknown"] == 1
    )
    analyze(profile_store)
    assert (
        service.compare_personal(preferences={"desired_tasks": ["RAG"]})["counts"]["matched"] == 1
    )
    stored = service.save_preferences({"cities": ["北京"], "desired_tasks": ["训练模型"]})
    assert stored["version"] == 1
    assert ProfileService(repository).compare_personal()["counts"]["excluded"] == 1
    updated = service.save_preferences({"cities": ["上海"]})
    assert updated["version"] == 2
    assert service.compare_personal()["counts"]["matched"] == 1
    MemoryService(repository).withdraw(updated["memory_id"])
    assert service.get_preferences()["memory_id"] is None


def test_unanalyzed_profile_and_explicit_conditions_validate(profile_store):
    service, _, _, job_id = profile_store
    assert service.get(job_id)["status"] == "not_analyzed"
    for values in (
        {"salary_min": 30000, "salary_max": 10000},
        {"cities": [""]},
        {"employment_types": ["x" * 101]},
        {"invented_resume": "大学"},
    ):
        with pytest.raises(ValueError):
            PersonalPreferences.model_validate(values)
