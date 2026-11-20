"""同岗位详情版本的确定性比较，观察历史与原始证据分开呈现。"""

from difflib import SequenceMatcher, unified_diff

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.storage.models import (
    CollectionRun,
    Job,
    JobObservation,
    JobSnapshot,
    SourceDocument,
    Watchset,
)


class HistoryService:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _rows(session, job_id, observed_before=None):
        if not session.get(Job, job_id):
            raise ProbeError("JOB_NOT_FOUND")
        statement = (
            select(JobObservation, JobSnapshot, SourceDocument, CollectionRun, Watchset)
            .join(JobSnapshot, JobObservation.snapshot_id == JobSnapshot.id)
            .join(SourceDocument, JobObservation.document_id == SourceDocument.id)
            .join(CollectionRun, JobObservation.collection_run_id == CollectionRun.id)
            .join(Watchset, CollectionRun.watchset_id == Watchset.id)
            .where(
                JobObservation.job_id == job_id,
                JobObservation.kind == "detail",
                JobSnapshot.kind == "detail",
            )
            .order_by(
                JobObservation.observed_at,
                JobObservation.processed_at,
                JobObservation.id,
            )
        )
        if observed_before is not None:
            # 后导入的回放即便有较早来源时间，也不能进入已经启动的研究。
            statement = statement.where(
                JobObservation.observed_at <= observed_before,
                JobObservation.processed_at <= observed_before,
            )
        return session.execute(statement).all()

    @staticmethod
    def _observation(row):
        observation, snapshot, document, run, watchset = row
        return {
            "observation_id": observation.id,
            "snapshot_id": snapshot.id,
            "document_id": document.id,
            "content_sha256": snapshot.content_sha256,
            "observed_at": observation.observed_at,
            "processed_at": observation.processed_at,
            "response_origin": document.response_origin,
            "data_kind": document.provenance.get("data_kind", "unspecified"),
            "mode": run.mode,
            "watchset": {"name": watchset.name, "version": watchset.version},
        }

    def list_versions(self, job_id, *, observed_before=None):
        with Session(self.repository.engine) as session:
            rows = self._rows(session, job_id, observed_before)
            return {
                "job_id": job_id,
                "distinct_detail_versions": len({row[1].id for row in rows}),
                "observations": [self._observation(row) for row in rows],
                "note": "只列已保存的详情观察；相同版本再次出现不新增版本，A→B→A的观察顺序保留。",
            }

    def compare(
        self,
        job_id,
        before_snapshot_id=None,
        after_snapshot_id=None,
        *,
        observed_before=None,
        before_cutoff=None,
    ):
        """比较所选版本；面板对照可分别限定两侧观察时间，避免重现版本漂移到后次观察。"""
        with Session(self.repository.engine) as session:
            rows = self._rows(session, job_id, observed_before)
            history = [self._observation(row) for row in rows]
            after = next(
                (
                    row
                    for row in reversed(rows)
                    if after_snapshot_id is None or row[1].id == after_snapshot_id
                ),
                None,
            )
            if after_snapshot_id is not None and after is None:
                raise ProbeError("HISTORY_SNAPSHOT_NOT_FOUND")
            after_index = rows.index(after) if after else -1
            before = next(
                (
                    row
                    for row in reversed(rows[:after_index])
                    if row[1].id != after[1].id
                    and (before_snapshot_id is None or row[1].id == before_snapshot_id)
                    and (
                        before_cutoff is None
                        or row[0].observed_at <= before_cutoff
                        and row[0].processed_at <= before_cutoff
                    )
                ),
                None,
            )
            if before_snapshot_id is not None and before is None:
                if before_snapshot_id not in {row[1].id for row in rows}:
                    raise ProbeError("HISTORY_SNAPSHOT_NOT_FOUND")
                raise ProbeError("HISTORY_VERSION_ORDER_INVALID")
            if before is None or after is None:
                return {
                    "status": "insufficient_history",
                    "job_id": job_id,
                    "observations": history,
                    "evidence": [],
                    "changes": [],
                    "gaps": [
                        "缺少两个按观察顺序可比较的不同详情版本；不能据此判断职责变化或市场趋势。"
                    ],
                }
            old, new = before[1].payload, after[1].payload
            a, b = old.get("description", ""), new.get("description", "")
            if not isinstance(a, str) or not isinstance(b, str) or not a or not b:
                raise ProbeError("HISTORY_DETAIL_BODY_MISSING")
            changes = [
                {"field": key, "before": old.get(key), "after": new.get(key)}
                for key in sorted(set(old) | set(new))
                if old.get(key) != new.get(key)
            ]
            positions = [set(), set()]
            for tag, a_start, a_end, b_start, b_end in SequenceMatcher(None, a, b).get_opcodes():
                if tag != "equal":
                    positions[0].update(range(a_start // 700, max(a_start, a_end - 1) // 700 + 1))
                    positions[1].update(range(b_start // 700, max(b_start, b_end - 1) // 700 + 1))
            job = session.get(Job, job_id)
            evidence = self._evidence(job, before, positions[0]) + self._evidence(
                job, after, positions[1]
            )
            return {
                "status": "compared",
                "job_id": job_id,
                "before": self._observation(before),
                "after": self._observation(after),
                "observations": history,
                "changes": changes,
                "description_diff": "\n".join(
                    unified_diff(
                        a.splitlines(),
                        b.splitlines(),
                        fromfile="较早详情",
                        tofile="较晚详情",
                        lineterm="",
                    )
                )[:16000],
                "evidence": evidence,
                "gaps": [
                    "差异仅表示已保存详情版本的来源内容变化，不代表全市场趋势或准确的网站更新时间。",
                    "manual 为人工维护，replay 为历史回放；来源没有提供的发布时间仍未知。",
                ],
            }

    @staticmethod
    def _evidence(job, row, positions):
        observation, snapshot, document, run, watchset = row
        text = snapshot.payload["description"]
        chunks = []
        for index in sorted(positions or {0})[:8]:
            start = min(index * 700, max(0, len(text) - 1))
            quote = text[start : start + 700]
            chunks.append(
                {
                    "id": f"{snapshot.id}:{start}:{start + len(quote)}",
                    "job_id": job.id,
                    "title": snapshot.payload.get("title") or job.title,
                    "company": snapshot.payload.get("company") or job.company_name_raw,
                    "snapshot_id": snapshot.id,
                    "content_sha256": snapshot.content_sha256,
                    "document_id": document.id,
                    "document_sha256": document.sha256,
                    "quote": quote,
                    "start": start,
                    "end": start + len(quote),
                    "full_text_length": len(text),
                    "source": job.source,
                    "response_origin": document.response_origin,
                    "data_kind": document.provenance.get("data_kind", "unspecified"),
                    "transport": document.transport,
                    "mode": run.mode,
                    "observed_at": observation.observed_at,
                    "processed_at": observation.processed_at,
                    "source_fetched_at": document.source_fetched_at,
                    "source_published_at": snapshot.payload.get("source_published_at"),
                    "watchset": {"name": watchset.name, "version": watchset.version},
                }
            )
        return chunks
