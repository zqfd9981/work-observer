"""原始 MCP 响应按字节指纹存档；同内容复用文件，每次请求独立记录来源。"""

import hashlib
import os
from pathlib import Path
from uuid import uuid4

from work_observer.collection.contracts import canonical
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.evidence import redact


class RawArchive:
    def __init__(self, root: Path, secrets=()):
        self.root = root
        self.secrets = secrets

    def sanitize(self, capture):
        return capture.model_copy(
            update={
                "raw": redact(capture.raw, self.secrets),
                "request": redact(capture.request, self.secrets),
            }
        )

    def save(self, raw: dict):
        data = canonical(redact(raw, self.secrets)) + b"\n"
        sha = hashlib.sha256(data).hexdigest()
        path = self.root / sha[:2] / f"{sha}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ProbeError("ARCHIVE_CORRUPTED")
        else:
            temporary = path.with_suffix(f".{uuid4().hex}.tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        return str(path.resolve()), sha
