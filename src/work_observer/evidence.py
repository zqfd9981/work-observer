"""仅本地保存 M0 证据，不承担 M1 业务档案、身份或去重。"""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "password",
    "client_secret",
    "token",
    "headers",
}


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if k.lower() in SENSITIVE_KEYS else redact(v, secrets)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)Bearer\s+[^\s\"<>]+", "Bearer [REDACTED]", value)
    return value


class Evidence:
    def __init__(self, secrets=(), root=Path("data/raw/m0")):
        self.path = root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex[:8])
        self.path.mkdir(parents=True)
        self.secrets = secrets
        self.files: dict[str, str] = {}

    def save(self, name: str, payload):
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json", by_alias=True)
        data = json.dumps(redact(payload, self.secrets), ensure_ascii=False, indent=2) + "\n"
        encoded = data.encode("utf-8")
        # 显式写字节，避免 Windows 文本写入将 LF 转成 CRLF 后与记录的指纹不一致。
        (self.path / name).write_bytes(encoded)
        self.files[name] = hashlib.sha256(encoded).hexdigest()

    def finish(self, report):
        report["evidence_sha256"] = self.files.copy()
        self.save("report.json", report)
