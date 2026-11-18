"""显式本地观察任务与每日时段。没有系统定时任务，不恢复暂停的招聘连接。"""

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from work_observer.collection.contracts import WatchsetSpec, digest, now
from work_observer.collection.service import collect, error_code
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.recruitment import M0ReplaySource, MCPSource
from work_observer.connectors.source_status import require_source_available
from work_observer.reports.inbox import InboxService
from work_observer.storage.archive import RawArchive
from work_observer.storage.locks import exclusive
from work_observer.storage.models import Watchset
from work_observer.storage.operations_models import ObservationSchedule, WorkTask

SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
RETRYABLE = {"failed", "partial", "blocked", "interrupted", "needs_auth"}


def _watchset(row):
    return {
        key: getattr(row, key)
        for key in ("id", "name", "version", "config_sha256", "config", "created_at")
    }


def _task(row):
    result = {
        key: getattr(row, key)
        for key in (
            "id",
            "kind",
            "watchset_id",
            "mode",
            "state",
            "progress",
            "collection_run_ids",
            "result_id",
            "error_code",
            "attempts",
            "dedupe_key",
            "created_at",
            "started_at",
            "finished_at",
        )
    }
    result["has_replay_bundle"] = bool(row.parameters.get("replay_bundle"))
    return result


def _schedule(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "watchset_id",
            "hour",
            "minute",
            "timezone",
            "enabled",
            "created_at",
            "updated_at",
        )
    }


class TaskService:
    def __init__(self, repository):
        self.repository = repository
        self.inbox = InboxService(repository)
        self.path = repository.engine.url.database

    def watchsets(self, include_history=False):
        with Session(self.repository.engine) as session:
            rows = session.scalars(
                select(Watchset).order_by(Watchset.name, Watchset.version.desc())
            ).all()
            if include_history:
                return [_watchset(row) for row in rows]
            latest = {}
            for row in rows:
                latest.setdefault(row.name, _watchset(row))
            return list(latest.values())

    def save_watchset(self, name, spec):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ProbeError("INVALID_WATCHSET_NAME")
        spec = WatchsetSpec.model_validate(spec)
        config, stamp = spec.model_dump(mode="json"), now()
        with exclusive(self.path, purpose="configuration"):
            with Session(self.repository.engine) as session, session.begin():
                row = session.scalar(
                    select(Watchset).where(
                        Watchset.name == name.strip(), Watchset.config_sha256 == digest(config)
                    )
                )
                if row is None:
                    version = (
                        session.scalar(
                            select(func.max(Watchset.version)).where(Watchset.name == name.strip())
                        )
                        or 0
                    ) + 1
                    row = Watchset(
                        id=uuid4().hex,
                        name=name.strip(),
                        version=version,
                        config_sha256=digest(config),
                        config=config,
                        created_at=stamp,
                    )
                    session.add(row)
                    session.flush()
                return _watchset(row)

    def _get(self, session, identity):
        row = session.get(WorkTask, identity)
        if row is None:
            raise ProbeError("TASK_NOT_FOUND")
        return row

    def get(self, identity):
        with Session(self.repository.engine) as session:
            return _task(self._get(session, identity))

    def list(self, limit=100):
        if not 1 <= limit <= 200:
            raise ProbeError("INVALID_TASK_LIMIT")
        with Session(self.repository.engine) as session:
            return [
                _task(row)
                for row in session.scalars(
                    select(WorkTask).order_by(WorkTask.created_at.desc(), WorkTask.id).limit(limit)
                )
            ]

    def create_collection(self, watchset_id, *, mode="live", replay_bundle=None, dedupe_key=None):
        if mode not in {"live", "replay"} or (mode == "replay" and not replay_bundle):
            raise ProbeError("INVALID_TASK_MODE")
        if mode == "live" and replay_bundle is not None:
            raise ProbeError("INVALID_TASK_MODE")
        if dedupe_key is not None and (
            not isinstance(dedupe_key, str) or not 1 <= len(dedupe_key) <= 200
        ):
            raise ProbeError("INVALID_TASK_KEY")
        with Session(self.repository.engine) as session, session.begin():
            watchset = session.get(Watchset, watchset_id)
            if watchset is None:
                raise ProbeError("WATCHSET_NOT_FOUND")
            if watchset.config.get("source") != "boss":
                raise ProbeError("MANUAL_SOURCE_USE_IMPORT")
            identity = uuid4().hex
            session.execute(
                insert(WorkTask)
                .values(
                    id=identity,
                    kind="collection",
                    watchset_id=watchset_id,
                    mode=mode,
                    state="queued",
                    parameters={"replay_bundle": str(Path(replay_bundle).resolve())}
                    if replay_bundle
                    else {},
                    progress={"stage": "queued"},
                    collection_run_ids=[],
                    attempts=0,
                    dedupe_key=dedupe_key,
                    created_at=now(),
                )
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
            )
            row = session.scalar(
                select(WorkTask).where(
                    WorkTask.dedupe_key == dedupe_key if dedupe_key else WorkTask.id == identity
                )
            )
            if row.watchset_id != watchset_id or row.mode != mode:
                raise ProbeError("TASK_KEY_CONFLICT")
            expected_bundle = str(Path(replay_bundle).resolve()) if replay_bundle else None
            if row.parameters.get("replay_bundle") != expected_bundle:
                raise ProbeError("TASK_KEY_CONFLICT")
            return _task(row)

    def retry(self, identity):
        with exclusive(self.path, purpose="collection"):
            with Session(self.repository.engine) as session, session.begin():
                row = self._get(session, identity)
                if row.state not in RETRYABLE:
                    raise ProbeError("TASK_NOT_RETRYABLE")
                if row.attempts >= 2:
                    raise ProbeError("TASK_RETRY_LIMIT")
                row.state, row.error_code, row.finished_at = "queued", None, None
                row.progress = {
                    "stage": "queued",
                    "note": "显式重试；既有归档保留，下一次执行仍检查来源暂停。",
                }
                return _task(row)

    def _save(self, identity, **values):
        with Session(self.repository.engine) as session, session.begin():
            row = self._get(session, identity)
            for key, value in values.items():
                setattr(row, key, value)
            return _task(row)

    def _progress(self, identity, run_id, stage):
        report = self.repository.run(run_id)
        self._save(
            identity,
            progress={
                "stage": stage,
                "stats": report["stats"],
                "error_codes": [item["code"] for item in report["issues"]],
            },
        )

    def _finish_interrupted_run(self, run_id, code):
        if run_id:
            report = self.repository.run(run_id)
            if report["status"] == "running":
                self.repository.issue(run_id, code, "worker")
                self.repository.finish(
                    run_id,
                    "partial" if report["stats"]["pages_succeeded"] else "failed",
                    code,
                    True,
                    True,
                )
                self.inbox.collection_update(run_id)

    def _recover_locked(self):
        with Session(self.repository.engine) as session:
            interrupted = [
                _task(row)
                for row in session.scalars(select(WorkTask).where(WorkTask.state == "running"))
            ]
        for row in interrupted:
            self._finish_interrupted_run(row["result_id"], "PROCESS_INTERRUPTED")
            self._save(
                row["id"],
                state="interrupted",
                error_code="PROCESS_INTERRUPTED",
                finished_at=now(),
                progress={
                    "stage": "interrupted",
                    "note": "上次进程已停止；保留归档，可显式重试一次。",
                },
            )
        return interrupted

    def recover_interrupted(self):
        with exclusive(self.path, purpose="collection"):
            return self._recover_locked()

    async def run(self, identity, settings, source=None):
        with exclusive(self.path, purpose="collection"):
            self._recover_locked()
            return await self._run_locked(identity, settings, source=source)

    async def _run_locked(self, identity, settings, source=None):
        with Session(self.repository.engine) as session:
            row = self._get(session, identity)
            if row.state != "queued":
                raise ProbeError("TASK_NOT_QUEUED")
            watchset = session.get(Watchset, row.watchset_id)
            spec, name, mode = WatchsetSpec.model_validate(watchset.config), watchset.name, row.mode
            parameters, attempts = dict(row.parameters), row.attempts
        self._save(
            identity,
            state="running",
            started_at=now(),
            finished_at=None,
            attempts=attempts + 1,
            progress={"stage": "preflight"},
        )
        try:
            if mode == "live":
                config = settings.load_mcp()
                # 必须在构造/打开来源前检查；注入适配器同样不能绕过真实模式的暂停。
                require_source_available(config)
                source = source or MCPSource(config)
            else:
                source = source or M0ReplaySource(Path(parameters["replay_bundle"]))
            if source.mode != mode:
                raise ProbeError("TASK_SOURCE_MODE_MISMATCH")
            archive = RawArchive(
                settings.raw_directory,
                [
                    settings.model_api_key.get_secret_value(),
                    settings.tavily_api_key.get_secret_value(),
                ],
            )
            proxy = _ProgressRepository(self, identity)
            async with asyncio.timeout(300):
                report = await collect(proxy, archive, source, name, spec)
            self._save(
                identity,
                state=report["status"],
                result_id=report["id"],
                finished_at=now(),
                error_code=report["stop_reason"] if report["status"] != "success" else None,
                progress={
                    "stage": "finished",
                    "stats": report["stats"],
                    "coverage_limited": report["coverage"]["list_limited"]
                    or report["coverage"]["details_limited"],
                },
            )
            self.inbox.collection_update(report["id"])
        except asyncio.CancelledError:
            current = self.get(identity)
            self._finish_interrupted_run(current["result_id"], "PROCESS_INTERRUPTED")
            self._save(
                identity,
                state="interrupted",
                error_code="PROCESS_INTERRUPTED",
                finished_at=now(),
                progress={"stage": "interrupted"},
            )
            raise
        except Exception as exc:
            code = error_code(exc)
            current = self.get(identity)
            self._finish_interrupted_run(current["result_id"], code)
            self._save(
                identity,
                state="blocked" if code == "SOURCE_PAUSED_USE_LOCAL_DATA" else "failed",
                error_code=code,
                finished_at=now(),
                progress={"stage": "stopped", "error_code": code},
            )
            self.inbox.create(
                "system",
                "观察执行已停止",
                "停止原因：" + code + "。已有资料保留，失败不表示岗位关闭。",
                related_id=identity,
                dedupe_key=f"task:{identity}:{attempts + 1}",
            )
        return self.get(identity)

    def schedules(self):
        with Session(self.repository.engine) as session:
            return [
                _schedule(row)
                for row in session.scalars(
                    select(ObservationSchedule).order_by(ObservationSchedule.created_at.desc())
                )
            ]

    def save_schedule(self, watchset_id, *, hour=8, minute=30, enabled=False, schedule_id=None):
        if (
            type(hour) is not int
            or type(minute) is not int
            or not 0 <= hour <= 23
            or not 0 <= minute <= 59
            or type(enabled) is not bool
        ):
            raise ProbeError("INVALID_SCHEDULE")
        with Session(self.repository.engine) as session, session.begin():
            watchset = session.get(Watchset, watchset_id)
            if watchset is None:
                raise ProbeError("WATCHSET_NOT_FOUND")
            if watchset.config.get("source") != "boss":
                raise ProbeError("MANUAL_SOURCE_USE_IMPORT")
            row = session.get(ObservationSchedule, schedule_id) if schedule_id else None
            if schedule_id and row is None:
                raise ProbeError("SCHEDULE_NOT_FOUND")
            if row is None:
                if session.scalar(select(func.count()).select_from(ObservationSchedule)) >= 20:
                    raise ProbeError("SCHEDULE_LIMIT")
                row = ObservationSchedule(
                    id=uuid4().hex,
                    watchset_id=watchset_id,
                    hour=hour,
                    minute=minute,
                    timezone="Asia/Shanghai",
                    enabled=enabled,
                    created_at=now(),
                    updated_at=now(),
                )
                session.add(row)
            else:
                row.watchset_id, row.hour, row.minute = watchset_id, hour, minute
                row.enabled, row.updated_at = enabled, now()
            session.flush()
            return _schedule(row)

    async def tick(self, settings, *, at=None, run=True, limit=1):
        if not 1 <= limit <= 3 or type(run) is not bool:
            raise ProbeError("INVALID_WORKER_LIMIT")
        at = (
            datetime.now(UTC)
            if at is None
            else datetime.fromisoformat(at)
            if isinstance(at, str)
            else at
        )
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise ProbeError("SCHEDULE_TIME_REQUIRES_TIMEZONE")
        local, created, results = at.astimezone(SHANGHAI), [], []
        with exclusive(self.path, purpose="collection"):
            self._recover_locked()
            for schedule in self.schedules():
                if not schedule["enabled"] or (local.hour, local.minute) < (
                    schedule["hour"],
                    schedule["minute"],
                ):
                    continue
                task = self.create_collection(
                    schedule["watchset_id"],
                    dedupe_key=f"schedule:{schedule['id']}:{local.date().isoformat()}",
                )
                created.append(task)
            if run:
                with Session(self.repository.engine) as session:
                    identities = list(
                        session.scalars(
                            select(WorkTask.id)
                            .where(WorkTask.state == "queued")
                            .order_by(WorkTask.created_at, WorkTask.id)
                            .limit(limit)
                        )
                    )
                for identity in identities:
                    results.append(await self._run_locked(identity, settings))
        return {
            "checked_at": at.astimezone(UTC).isoformat(),
            "timezone": "Asia/Shanghai",
            "scheduled": created,
            "executed": results,
            "note": "仅本次显式检查；不是系统计划任务。",
        }


class _ProgressRepository:
    def __init__(self, service, identity):
        self.service, self.identity, self.repository = service, identity, service.repository

    def __getattr__(self, name):
        return getattr(self.repository, name)

    def begin_run(self, *args, **kwargs):
        run_id = self.repository.begin_run(*args, **kwargs)
        previous = self.service.get(self.identity)["collection_run_ids"]
        self.service._save(
            self.identity,
            result_id=run_id,
            collection_run_ids=[*previous, run_id],
            progress={"stage": "collecting"},
        )
        return run_id

    def start_step(self, run_id, stage, *args, **kwargs):
        identity = self.repository.start_step(run_id, stage, *args, **kwargs)
        self.service._progress(self.identity, run_id, stage)
        return identity

    def page(self, run_id, *args, **kwargs):
        result = self.repository.page(run_id, *args, **kwargs)
        self.service._progress(self.identity, run_id, "pages")
        return result

    def detail(self, run_id, *args, **kwargs):
        result = self.repository.detail(run_id, *args, **kwargs)
        self.service._progress(self.identity, run_id, "details")
        return result
