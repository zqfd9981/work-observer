"""遗忘失败关闭及读取期间变更拦截，使用合成私密哨兵。"""

import json

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from work_observer.api.privacy import PrivacyRecoveryGuard, result_read_blocked, unavailable
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.store import ResearchStore


def journal(store, completed, namespace=None):
    with store.lock, store.db:
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS privacy_erasures(namespace TEXT,id TEXT,record TEXT)"
        )
        store.db.execute(
            "DELETE FROM privacy_erasures WHERE namespace=?", (namespace or store.namespace,)
        )
        store.db.execute(
            "INSERT INTO privacy_erasures VALUES (?,?,?)",
            (
                namespace or store.namespace,
                "synthetic-erasure",
                json.dumps({"id": "synthetic-erasure", "completed": completed}),
            ),
        )


def app_for(store, recover, change=None):
    async def read(request):
        body = {"private_text": "SYNTHETIC_PRIVATE_SENTINEL"}
        if change:
            change()
        return unavailable() if result_read_blocked(store) else JSONResponse(body)

    app = Starlette(
        routes=[Route("/api/read", read), Route("/api/projects/test", read, methods=["DELETE"])]
    )
    app.add_middleware(PrivacyRecoveryGuard, store=lambda: store, recover=recover)
    return app


def test_pending_recovery_failure_returns_no_old_context(tmp_path):
    store = ResearchStore(tmp_path / "cp.db", "first")
    journal(store, False)

    def fail():
        raise ProbeError("PRIVACY_REPORT_DIRECTORY_MISMATCH")

    with TestClient(app_for(store, fail)) as client:
        response = client.get("/api/read")
        assert response.status_code == 503
        assert "SYNTHETIC_PRIVATE_SENTINEL" not in response.text
        assert response.json()["error_code"] == "PRIVACY_REPORT_DIRECTORY_MISMATCH"
    store.close()


def test_pending_recovery_completes_before_read_and_other_namespace_is_ignored(tmp_path):
    store = ResearchStore(tmp_path / "cp.db", "first")
    journal(store, False)
    calls = []

    def recover():
        calls.append(True)
        journal(store, True)

    with TestClient(app_for(store, recover)) as client:
        assert client.get("/api/read").status_code == 200
        assert client.get("/api/read").status_code == 200
        assert len(calls) == 1
        journal(store, False, namespace="other")
        assert client.get("/api/read").status_code == 200
        assert len(calls) == 1
    store.close()


def test_epoch_change_blocks_previously_read_payload_but_allows_erase_metadata(tmp_path):
    store = ResearchStore(tmp_path / "cp.db", "first")
    with TestClient(app_for(store, lambda: None, change=lambda: journal(store, True))) as client:
        response = client.get("/api/read")
        assert response.status_code == 503 and "SYNTHETIC_PRIVATE_SENTINEL" not in response.text
    # 实际项目DELETE只返回ID；这里验证当前请求允许自己的完成epoch变化。
    with store.lock, store.db:
        store.db.execute("DELETE FROM privacy_erasures")
    with TestClient(app_for(store, lambda: None, change=lambda: journal(store, True))) as client:
        assert client.delete("/api/projects/test").status_code == 200
    store.close()
