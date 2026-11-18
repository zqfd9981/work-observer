"""显式启动、跨进程互斥的有限调查队列批处理；不建立常驻调度。"""

import asyncio
import json
import time

from work_observer.collection.service import error_code
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.lifecycle import pending_erasures
from work_observer.research.projects import execute_project, step_reservation
from work_observer.storage.locks import exclusive

SCAN_LIMIT = 100


def _scan(service, project_id):
    if project_id:
        record = service.get(project_id)
        if record["state"] == "invalidated":
            raise ProbeError("PROJECT_FORGOTTEN_RESTART")
        return [record], 1
    with service.store.lock:
        where = "namespace=? AND json_extract(record,'$.state') != 'invalidated'"
        total = service.store.db.execute(
            "SELECT COUNT(*) FROM research_projects WHERE " + where,
            (service.store.namespace,),
        ).fetchone()[0]
        rows = service.store.db.execute(
            "SELECT record FROM research_projects WHERE "
            + where
            + " ORDER BY json_extract(record,'$.updated_at') DESC,id LIMIT ?",
            (service.store.namespace, SCAN_LIMIT),
        ).fetchall()
    return [json.loads(row[0]) for row in rows], total


def _recover_scanned(service, records):
    """研究锁内恢复本次有限扫描，不影响其他命名空间，也不自动消费预算。"""
    recovered = []
    for record in records:
        for step in record["steps"]:
            if step["state"] != "running":
                continue
            run = service.store.get(step["run_id"])
            if run["state"] == "invalidated":
                raise ProbeError("MEMORY_FORGOTTEN_RESTART")
            if run["state"] == "running":
                service.store.save(run["id"], state="interrupted")
            service.finish(
                record["id"], step["id"], state="interrupted", reason="worker_explicit_recovery"
            )
            recovered.append(step["run_id"])
    return recovered


def _ready(record):
    completed = {step["id"] for step in record["steps"] if step["state"] == "completed"}
    return [
        step
        for step in record["steps"]
        if step["state"] in {"queued", "interrupted"} and set(step["depends_on"]) <= completed
    ]


def _run_usage(store, run_id):
    result = store.get(run_id).get("result") or {}
    return {
        "calls": result.get("model_calls", 0),
        "seconds": result.get("elapsed_seconds", 0),
        "public": result.get("public_searches", 0) + result.get("public_reads", 0),
    }


async def run_research_worker(
    service,
    repository,
    settings,
    *,
    project_id=None,
    max_steps=3,
    max_calls=36,
    max_seconds=900,
    max_public=4,
    model=None,
):
    """一次有界batch；领取原子检查剩余caps，项目累计预算仍由项目服务负责。"""
    if (
        type(max_steps) is not int
        or not 1 <= max_steps <= 6
        or type(max_calls) is not int
        or not 0 <= max_calls <= 36
        or type(max_seconds) is not int
        or not 1 <= max_seconds <= 900
        or type(max_public) is not int
        or not 0 <= max_public <= 4
    ):
        raise ProbeError("INVALID_WORKER_BUDGET")
    limits = {"calls": max_calls, "seconds": max_seconds, "public": max_public}
    reserved, actual = ({key: 0 for key in limits} for _ in range(2))
    processed, skipped, blocked = [], {}, set()
    started = time.monotonic()
    stop_reason, timed_out, current = "no_ready_steps", False, None

    def account(before, after, claimed_run_ids=()):
        previous = {step["id"]: step for step in before["steps"]}
        for step in after["steps"]:
            old = previous.get(step["id"], {})
            if not step.get("run_id"):
                continue
            baseline = current["usage"].get(step["run_id"], {key: 0 for key in limits})
            usage = _run_usage(service.store, step["run_id"])
            if (
                step["run_id"] not in claimed_run_ids
                and old.get("run_id") == step["run_id"]
                and old.get("started_at") == step.get("started_at")
                and usage == baseline
            ):
                continue
            reservation = step_reservation(step)
            for key in reserved:
                reserved[key] += reservation[key]
            for key in actual:
                actual[key] += max(0, usage[key] - baseline[key])
            processed.append(
                {
                    "project_id": after["id"],
                    "step_id": step["id"],
                    "run_id": step["run_id"],
                    "state": step["state"],
                    "stop_reason": step.get("stop_reason"),
                    "reservation": reservation,
                }
            )

    with exclusive(repository.engine.url.database):
        if pending_erasures(service.store):
            raise ProbeError("PRIVACY_ERASURE_PENDING")
        records, total = _scan(service, project_id)
        recovered = _recover_scanned(service, records)
        try:
            async with asyncio.timeout(max(0.001, max_seconds - (time.monotonic() - started))):
                while len(processed) < max_steps:
                    records, total = _scan(service, project_id)
                    ready = [
                        record
                        for record in records
                        if record["id"] not in blocked and _ready(record)
                    ]
                    if not ready:
                        stop_reason = (
                            "worker_budget_exhausted"
                            if any(value == "worker_budget_exhausted" for value in skipped.values())
                            else "no_ready_steps"
                        )
                        break
                    remaining = {key: limits[key] - reserved[key] for key in limits}
                    remaining["seconds"] = min(
                        remaining["seconds"],
                        max(0, int(max_seconds - (time.monotonic() - started))),
                    )
                    if remaining["seconds"] <= 0:
                        stop_reason = "worker_time_limit"
                        break
                    before = service.get(ready[0]["id"])
                    current = {
                        "project_id": before["id"],
                        "before": before,
                        "usage": {
                            step["run_id"]: _run_usage(service.store, step["run_id"])
                            for step in before["steps"]
                            if step.get("run_id")
                        },
                    }
                    try:
                        after = await execute_project(
                            service,
                            before["id"],
                            repository,
                            settings,
                            model=model,
                            max_steps=1,
                            _lock_held=True,
                            worker_caps=remaining,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        skipped[before["id"]] = error_code(exc)
                        blocked.add(before["id"])
                        account(before, service.get(before["id"]))
                        current = None
                        stop_reason = "worker_execution_error"
                        break
                    batch = after["worker_batch"]
                    account(before, after, batch["run_ids"])
                    if not batch["run_ids"]:
                        skipped[before["id"]] = batch["stop_reason"]
                        blocked.add(before["id"])
                    current = None
                else:
                    stop_reason = "worker_step_limit"
        except TimeoutError:
            timed_out, stop_reason = True, "worker_time_limit"
            if current:
                account(current["before"], service.get(current["project_id"]))
        records, total = _scan(service, project_id)
        waiting = []
        for record in records:
            completed = {step["id"] for step in record["steps"] if step["state"] == "completed"}
            counts = {
                key: sum(step["state"] == key for step in record["steps"])
                for key in ("waiting_review", "waiting_material", "queued", "interrupted", "failed")
            }
            counts["blocked_dependencies"] = sum(
                step["state"] in {"queued", "interrupted"}
                and not set(step["depends_on"]) <= completed
                for step in record["steps"]
            )
            if any(counts.values()):
                waiting.append({"project_id": record["id"], **counts})
        return {
            "status": "stopped"
            if timed_out or stop_reason == "worker_execution_error"
            else "finished",
            "stop_reason": stop_reason,
            "processed": processed,
            "run_ids": list(dict.fromkeys(row["run_id"] for row in processed)),
            "waiting": waiting,
            "skipped": [
                {"project_id": identity, "reason": reason} for identity, reason in skipped.items()
            ],
            "recovered_run_ids": recovered,
            "budget": {
                "limits": {"steps": max_steps, **limits},
                "reserved": reserved,
                "actual": actual,
                "wall_seconds": round(time.monotonic() - started, 3),
            },
            "scan": {
                "limit": SCAN_LIMIT,
                "scanned_projects": len(records),
                "scope_total": total,
                "truncated": total > len(records),
                "selected_project_id": project_id,
            },
            "note": (
                "本次仅显式处理有限队列；等待审核/资料直接释放，不轮询，不保证24小时运行。"
                "项目原累计预算和来源暂停均保留。"
            ),
        }
