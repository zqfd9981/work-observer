"""业务记忆：显式意图和纠正有版本，研究知识先审核且始终回链原文。

这不是额外来源库。knowledge 中的内容是派生判断，引用仍指向岗位原文；
程序只能检查引用完整性，不能自动保证原文在语义上支持某个判断。
"""

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.connectors.public_models import PublicDocument
from work_observer.storage.models import (
    Job,
    JobAnalysis,
    JobObservation,
    JobSnapshot,
    MemoryEvent,
    MemoryRecord,
    SourceDocument,
)

KINDS = {"preference", "correction", "knowledge", "hypothesis", "method"}
REVIEWED_KINDS = {"knowledge", "hypothesis", "method"}
CURRENT = {"active", "candidate", "conflict"}


def _timestamp(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        raise ProbeError("INVALID_MEMORY_TIME") from None


def _valid_at(row, stamp):
    return (not row.valid_from or row.valid_from <= stamp) and (
        not row.valid_until or stamp < row.valid_until
    )


def _overlapping(left_from, left_until, right_from, right_until):
    return not (
        left_until
        and right_from
        and left_until <= right_from
        or right_until
        and left_from
        and right_until <= left_from
    )


def _content(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ProbeError("INVALID_MEMORY_CONTENT")
    return value.strip()


def _tokens(value):
    """英文术语与中文连续二字词；用于有界召回而非推断事实。"""
    value = value.casefold()
    result = set(re.findall(r"[a-z0-9_+#.-]{2,}", value))
    for phrase in re.findall(r"[\u4e00-\u9fff]+", value):
        result.update(phrase[i : i + 2] for i in range(len(phrase) - 1))
    return result


def _record(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "root_id",
            "previous_id",
            "version",
            "kind",
            "content",
            "status",
            "job_id",
            "evidence",
            "source_run_id",
            "created_at",
            "updated_at",
            "scope",
            "project_id",
            "subject",
            "valid_from",
            "valid_until",
            "origin",
            "conflict_ids",
        )
    }


class MemoryService:
    def __init__(self, repository):
        self.repository = repository

    def _get(self, session, identity):
        row = session.get(MemoryRecord, identity)
        if row is None:
            raise ProbeError("MEMORY_NOT_FOUND")
        return row

    def _validate_evidence(self, session, evidence, job_id=None):
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 10:
            raise ProbeError("MEMORY_EVIDENCE_REQUIRED")
        canonical = []
        for item in evidence:
            if not isinstance(item, dict):
                raise ProbeError("INVALID_MEMORY_EVIDENCE")
            if item.get("public_document_id"):
                if job_id:
                    raise ProbeError("MEMORY_SCOPE_VIOLATION")
                document = session.get(PublicDocument, item["public_document_id"])
                start, end = item.get("start"), item.get("end")
                if (
                    not document
                    or type(start) is not int
                    or type(end) is not int
                    or not 0 <= start < end <= len(document.text)
                    or end - start > 700
                    or item.get("quote") != document.text[start:end]
                    or item.get("id") != f"publicdoc:{document.id}:{start}:{end}"
                ):
                    raise ProbeError("INVALID_MEMORY_EVIDENCE")
                try:
                    metadata = PublicDocumentService._metadata(document)
                except OSError:
                    raise ProbeError("MEMORY_SOURCE_INTEGRITY_FAILED") from None
                if metadata["integrity"] != "verified":
                    raise ProbeError("MEMORY_SOURCE_INTEGRITY_FAILED")
                if metadata["content_state"] != "body_text":
                    raise ProbeError("INVALID_MEMORY_EVIDENCE")
                canonical.append(
                    {
                        "id": item["id"],
                        "public_document_id": document.id,
                        "evidence_kind": metadata["evidence_kind"],
                        "job_id": None,
                        "snapshot_id": None,
                        "document_id": None,
                        "document_sha256": document.sha256,
                        "content_sha256": document.text_sha256,
                        "quote": document.text[start:end],
                        "start": start,
                        "end": end,
                        "full_text_length": len(document.text),
                        "title": document.title,
                        "publisher": document.publisher,
                        "url": document.final_url,
                        "source": metadata["source"],
                        "response_origin": metadata["response_origin"],
                        "observed_at": document.observed_at,
                        "source_published_at": document.source_published_at,
                    }
                )
                continue
            snapshot = session.get(JobSnapshot, item.get("snapshot_id"))
            document = session.get(SourceDocument, item.get("document_id"))
            if not snapshot or not document or snapshot.kind != "detail":
                raise ProbeError("INVALID_MEMORY_EVIDENCE")
            if item.get("job_id") != snapshot.job_id or (job_id and job_id != snapshot.job_id):
                raise ProbeError("MEMORY_SCOPE_VIOLATION")
            observation = session.scalar(
                select(JobObservation).where(
                    JobObservation.snapshot_id == snapshot.id,
                    JobObservation.document_id == document.id,
                    JobObservation.kind == "detail",
                )
            )
            start, end = item.get("start"), item.get("end")
            text = snapshot.payload.get("description", "")
            if (
                observation is None
                or type(start) is not int
                or type(end) is not int
                or not 0 <= start < end <= len(text)
                or end - start > 700
                or text[start:end] != item.get("quote")
                or item.get("id") != f"{snapshot.id}:{start}:{end}"
            ):
                raise ProbeError("INVALID_MEMORY_EVIDENCE")
            path = Path(document.path)
            try:
                intact = path.is_file() and (
                    hashlib.sha256(path.read_bytes()).hexdigest() == document.sha256
                )
            except OSError:
                intact = False
            if not intact:
                raise ProbeError("MEMORY_SOURCE_INTEGRITY_FAILED")
            job = session.get(Job, snapshot.job_id)
            canonical.append(
                {
                    "id": item["id"],
                    "job_id": snapshot.job_id,
                    "snapshot_id": snapshot.id,
                    "document_id": document.id,
                    "document_sha256": document.sha256,
                    "content_sha256": snapshot.content_sha256,
                    "start": start,
                    "end": end,
                    "full_text_length": len(text),
                    "quote": text[start:end],
                    "title": snapshot.payload.get("title") or job.title,
                    "company": snapshot.payload.get("company") or job.company_name_raw,
                    "source": job.source,
                    "response_origin": document.response_origin,
                    "observed_at": observation.observed_at,
                    "source_published_at": snapshot.payload.get("source_published_at"),
                }
            )
        return list({item["id"]: item for item in canonical}.values())

    def _event(self, session, row, action):
        session.add(MemoryEvent(id=uuid4().hex, memory_id=row.id, action=action, created_at=now()))

    def list(self, include_history=False):
        statement = select(MemoryRecord)
        if not include_history:
            statement = statement.where(MemoryRecord.status.in_(CURRENT))
        with Session(self.repository.engine) as session:
            return [
                _record(row)
                for row in session.scalars(
                    statement.order_by(MemoryRecord.created_at.desc(), MemoryRecord.id).limit(500)
                )
            ]

    def create(
        self,
        kind,
        content,
        *,
        job_id=None,
        evidence=None,
        source_run_id=None,
        scope=None,
        project_id=None,
        subject=None,
        valid_from=None,
        valid_until=None,
        origin="user",
    ):
        if kind not in KINDS:
            raise ProbeError("INVALID_MEMORY_KIND")
        content = _content(content)
        scope = scope or ("job" if job_id else "project" if project_id else "global")
        if (
            scope not in {"global", "project", "job"}
            or (scope == "job") != bool(job_id)
            or (scope == "project") != bool(project_id)
            or origin not in {"user", "agent"}
            or (
                project_id is not None
                and (
                    not isinstance(project_id, str) or not re.fullmatch(r"[a-f0-9]{32}", project_id)
                )
            )
        ):
            raise ProbeError("INVALID_MEMORY_SCOPE")
        if subject is not None:
            if not isinstance(subject, str) or not subject.strip() or len(subject) > 200:
                raise ProbeError("INVALID_MEMORY_SUBJECT")
            subject = subject.strip().casefold()
        valid_from, valid_until = _timestamp(valid_from), _timestamp(valid_until)
        if valid_from and valid_until and valid_from >= valid_until:
            raise ProbeError("INVALID_MEMORY_TIME")
        if source_run_id is not None and (
            not isinstance(source_run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", source_run_id)
        ):
            raise ProbeError("INVALID_RESEARCH_ID")
        with Session(self.repository.engine) as session, session.begin():
            if job_id and session.get(Job, job_id) is None:
                raise ProbeError("JOB_NOT_FOUND")
            verified = (
                self._validate_evidence(session, evidence, job_id)
                if (kind == "knowledge" or evidence)
                else []
            )
            # 同一结果的同一候选重复点击不会制造独立知识。
            if kind in REVIEWED_KINDS and source_run_id:
                previous = session.scalars(
                    select(MemoryRecord).where(
                        MemoryRecord.kind == kind,
                        MemoryRecord.source_run_id == source_run_id,
                        MemoryRecord.content == content,
                    )
                ).all()
                for row in previous:
                    if (
                        row.evidence == verified
                        and row.job_id == job_id
                        and row.project_id == project_id
                        and row.subject == subject
                        and row.valid_from == valid_from
                        and row.valid_until == valid_until
                    ):
                        return _record(row)
            identity, stamp = uuid4().hex, now()
            conflicts = []
            if subject:
                peers = session.scalars(
                    select(MemoryRecord).where(
                        MemoryRecord.subject == subject,
                        MemoryRecord.kind == kind,
                        MemoryRecord.scope == scope,
                        MemoryRecord.project_id == project_id,
                        MemoryRecord.job_id == job_id,
                        MemoryRecord.status.in_(CURRENT),
                    )
                ).all()
                for peer in peers:
                    # 不相交的有效期可并存；同主体不同内容须由用户选择。
                    overlaps = _overlapping(
                        valid_from, valid_until, peer.valid_from, peer.valid_until
                    )
                    if peer.content != content and overlaps:
                        conflicts.append(peer)
                if conflicts:
                    for peer in conflicts:
                        peer.status, peer.updated_at = "conflict", stamp
                        peer.conflict_ids = sorted(set(peer.conflict_ids or []) | {identity})
                        self._event(session, peer, "conflict_detected")
            row = MemoryRecord(
                id=identity,
                root_id=identity,
                previous_id=None,
                version=1,
                kind=kind,
                content=content,
                status="conflict"
                if conflicts
                else ("candidate" if kind in REVIEWED_KINDS or origin == "agent" else "active"),
                job_id=job_id,
                evidence=verified,
                source_run_id=source_run_id,
                created_at=stamp,
                updated_at=stamp,
                scope=scope,
                project_id=project_id,
                subject=subject,
                valid_from=valid_from,
                valid_until=valid_until,
                origin=origin,
                conflict_ids=[peer.id for peer in conflicts],
            )
            session.add(row)
            session.flush()
            self._event(session, row, "created")
            return _record(row)

    def revise(self, identity, content):
        content = _content(content)
        with Session(self.repository.engine) as session, session.begin():
            old = self._get(session, identity)
            if old.status not in {"active", "candidate"}:
                raise ProbeError("MEMORY_VERSION_NOT_CURRENT")
            if old.content == content:
                return _record(old)
            identity, stamp = uuid4().hex, now()
            # 条件写入防止两个窗口同时用旧版本覆盖各自修改。
            changed = session.execute(
                update(MemoryRecord)
                .where(
                    MemoryRecord.id == old.id,
                    MemoryRecord.status.in_({"active", "candidate"}),
                )
                .values(status="superseded", updated_at=stamp)
            )
            if changed.rowcount != 1:
                raise ProbeError("MEMORY_VERSION_NOT_CURRENT")
            row = MemoryRecord(
                id=identity,
                root_id=old.root_id,
                previous_id=old.id,
                version=old.version + 1,
                kind=old.kind,
                content=content,
                status="candidate"
                if old.kind in REVIEWED_KINDS or old.origin == "agent"
                else "active",
                job_id=old.job_id,
                evidence=old.evidence,
                source_run_id=old.source_run_id,
                created_at=stamp,
                updated_at=stamp,
                scope=old.scope,
                project_id=old.project_id,
                subject=old.subject,
                valid_from=old.valid_from,
                valid_until=old.valid_until,
                origin=old.origin,
                conflict_ids=list(old.conflict_ids or []),
            )
            session.add(row)
            session.flush()
            self._event(session, old, "superseded")
            self._event(session, row, "revised")
            return _record(row)

    def withdraw(self, identity):
        with Session(self.repository.engine) as session, session.begin():
            row = self._get(session, identity)
            if row.status == "withdrawn":
                return _record(row)
            if row.status not in CURRENT:
                raise ProbeError("MEMORY_VERSION_NOT_CURRENT")
            row.status, row.updated_at = "withdrawn", now()
            self._event(session, row, "withdrawn")
            return _record(row)

    def forget(self, identity):
        """忘记整条个人记忆版本链，清理可重建画像；原始资料不动。"""
        with Session(self.repository.engine) as session, session.begin():
            requested = self._get(session, identity)
            if requested.kind not in {"preference", "correction"}:
                raise ProbeError("MEMORY_FORGET_PERSONAL_ONLY")
            rows = session.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.root_id == requested.root_id)
                .order_by(MemoryRecord.version)
            ).all()
            affected = self._forget_rows(session, rows)
            return {
                "forgotten_memory_ids": [row.id for row in rows],
                "deleted_profile_ids": affected,
                "scope": "当前业务库中的个人记忆及可重建画像；原始岗位、独立导出副本与备份不变。",
            }

    def forget_project(self, project_id):
        """清除指定项目的全部类型与版本；保留不可回放的最少审核元数据。"""
        if not isinstance(project_id, str) or not re.fullmatch(r"[a-f0-9]{32}", project_id):
            raise ProbeError("INVALID_PROJECT_ID")
        with Session(self.repository.engine) as session, session.begin():
            rows = session.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.scope == "project", MemoryRecord.project_id == project_id)
                .order_by(MemoryRecord.root_id, MemoryRecord.version)
            ).all()
            affected = self._forget_rows(session, rows)
            return {
                "forgotten_memory_ids": [row.id for row in rows],
                "deleted_profile_ids": affected,
            }

    def _forget_rows(self, session, rows):
        identities = {row.id for row in rows}
        for row in rows:
            if row.status != "forgotten":
                row.content, row.status, row.updated_at = "[已忘记]", "forgotten", now()
                row.evidence = []
                row.subject = None
                self._event(session, row, "forgotten")
        # 画像是从来源和记忆重建的派生结果，不能留着可删除的个人上下文。
        profiles = session.execute(select(JobAnalysis.id, JobAnalysis.memory_versions)).all()
        affected = [
            profile_id
            for profile_id, versions in profiles
            if any(
                isinstance(version, dict) and version.get("id") in identities
                for version in (versions or [])
            )
        ]
        if affected:
            session.execute(delete(JobAnalysis).where(JobAnalysis.id.in_(affected)))
        return affected

    def invalidate_research(self, run_ids):
        """清理被遗忘研究派生的知识摘要，阻断其再次进入其他研究。"""
        run_ids = list(dict.fromkeys(run_ids))
        if any(
            not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity)
            for identity in run_ids
        ):
            raise ProbeError("INVALID_RESEARCH_ID")
        with Session(self.repository.engine) as session, session.begin():
            roots = session.scalars(
                select(MemoryRecord.root_id).where(MemoryRecord.source_run_id.in_(run_ids))
            ).all()
            rows = session.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.root_id.in_(set(roots)))
                .order_by(MemoryRecord.root_id, MemoryRecord.version)
            ).all()
            return {
                "affected_memory_ids": [row.id for row in rows],
                "deleted_profile_ids": self._forget_rows(session, rows),
            }

    def activate(self, identity):
        with Session(self.repository.engine) as session, session.begin():
            row = self._get(session, identity)
            if row.status not in {"candidate", "active"} or (
                row.kind not in REVIEWED_KINDS and row.origin != "agent"
            ):
                raise ProbeError("MEMORY_NOT_A_CANDIDATE")
            if row.kind == "knowledge" or row.evidence:
                self._validate_evidence(session, row.evidence, row.job_id)
            if row.source_run_id:
                from work_observer.memory.dependencies import DependencyAudit

                if not DependencyAudit(self.repository).memory(row.id, ignore_status=True)[
                    "eligible"
                ]:
                    raise ProbeError("MEMORY_DERIVED_DEPENDENCY_STALE")
            if row.status != "active":
                row.status, row.updated_at = "active", now()
                self._event(session, row, "accepted_by_user")
            return _record(row)

    def resolve(self, identity, action):
        """用户显式选择冲突项；被否决项不会作为旧值自动复活。"""
        if action not in {"accept", "reject"}:
            raise ProbeError("INVALID_MEMORY_RESOLUTION")
        with Session(self.repository.engine) as session, session.begin():
            row = self._get(session, identity)
            if row.status != "conflict":
                raise ProbeError("MEMORY_NOT_CONFLICTED")
            stamp = now()
            if action == "accept":
                if row.kind == "knowledge" or row.evidence:
                    self._validate_evidence(session, row.evidence, row.job_id)
                if row.source_run_id:
                    from work_observer.memory.dependencies import DependencyAudit

                    if not DependencyAudit(self.repository).memory(row.id, ignore_status=True)[
                        "eligible"
                    ]:
                        raise ProbeError("MEMORY_DERIVED_DEPENDENCY_STALE")
                # 遍历整组，避免 A-B、B-C 冲突只处理直接邻居。
                pending, visited = [row.id], set()
                while pending:
                    current = self._get(session, pending.pop())
                    if current.id in visited:
                        continue
                    visited.add(current.id)
                    pending.extend(current.conflict_ids or [])
                    if (
                        current.id != row.id
                        and current.status == "conflict"
                        and _overlapping(
                            row.valid_from,
                            row.valid_until,
                            current.valid_from,
                            current.valid_until,
                        )
                    ):
                        current.status, current.updated_at = "withdrawn", stamp
                        self._event(session, current, "conflict_rejected_by_user")
                row.status = "active"
            else:
                row.status = "withdrawn"
            row.updated_at = stamp
            self._event(session, row, f"conflict_{action}_by_user")
            return _record(row)

    def conflicts(self, *, project_id=None):
        return [
            item
            for item in self.list()
            if item["status"] == "conflict"
            and (item["scope"] != "project" or item["project_id"] == project_id)
        ]

    def validity(self, identity, at=None):
        """当前资格和派生依赖；不修改历史采纳状态。"""
        audited = self.audit(identity, at=at)
        reasons = list(
            dict.fromkeys(
                item["reason"]
                if item["kind"] == "memory" and item["id"] == identity
                else "derived_dependency_stale"
                for item in audited["issues"]
            )
        )
        return {
            "id": identity,
            "eligible": audited["eligible"],
            "reasons": reasons,
            "dependency_issues": audited["issues"],
            "checked_at": audited["checked_at"],
            "is_source_evidence": False,
        }

    def audit(self, identity, *, version=None, job_ids=None, project_id=None, at=None):
        from work_observer.memory.dependencies import DependencyAudit

        return DependencyAudit(self.repository, at=at).memory(
            identity,
            version=version,
            job_ids=job_ids,
            project_id=project_id,
        )

    def derived_eligibility(
        self, source_run_id, *, job_ids=None, project_id=None, at=None, evidence_ids=None
    ):
        from work_observer.memory.dependencies import DependencyAudit

        return DependencyAudit(self.repository, at=at).run(
            source_run_id,
            job_ids=job_ids,
            project_id=project_id,
            evidence_ids=evidence_ids,
        )

    def recall(self, question, job_ids, project_id=None, at=None, kinds=None, excluded_runs=()):
        job_ids = set(job_ids or [])
        kinds = set(kinds) if kinds is not None else KINDS
        if not kinds.issubset(KINDS):
            raise ProbeError("INVALID_MEMORY_KIND")
        stamp = _timestamp(at) or now()
        query = _tokens(question)
        selected = []
        from work_observer.memory.dependencies import DependencyAudit

        auditor = DependencyAudit(self.repository, at=stamp, excluded_runs=excluded_runs)
        with Session(self.repository.engine) as session:
            rows = session.scalars(
                select(MemoryRecord)
                .where(
                    MemoryRecord.status == "active",
                    MemoryRecord.kind.in_(kinds),
                )
                .order_by(MemoryRecord.created_at.desc(), MemoryRecord.id)
                .limit(500)
            )
            for row in rows:
                if row.scope == "project" and row.project_id != project_id:
                    continue
                if row.job_id and row.job_id not in job_ids:
                    continue
                if not auditor.memory(row.id, job_ids=job_ids, project_id=project_id)["eligible"]:
                    continue
                overlap = len(query & _tokens(row.content))
                if row.kind != "preference" and not row.job_id and not overlap:
                    continue
                priority = {
                    "correction": 4,
                    "preference": 3,
                    "knowledge": 2,
                    "hypothesis": 1,
                    "method": 1,
                }[row.kind]
                selected.append((priority, overlap, row.created_at, _record(row)))
        selected.sort(key=lambda item: item[:3], reverse=True)
        return [item[3] for item in selected[:8]]

    @staticmethod
    def _sources_current(session, evidence):
        for item in evidence:
            if item.get("public_document_id"):
                document = session.get(PublicDocument, item["public_document_id"])
                newer = session.scalar(
                    select(PublicDocument)
                    .where(
                        PublicDocument.final_url == document.final_url,
                        PublicDocument.observed_at > document.observed_at,
                    )
                    .order_by(PublicDocument.observed_at.desc(), PublicDocument.id.desc())
                    .limit(1)
                )
                if newer and newer.text_sha256 != document.text_sha256:
                    return False
            elif session.get(Job, item["job_id"]).description_text != session.get(
                JobSnapshot, item["snapshot_id"]
            ).payload.get("description"):
                return False
        return True
