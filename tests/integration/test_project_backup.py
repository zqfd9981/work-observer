"""项目与业务审核备份按业务库隔离，恢复后不自动执行。"""

import sqlite3

from work_observer.demo import create_demo
from work_observer.maintenance import backup_workspace, restore_workspace
from work_observer.quality.reviews import QualityReviewService
from work_observer.research.projects import ProjectService
from work_observer.research.store import ResearchStore


def test_project_namespace_backup_and_restore(tmp_path):
    demo = tmp_path / "demo"
    create_demo(demo)
    database = (demo / "app.db").resolve()
    with sqlite3.connect(database) as db:
        job_id = db.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    store = ResearchStore(demo / "checkpoints.db", str(database))
    service = ProjectService(store)
    project = service.create("合成项目", "Python", [job_id])
    project = service.add(project["id"], "合成问题", revision=project["revision"])
    service.claim(project["id"])
    QualityReviewService(store)
    other = ResearchStore(demo / "checkpoints.db", "unrelated-database")
    unrelated = ProjectService(other).create("不应被备份的其他项目", "其他资料", ["other"])
    other.create({"question": "其他问题"})
    QualityReviewService(other)
    other.close()
    store.close()
    backup = tmp_path / "backup"
    backup_workspace(database, backup, demo / "reports")
    with sqlite3.connect(backup / "checkpoints.db") as db:
        for table in ("research_checkpoints", "research_projects", "quality_reviews"):
            assert {r[0] for r in db.execute(f'SELECT namespace FROM "{table}"')} <= {str(database)}
    restored = tmp_path / "restored"
    restore_workspace(backup, restored)
    store = ResearchStore(restored / "checkpoints.db", str((restored / "app.db").resolve()))
    project = ProjectService(store).get(project["id"])
    assert project["steps"][0]["state"] == "interrupted"
    assert all(p["id"] != unrelated["id"] for p in ProjectService(store).list())
    assert store.get(project["steps"][0]["run_id"])["state"] == "interrupted"
    store.close()
