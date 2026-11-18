"""显式冻结两次观察面板，分离原文、样本和方法变化；不把两次采样称为趋势。"""

import hashlib
import json
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.analysis.profiles import PREFERENCE_PREFIX, PersonalPreferences
from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.memory.service import MemoryService
from work_observer.quality.service import digest
from work_observer.reports.inbox import InboxService
from work_observer.research.history import HistoryService
from work_observer.retrieval.catalog import Catalog, Filters
from work_observer.retrieval.enhanced import RetrievalService, validated_terms
from work_observer.storage.models import JobAnalysis

FIELDS = (
    "title",
    "company_name_raw",
    "city",
    "salary_raw",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_unit",
    "employment_type",
    "education_raw",
    "experience_raw",
)


def _json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class DomainUpdateService:
    def __init__(self, store, repository):
        self.store, self.repository = store, repository
        self.memory = MemoryService(repository)
        with store.lock, store.db:
            for name in ("domain_update_captures", "domain_update_reports"):
                store.db.execute(
                    f"CREATE TABLE IF NOT EXISTS {name} (namespace TEXT NOT NULL, "
                    "id TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(namespace,id))"
                )

    def _get(self, table, identity):
        with self.store.lock:
            row = self.store.db.execute(
                f"SELECT record FROM {table} WHERE namespace=? AND id=?",
                (self.store.namespace, identity),
            ).fetchone()
        if not row:
            raise ProbeError("UPDATE_RECORD_NOT_FOUND")
        record = json.loads(row[0])
        if record.get("state") == "invalidated":
            raise ProbeError("UPDATE_MEMORY_FORGOTTEN")
        known = {item["id"]: item for item in self.memory.list(include_history=True)}
        forgotten = {
            ref["id"]
            for ref in record.get("memory_refs", [])
            if ref["id"] not in known or known[ref["id"]]["status"] == "forgotten"
        }
        if forgotten:
            self.invalidate([], forgotten)
            raise ProbeError("UPDATE_MEMORY_FORGOTTEN")
        return record

    def _write(self, table, record):
        with self.store.lock, self.store.db:
            known_memories = {row["id"]: row for row in self.memory.list(include_history=True)}
            if any(
                ref["id"] not in known_memories
                or known_memories[ref["id"]]["status"] == "forgotten"
                for ref in record.get("memory_refs", [])
            ):
                raise ProbeError("UPDATE_MEMORY_FORGOTTEN")
            for identity in record.get("source_run_ids", []):
                try:
                    run = self.store.get(identity)
                except ProbeError:
                    continue
                if run["state"] == "invalidated":
                    raise ProbeError("UPDATE_MEMORY_FORGOTTEN")
            self.store.db.execute(
                f"INSERT OR IGNORE INTO {table}(namespace,id,record) VALUES (?,?,?)",
                (self.store.namespace, record["id"], json.dumps(_json(record), ensure_ascii=False)),
            )
        return self._get(table, record["id"])

    def list(self):
        output = {}
        with self.store.lock:
            for name in ("captures", "reports"):
                rows = self.store.db.execute(
                    f"SELECT record FROM domain_update_{name} WHERE namespace=? "
                    "ORDER BY json_extract(record,'$.created_at') DESC LIMIT 100",
                    (self.store.namespace,),
                ).fetchall()
                output[name] = [
                    {
                        key: record.get(key)
                        for key in (
                            "id",
                            "title",
                            "created_at",
                            "state",
                            "sample",
                            "before_id",
                            "after_id",
                        )
                    }
                    for (encoded,) in rows
                    if (record := json.loads(encoded)).get("state") != "invalidated"
                ]
        return output

    def _personal(self, job_ids):
        memories, structured, notes = [], None, []
        for row in self.memory.list():
            if (
                row["kind"] != "preference"
                or row["status"] != "active"
                or row.get("origin") != "user"
                or row.get("scope", "global") not in {"global", "job"}
                or row.get("job_id")
                and row["job_id"] not in job_ids
                or not self.memory.validity(row["id"])["eligible"]
            ):
                continue
            if row["content"].startswith(PREFERENCE_PREFIX):
                try:
                    value = PersonalPreferences.model_validate_json(
                        row["content"][len(PREFERENCE_PREFIX) :]
                    )
                except ValueError:
                    continue
                # 结构化个人条件只使用全局明确偏好，单岗文本不升格为全局条件。
                if row.get("job_id") is None and structured is None:
                    structured = value.model_dump(mode="json")
                else:
                    continue
            elif len(notes) < 8:
                notes.append(
                    {
                        "memory_id": row["id"],
                        "content": row["content"],
                        "job_id": row.get("job_id"),
                        "interpretation": "明确文本偏好，仅供核对；未自动提取硬性条件。",
                    }
                )
            else:
                continue
            memories.append({"id": row["id"], "version": row["version"]})
        return {"structured": structured, "notes": notes, "memory_refs": memories}

    @staticmethod
    def _impact(record, text, personal):
        preferences = personal.get("structured")
        if not preferences:
            return {
                "state": "unknown",
                "reasons": [],
                "note": "没有明确结构化个人条件；文本偏好待人工解释。",
            }
        reasons = []
        for field, key, label in (
            ("city", "cities", "城市"),
            ("employment_type", "employment_types", "用工形式"),
        ):
            if preferences[key]:
                value = record.get(field)
                reasons.append(
                    {
                        "condition": label,
                        "state": "unknown"
                        if not value
                        else "matched"
                        if value in preferences[key]
                        else "excluded",
                        "evidence_value": value,
                    }
                )
        if preferences["salary_min"] is not None or preferences["salary_max"] is not None:
            valid = (
                record.get("salary_min") is not None
                and record.get("salary_max") is not None
                and record.get("salary_currency") == "CNY"
                and record.get("salary_unit") == preferences["salary_unit"]
            )
            matches = (
                valid
                and (
                    preferences["salary_min"] is None
                    or Decimal(str(record["salary_max"])) >= Decimal(str(preferences["salary_min"]))
                )
                and (
                    preferences["salary_max"] is None
                    or Decimal(str(record["salary_min"])) <= Decimal(str(preferences["salary_max"]))
                )
            )
            reasons.append(
                {
                    "condition": "披露薪资区间",
                    "state": "unknown" if not valid else "matched" if matches else "excluded",
                    "evidence_value": record.get("salary_raw"),
                    "note": "同币种/周期区间相交，不保证实际薪酬。",
                }
            )
        for term in preferences["desired_tasks"]:
            start = text.casefold().find(term.casefold())
            reasons.append(
                {
                    "condition": "明确期望任务：" + term,
                    "state": "matched" if start >= 0 else "unknown",
                    "start": start if start >= 0 else None,
                    "quote": text[max(0, start - 60) : start + len(term) + 100]
                    if start >= 0
                    else None,
                    "note": "仅为原文字面命中，不等同任务/资历已完全匹配；未命中保留待核实。",
                }
            )
        states = {item["state"] for item in reasons}
        return {
            "state": "excluded"
            if "excluded" in states
            else "unknown"
            if "unknown" in states or not states
            else "matched",
            "reasons": reasons,
        }

    def capture(
        self,
        title,
        *,
        filters=None,
        domain_id=None,
        job_ids=None,
        terms=None,
        include_personal=False,
    ):
        if not isinstance(title, str) or not title.strip() or len(title) > 150:
            raise ProbeError("INVALID_UPDATE_TITLE")
        terms = validated_terms(terms) if terms else []
        filters = Filters.model_validate(filters or {})
        records, actual_filters, cutoff = RetrievalService(self.repository)._records(
            filters, job_ids, None
        )
        if len(records) > 2000:
            raise ProbeError("UPDATE_SCOPE_LIMIT_2000_NARROW_SCOPE")
        knowledge = DomainKnowledgeService(self.repository)
        domain_rows = []
        offset = 0
        while True:
            page = knowledge.collection(
                domain_id, filters=filters, job_ids=job_ids, limit=200, offset=offset
            )
            domain_rows.extend(page["jobs"])
            if not page["truncated"]:
                break
            offset += 200
        assignments = {row["job_id"]: row for row in domain_rows}
        scope_ids = [item["job_id"] for item in records if item["state"] != "excluded"]
        personal = (
            self._personal(scope_ids)
            if include_personal
            else {"structured": None, "notes": [], "memory_refs": []}
        )
        memory_refs = {row["id"]: row for row in personal["memory_refs"]}
        memory_rows = {row["id"]: row for row in self.memory.list(include_history=True)}
        for row in domain_rows:
            if row.get("correction_id"):
                value = memory_rows[row["correction_id"]]
                memory_refs[value["id"]] = {"id": value["id"], "version": value["version"]}
        relations = [
            row
            for row in knowledge.list_relations(include_history=True)
            if (not domain_id or row["domain_id"] == domain_id)
            and (set(row["scope"].get("job_ids", [])) & set(scope_ids))
        ]
        definitions = knowledge.list_domains(include_history=True)
        profiles = {}
        with Session(self.repository.engine) as session:
            for row in session.scalars(
                select(JobAnalysis)
                .where(JobAnalysis.job_id.in_(scope_ids))
                .order_by(JobAnalysis.created_at, JobAnalysis.id)
            ):
                profiles[row.job_id] = {
                    "analysis_id": row.id,
                    "snapshot_id": row.snapshot_id,
                    "analyzer_version": row.analyzer_version,
                    "prompt_version": row.prompt_version,
                    "model_name": row.model_name,
                    "status": row.status,
                    "memory_versions": row.memory_versions,
                }
                for memory in row.memory_versions:
                    memory_refs[memory["id"]] = memory
        jobs = []
        for item in records:
            identity = item["job_id"]
            record = item["record"]
            row = item["row"]
            source = None
            if row:
                observation, snapshot, document, run, watchset = row
                source = {
                    "snapshot_id": snapshot.id,
                    "document_id": document.id,
                    "content_sha256": snapshot.content_sha256,
                    "text_sha256": hashlib.sha256(
                        snapshot.payload.get("description", "").encode("utf-8")
                    ).hexdigest(),
                    "document_sha256": document.sha256,
                    "observed_at": observation.observed_at,
                    "processed_at": observation.processed_at,
                    "data_kind": document.provenance.get("data_kind", "unspecified"),
                    "response_origin": document.response_origin,
                    "source_published_at": record.get("source_published_at"),
                    "integrity": Catalog(self.repository).document(document.id)["integrity"],
                }
            profile = profiles.get(identity)
            if profile:
                profile = {
                    **profile,
                    "stale_snapshot": not source or profile["snapshot_id"] != source["snapshot_id"],
                    "stale_memories": [
                        ref["id"]
                        for ref in profile["memory_versions"]
                        if ref["id"] not in memory_rows
                        or memory_rows[ref["id"]]["version"] != ref["version"]
                        or memory_rows[ref["id"]]["status"] != "active"
                    ],
                }
            job = {
                "job_id": identity,
                "fields": {key: record.get(key) for key in FIELDS},
                "filter_state": item["state"],
                "domain": assignments.get(identity),
                "source": source,
                "profile": profile,
                "personal_impact": self._impact(
                    record, record.get("description_text") or "", personal
                )
                if item["state"] != "excluded"
                else None,
            }
            jobs.append(job)
        by_id = {job["job_id"]: job for job in jobs}
        eligible = [
            item
            for item in records
            if item["state"] == "matched"
            and item["record"].get("description_text")
            and (not domain_id or assignments.get(item["job_id"], {}).get("state") == "matched")
            and by_id[item["job_id"]]["source"]
            and by_id[item["job_id"]]["source"]["integrity"] == "verified"
        ]
        stats = [
            {
                "term": term,
                "literal_jobs": sum(
                    term.casefold() in item["record"]["description_text"].casefold()
                    for item in eligible
                )
                if eligible
                else None,
                "denominator": len(eligible),
            }
            for term in terms
        ]
        payload = {
            "id": uuid4().hex,
            "state": "captured",
            "title": title.strip(),
            "created_at": now(),
            "domain_id": domain_id,
            "filters": actual_filters.model_dump(mode="json"),
            "requested_job_ids": job_ids,
            "sample": {
                "scope_total": len(records),
                "eligible_detail_denominator": len(eligible),
                "missing_details": sum(
                    not item["record"].get("description_text")
                    for item in records
                    if item["state"] != "excluded"
                ),
                "filter_unknown": sum(item["state"] == "unknown" for item in records),
                "missing_profiles": sum(job["profile"] is None for job in jobs),
                "invalid_sources": sum(
                    job["source"] is not None and job["source"]["integrity"] != "verified"
                    for job in jobs
                ),
                "domain_counts": page["counts"],
            },
            "jobs": jobs,
            "terms": terms,
            "statistics": stats,
            "definitions": definitions,
            "relations": relations,
            "personal": personal,
            "memory_refs": list(memory_refs.values()),
            "source_run_ids": sorted(
                {row["source_run_id"] for row in relations if row.get("source_run_id")}
            ),
            "note": (
                "用户显式冻结的本地观察，不是新采集或市场趋势；未知分类/画像/关系不记为不存在。"
            ),
        }
        return self._write("domain_update_captures", _json(payload))

    def compare(self, before_id, after_id):
        before = self._get("domain_update_captures", before_id)
        after = self._get("domain_update_captures", after_id)
        if before["created_at"] > after["created_at"]:
            raise ProbeError("UPDATE_CAPTURE_ORDER_INVALID")

        def included(row, panel):
            return row["filter_state"] != "excluded" and (
                not panel["domain_id"] or (row["domain"] or {}).get("state") != "excluded"
            )

        a = {row["job_id"]: row for row in before["jobs"] if included(row, before)}
        b = {row["job_id"]: row for row in after["jobs"] if included(row, after)}
        shared = sorted(a.keys() & b.keys())
        content = []
        metadata = []
        analysis = []
        classifications = []
        profile_validity = []

        def profile_method(profile):
            return (
                {
                    key: profile.get(key)
                    for key in (
                        "analysis_id",
                        "snapshot_id",
                        "analyzer_version",
                        "prompt_version",
                        "model_name",
                        "status",
                        "memory_versions",
                    )
                }
                if profile
                else None
            )

        def assignment(domain):
            return (
                {
                    key: domain.get(key)
                    for key in (
                        "domain_ids",
                        "corrected_domain_keys",
                        "correction_id",
                        "correction_definition_ids",
                        "classification",
                    )
                }
                if domain
                else None
            )

        for identity in shared:
            left, right = a[identity], b[identity]
            old, new = left.get("source"), right.get("source")
            if (
                old
                and new
                and old.get("text_sha256", old["content_sha256"])
                != new.get("text_sha256", new["content_sha256"])
            ):
                diff = HistoryService(self.repository).compare(
                    identity, old["snapshot_id"], new["snapshot_id"]
                )
                content.append(
                    {
                        "job_id": identity,
                        "before": old,
                        "after": new,
                        "description_diff": diff.get("description_diff"),
                        "evidence": diff.get("evidence", []),
                        "note": "已存原文版本差异，非实际网站更新时刻或全市场趋势。",
                    }
                )
            elif bool(old) != bool(new):
                content.append(
                    {
                        "job_id": identity,
                        "kind": "detail_completion_or_missing",
                        "before": old,
                        "after": new,
                    }
                )
            fields = [
                field for field in FIELDS if left["fields"].get(field) != right["fields"].get(field)
            ]
            if fields:
                metadata.append(
                    {
                        "job_id": identity,
                        "fields": [
                            {
                                "name": field,
                                "before": left["fields"].get(field),
                                "after": right["fields"].get(field),
                            }
                            for field in fields
                        ],
                    }
                )
            if profile_method(left["profile"]) != profile_method(right["profile"]):
                analysis.append(
                    {"job_id": identity, "before": left["profile"], "after": right["profile"]}
                )
            elif left["profile"] != right["profile"]:
                profile_validity.append(
                    {"job_id": identity, "before": left["profile"], "after": right["profile"]}
                )
            if assignment(left["domain"]) != assignment(right["domain"]):
                classifications.append(
                    {"job_id": identity, "before": left["domain"], "after": right["domain"]}
                )
        definition_changed = digest(before["definitions"]) != digest(after["definitions"])

        def relation_versions(panel):
            return [
                {key: value for key, value in row.items() if key not in {"stale", "stale_reasons"}}
                for row in panel["relations"]
            ]

        relation_changed = digest(relation_versions(before)) != digest(relation_versions(after))
        relation_validity_changed = not relation_changed and digest(before["relations"]) != digest(
            after["relations"]
        )
        scope_changed = any(
            before.get(key) != after.get(key)
            for key in ("filters", "domain_id", "requested_job_ids")
        )
        gaps = [
            "只有两次用户冻结的观察面板；不能据此认定职业演化、需求上涨或下降。",
            "字面出现不是必备要求；缺画像、关系或未分类保留未知，不使用top-k作分母。",
        ]
        if not content:
            gaps.append("没有可核对的正文版本变化；重复观察不构成变化证据。")
        if after["sample"]["eligible_detail_denominator"] == 0:
            gaps.append("没有明确符合范围且可核验的正文分母，词项命中保持未知，不能认定没有需求。")
        if any(row["profile"] is None for row in after["jobs"]):
            gaps.append("部分岗位没有画像，不能据空画像认定没有任务/能力要求。")
        if not any(row["status"] == "active" and not row["stale"] for row in after["relations"]):
            gaps.append("没有有效审核关系可支撑领域能力演化，关系变化保持未知。")
        identity = digest({"before": before_id, "after": after_id, "version": "domain-updates-v1"})[
            :32
        ]
        report = {
            "id": identity,
            "state": "compared",
            "title": before["title"] + " → " + after["title"],
            "created_at": now(),
            "before_id": before_id,
            "after_id": after_id,
            "sample": {"before": before["sample"], "after": after["sample"]},
            "content_changes": content,
            "metadata_changes": metadata,
            "sample_changes": {
                "added_job_ids": sorted(b.keys() - a.keys()),
                "removed_job_ids": sorted(a.keys() - b.keys()),
                "shared_job_ids": shared,
                "scope_rule_changed": scope_changed,
                "note": "样本加入/离开只描述观察面板，不推断新招聘/岗位关闭。",
            },
            "method_changes": {
                "profiles": analysis,
                "profile_validity_changed": profile_validity,
                "classifications": classifications,
                "literal_terms_changed": before["terms"] != after["terms"],
                "domain_definitions_changed": definition_changed,
                "reviewed_relations_changed": relation_changed,
                "relation_validity_changed": relation_validity_changed,
                "note": "分析或分类口径变化与原文变化分别列示。",
            },
            "statistics": {
                "before": before["statistics"],
                "after": after["statistics"],
                "comparable": not (
                    scope_changed
                    or definition_changed
                    or relation_changed
                    or analysis
                    or classifications
                    or before["terms"] != after["terms"]
                )
                and set(a) == set(b),
                "interpretation": "完整明确符合且有正文的分母；只描述字面，不作市场趋势。",
            },
            "personal_impact": {
                "goal_changed": digest(before["personal"]) != digest(after["personal"]),
                "explicit_goals": after["personal"],
                "jobs": [
                    {
                        "job_id": key,
                        "before": a[key]["personal_impact"] if key in a else None,
                        "after": row["personal_impact"],
                        "evidence": row["source"],
                    }
                    for key, row in b.items()
                ],
                "note": "只解释明确条件与原文/披露字段；不推测个人履历、能力或适配分数。",
            },
            "job_ids": sorted(b),
            "source_run_ids": sorted(set(before["source_run_ids"] + after["source_run_ids"])),
            "memory_refs": list(
                {row["id"]: row for row in before["memory_refs"] + after["memory_refs"]}.values()
            ),
            "gaps": gaps,
            "trend_status": "insufficient_comparable_time_series",
        }
        return self._write("domain_update_reports", report)

    def report(self, identity):
        report = self._get("domain_update_reports", identity)
        report["current_memory_validity"] = [
            self.memory.validity(ref["id"]) for ref in report.get("memory_refs", [])
        ]
        return report

    def followup(self, identity, note):
        report = self.report(identity)
        if not isinstance(note, str) or not note.strip() or len(note) > 2000:
            raise ProbeError("INVALID_UPDATE_FOLLOWUP")
        item = InboxService(self.repository).create(
            "followup",
            "核对领域观察中的变化",
            note.strip(),
            related_id=identity,
            dedupe_key="domain-update:" + identity + ":" + digest(note),
        )
        return {
            "notification": item,
            "question": note.strip(),
            "job_ids": report["job_ids"],
            "report_id": identity,
            "note": "待调查，不自动花费模型额度；可将问题与明确范围带入研究项目。",
        }

    def invalidate(self, run_ids, memory_ids):
        affected_captures = []
        affected_reports = []
        with self.store.lock, self.store.db:
            for table, target in (
                ("domain_update_captures", affected_captures),
                ("domain_update_reports", affected_reports),
            ):
                rows = self.store.db.execute(
                    f"SELECT id,record FROM {table} WHERE namespace=?", (self.store.namespace,)
                ).fetchall()
                for identity, encoded in rows:
                    row = json.loads(encoded)
                    if (
                        set(row.get("source_run_ids", [])) & set(run_ids)
                        or {m["id"] for m in row.get("memory_refs", [])} & set(memory_ids)
                        or row.get("before_id") in affected_captures
                        or row.get("after_id") in affected_captures
                    ):
                        minimal = {
                            "id": identity,
                            "state": "invalidated",
                            "created_at": row.get("created_at"),
                            "source_run_ids": row.get("source_run_ids", []),
                            "memory_refs": [
                                {key: ref.get(key) for key in ("id", "version")}
                                for ref in row.get("memory_refs", [])
                            ],
                            "before_id": row.get("before_id"),
                            "after_id": row.get("after_id"),
                        }
                        self.store.db.execute(
                            f"UPDATE {table} SET record=? WHERE namespace=? AND id=?",
                            (json.dumps(minimal), self.store.namespace, identity),
                        )
                        target.append(identity)
        InboxService(self.repository).invalidate_research(affected_reports)
        return {
            "invalidated_capture_ids": affected_captures,
            "invalidated_update_report_ids": affected_reports,
        }
