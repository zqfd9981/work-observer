"""人工审核领域定义和工作关系，保留版本、反例、来源与有限适用范围。"""

import json
import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.knowledge.models import DomainDefinition, WorkRelation
from work_observer.memory.service import MemoryService
from work_observer.retrieval.enhanced import RetrievalService

DIMENSIONS = {"business", "task", "deliverable", "responsibility", "ability", "tool"}


def _text(value, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ProbeError("INVALID_KNOWLEDGE_TEXT")
    return value.strip()


def _record(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class DomainKnowledgeService:
    def __init__(self, repository):
        self.repository = repository
        self.memory = MemoryService(repository)

    def propose_domain(
        self,
        domain_key,
        name,
        definition,
        *,
        inclusion="",
        exclusion="",
        previous_id=None,
        change_kind="create",
        related_ids=None,
        source_context=None,
    ):
        if not isinstance(domain_key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", domain_key):
            raise ProbeError("INVALID_DOMAIN_KEY")
        name, definition = _text(name, 160), _text(definition)
        if not isinstance(inclusion, str) or not isinstance(exclusion, str):
            raise ProbeError("INVALID_KNOWLEDGE_TEXT")
        if len(inclusion) > 4000 or len(exclusion) > 4000:
            raise ProbeError("INVALID_KNOWLEDGE_TEXT")
        if change_kind not in {"create", "revise", "merge", "split"}:
            raise ProbeError("INVALID_DOMAIN_CHANGE")
        if change_kind == "revise" and not previous_id or change_kind == "create" and previous_id:
            raise ProbeError("INVALID_DOMAIN_CHANGE")
        if related_ids is not None and (
            not isinstance(related_ids, list)
            or any(not isinstance(value, str) for value in related_ids)
        ):
            raise ProbeError("INVALID_DOMAIN_CHANGE")
        related_ids = list(dict.fromkeys(related_ids or []))
        if len(related_ids) > 20:
            raise ProbeError("INVALID_DOMAIN_CHANGE")
        if change_kind in {"merge", "split"} and not related_ids:
            raise ProbeError("DOMAIN_LINEAGE_REQUIRED")
        if change_kind == "merge" and len(related_ids) < 2:
            raise ProbeError("DOMAIN_LINEAGE_REQUIRED")
        with Session(self.repository.engine) as session, session.begin():
            previous = session.get(DomainDefinition, previous_id) if previous_id else None
            latest = session.scalar(
                select(DomainDefinition)
                .where(DomainDefinition.domain_key == domain_key)
                .order_by(DomainDefinition.version.desc())
                .limit(1)
            )
            if latest and (not previous or previous.id != latest.id):
                raise ProbeError("DOMAIN_VERSION_CONFLICT")
            if previous_id and (not previous or previous.domain_key != domain_key):
                raise ProbeError("DOMAIN_VERSION_CONFLICT")
            for identity in related_ids:
                if session.get(DomainDefinition, identity) is None:
                    raise ProbeError("DOMAIN_NOT_FOUND")
            row = DomainDefinition(
                id=uuid4().hex,
                domain_key=domain_key,
                version=latest.version + 1 if latest else 1,
                previous_id=previous_id,
                name=name,
                definition=definition,
                inclusion=inclusion.strip(),
                exclusion=exclusion.strip(),
                status="candidate",
                change_kind=change_kind,
                related_ids=related_ids,
                source_context=(
                    source_context
                    if source_context is not None
                    else dict(previous.source_context or {})
                    if previous
                    else {}
                ),
                review_reason=None,
                created_at=now(),
                reviewed_at=None,
            )
            session.add(row)
            session.flush()
            return _record(row)

    def review_domain(self, identity, decision, reason):
        if decision not in {"accept", "reject", "withdraw"}:
            raise ProbeError("INVALID_KNOWLEDGE_REVIEW")
        reason = _text(reason, 1200)
        with Session(self.repository.engine) as session, session.begin():
            row = session.get(DomainDefinition, identity)
            if not row:
                raise ProbeError("DOMAIN_NOT_FOUND")
            target = {"accept": "active", "reject": "rejected", "withdraw": "withdrawn"}[decision]
            if row.status == target:
                return _record(row)
            if row.status not in {"candidate", "active"} or (
                row.status == "active" and decision != "withdraw"
            ):
                raise ProbeError("DOMAIN_REVIEW_STATE_CONFLICT")
            if decision == "accept":
                if self.definition_validity(row):
                    raise ProbeError("DOMAIN_RESEARCH_SOURCE_STALE")
                if session.scalar(
                    select(DomainDefinition.id)
                    .where(
                        DomainDefinition.domain_key == row.domain_key,
                        DomainDefinition.version > row.version,
                        DomainDefinition.status == "active",
                    )
                    .limit(1)
                ):
                    raise ProbeError("DOMAIN_VERSION_CONFLICT")
                for other in session.scalars(
                    select(DomainDefinition).where(
                        DomainDefinition.domain_key == row.domain_key,
                        DomainDefinition.status == "active",
                        DomainDefinition.id != row.id,
                    )
                ):
                    other.status = "superseded"
                if row.change_kind in {"merge", "split"}:
                    for related in row.related_ids:
                        original = session.get(DomainDefinition, related)
                        if original.status == "active":
                            original.status = "retired"
            row.status, row.review_reason, row.reviewed_at = target, reason, now()
            session.flush()
            return _record(row)

    def list_domains(self, include_history=False):
        statement = select(DomainDefinition)
        if not include_history:
            statement = statement.where(DomainDefinition.status.in_({"active", "candidate"}))
        with Session(self.repository.engine) as session:
            output = []
            for row in session.scalars(
                statement.order_by(DomainDefinition.domain_key, DomainDefinition.version.desc())
            ):
                reasons = self.definition_validity(row)
                output.append({**_record(row), "stale": bool(reasons), "stale_reasons": reasons})
            return output

    def definition_validity(
        self, row, *, job_ids=None, public_document_ids=None, project_id=None, scoped=False, at=None
    ):
        context = row.source_context or {}
        if not context.get("run_id"):
            return []
        if scoped and (
            not set(context.get("job_ids", [])) <= set(job_ids or [])
            or not set(context.get("public_document_ids", [])) <= set(public_document_ids or [])
        ):
            return ["工作类型的来源不在本轮资料范围"]
        eligible = self.memory.derived_eligibility(
            context["run_id"],
            job_ids=job_ids if scoped else context.get("job_ids", []),
            project_id=project_id if scoped else context.get("project_id"),
            at=at,
            evidence_ids=context.get("evidence_ids"),
        )["eligible"]
        return [] if eligible else ["来源研究、原文或所用背景需要重新核对"]

    def _relation_evidence(self, session, evidence):
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 60:
            raise ProbeError("MEMORY_EVIDENCE_REQUIRED")
        return [
            item
            for start in range(0, len(evidence), 10)
            for item in self.memory._validate_evidence(session, evidence[start : start + 10])
        ]

    def propose_relation(
        self,
        domain_id,
        source_kind,
        source_text,
        target_kind,
        target_text,
        evidence,
        *,
        predicate="supports",
        counterevidence=None,
        conflict_ids=None,
        project_id=None,
        source_run_id=None,
        research_map=None,
    ):
        if source_kind not in DIMENSIONS or target_kind not in DIMENSIONS:
            raise ProbeError("INVALID_RELATION_DIMENSION")
        if predicate not in {"supports", "requires", "produces", "contradicts"}:
            raise ProbeError("INVALID_RELATION_PREDICATE")
        source_text, target_text = _text(source_text, 500), _text(target_text, 500)
        if source_run_id is not None and (
            not isinstance(source_run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", source_run_id)
        ):
            raise ProbeError("INVALID_RESEARCH_ID")
        if project_id is not None and (
            not isinstance(project_id, str) or not re.fullmatch(r"[a-f0-9]{32}", project_id)
        ):
            raise ProbeError("INVALID_PROJECT_ID")
        if conflict_ids is not None and (
            not isinstance(conflict_ids, list)
            or any(not isinstance(value, str) for value in conflict_ids)
        ):
            raise ProbeError("INVALID_RELATION_CONFLICT")
        conflict_ids = list(dict.fromkeys(conflict_ids or []))
        if len(conflict_ids) > 20:
            raise ProbeError("INVALID_RELATION_CONFLICT")
        with Session(self.repository.engine) as session, session.begin():
            domain = session.get(DomainDefinition, domain_id)
            if domain is None:
                raise ProbeError("DOMAIN_NOT_FOUND")
            verified = self._relation_evidence(session, evidence)
            counter = self._relation_evidence(session, counterevidence) if counterevidence else []
            evidence_scope = (
                "job"
                if any(item.get("job_id") for item in verified)
                else "work_material"
                if any(item.get("evidence_kind") == "work_material" for item in verified)
                else "public_context"
            )
            if (
                (source_kind != "business" or target_kind != "business")
                and not any(item.get("job_id") for item in verified)
                and evidence_scope != "work_material"
                and not (research_map and research_map.get("evidence_scope") == "public_context")
            ):
                raise ProbeError("RELATION_JOB_EVIDENCE_REQUIRED")
            scope = {
                "job_ids": sorted({item["job_id"] for item in verified if item.get("job_id")}),
                "public_document_ids": sorted(
                    {
                        item["public_document_id"]
                        for item in verified
                        if item.get("public_document_id")
                    }
                ),
                "counter_job_ids": sorted(
                    {item["job_id"] for item in counter if item.get("job_id")}
                ),
                "counter_public_document_ids": sorted(
                    {
                        item["public_document_id"]
                        for item in counter
                        if item.get("public_document_id")
                    }
                ),
                "project_id": project_id,
                "evidence_scope": evidence_scope,
                **({"research_map": research_map} if research_map is not None else {}),
            }
            for identity in conflict_ids:
                previous = session.get(WorkRelation, identity)
                previous_domain = (
                    session.get(DomainDefinition, previous.domain_id) if previous else None
                )
                if previous is None or previous_domain.domain_key != domain.domain_key:
                    raise ProbeError("INVALID_RELATION_CONFLICT")
            # 同一次研究的重复提议不成为第二份独立认识。
            if source_run_id:
                existing = session.scalars(
                    select(WorkRelation).where(WorkRelation.source_run_id == source_run_id)
                )
                for old in existing:
                    if (
                        old.domain_id == domain_id
                        and old.source_kind == source_kind
                        and old.source_text == source_text
                        and old.target_kind == target_kind
                        and old.target_text == target_text
                        and old.predicate == predicate
                        and old.evidence == verified
                        and old.counterevidence == counter
                        and old.scope.get("research_map") == research_map
                        and old.status != "invalidated"
                    ):
                        return _record(old)
            row = WorkRelation(
                id=uuid4().hex,
                domain_id=domain_id,
                source_kind=source_kind,
                source_text=source_text,
                target_kind=target_kind,
                target_text=target_text,
                predicate=predicate,
                scope=scope,
                evidence=verified,
                counterevidence=counter,
                conflict_ids=conflict_ids,
                status="conflicted" if conflict_ids else "candidate",
                review_reason=None,
                source_run_id=source_run_id,
                created_at=now(),
                reviewed_at=None,
            )
            session.add(row)
            session.flush()
            return _record(row)

    def _validity(self, session, row):
        domain = session.get(DomainDefinition, row.domain_id)
        reasons = []
        if (
            row.source_run_id
            and not self.memory.derived_eligibility(
                row.source_run_id,
                job_ids=row.scope.get("job_ids", []),
                project_id=row.scope.get("project_id"),
                evidence_ids=[item["id"] for item in [*row.evidence, *row.counterevidence]],
            )["eligible"]
        ):
            reasons.append("来源研究依赖已变化、范围不符或无法核验")
        if domain.status != "active":
            reasons.append("领域定义已替换、撤回或尚未审核")
        reasons.extend(self.definition_validity(domain))
        # 关系中的领域归属也服从明确的单岗纠正；不让旧图谱绕过人工口径。
        for job_id in row.scope.get("job_ids", []):
            for correction in self.memory.recall(
                "领域", [job_id], project_id=row.scope.get("project_id"), kinds=["correction"]
            ):
                if correction.get("job_id") != job_id:
                    continue
                prefix = "画像领域纠正："
                if not correction["content"].startswith(prefix):
                    continue
                try:
                    values = json.loads(correction["content"][len(prefix) :])
                    accepted = (
                        row.domain_id in values["definition_ids"]
                        if "definition_ids" in values
                        else domain.domain_key in values["domains"]
                    )
                    if not accepted:
                        reasons.append("人工岗位领域纠正与旧关系归属不同")
                except (ValueError, KeyError, TypeError):
                    pass
                break
        for other in session.scalars(
            select(WorkRelation).where(WorkRelation.status.in_({"candidate", "conflicted"}))
        ):
            if row.id in other.conflict_ids:
                reasons.append("存在待审核冲突关系")
        try:
            verified = self._relation_evidence(session, row.evidence)
            if row.counterevidence:
                verified.extend(self._relation_evidence(session, row.counterevidence))
            from work_observer.connectors.public_models import PublicDocument
            from work_observer.storage.models import Job, JobSnapshot

            for item in verified:
                if item.get("job_id"):
                    job = session.get(Job, item["job_id"])
                    snapshot = session.get(JobSnapshot, item["snapshot_id"])
                    if job.description_text != snapshot.payload.get("description"):
                        reasons.append("岗位正文版本已变化")
                elif item.get("public_document_id"):
                    document = session.get(PublicDocument, item["public_document_id"])
                    latest = session.scalar(
                        select(PublicDocument)
                        .where(PublicDocument.url == document.url)
                        .order_by(PublicDocument.observed_at.desc(), PublicDocument.id.desc())
                        .limit(1)
                    )
                    if latest.text_sha256 != document.text_sha256:
                        reasons.append("公开材料已有新内容版本")
        except ProbeError:
            reasons.append("来源失效或原文引用不再可核验")
        return sorted(set(reasons))

    def review_relation(self, identity, decision, reason):
        if decision not in {"accept", "reject", "withdraw"}:
            raise ProbeError("INVALID_KNOWLEDGE_REVIEW")
        reason = _text(reason, 1200)
        with Session(self.repository.engine) as session, session.begin():
            row = session.get(WorkRelation, identity)
            if not row:
                raise ProbeError("RELATION_NOT_FOUND")
            target = {"accept": "active", "reject": "rejected", "withdraw": "withdrawn"}[decision]
            if row.status == target:
                return _record(row)
            if row.status not in {"candidate", "conflicted", "active"} or (
                row.status == "active" and decision != "withdraw"
            ):
                raise ProbeError("RELATION_REVIEW_STATE_CONFLICT")
            if decision == "accept":
                if self._validity(session, row):
                    raise ProbeError("RELATION_SOURCE_OR_DOMAIN_STALE")
                # 冲突不自动覆盖；先显式撤回或拒绝旧认识，再采纳新关系。
                if any(
                    session.get(WorkRelation, value).status in {"active", "candidate", "conflicted"}
                    for value in row.conflict_ids
                ):
                    raise ProbeError("RELATION_CONFLICT_REQUIRES_REVIEW")
            row.status, row.review_reason, row.reviewed_at = target, reason, now()
            session.flush()
            return _record(row)

    def list_relations(self, domain_id=None, *, include_history=False, project_id=None):
        statement = select(WorkRelation)
        if domain_id:
            statement = statement.where(WorkRelation.domain_id == domain_id)
        if not include_history:
            statement = statement.where(
                WorkRelation.status.in_({"active", "candidate", "conflicted"})
            )
        with Session(self.repository.engine) as session:
            output = []
            for row in session.scalars(
                statement.order_by(WorkRelation.created_at, WorkRelation.id)
            ):
                if row.scope.get("project_id") and row.scope["project_id"] != project_id:
                    continue
                reasons = (
                    self._validity(session, row)
                    if row.status != "invalidated"
                    else ["上游研究已失效"]
                )
                output.append({**_record(row), "stale": bool(reasons), "stale_reasons": reasons})
            return output

    def invalidate_research(self, run_ids):
        """忘记闭包调用：研究文本不能经关系知识复生，原文不删除。"""
        affected = self.research_dependencies(run_ids)
        with Session(self.repository.engine) as session, session.begin():
            for row in session.scalars(
                select(DomainDefinition).where(DomainDefinition.id.in_(affected["domain_ids"]))
            ):
                origin = (row.source_context or {}).get("run_id")
                row.name = row.definition = row.inclusion = row.exclusion = "[上游研究已失效]"
                row.source_context = {"run_id": origin} if origin else {}
                row.review_reason, row.status = None, "invalidated"
            rows = session.scalars(
                select(WorkRelation).where(WorkRelation.id.in_(affected["relation_ids"]))
            ).all()
            for row in rows:
                row.source_text = row.target_text = "[上游研究已失效]"
                row.evidence = row.counterevidence = row.conflict_ids = []
                row.scope, row.review_reason, row.status = {}, None, "invalidated"
            return {
                "invalidated_relation_ids": [row.id for row in rows],
                "invalidated_domain_ids": affected["domain_ids"],
            }

    def research_dependencies(self, run_ids):
        """Find definition revisions and their relations before erasing source records."""
        runs = set(run_ids)
        with Session(self.repository.engine) as session:
            domains = list(session.scalars(select(DomainDefinition)))
            affected = {
                row.id for row in domains if (row.source_context or {}).get("run_id") in runs
            }
            while True:
                expanded = affected | {
                    row.id
                    for row in domains
                    if row.previous_id in affected or set(row.related_ids or []) & affected
                }
                if expanded == affected:
                    break
                affected = expanded
            relations = [
                row.id
                for row in session.scalars(select(WorkRelation))
                if row.source_run_id in runs or row.domain_id in affected
            ]
            return {"domain_ids": sorted(affected), "relation_ids": relations}

    def dependent_domain_corrections(self, domain_ids):
        """Classification decisions can contain copied labels from a forgotten definition."""
        from work_observer.analysis.profiles import CORRECTION_PREFIX
        from work_observer.storage.models import MemoryRecord

        identities = set(domain_ids)
        if not identities:
            return []
        with Session(self.repository.engine) as session:
            output = []
            for row in session.scalars(
                select(MemoryRecord).where(
                    MemoryRecord.kind == "correction", MemoryRecord.status != "forgotten"
                )
            ):
                if not row.content.startswith(CORRECTION_PREFIX):
                    continue
                try:
                    value = json.loads(row.content[len(CORRECTION_PREFIX) :])
                    if isinstance(value, dict) and identities.intersection(
                        value.get("definition_ids", [])
                    ):
                        output.append(row.id)
                except (ValueError, TypeError):
                    continue
            return output

    @staticmethod
    def _in_scope(row, job_ids, public_document_ids, project_id):
        if row.scope.get("project_id") and row.scope["project_id"] != project_id:
            return False
        for item in [*row.evidence, *row.counterevidence]:
            if item.get("job_id") and item["job_id"] not in job_ids:
                return False
            if (
                item.get("public_document_id")
                and item["public_document_id"] not in public_document_ids
            ):
                return False
        return True

    def audit_dependencies(self, dependencies, *, job_ids, public_document_ids, project_id=None):
        """只核对已采用的权威记录，不重新召回新知识替换旧上下文。"""
        issues = []
        with Session(self.repository.engine) as session:
            for item in dependencies:
                if not isinstance(item, dict):
                    issues.append({"id": None, "reason": "invalid_dependency"})
                    continue
                identity, kind = item.get("id"), item.get("kind")
                model = {"domain_definition": DomainDefinition, "work_relation": WorkRelation}.get(
                    kind
                )
                if not model or not isinstance(identity, str):
                    issues.append({"id": identity, "reason": "invalid_dependency"})
                    continue
                row = session.get(model, identity)
                reasons = []
                if row is None:
                    reasons.append("missing")
                elif row.status != "active" or item.get("status") != row.status:
                    reasons.append("status_changed")
                elif row.reviewed_at != item.get("reviewed_at"):
                    reasons.append("review_changed")
                if row and kind == "domain_definition" and row.version != item.get("version"):
                    reasons.append("version_changed")
                if row and kind == "domain_definition":
                    reasons.extend(
                        self.definition_validity(
                            row,
                            job_ids=job_ids,
                            public_document_ids=public_document_ids,
                            project_id=project_id,
                            scoped=True,
                        )
                    )
                if row and kind == "work_relation":
                    if not self._in_scope(row, set(job_ids), set(public_document_ids), project_id):
                        reasons.append("scope_changed")
                    reasons.extend(self._validity(session, row))
                issues.extend(
                    {"id": identity, "kind": kind, "reason": reason}
                    for reason in sorted(set(reasons))
                )
        return issues

    def browse_for_research(
        self, terms, *, job_ids, public_document_ids, project_id=None, as_of=None
    ):
        """只返回有限派生线索和原文定位信息，不生成可直接提交的引用。"""
        from work_observer.retrieval.enhanced import normalized_time, validated_terms

        terms = validated_terms(terms)
        cutoff = normalized_time(as_of)
        jobs, public_ids = set(job_ids), set(public_document_ids)
        with Session(self.repository.engine) as session:
            definitions = {
                row.id: row
                for row in session.scalars(
                    select(DomainDefinition).where(DomainDefinition.status == "active")
                )
                if (not cutoff or row.reviewed_at <= cutoff)
                and not self.definition_validity(
                    row,
                    job_ids=jobs,
                    public_document_ids=public_ids,
                    project_id=project_id,
                    scoped=True,
                    at=cutoff,
                )
            }
            ranked, dependencies, source_runs = [], [], set()
            for row in session.scalars(select(WorkRelation).where(WorkRelation.status == "active")):
                if row.domain_id not in definitions or cutoff and row.reviewed_at > cutoff:
                    continue
                if not self._in_scope(row, jobs, public_ids, project_id) or self._validity(
                    session, row
                ):
                    continue
                definition = definitions[row.domain_id]
                text = " ".join(
                    (row.source_text, row.target_text, definition.name, definition.definition)
                )
                score = sum(text.casefold().count(term.casefold()) for term in terms)
                if score:
                    ranked.append((-score, row.id, row))
            ranked.sort(key=lambda item: item[:2])
            domain_ids, relations = [], []
            for _, _, row in ranked:
                if row.domain_id not in domain_ids:
                    if len(domain_ids) >= 6:
                        continue
                    domain_ids.append(row.domain_id)
                relations.append(row)
                if len(relations) == 10:
                    break
            for row in sorted(definitions.values(), key=lambda value: value.id):
                if len(domain_ids) == 6:
                    break
                if row.id not in domain_ids and any(
                    term.casefold()
                    in " ".join((row.name, row.definition, row.inclusion, row.exclusion)).casefold()
                    for term in terms
                ):
                    domain_ids.append(row.id)
            domain_output, relation_output = [], []
            for identity in domain_ids:
                row = definitions[identity]
                dependencies.append(
                    {
                        "kind": "domain_definition",
                        "id": row.id,
                        "version": row.version,
                        "status": row.status,
                        "reviewed_at": row.reviewed_at,
                    }
                )
                domain_output.append(
                    {
                        "id": row.id,
                        "version": row.version,
                        "name": row.name,
                        "definition": row.definition[:1200],
                        "inclusion": row.inclusion[:500],
                        "exclusion": row.exclusion[:500],
                        "derived": True,
                        "source_context": row.source_context or {},
                        "independent_source": False,
                    }
                )
            for row in relations:
                dependencies.append(
                    {
                        "kind": "work_relation",
                        "id": row.id,
                        "status": row.status,
                        "reviewed_at": row.reviewed_at,
                    }
                )
                if row.source_run_id:
                    source_runs.add(row.source_run_id)

                def references(items):
                    return [
                        {
                            key: item.get(key)
                            for key in (
                                "id",
                                "job_id",
                                "snapshot_id",
                                "public_document_id",
                                "start",
                                "end",
                            )
                        }
                        for item in items
                    ]

                relation_output.append(
                    {
                        "id": row.id,
                        "domain_id": row.domain_id,
                        "source_kind": row.source_kind,
                        "source_text": row.source_text,
                        "target_kind": row.target_kind,
                        "target_text": row.target_text,
                        "predicate": row.predicate,
                        "scope": row.scope,
                        "source_references": references(row.evidence),
                        "counter_references": references(row.counterevidence),
                        "derived": True,
                        "independent_source": False,
                    }
                )
            return {
                "domains": domain_output,
                "relations": relation_output,
                "dependencies": dependencies,
                "source_run_ids": sorted(source_runs),
                "matching_relations": len(ranked),
                "truncated": len(ranked) > len(relations),
                "limits": {"domains": 6, "relations": 10},
                "rules": (
                    "领域与关系是人审派生线索，不是独立来源；原文引用尚未读取，"
                    "必须用read_job或search_archived_sources重新取得当前研究的证据后才能提交判断。"
                ),
            }

    def correct_job_domains(self, job_id, domain_ids, reason):
        """显式人工纠正可采用新审核领域，空数组表示保留未分类。"""
        from work_observer.analysis.profiles import CORRECTION_PREFIX

        self.repository.job(job_id)
        if (
            not isinstance(domain_ids, list)
            or len(domain_ids) > 10
            or any(not isinstance(identity, str) for identity in domain_ids)
        ):
            raise ProbeError("INVALID_DOMAIN_CORRECTION")
        reason = _text(reason, 1200)
        from work_observer.analysis.profiles import ProfileService

        domains = {
            row["id"]: row
            for row in ProfileService(self.repository).classification_definitions(job_id)
        }
        if any(identity not in domains for identity in domain_ids):
            raise ProbeError("DOMAIN_CORRECTION_REQUIRES_ACTIVE_DEFINITION")
        content = CORRECTION_PREFIX + json.dumps(
            {
                "domains": list(
                    dict.fromkeys(domains[identity]["domain_key"] for identity in domain_ids)
                ),
                "definition_ids": list(dict.fromkeys(domain_ids)),
                "domain_labels": {
                    domains[identity]["domain_key"]: domains[identity]["name"]
                    for identity in domain_ids
                },
                "reason": reason,
            },
            ensure_ascii=False,
        )
        previous = next(
            (
                row
                for row in self.memory.list()
                if row["kind"] == "correction"
                and row["job_id"] == job_id
                and row["status"] == "active"
                and row["content"].startswith(CORRECTION_PREFIX)
            ),
            None,
        )
        return (
            self.memory.revise(previous["id"], content)
            if previous
            else self.memory.create("correction", content, job_id=job_id)
        )

    def collection(
        self,
        domain_id=None,
        *,
        filters=None,
        job_ids=None,
        as_of=None,
        limit=100,
        offset=0,
        project_id=None,
    ):
        """领域集合先逐一归类再分页，未知与人工纠正独立保留。"""
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise ProbeError("INVALID_DOMAIN_COLLECTION_PAGE")
        from work_observer.analysis.profiles import CORRECTION_PREFIX

        records, actual_filters, cutoff = RetrievalService(self.repository)._records(
            filters, job_ids, as_of
        )
        definitions = {item["id"]: item for item in self.list_domains(include_history=True)}
        if domain_id and domain_id not in definitions:
            raise ProbeError("DOMAIN_NOT_FOUND")
        relations = [
            row
            for row in self.list_relations(project_id=project_id)
            if row["status"] == "active"
            and not row["stale"]
            and (not cutoff or row["reviewed_at"] <= cutoff)
        ]
        counts = {key: 0 for key in ("matched", "unknown", "excluded")}
        output = []
        for item in records:
            if item["state"] == "excluded":
                continue
            identity = item["job_id"]
            assigned, classification = [], "unknown"
            for relation in relations:
                if identity in relation["scope"].get("job_ids", []):
                    assigned.append(relation["domain_id"])
                    classification = "reviewed_relation"
            corrected_keys, correction_id, corrected_definitions = None, None, None
            # 历史截止不能把今天的纠正投影成过去已知的分类。
            for memory in self.memory.recall("领域", [identity], project_id=project_id, at=cutoff):
                if memory["kind"] == "correction" and memory["content"].startswith(
                    CORRECTION_PREFIX
                ):
                    try:
                        correction = json.loads(memory["content"][len(CORRECTION_PREFIX) :])
                        corrected_keys = correction["domains"]
                        corrected_definitions = correction.get("definition_ids")
                        correction_id = memory["id"]
                    except (ValueError, KeyError, TypeError):
                        continue
                    break
            if corrected_keys is not None:
                assigned = (
                    corrected_definitions
                    if corrected_definitions is not None
                    else [
                        key
                        for key, value in definitions.items()
                        if value["domain_key"] in corrected_keys and value["status"] == "active"
                    ]
                )
                classification = "user_corrected"
            if domain_id:
                wanted_key = definitions[domain_id]["domain_key"]
                matches = (
                    domain_id in assigned
                    or corrected_definitions is None
                    and corrected_keys is not None
                    and wanted_key in corrected_keys
                )
                state = (
                    "matched"
                    if matches
                    else "excluded"
                    if corrected_keys is not None or assigned
                    else "unknown"
                )
                if (
                    corrected_definitions is not None
                    and not matches
                    and wanted_key in corrected_keys
                ):
                    state = "unknown"
            else:
                state = "matched" if assigned or corrected_keys else "unknown"
            if item["state"] == "unknown" and state == "matched":
                state = "unknown"
            counts[state] += 1
            output.append(
                {
                    "job_id": identity,
                    "title": item["record"].get("title"),
                    "company": item["record"].get("company_name_raw"),
                    "domain_ids": sorted(set(assigned)),
                    "corrected_domain_keys": corrected_keys,
                    "correction_id": correction_id,
                    "correction_definition_ids": corrected_definitions,
                    "classification": classification,
                    "state": state,
                    "has_detail": bool(item["record"].get("description_text")),
                }
            )
        return {
            "domain": definitions.get(domain_id),
            "counts": {"scope_total": len(output), **counts},
            "jobs": output[offset : offset + limit],
            "offset": offset,
            "limit": limit,
            "truncated": offset + limit < len(output),
            "as_of": cutoff,
            "filters": actual_filters.model_dump(mode="json"),
            "rules": (
                "全范围先计数再分页；领域定义与关系版本明确；人工单岗纠正优先，"
                "未知/未分类不强制分配。历史截止不代表可重建当时所有人审分类。"
            ),
        }
