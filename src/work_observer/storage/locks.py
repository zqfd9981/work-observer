"""按业务库隔离的跨进程互斥；进程退出由操作系统释放。"""

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path

from work_observer.connectors.mcp_probe import ProbeError


@contextmanager
def exclusive(path, purpose="research"):
    path = Path(path).resolve()
    signature = hashlib.sha256(str(path).casefold().encode()).hexdigest()[:20]
    directory = path.parent / ".locks"
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / f"{purpose}-{signature}.lock").open("a+b")
    try:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ProbeError(
                "RESEARCH_BUSY" if purpose == "research" else "DATABASE_IN_USE"
            ) from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()
