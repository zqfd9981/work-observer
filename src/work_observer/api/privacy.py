"""遗忘中断时关闭派生结果读取，避免部分擦除后继续展示旧上下文。"""

import hashlib
from contextvars import ContextVar

from starlette.responses import JSONResponse

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.lifecycle import pending_erasures

request_epoch = ContextVar("privacy_epoch", default=None)
erase_request = ContextVar("privacy_erase_request", default=False)


def epoch(store):
    if store is None:
        return None
    with store.lock:
        if not store.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='privacy_erasures'"
        ).fetchone():
            return "empty"
        rows = store.db.execute(
            "SELECT record FROM privacy_erasures WHERE namespace=? ORDER BY id", (store.namespace,)
        ).fetchall()
    return hashlib.sha256("\n".join(row[0] for row in rows).encode()).hexdigest()


def result_read_blocked(store):
    before = request_epoch.get()
    if store is not None and erase_request.get() and not pending_erasures(store):
        return False  # 遗忘成功响应仅返回清理ID，不含已擦除内容。
    return store is not None and (
        pending_erasures(store) or before is not None and before != epoch(store)
    )


def unavailable(code="PRIVACY_RECOVERY_REQUIRED"):
    return JSONResponse(
        {
            "error_code": code,
            "message": "遗忘清理尚在恢复或本次读取期间已发生变更。请刷新后重试；"
            "若使用自定义报告目录，请使用原报告目录启动，以完成清理。",
        },
        503,
    )


class PrivacyRecoveryGuard:
    def __init__(self, app, *, store, recover):
        self.app, self.store, self.recover = app, store, recover

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        store = self.store()
        if store is not None and pending_erasures(store):
            try:
                self.recover()
            except Exception as exc:
                code = exc.code if isinstance(exc, ProbeError) else "PRIVACY_RECOVERY_REQUIRED"
                return await unavailable(code)(scope, receive, send)
        token = request_epoch.set(epoch(store))
        erase_token = erase_request.set(
            scope.get("method") == "DELETE"
            and scope["path"].split("/")[2] in {"projects", "memories"}
        )
        blocked = False

        async def checked_send(message):
            nonlocal blocked
            if message["type"] == "http.response.start" and result_read_blocked(store):
                blocked = True
                return await unavailable()(scope, receive, send)
            if not blocked:
                await send(message)

        try:
            await self.app(scope, receive, checked_send)
        finally:
            request_epoch.reset(token)
            erase_request.reset(erase_token)
