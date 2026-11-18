"""页面与CLI共用的个人记忆遗忘闭包，不删除原始来源。"""

import re
from pathlib import Path

from work_observer.memory.service import MemoryService
from work_observer.reports.inbox import InboxService
from work_observer.reports.results import forget_reports, read_result
from work_observer.storage.locks import exclusive


def forget_personal(repository, store, identity, reports_dir=Path("reports")):
    with exclusive(repository.engine.url.database):
        return _forget(repository, store, identity, Path(reports_dir))


def _forget(repository, store, identity, reports_dir):
    memory = MemoryService(repository)
    forgotten = memory.forget(identity)
    identities, pending = set(), set(forgotten["forgotten_memory_ids"])
    affected_runs, report_ids = set(), set()
    deleted_profiles = set(forgotten.get("deleted_profile_ids", []))
    while pending:
        identities.update(pending)
        invalidated = store.invalidate_memories(sorted(pending))
        new_runs = set(invalidated["affected_run_ids"]) - affected_runs
        affected_runs.update(new_runs)
        report_ids.update(invalidated["report_ids"])
        derived = memory.invalidate_research(sorted(new_runs))
        deleted_profiles.update(derived.get("deleted_profile_ids", []))
        pending = set(derived.get("affected_memory_ids", [])) - identities
    notifications = InboxService(repository).invalidate_research(sorted(affected_runs))
    if reports_dir.exists():
        for path in reports_dir.glob("*.json"):
            if path.is_symlink() or not re.fullmatch(r"[a-f0-9]{32}", path.stem):
                continue
            result = read_result(path.stem, reports_dir)
            used = result.get("memory_used", result.get("memories", []))
            if identities & {item.get("id") for item in used if isinstance(item, dict)}:
                report_ids.add(path.stem)
    return {
        **forgotten,
        "deleted_profile_ids": sorted(deleted_profiles),
        "affected_memory_ids": sorted(identities),
        "affected_run_ids": sorted(affected_runs),
        "report_ids": sorted(report_ids),
        **notifications,
        **forget_reports(sorted(report_ids), reports_dir),
    }
