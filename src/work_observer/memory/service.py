"""业务记忆：显式意图和纠正有版本，研究知识先审核且始终回链原文。

这不是额外来源库。knowledge 中的内容是派生判断，引用仍指向岗位原文；
程序只能检查引用完整性，不能自动保证原文在语义上支持某个判断。
"""

import hashlib
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.storage.models import (
    Job,
    JobAnalysis,
    JobObservation,
    JobSnapshot,
    MemoryEvent,
    MemoryRecord,
    SourceDocument,
)

KINDS = {"preference", "correction", "knowledge"}
CURRENT = {"active", "candidate"}


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
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != document.sha256
            ):
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

    def create(self, kind, content, *, job_id=None, evidence=None, source_run_id=None):
        if kind not in KINDS:
            raise ProbeError("INVALID_MEMORY_KIND")
        content = _content(content)
        if source_run_id is not None and (
            not isinstance(source_run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", source_run_id)
        ):
            raise ProbeError("INVALID_RESEARCH_ID")
        with Session(self.repository.engine) as session, session.begin():
            if job_id and session.get(Job, job_id) is None:
                raise ProbeError("JOB_NOT_FOUND")
            verified = (
                self._validate_evidence(session, evidence, job_id) if kind == "knowledge" else []
            )
            # 同一结果的同一候选重复点击不会制造独立知识。
            if kind == "knowledge" and source_run_id:
                previous = session.scalars(
                    select(MemoryRecord).where(
                        MemoryRecord.kind == kind,
                        MemoryRecord.source_run_id == source_run_id,
                        MemoryRecord.content == content,
                        MemoryRecord.status.in_(CURRENT),
                    )
                ).all()
                for row in previous:
                    if row.evidence == verified and row.job_id == job_id:
                        return _record(row)
            identity, stamp = uuid4().hex, now()
            row = MemoryRecord(
                id=identity,
                root_id=identity,
                previous_id=None,
                version=1,
                kind=kind,
                content=content,
                status="candidate" if kind == "knowledge" else "active",
                job_id=job_id,
                evidence=verified,
                source_run_id=source_run_id,
                created_at=stamp,
                updated_at=stamp,
            )
            session.add(row)
            session.flush()
            self._event(session, row, "created")
            return _record(row)

    def revise(self, identity, content):
        content = _content(content)
        with Session(self.repository.engine) as session, session.begin():
            old = self._get(session, identity)
            if old.status not in CURRENT:
                raise ProbeError("MEMORY_VERSION_NOT_CURRENT")
            if old.content == content:
                return _record(old)
            identity, stamp = uuid4().hex, now()
            # 条件写入防止两个窗口同时用旧版本覆盖各自修改。
            changed = session.execute(
                update(MemoryRecord)
                .where(
                    MemoryRecord.id == old.id,
                    MemoryRecord.status.in_(CURRENT),
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
                status="candidate" if old.kind == "knowledge" else "active",
                job_id=old.job_id,
                evidence=old.evidence,
                source_run_id=old.source_run_id,
                created_at=stamp,
                updated_at=stamp,
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

    def _forget_rows(self, session, rows):
        identities = {row.id for row in rows}
        for row in rows:
            if row.status != "forgotten":
                row.content, row.status, row.updated_at = "[已忘记]", "forgotten", now()
                row.evidence = []
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
                select(MemoryRecord.root_id).where(
                    MemoryRecord.kind == "knowledge", MemoryRecord.source_run_id.in_(run_ids)
                )
            ).all()
            rows = session.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.kind == "knowledge", MemoryRecord.root_id.in_(set(roots)))
                .order_by(MemoryRecord.root_id, MemoryRecord.version)
            ).all()
            return {
                "affected_memory_ids": [row.id for row in rows],
                "deleted_profile_ids": self._forget_rows(session, rows),
            }

    def activate(self, identity):
        with Session(self.repository.engine) as session, session.begin():
            row = self._get(session, identity)
            if row.kind != "knowledge" or row.status not in {"candidate", "active"}:
                raise ProbeError("MEMORY_NOT_A_CANDIDATE")
            self._validate_evidence(session, row.evidence, row.job_id)
            if row.status != "active":
                row.status, row.updated_at = "active", now()
                self._event(session, row, "accepted_by_user")
            return _record(row)

    def recall(self, question, job_ids):
        job_ids = set(job_ids or [])
        query = _tokens(question)
        selected = []
        with Session(self.repository.engine) as session:
            rows = session.scalars(
                select(MemoryRecord)
                .where(
                    MemoryRecord.status == "active",
                )
                .order_by(MemoryRecord.created_at.desc(), MemoryRecord.id)
                .limit(500)
            )
            for row in rows:
                if row.job_id and row.job_id not in job_ids:
                    continue
                overlap = len(query & _tokens(row.content))
                if row.kind == "knowledge":
                    # 旧版本知识保留历史，但不默认为新正文的有效判断。
                    if any(item["job_id"] not in job_ids for item in row.evidence):
                        continue
                    try:
                        verified = self._validate_evidence(session, row.evidence, row.job_id)
                    except ProbeError:
                        continue
                    if any(
                        session.get(Job, item["job_id"]).description_text
                        != session.get(JobSnapshot, item["snapshot_id"]).payload.get("description")
                        for item in verified
                    ):
                        continue
                if row.kind != "preference" and not row.job_id and not overlap:
                    continue
                priority = {"correction": 3, "preference": 2, "knowledge": 1}[row.kind]
                selected.append((priority, overlap, row.created_at, _record(row)))
        selected.sort(key=lambda item: item[:3], reverse=True)
        return [item[3] for item in selected[:8]]
