"""本地研究/采集结果与待验证问题收件箱；只回链结果，不复制来源正文。"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.storage.models import CollectionRun, JobObservation, Watchset
from work_observer.storage.operations_models import Notification

KINDS = {"research", "collection", "followup", "hypothesis", "attention", "system"}


def _value(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "kind",
            "title",
            "body",
            "state",
            "related_id",
            "dedupe_key",
            "details",
            "created_at",
            "read_at",
            "resolved_at",
        )
    }


class InboxService:
    def __init__(self, repository):
        self.repository = repository

    def list(self, unread=False):
        statement = select(Notification)
        if unread:
            statement = statement.where(Notification.state == "unread")
        with Session(self.repository.engine) as session:
            return [
                _value(row)
                for row in session.scalars(
                    statement.order_by(Notification.created_at.desc(), Notification.id).limit(200)
                )
            ]

    def create(self, kind, title, body, *, related_id=None, dedupe_key=None):
        return self._create(
            kind, title, body, related_id=related_id, dedupe_key=dedupe_key, details={}
        )

    def _create(self, kind, title, body, *, related_id=None, dedupe_key=None, details=None):
        if (
            kind not in KINDS
            or not isinstance(title, str)
            or not 1 <= len(title.strip()) <= 300
            or not isinstance(body, str)
            or not 1 <= len(body.strip()) <= 8000
            or (
                related_id is not None
                and (not isinstance(related_id, str) or len(related_id) > 100)
            )
            or (
                dedupe_key is not None
                and (not isinstance(dedupe_key, str) or not 1 <= len(dedupe_key) <= 200)
            )
        ):
            raise ProbeError("INVALID_NOTIFICATION")
        identity = uuid4().hex
        with Session(self.repository.engine) as session, session.begin():
            session.execute(
                insert(Notification)
                .values(
                    id=identity,
                    kind=kind,
                    title=title.strip(),
                    body=body.strip(),
                    state="unread",
                    related_id=related_id,
                    dedupe_key=dedupe_key,
                    details=details or {},
                    created_at=now(),
                )
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
            )
            row = session.scalar(
                select(Notification).where(
                    Notification.dedupe_key == dedupe_key
                    if dedupe_key
                    else Notification.id == identity
                )
            )
            return _value(row)

    def mark_read(self, identity):
        return self._state(identity, resolve=False)

    def resolve(self, identity):
        return self._state(identity, resolve=True)

    def _state(self, identity, resolve):
        with Session(self.repository.engine) as session, session.begin():
            row = session.get(Notification, identity)
            if row is None:
                raise ProbeError("NOTIFICATION_NOT_FOUND")
            if row.read_at is None:
                row.read_at = now()
            if resolve:
                row.state, row.resolved_at = "resolved", row.resolved_at or now()
            elif row.state != "resolved":
                row.state = "read"
            return _value(row)

    def add_followup(self, question, source_run_id=None):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 4000:
            raise ProbeError("INVALID_FOLLOWUP_QUESTION")
        return self.create("followup", question[:120], question, related_id=source_run_id)

    def invalidate_research(self, run_ids):
        """忘记个人记忆后清除其关联研究的派生通知文本，保留最少历史状态。"""
        if not isinstance(run_ids, (list, tuple, set)) or any(
            not isinstance(identity, str) for identity in run_ids
        ):
            raise ProbeError("INVALID_RESEARCH_IDS")
        identities = set(run_ids)
        affected = []
        with Session(self.repository.engine) as session, session.begin():
            rows = session.scalars(
                select(Notification).where(
                    Notification.related_id.in_(identities),
                    Notification.kind.in_({"research", "followup", "hypothesis"}),
                )
            )
            for row in rows:
                if row.details.get("cleared"):
                    continue
                row.title = "关联研究的派生内容已清除"
                row.body = "相关个人记忆已被忘记；此处保留最少状态，原派生文本不再提供。"
                row.details = {"cleared": True, "reason": "related_memory_forgotten"}
                row.dedupe_key = "cleared:" + row.id
                row.state, row.read_at, row.resolved_at = "resolved", row.read_at or now(), now()
                affected.append(row.id)
        return {"affected_notification_ids": affected}

    def collection_update(self, run_id):
        with Session(self.repository.engine) as session:
            run = session.get(CollectionRun, run_id)
            if run is None:
                raise ProbeError("RUN_NOT_FOUND")
            watchset = session.get(Watchset, run.watchset_id)
            observations = session.scalars(
                select(JobObservation)
                .where(JobObservation.collection_run_id == run_id)
                .order_by(JobObservation.processed_at, JobObservation.id)
            ).all()
            job_ids = {item.job_id for item in observations}
            new_jobs, enriched, changed = [], [], []
            for job_id in sorted(job_ids):
                previous = session.scalars(
                    select(JobObservation)
                    .where(
                        JobObservation.job_id == job_id,
                        JobObservation.collection_run_id != run_id,
                        JobObservation.processed_at < run.started_at,
                    )
                    .order_by(JobObservation.processed_at.desc(), JobObservation.id)
                ).all()
                if not previous:
                    new_jobs.append(job_id)
                    continue
                for kind in {item.kind for item in observations if item.job_id == job_id}:
                    current = [
                        item for item in observations if item.job_id == job_id and item.kind == kind
                    ][-1]
                    older = next((item for item in previous if item.kind == kind), None)
                    if older is None:
                        enriched.append(
                            {"job_id": job_id, "kind": kind, "snapshot_id": current.snapshot_id}
                        )
                    elif older.snapshot_id != current.snapshot_id:
                        changed.append(
                            {
                                "job_id": job_id,
                                "kind": kind,
                                "before_snapshot_id": older.snapshot_id,
                                "after_snapshot_id": current.snapshot_id,
                            }
                        )
            previous_run = session.scalar(
                select(CollectionRun)
                .join(Watchset)
                .where(
                    Watchset.name == watchset.name,
                    CollectionRun.started_at < run.started_at,
                )
                .order_by(CollectionRun.started_at.desc())
                .limit(1)
            )
            summary = {
                "run_id": run.id,
                "mode": run.mode,
                "status": run.status,
                "watchset": watchset.name,
                "watchset_version": watchset.version,
                "new_job_ids": new_jobs,
                "observed_jobs": len(job_ids),
                "content_changes": changed,
                "detail_enrichments": enriched,
                "sample_scope_changed": bool(
                    previous_run and previous_run.watchset_id != run.watchset_id
                ),
                "analysis_changed": False,
                "coverage_limited": bool(
                    run.coverage.get("list_limited") or run.coverage.get("details_limited")
                ),
                "error_codes": [item["code"] for item in run.issues],
                "stop_reason": run.stop_reason,
                "note": "观察到的内容变化、样本范围变化与分析方法变化分开；失败不表示岗位关闭。"
                "回放不是新的市场观察。",
            }
        body = (
            f"执行状态：{summary['status']}；模式：{summary['mode']}。"
            f"本批看到 {len(job_ids)} 个岗位，新归档 {len(new_jobs)} 个，"
            f"已有内容变化 {len(changed)} 处，资料补充 {len(enriched)} 处。"
        )
        if summary["coverage_limited"]:
            body += " 来源覆盖有限，不能代表完整市场。"
        if summary["sample_scope_changed"]:
            body += " 观察配置版本有变化，不直接解释为市场趋势。"
        if summary["error_codes"]:
            body += " 本次存在执行失败；未取得资料的部分保持未知。"
        return self._create(
            "collection",
            f"观察更新 · {summary['watchset']}",
            body,
            related_id=run_id,
            dedupe_key="collection:" + run_id,
            details=summary,
        )
