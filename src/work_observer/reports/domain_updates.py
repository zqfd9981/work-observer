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
from work_observer.retrieval.enhanced import RetrievalService, normalized_time, validated_terms
from work_observer.storage.models import JobAnalysis
from work_observer.text_match import match_text

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


def _knowledge_rows(rows):
    # Later opinions are available on the knowledge page; they are not a new
    # definition/version and must not be copied into unrelated observation panels.
    return [{key: value for key, value in row.items() if key != "revision_notices"} for row in rows]


def _membership(row, panel):
    if row is None:
        return "not_observed"
    if row["filter_state"] == "excluded":
        return "filter_excluded"
    domain = (row.get("domain") or {}).get("state") if panel["domain_id"] else None
    if domain == "excluded":
        return "domain_excluded"
    if row["filter_state"] == "unknown" or panel["domain_id"] and domain != "matched":
        return "scope_unknown"
    return "included"


def _comparison_scope(before, after):
    left = {row["job_id"]: row for row in before["jobs"]}
    right = {row["job_id"]: row for row in after["jobs"]}
    members = []
    for identity in sorted(left.keys() | right.keys()):
        a, b = left.get(identity), right.get(identity)
        states = (_membership(a, before), _membership(b, after))
        if not {"included", "scope_unknown"}.intersection(states):
            continue
        members.append(
            {
                "job_id": identity,
                "title": (b or a)["fields"].get("title"),
                "before": states[0],
                "after": states[1],
                "before_document_id": ((a or {}).get("source") or {}).get("document_id"),
                "after_document_id": ((b or {}).get("source") or {}).get("document_id"),
            }
        )
    return {
        "job_ids": [row["job_id"] for row in members],
        "members": members,
        "note": (
            "补查覆盖两次面板中曾纳入的岗位，包括离开较晚范围的岗位；"
            "范围条件未知仍单列，不视为明确符合。未观察到或被范围排除不代表岗位关闭，"
            "加入面板也不证明首次招聘。两侧原文按各自冻结时点核对。"
        ),
    }


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
                            "as_of",
                            "analysis_observed",
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
        include_archived=False,
        public_document_ids=None,
        as_of=None,
    ):
        if not isinstance(title, str) or not title.strip() or len(title) > 150:
            raise ProbeError("INVALID_UPDATE_TITLE")
        terms = validated_terms(terms) if terms else []
        created_at = now()
        cutoff = normalized_time(as_of)
        if cutoff and cutoff > created_at:
            raise ProbeError("UPDATE_CUTOFF_IN_FUTURE")
        if cutoff and domain_id:
            raise ProbeError("UPDATE_HISTORICAL_DOMAIN_UNAVAILABLE")
        from work_observer.reports.archived_updates import capture_archived

        archived = capture_archived(
            self.repository,
            include_archived or public_document_ids is not None,
            public_document_ids,
            as_of=cutoff,
        )
        archived_ids = {row["id"] for row in archived["documents"]}
        filters = Filters.model_validate(filters or {})
        records, actual_filters, cutoff = RetrievalService(self.repository)._records(
            filters, job_ids, cutoff
        )
        if len(records) > 2000:
            raise ProbeError("UPDATE_SCOPE_LIMIT_2000_NARROW_SCOPE")
        domain_rows = []
        page = {
            "counts": {
                "scope_total": sum(item["state"] != "excluded" for item in records),
                "matched": 0,
                "unknown": sum(item["state"] != "excluded" for item in records),
                "excluded": 0,
            }
        }
        if not cutoff:
            knowledge = DomainKnowledgeService(self.repository)
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
        memory_rows = (
            {row["id"]: row for row in self.memory.list(include_history=True)} if not cutoff else {}
        )
        for row in domain_rows:
            if row.get("correction_id"):
                value = memory_rows[row["correction_id"]]
                memory_refs[value["id"]] = {"id": value["id"], "version": value["version"]}
        relations = (
            _knowledge_rows(
                [
                    row
                    for row in knowledge.list_relations(include_history=True)
                    if (not domain_id or row["domain_id"] == domain_id)
                    and (
                        set(row["scope"].get("job_ids", [])) & set(scope_ids)
                        or set(row["scope"].get("public_document_ids", [])) & archived_ids
                    )
                ]
            )
            if not cutoff
            else []
        )
        definitions = (
            _knowledge_rows(knowledge.list_domains(include_history=True)) if not cutoff else []
        )
        profiles = {}
        with Session(self.repository.engine) as session:
            for row in session.scalars(
                select(JobAnalysis)
                .where(JobAnalysis.job_id.in_(scope_ids), not bool(cutoff))
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
        eligible_ids = {item["job_id"] for item in eligible}
        for item in records:
            hits = None
            if item["job_id"] in eligible_ids:
                folded = match_text(item["record"]["description_text"])
                hits = [term for term in terms if match_text(term) in folded]
            by_id[item["job_id"]]["literal_hits"] = hits
        stats = [
            {
                "term": term,
                "literal_jobs": sum(
                    term in by_id[item["job_id"]]["literal_hits"]
                    for item in eligible
                )
                if eligible
                else None,
                "denominator": len(eligible),
            }
            for term in terms
        ]
        composition = {}
        for item in records:
            job = by_id[item["job_id"]]
            if (
                item["state"] == "excluded"
                or domain_id
                and (job["domain"] or {}).get("state") == "excluded"
            ):
                continue
            source = job["source"] or {}
            key = (item["record"].get("source", "unknown"), source.get("data_kind", "unspecified"))
            group = composition.setdefault(
                key,
                {
                    "source": key[0],
                    "data_kind": key[1],
                    "jobs": 0,
                    "eligible_details": 0,
                    "missing_details": 0,
                    "unknown_scope": 0,
                    "known_published_time": 0,
                },
            )
            group["jobs"] += 1
            group["eligible_details"] += item["job_id"] in eligible_ids
            group["missing_details"] += not bool(item["record"].get("description_text"))
            group["unknown_scope"] += item["state"] == "unknown" or bool(
                domain_id and (job["domain"] or {}).get("state") == "unknown"
            )
            group["known_published_time"] += bool(item["record"].get("source_published_at"))
        payload = {
            "id": uuid4().hex,
            "state": "captured",
            "title": title.strip(),
            "created_at": created_at,
            "as_of": cutoff,
            "analysis_observed": not bool(cutoff),
            "personal_basis": "current_explicit_conditions",
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
                "missing_profiles": None if cutoff else sum(job["profile"] is None for job in jobs),
                "invalid_sources": sum(
                    job["source"] is not None and job["source"]["integrity"] != "verified"
                    for job in jobs
                ),
                "archived_documents": len(archived["documents"]),
                "archived_observed": archived["enabled"],
                "invalid_archived_documents": sum(
                    row["integrity"] != "verified" for row in archived["documents"]
                ),
                "domain_counts": page["counts"],
                "source_composition": [composition[key] for key in sorted(composition)],
            },
            "jobs": jobs,
            "terms": terms,
            "literal_matching": "casefold-kangxi-radicals",
            "archived_scope": archived,
            "statistics": stats,
            "definitions": definitions,
            "relations": relations,
            "personal": personal,
            "memory_refs": list(memory_refs.values()),
            "source_run_ids": sorted(
                {row["source_run_id"] for row in relations if row.get("source_run_id")}
                | {
                    row["source_context"]["run_id"]
                    for row in definitions
                    if (row.get("source_context") or {}).get("run_id")
                }
            ),
            "note": (
                "用户显式冻结的本地观察，不是新采集或市场趋势；未知分类/画像/关系不记为不存在。"
                + (
                    "历史面板只重建截止时已观察且入库的来源，不还原当时分类、审核或个人偏好；"
                    "完整性按本次读取的本地归档核对，个人条件若启用则使用本次已明确条件。"
                    if cutoff
                    else ""
                )
            ),
        }
        return self._write("domain_update_captures", _json(payload))

    def compare(self, before_id, after_id):
        from work_observer.reports.archived_updates import compare_archived
        from work_observer.reports.literal_cohort import compare_literal_cohort

        before = self._get("domain_update_captures", before_id)
        after = self._get("domain_update_captures", after_id)
        before, after = [
            {
                **panel,
                "definitions": _knowledge_rows(panel["definitions"]),
                "relations": _knowledge_rows(panel["relations"]),
            }
            for panel in (before, after)
        ]
        if (before.get("as_of") or before["created_at"]) > (
            after.get("as_of") or after["created_at"]
        ):
            raise ProbeError("UPDATE_CAPTURE_ORDER_INVALID")
        analysis_comparable = before.get("analysis_observed", True) and after.get(
            "analysis_observed", True
        )

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
                    identity,
                    old["snapshot_id"],
                    new["snapshot_id"],
                    observed_before=after.get("as_of") or after["created_at"],
                    before_cutoff=before.get("as_of") or before["created_at"],
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
            if analysis_comparable and profile_method(left["profile"]) != profile_method(
                right["profile"]
            ):
                analysis.append(
                    {"job_id": identity, "before": left["profile"], "after": right["profile"]}
                )
            elif analysis_comparable and left["profile"] != right["profile"]:
                profile_validity.append(
                    {"job_id": identity, "before": left["profile"], "after": right["profile"]}
                )
            if analysis_comparable and assignment(left["domain"]) != assignment(right["domain"]):
                classifications.append(
                    {"job_id": identity, "before": left["domain"], "after": right["domain"]}
                )

        def versions(rows):
            return [
                {key: value for key, value in row.items() if key not in {"stale", "stale_reasons"}}
                for row in rows
            ]

        definition_changed = digest(versions(before["definitions"])) != digest(
            versions(after["definitions"])
        )
        definition_validity_changed = not definition_changed and digest(
            before["definitions"]
        ) != digest(after["definitions"])

        def relation_versions(panel):
            return [
                {key: value for key, value in row.items() if key not in {"stale", "stale_reasons"}}
                for row in panel["relations"]
            ]

        relation_changed = digest(relation_versions(before)) != digest(relation_versions(after))
        relation_validity_changed = not relation_changed and digest(before["relations"]) != digest(
            after["relations"]
        )
        if not analysis_comparable:
            definition_changed = definition_validity_changed = None
            relation_changed = relation_validity_changed = None
        scope_changed = any(
            before.get(key) != after.get(key)
            for key in ("filters", "domain_id", "requested_job_ids")
        )
        literal_matching_changed = before.get("literal_matching", "casefold") != after.get(
            "literal_matching", "casefold"
        )

        def composition(panel):
            rows = panel["sample"].get("source_composition")
            return (
                [(row["source"], row["data_kind"], row["jobs"]) for row in rows]
                if rows is not None
                else None
            )

        composition_changed = (
            composition(before) != composition(after)
            if composition(before) is not None and composition(after) is not None
            else None
        )
        gaps = [
            "只有两次用户冻结的观察面板；不能据此认定职业演化、需求上涨或下降。",
            "字面出现不是必备要求；缺画像、关系或未分类保留未知，不使用top-k作分母。",
        ]
        if not content:
            gaps.append("没有可核对的正文版本变化；重复观察不构成变化证据。")
        if composition_changed:
            gaps.append(
                "来源或正文资料性质的样本构成改变；数量差异不能直接解释为外部招聘需求变化。"
            )
        if literal_matching_changed:
            gaps.append("字面词项匹配方式发生变化；不同算法的计数差异不能解释为需求变化。")
        if after["sample"]["eligible_detail_denominator"] == 0:
            gaps.append("没有明确符合范围且可核验的正文分母，词项命中保持未知，不能认定没有需求。")
        if not analysis_comparable:
            gaps.append(
                "至少一侧是历史来源重建，不能据此判断当时画像、分类、定义或审核状态如何变化。"
            )
        elif any(row["profile"] is None for row in after["jobs"]):
            gaps.append("部分岗位没有画像，不能据空画像认定没有任务/能力要求。")
        if analysis_comparable and not any(
            row["status"] == "active" and not row["stale"] for row in after["relations"]
        ):
            gaps.append("没有有效审核关系可支撑领域能力演化，关系变化保持未知。")
        identity = digest({"before": before_id, "after": after_id, "version": "domain-updates-v1"})[
            :32
        ]
        comparison_scope = _comparison_scope(before, after)
        report = {
            "id": identity,
            "state": "compared",
            "title": before["title"] + " → " + after["title"],
            "created_at": now(),
            "before_id": before_id,
            "after_id": after_id,
            "sample": {"before": before["sample"], "after": after["sample"]},
            "observation_times": {
                side: {
                    "source_cutoff": panel.get("as_of") or panel["created_at"],
                    "captured_at": panel["created_at"],
                    "mode": "historical_sources" if panel.get("as_of") else "current",
                }
                for side, panel in (("before", before), ("after", after))
            },
            "content_changes": content,
            "metadata_changes": metadata,
            "archived_changes": compare_archived(self.repository, before, after),
            "sample_changes": {
                "added_job_ids": sorted(b.keys() - a.keys()),
                "removed_job_ids": sorted(a.keys() - b.keys()),
                "shared_job_ids": shared,
                "scope_rule_changed": scope_changed,
                "source_composition_changed": composition_changed,
                "note": "样本加入/离开只描述观察面板，不推断新招聘/岗位关闭。",
            },
            "method_changes": {
                "analysis_comparable": analysis_comparable,
                "profiles": analysis,
                "profile_validity_changed": profile_validity,
                "classifications": classifications,
                "literal_terms_changed": before["terms"] != after["terms"],
                "literal_matching_changed": literal_matching_changed,
                "domain_definitions_changed": definition_changed,
                "definition_validity_changed": definition_validity_changed,
                "reviewed_relations_changed": relation_changed,
                "relation_validity_changed": relation_validity_changed,
                "note": "分析或分类口径变化与原文变化分别列示。",
            },
            "statistics": {
                "before": before["statistics"],
                "after": after["statistics"],
                "comparable": not (
                    scope_changed
                    or composition_changed
                    or literal_matching_changed
                    or definition_changed
                    or definition_validity_changed
                    or relation_changed
                    or relation_validity_changed
                    or analysis
                    or classifications
                    or before["terms"] != after["terms"]
                )
                and set(a) == set(b),
                "interpretation": "完整明确符合且有正文的分母；只描述字面，不作市场趋势。",
            },
            "common_cohort": compare_literal_cohort(before, after, a, b),
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
                "note": (
                    "只解释本次冻结时的明确条件与所选时点原文/披露字段，不还原当时个人偏好；"
                    "不推测个人履历、能力或适配分数。"
                ),
            },
            "job_ids": comparison_scope["job_ids"],
            "comparison_scope": comparison_scope,
            "public_document_ids": [
                row["id"] for row in after.get("archived_scope", {}).get("documents", [])
            ],
            "archived_documents": after.get("archived_scope", {}).get("documents", []),
            "source_run_ids": sorted(set(before["source_run_ids"] + after["source_run_ids"])),
            "memory_refs": list(
                {row["id"]: row for row in before["memory_refs"] + after["memory_refs"]}.values()
            ),
            "gaps": gaps,
            "trend_status": "insufficient_comparable_time_series",
        }
        return self._write("domain_update_reports", report)

    def report(self, identity):
        from work_observer.reports.research_impact import research_impact

        report = self._get("domain_update_reports", identity)
        before = self._get("domain_update_captures", report["before_id"])
        after = self._get("domain_update_captures", report["after_id"])
        report["comparison_scope"] = _comparison_scope(before, after)
        report["job_ids"] = report["comparison_scope"]["job_ids"]
        report["current_memory_validity"] = [
            self.memory.validity(ref["id"]) for ref in report.get("memory_refs", [])
        ]
        report["research_impact"] = research_impact(
            self.repository,
            self.store,
            before,
            after,
            report,
        )
        return report

    def followup(self, identity, note, run_id=None):
        from work_observer.storage.locks import exclusive

        with exclusive(self.repository.engine.url.database):
            return self._followup(identity, note, run_id)

    def _followup(self, identity, note, run_id):
        report = self.report(identity)
        if not isinstance(note, str) or not note.strip() or len(note) > 2000:
            raise ProbeError("INVALID_UPDATE_FOLLOWUP")
        question = note.strip()
        times = report.get("observation_times", {})
        historical = any(row.get("mode") == "historical_sources" for row in times.values())
        if times:
            question += (
                "\n对照的来源截止："
                + times["before"]["source_cutoff"]
                + " → "
                + times["after"]["source_cutoff"]
                + (
                    "。这是归档来源重建，不是当时的分析或偏好。"
                    if historical
                    else "。这是报告中当时冻结的两次观察；报告之后取得的资料须另行说明。"
                )
                + "分别核对上述两个来源截止时点的岗位原文，读取不完整时继续查看后文；"
                "归档工作资料须核对所选的两版原文。"
                "当前补查须区分现在读取的材料与报告中的历史版本；未读到对应历史原文时保留未知，"
                "不能把现在的内容代替过去。样本加入与资料补全不表示新招聘或新增职责，"
                "离开较晚观察范围也不代表岗位关闭。分别区分未观察到、筛选排除与条件未知。"
            )
        if run_id:
            from work_observer.research.projects import ProjectService

            source = next(
                (row for row in report["research_impact"]["runs"] if row["run_id"] == run_id), None
            )
            if not source or not source["can_followup"]:
                raise ProbeError("UPDATE_LINKED_RESEARCH_UNAVAILABLE")
            projects = ProjectService(self.store)
            project = projects.get(source["project_id"])
            if any(step["state"] == "running" for step in project["steps"]):
                raise ProbeError("PROJECT_RUNNING")
            key = "domain-update:" + identity + ":" + run_id + ":" + digest(note)
            saved = next((step for step in project["steps"] if step.get("key") == key), None)
            if not saved:
                previous = next(s for s in project["steps"] if s["id"] == source["step_id"])
                used, budget = projects.usage(project), project["budget"]
                calls = min(6, budget["max_calls"] - used["reserved_calls"])
                seconds = min(180, int(budget["max_seconds"] - used["reserved_seconds"]))
                if calls < 1 or seconds < 1:
                    raise ProbeError("UPDATE_PROJECT_BUDGET_EXHAUSTED")
                if len(project["steps"]) >= budget["max_rounds"]:
                    raise ProbeError("PROJECT_ROUND_LIMIT")
                if source.get("document_updates"):
                    replacements = {
                        row["before_id"]: row["after_id"] for row in source["document_updates"]
                    }
                    project = projects.revise(
                        project["id"],
                        revision=project["revision"],
                        goal=project["goal"],
                        job_ids=project["job_ids"],
                        public_document_ids=(
                            list(
                                dict.fromkeys(
                                    [*project["public_document_ids"], *replacements.values()]
                                )
                            )
                            if times
                            else [
                                replacements.get(key, key) for key in project["public_document_ids"]
                            ]
                        ),
                    )
                project = projects.add(
                    project["id"],
                    question,
                    revision=project["revision"],
                    reply_to_step_id=source["step_id"],
                    approach=(
                        "standard"
                        if times and previous.get("approach") == "source_first"
                        else previous.get("approach", "standard")
                    ),
                    coverage_mode=previous.get("coverage_mode", "all"),
                    max_calls=calls,
                    timeout=seconds,
                    key=key,
                    completion=(
                        "分别核对两个来源截止的历史原文，说明旧认识是否保留、修订或撤回；区分正文、补齐与样本变化。"
                        if times
                        else (
                            "重读当前原文并比较已存版本，核对旧认识是否保留、修订或撤回；"
                            "区分原文、样本与分析口径变化。"
                        )
                    ),
                )
                saved = next(step for step in project["steps"] if step.get("key") == key)
            return {
                "project_id": project["id"],
                "step_id": saved["id"],
                "state": saved["state"],
                "question": saved["question"],
                "report_id": identity,
                "note": "复核问题已保存回原研究，沿用原范围和累计预算；尚未启动模型。",
            }
        item = InboxService(self.repository).create(
            "followup",
            "核对领域观察中的变化",
            question,
            related_id=identity,
            dedupe_key="domain-update:" + identity + ":" + digest(note),
        )
        return {
            "notification": item,
            "question": question,
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
