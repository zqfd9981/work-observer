"""岗位画像与显式个人条件匹配；分析、人工纠正和来源事实分别保存。"""

import asyncio
import hashlib
import json
import time
from copy import deepcopy
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.evidence import redact
from work_observer.memory.service import MemoryService
from work_observer.research.agent import ModelClient, finalize, method_fingerprint, research, tool
from work_observer.retrieval.catalog import Catalog, Filters
from work_observer.storage.locks import exclusive
from work_observer.storage.models import Job, JobAnalysis

ANALYZER_VERSION = "job-profile-v1"
PROMPT_VERSION = "job-profile-prompt-v4-domain-definitions"
QUESTION = (
    "为该岗位建立工作画像：区分企业业务背景与目标、具体任务、预期交付物、承担责任、"
    "能力、工具六类，说明必备与加分性质。每条均引用招聘原文；未知就列缺口。"
    "企业整体背景不等于该岗位归属。遵循有效人工纠正，不根据技术名词推断任务。"
)
Domain = Literal[
    "business_application",
    "agent_platform",
    "domain_decision",
    "model_serving",
    "configuration_delivery",
    "other",
]
DOMAIN_LABELS = {
    "business_application": "业务应用开发",
    "agent_platform": "执行平台与 Harness",
    "domain_decision": "领域决策系统",
    "model_serving": "模型与推理部署",
    "configuration_delivery": "平台配置与实施",
    "other": "其他待定义领域",
}
CORRECTION_PREFIX = "画像领域纠正："
PREFERENCE_PREFIX = "结构化个人条件："


class DomainCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str = Field(pattern="^[a-z][a-z0-9_]{1,79}$")
    rationale: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class ProfileSupplement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domains: list[DomainCandidate] = Field(max_length=6)
    interview_questions: list[str] = Field(min_length=1, max_length=8)


class PersonalPreferences(BaseModel):
    """只接受用户显式结构化条件，不将自然语言记忆悄悄变为硬性条件。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cities: list[str] = Field(default_factory=list, max_length=10)
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    salary_unit: Literal["month", "year", "day", "hour"] = "month"
    employment_types: list[str] = Field(default_factory=list, max_length=10)
    desired_tasks: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def valid_values(self):
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_min > self.salary_max:
                raise ValueError("薪资下限不能大于上限")
        for values in (self.cities, self.employment_types, self.desired_tasks):
            if any(not value or len(value) > 100 for value in values):
                raise ValueError("条件不能为空或超过100字")
        return self


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


class ProfileService:
    def __init__(self, repository):
        self.repository = repository
        self.memory = MemoryService(repository)
        self.catalog = Catalog(repository)

    def _strategy_context(self):
        from work_observer.tracking.evaluation import BASELINE_ID, StrategyService, config_hash

        service = StrategyService(self.repository)
        return {
            "id": next(
                (item["id"] for item in service.list() if item["status"] == "active"), BASELINE_ID
            ),
            "config_sha256": config_hash(service.active_config()),
        }

    def get_preferences(self):
        for item in self.memory.list():
            if (
                item["kind"] == "preference"
                and item["job_id"] is None
                and item["content"].startswith(PREFERENCE_PREFIX)
            ):
                try:
                    value = PersonalPreferences.model_validate_json(
                        item["content"][len(PREFERENCE_PREFIX) :]
                    )
                    return {
                        "preferences": value.model_dump(mode="json"),
                        "memory_id": item["id"],
                        "version": item["version"],
                    }
                except ValueError:
                    continue
        return {
            "preferences": PersonalPreferences().model_dump(mode="json"),
            "memory_id": None,
            "version": None,
        }

    def save_preferences(self, preferences):
        value = PersonalPreferences.model_validate(preferences)
        previous = self.get_preferences()
        content = PREFERENCE_PREFIX + value.model_dump_json()
        if previous["memory_id"]:
            self.memory.revise(previous["memory_id"], content)
        else:
            self.memory.create("preference", content)
        return self.get_preferences()

    def _context(self, job_id):
        self.repository.job(job_id)
        evidence = self.catalog.evidence(job_id, limit=1)
        snapshot_id = evidence[0]["snapshot_id"] if evidence else None
        memories = self.memory.recall(QUESTION, [job_id])
        versions = [{"id": item["id"], "version": item["version"]} for item in memories]
        return snapshot_id, memories, versions

    def classification_definitions(self, job_id):
        """Use the same active, source-valid definitions as research; never seed the old five."""
        from work_observer.connectors.public_models import PublicDocument
        from work_observer.knowledge.models import DomainDefinition
        from work_observer.knowledge.service import DomainKnowledgeService

        knowledge = DomainKnowledgeService(self.repository)
        with Session(self.repository.engine) as session:
            public_ids = list(session.scalars(select(PublicDocument.id)))
            return [
                {
                    key: getattr(row, key)
                    for key in (
                        "id",
                        "domain_key",
                        "version",
                        "name",
                        "definition",
                        "inclusion",
                        "exclusion",
                        "status",
                        "reviewed_at",
                    )
                }
                for row in session.scalars(
                    select(DomainDefinition)
                    .where(DomainDefinition.status == "active")
                    .order_by(DomainDefinition.domain_key)
                )
                if not knowledge.definition_validity(
                    row, job_ids=[job_id], public_document_ids=public_ids, scoped=True
                )
            ]

    def _output(self, row, *, cached=False):
        snapshot_id, current_memory, memories = self._context(row.job_id)
        definitions = self.classification_definitions(row.job_id)
        stale = []
        from work_observer.quality.profile_reviews import profile_review_state

        profile_review = profile_review_state(self.repository, row.id, row.result)
        if profile_review["status"] == "rejected":
            stale.append("完整画像已被人工审核拒绝，需重新分析；基础研究事实另行保留。")
        if profile_review["status"] == "unavailable":
            stale.append("完整画像审核记录暂不可核验，请恢复后再使用缓存。")
        if row.snapshot_id != snapshot_id:
            stale.append("岗位正文版本已变化")
        if row.memory_versions != memories:
            stale.append("有效偏好、纠正或知识版本已变化")
        from work_observer.memory.dependencies import DependencyAudit

        dependency = DependencyAudit(self.repository).result(row.result)
        if not dependency["eligible"]:
            stale.append("画像采用的上游记忆、研究或知识依赖已失效")
        if row.status == "completed" and row.result.get("run_id"):
            if not DependencyAudit(self.repository).run(row.result["run_id"])["eligible"]:
                stale.append("画像的权威来源研究已失效或被明确拒绝")
        if row.analyzer_version != ANALYZER_VERSION or row.prompt_version != PROMPT_VERSION:
            stale.append("画像分析方法已变化")
        if row.result.get("classification_definitions") is not None and (
            row.result["classification_definitions"] != definitions
        ):
            stale.append("工作类型定义、版本或有效范围已变化")
        if row.result.get("research_method_sha256") != method_fingerprint():
            stale.append("采用的研究方法或检查口径已变化")
        strategy = row.result.get("strategy")
        if strategy and any(
            strategy.get(key) != value for key, value in self._strategy_context().items()
        ):
            stale.append("采用的检索策略已替换或回退")
        if any(
            self.catalog.document(item["document_id"])["integrity"] != "verified"
            for item in row.result.get("evidence", [])
            if item.get("document_id")
        ):
            stale.append("原始文件缺失或完整性发生变化")
        result = deepcopy(row.result)
        result["analysis_corrections"] = result.get("corrections", [])
        result["corrections"] = [item for item in current_memory if item["kind"] == "correction"]
        result["effective_domains"] = self._effective_domains(
            result.get("domains", []), current_memory
        )
        if any(
            item.get("status") == "user_corrected_stale"
            for item in result["effective_domains"]
            if isinstance(item, dict)
        ):
            stale.append("人工领域纠正采用的领域定义已替换或失效，请按新定义重新核对。")
        return {
            "id": row.id,
            "job_id": row.job_id,
            "snapshot_id": row.snapshot_id,
            "status": row.status,
            "cached": cached,
            "stale": bool(stale),
            "stale_reasons": stale,
            "analysis_version": row.analyzer_version,
            "prompt_version": row.prompt_version,
            "model_name": row.model_name,
            "memory_versions": row.memory_versions,
            "profile_quality_review": profile_review,
            "created_at": row.created_at,
            "result": result,
            "classification_options": definitions,
        }

    def get(self, job_id, analysis_id=None):
        self.repository.job(job_id)
        statement = select(JobAnalysis).where(JobAnalysis.job_id == job_id)
        if analysis_id:
            statement = statement.where(JobAnalysis.id == analysis_id)
        with Session(self.repository.engine) as session:
            row = session.scalar(statement.order_by(JobAnalysis.created_at.desc()).limit(1))
            if row:
                return self._output(row)
        if analysis_id:
            raise ProbeError("PROFILE_NOT_FOUND")
        return {
            "job_id": job_id,
            "status": "not_analyzed",
            "stale": False,
            "result": None,
            "classification_options": self.classification_definitions(job_id),
        }

    def list(self, limit=100):
        if not 1 <= limit <= 100:
            raise ProbeError("INVALID_PROFILE_LIMIT")
        with Session(self.repository.engine) as session:
            rows = session.scalars(
                select(JobAnalysis).order_by(JobAnalysis.created_at.desc()).limit(limit)
            )
            return [self._output(row) for row in rows]

    def set_domain_correction(self, job_id, domains, reason):
        """显式人工领域纠正形成唯一有效版本，不让模型覆盖领域分类。"""
        self.repository.job(job_id)
        if (
            not isinstance(domains, list)
            or len(domains) > 6
            or any(value not in DOMAIN_LABELS for value in domains)
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 1200
        ):
            raise ProbeError("INVALID_DOMAIN_CORRECTION")
        text = CORRECTION_PREFIX + json.dumps(
            {"domains": list(dict.fromkeys(domains)), "reason": reason.strip()}, ensure_ascii=False
        )
        previous = next(
            (
                item
                for item in self.memory.list()
                if item["job_id"] == job_id
                and item["kind"] == "correction"
                and item["content"].startswith(CORRECTION_PREFIX)
            ),
            None,
        )
        return (
            self.memory.revise(previous["id"], text)
            if previous
            else self.memory.create("correction", text, job_id=job_id)
        )

    def _effective_domains(self, domains, memories):
        for item in memories:
            if item["kind"] == "correction" and item["content"].startswith(CORRECTION_PREFIX):
                try:
                    values = json.loads(item["content"][len(CORRECTION_PREFIX) :])
                    if "definition_ids" in values:
                        from work_observer.knowledge.models import DomainDefinition

                        identities = values["definition_ids"]
                        if not isinstance(identities, list) or len(identities) > 10:
                            continue
                        corrected = []
                        with Session(self.repository.engine) as session:
                            for identity in identities:
                                if not isinstance(identity, str):
                                    raise ValueError("invalid domain definition")
                                definition = session.get(DomainDefinition, identity)
                                corrected.append(
                                    {
                                        "domain": definition.domain_key
                                        if definition
                                        else "unknown",
                                        "label": (
                                            f"{definition.name}（第 {definition.version} 版）"
                                            if definition
                                            else "原领域定义不可用"
                                        ),
                                        "definition_id": identity,
                                        "definition_version": definition.version
                                        if definition
                                        else None,
                                        "definition_status": definition.status
                                        if definition
                                        else "missing",
                                        "status": (
                                            "user_corrected"
                                            if definition
                                            and definition.status == "active"
                                            and not self._definition_stale(definition)
                                            else "user_corrected_stale"
                                        ),
                                        "rationale": values["reason"],
                                        "correction_id": item["id"],
                                        "evidence_ids": [],
                                    }
                                )
                        return corrected
                    if any(value not in DOMAIN_LABELS for value in values["domains"]):
                        continue
                    return [
                        {
                            "domain": value,
                            "label": DOMAIN_LABELS[value],
                            "status": "user_corrected",
                            "rationale": values["reason"],
                            "correction_id": item["id"],
                            "evidence_ids": [],
                        }
                        for value in values["domains"]
                    ]
                except (ValueError, KeyError, TypeError):
                    continue
        return domains

    def _definition_stale(self, definition):
        from work_observer.knowledge.service import DomainKnowledgeService

        return bool(DomainKnowledgeService(self.repository).definition_validity(definition))

    async def analyze(self, job_id, settings, *, model=None, offline=False, _lock_held=False):
        if _lock_held:
            async with asyncio.timeout(235):
                return await self._analyze_locked(job_id, settings, model=model, offline=offline)
        with exclusive(self.repository.engine.url.database, purpose="research"):
            async with asyncio.timeout(235):
                return await self._analyze_locked(job_id, settings, model=model, offline=offline)

    async def _analyze_locked(self, job_id, settings, *, model=None, offline=False):
        started = time.monotonic()
        snapshot_id, memories, versions = self._context(job_id)
        definitions = self.classification_definitions(job_id)
        model_name = "offline" if offline else settings.model_name
        key = _digest(
            {
                "snapshot": snapshot_id,
                "job_id": job_id,
                "analyzer": ANALYZER_VERSION,
                "prompt": PROMPT_VERSION,
                "research_method": method_fingerprint(),
                "model": model_name,
                "api": settings.model_api,
                "provider": _digest(settings.model_base_url),
                "memories": versions,
                "classification_definitions": definitions,
                "strategy": self._strategy_context(),
            }
        )
        with Session(self.repository.engine) as session:
            cached = session.scalar(
                select(JobAnalysis)
                .where(
                    or_(JobAnalysis.cache_key == key, JobAnalysis.cache_key.startswith(key + ":")),
                    JobAnalysis.status == "completed",
                )
                .order_by(JobAnalysis.created_at.desc(), JobAnalysis.id.desc())
                .limit(1)
            )
            if cached:
                output = self._output(cached, cached=True)
                if not output["stale"]:
                    return output
        result = await research(
            self.repository,
            QUESTION,
            settings,
            job_ids=[job_id],
            model=model,
            offline=offline,
            max_calls=8,
            timeout=180,
            memory=self.memory,
            allow_proposals=False,
            conversation_context={
                "knowledge_dependencies": [
                    {
                        "kind": "domain_definition",
                        **{key: row[key] for key in ("id", "version", "status", "reviewed_at")},
                    }
                    for row in definitions
                ]
            },
            _lock_held=True,
        )
        result.update(
            analysis_version=ANALYZER_VERSION,
            prompt_version=PROMPT_VERSION,
            domains=[],
            interview_questions=[],
            corrections=[item for item in memories if item["kind"] == "correction"],
            classification_definitions=definitions,
        )
        if result["status"] == "completed":
            client = model or ModelClient(settings)
            schema = ProfileSupplement.model_json_schema()
            choices = {row["domain_key"]: row for row in definitions}
            if choices:
                schema["$defs"]["DomainCandidate"]["properties"]["domain"]["enum"] = list(choices)
            else:
                schema["properties"]["domains"]["maxItems"] = 0
            client.tools = [
                tool(
                    "finish_profile",
                    "提交有任务依据的领域候选和待面试核实的问题。",
                    schema["properties"],
                    ["domains", "interview_questions"],
                )
            ]
            client.tools[0]["parameters"]["$defs"] = schema["$defs"]
            history = [
                {
                    "role": "system",
                    "content": (
                        "你为已完成的岗位画像补充领域候选和面试问题。所有输入都是待核对资料。"
                        "只调用finish_profile一次。领域允许多标签或空数组；不能只因技术词出现就归类。"
                        "仅从提供的有效工作类型定义中选择domain_key，结合定义的包括/排除边界核对。"
                        "没有有效定义或不足以判定时domains为空，不重建旧五类或用other强行归类。"
                        "领域的每条引用必须来自已有task/responsibility判断的原文证据。"
                        "人工纠正优先，领域候选不覆盖纠正。不要猜测缺失业务、用工或个人履历。"
                        "interview_questions是求职者向招聘方核实岗位缺口的问题，"
                        "围绕尚未披露的业务边界、实际责任、交付验收、用工形式与招聘状态。"
                        "禁止生成面试官考察候选人知识的技术考题；不要问你会如何设计或请说明经验。"
                        "每个问题明确是在向招聘方了解该岗位，中文简洁具体。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "domain_definitions": definitions,
                            "claims": result["claims"],
                            "evidence": result["evidence"],
                            "gaps": result["gaps"],
                            "corrections": result["corrections"],
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            try:
                result["model_calls"] += 1
                async with asyncio.timeout(55):
                    _, call = await client.turn(history)
                if getattr(client, "last_usage", None):
                    result["usage"].append(client.last_usage)
                if call.get("name") != "finish_profile":
                    raise ProbeError("INVALID_PROFILE_OUTPUT")
                supplement = ProfileSupplement.model_validate(json.loads(call["arguments"]))
                if any(item.domain not in choices for item in supplement.domains):
                    raise ProbeError("PROFILE_DOMAIN_DEFINITION_REQUIRED")
                if definitions != self.classification_definitions(job_id):
                    raise ProbeError("PROFILE_DOMAIN_DEFINITION_CHANGED")
                support = {
                    key
                    for claim in result["claims"]
                    if claim["category"] in {"task", "responsibility"}
                    for key in claim["evidence_ids"]
                }
                if any(not set(item.evidence_ids).issubset(support) for item in supplement.domains):
                    raise ProbeError("PROFILE_DOMAIN_EVIDENCE_REQUIRED")
                result["domains"] = [
                    {
                        **item.model_dump(),
                        "label": choices[item.domain]["name"],
                        "definition_id": choices[item.domain]["id"],
                        "definition_version": choices[item.domain]["version"],
                        "status": "candidate",
                    }
                    for item in supplement.domains
                ]
                result["interview_questions"] = supplement.interview_questions
            except Exception:
                result["status"] = "partial"
                result["gaps"].append("领域候选生成未通过，已有原文画像保留；可稍后重新分析。")
        if result["status"] in {"completed", "partial"}:
            result["effective_domains"] = self._effective_domains(result["domains"], memories)
        else:
            result["effective_domains"] = []
        if not result["interview_questions"]:
            result["interview_questions"] = [
                "该岗位的主要交付物、独立责任及验收方式是什么？",
                "用工形式、实际业务归属和目前招聘状态能否确认？",
            ]
        result["groups"] = {
            category: [claim for claim in result["claims"] if claim["category"] == category]
            for category in ("business", "task", "deliverable", "responsibility", "ability", "tool")
        }
        result["missing_dimensions"] = [
            category for category, claims in result["groups"].items() if not claims
        ]
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["budget"] = {
            "max_model_calls": 9,
            "max_elapsed_seconds": 235,
            "profile_supplement_calls": 1,
        }
        result = finalize(result)
        result = redact(
            result,
            [settings.model_api_key.get_secret_value(), settings.tavily_api_key.get_secret_value()],
        )
        status = result["status"]
        # 失败、离线和补充不完整均允许显式重试；不把失败缓存成成功。
        cache_key = key if status == "completed" and cached is None else key + ":" + uuid4().hex
        identity = uuid4().hex
        with Session(self.repository.engine) as session, session.begin():
            statement = (
                insert(JobAnalysis)
                .values(
                    id=identity,
                    job_id=job_id,
                    snapshot_id=snapshot_id,
                    cache_key=cache_key,
                    analyzer_version=ANALYZER_VERSION,
                    prompt_version=PROMPT_VERSION,
                    model_name=model_name,
                    memory_versions=versions,
                    result=result,
                    status=status,
                    created_at=now(),
                )
                .on_conflict_do_nothing(index_elements=["cache_key"])
            )
            session.execute(statement)
            row = session.scalar(select(JobAnalysis).where(JobAnalysis.cache_key == cache_key))
            return self._output(row)

    def compare_personal(self, filters=None, preferences=None, *, limit=100):
        if not 1 <= limit <= 100:
            raise ProbeError("INVALID_PROFILE_LIMIT")
        filters = (
            Filters.model_validate(filters or {}) if not isinstance(filters, Filters) else filters
        )
        preferences = PersonalPreferences.model_validate(
            self.get_preferences()["preferences"] if preferences is None else preferences
        )
        scope = self.catalog.query(filters, limit=max(1, self.repository.counts()["jobs"]))
        output, counts = [], {"matched": 0, "unknown": 0, "excluded": 0}
        with Session(self.repository.engine) as session:
            for summary in scope["jobs"]:
                job = session.get(Job, summary["id"])
                reasons = []

                def reason(condition, state, detail, target=reasons):
                    target.append({"condition": condition, "status": state, "detail": detail})

                if summary["match_status"] == "unknown":
                    reason("筛选范围", "unknown", "部分范围筛选字段未知")
                if preferences.cities:
                    reason(
                        "城市",
                        "unknown"
                        if not job.city
                        else "matched"
                        if job.city in preferences.cities
                        else "excluded",
                        job.city or "来源未提供工作城市",
                    )
                if preferences.salary_min is not None or preferences.salary_max is not None:
                    unknown = (
                        job.salary_min is None
                        or job.salary_max is None
                        or job.salary_currency != "CNY"
                        or job.salary_unit != preferences.salary_unit
                    )
                    matches = (
                        not unknown
                        and (
                            preferences.salary_min is None
                            or job.salary_max >= preferences.salary_min
                        )
                        and (
                            preferences.salary_max is None
                            or job.salary_min <= preferences.salary_max
                        )
                    )
                    reason(
                        "薪资",
                        "unknown" if unknown else "matched" if matches else "excluded",
                        (job.salary_raw or "来源未提供薪资")
                        + "；仅比较同周期披露区间，不保证实际薪酬",
                    )
                if preferences.employment_types:
                    reason(
                        "用工形式",
                        "unknown"
                        if not job.employment_type
                        else "matched"
                        if job.employment_type in preferences.employment_types
                        else "excluded",
                        job.employment_type or "来源未明确用工形式，不能据未提及推断非外包",
                    )
                if preferences.desired_tasks:
                    profile = self.get(job.id)
                    tasks = (
                        []
                        if profile.get("stale") or not profile.get("result")
                        else [
                            claim["text"]
                            for claim in profile["result"]["claims"]
                            if claim["category"] in {"task", "responsibility", "deliverable"}
                        ]
                    )
                    hit = [
                        term
                        for term in preferences.desired_tasks
                        if any(term.casefold() in task.casefold() for task in tasks)
                    ]
                    reason(
                        "希望承担的任务",
                        "matched" if hit else "unknown",
                        "有证据的任务描述命中：" + "、".join(hit)
                        if hit
                        else "尚无当前画像或任务表述未命中；不能据此认定职业目标不符，需核实",
                    )
                states = {item["status"] for item in reasons}
                state = (
                    "excluded"
                    if "excluded" in states
                    else "unknown"
                    if "unknown" in states
                    else "matched"
                )
                counts[state] += 1
                if len(output) < limit:
                    output.append({**summary, "match_status": state, "reasons": reasons})
        return {
            "preferences": preferences.model_dump(mode="json"),
            "counts": counts,
            "jobs": output,
            "scope_counts": scope["counts"],
            "truncated": sum(counts.values()) > len(output),
            "rules": "显式结构化条件逐项比较；未知单列；自由文本记忆不作为硬筛选。"
            "任务词仅检索已有画像，未命中保持待核实。",
        }
