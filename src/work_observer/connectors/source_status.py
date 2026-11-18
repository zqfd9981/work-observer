"""只读本地暂停状态；不启动连接器、不清锁、不探测平台。"""

from pathlib import Path

from work_observer.connectors.mcp_probe import ProbeError


def source_status(config):
    args = config.args
    directory = None
    for index, value in enumerate(args):
        if value == "--data-dir" and index + 1 < len(args):
            directory = Path(args[index + 1])
        elif value.startswith("--data-dir="):
            directory = Path(value.split("=", 1)[1])
    if directory is None:
        return {"source": "boss", "state": "unknown", "checked": "local_only"}
    path = directory / "cdp_risk_lock.json"
    if path.exists():
        # 文件存在即停止，包括无法解析和已过期的锁，不自动解释为可恢复。
        return {
            "source": "boss",
            "state": "paused",
            "checked": "local_only",
            "reason": "存在本地风险暂停记录；未发送平台请求，人工导入和静态研究可继续。",
        }
    return {
        "source": "boss",
        "state": "no_local_pause",
        "checked": "local_only",
        "reason": "未发现本地暂停记录，不代表来源当前可用。",
    }


def require_source_available(config):
    if source_status(config)["state"] == "paused":
        raise ProbeError("SOURCE_PAUSED_USE_LOCAL_DATA")
