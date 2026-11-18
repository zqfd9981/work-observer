"""独立研究检查点；不把执行上下文写成业务事实，也不在重启后自动消费额度。"""

import json
import re
import sqlite3
import threading
from pathlib import Path
from uuid import uuid4

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError


class ResearchStore:
    def __init__(self, path, namespace):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.namespace = namespace
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS research_checkpoints ("
            "namespace TEXT NOT NULL, id TEXT NOT NULL, record TEXT NOT NULL, "
            "checkpoint TEXT, PRIMARY KEY(namespace,id))"
        )
        self.db.commit()

    def create(self, input_dict):
        identity = uuid4().hex
        record = {
            "id": identity,
            "state": "running",
            "created_at": now(),
            "updated_at": now(),
            "input": input_dict,
            "result": None,
            "saved": None,
        }
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO research_checkpoints(namespace,id,record) VALUES (?,?,?)",
                (self.namespace, identity, json.dumps(record, ensure_ascii=False)),
            )
        return record

    def get(self, identity):
        with self.lock:
            row = self.db.execute(
                "SELECT record FROM research_checkpoints WHERE namespace=? AND id=?",
                (self.namespace, identity),
            ).fetchone()
        if not row:
            raise ProbeError("RESEARCH_NOT_FOUND")
        return json.loads(row[0])

    def list(self, limit=100):
        with self.lock:
            rows = self.db.execute(
                "SELECT record FROM research_checkpoints WHERE namespace=? "
                "ORDER BY json_extract(record,'$.created_at') DESC LIMIT ?",
                (self.namespace, min(max(limit, 1), 100)),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save(self, identity, **fields):
        if fields.keys() - {"state", "result", "saved", "error_code", "progress"}:
            raise ProbeError("INVALID_CHECKPOINT_FIELDS")
        with self.lock, self.db:
            record = self.get(identity)
            if record.get("state") == "invalidated":
                raise ProbeError("MEMORY_FORGOTTEN_RESTART")
            record.update(fields, updated_at=now())
            self.db.execute(
                "UPDATE research_checkpoints SET record=? WHERE namespace=? AND id=?",
                (json.dumps(record, ensure_ascii=False), self.namespace, identity),
            )
        return record

    def checkpoint(self, identity, state_dict):
        with self.lock, self.db:
            record = self.get(identity)
            if record.get("state") == "invalidated":
                raise ProbeError("MEMORY_FORGOTTEN_RESTART")
            self.db.execute(
                "UPDATE research_checkpoints SET checkpoint=? WHERE namespace=? AND id=?",
                (json.dumps(state_dict, ensure_ascii=False), self.namespace, identity),
            )

    def load_checkpoint(self, identity):
        with self.lock:
            self.get(identity)
            row = self.db.execute(
                "SELECT checkpoint FROM research_checkpoints WHERE namespace=? AND id=?",
                (self.namespace, identity),
            ).fetchone()
        return json.loads(row[0]) if row[0] else None

    def invalidate_memories(self, identities):
        """清除受影响的完整执行上下文与结果，保留最少运行元数据。"""
        identities = set(identities)
        affected, reports = [], set()
        with self.lock, self.db:
            rows = self.db.execute(
                "SELECT id,record,checkpoint FROM research_checkpoints WHERE namespace=?",
                (self.namespace,),
            ).fetchall()
            for identity, encoded, encoded_checkpoint in rows:
                record = json.loads(encoded)
                checkpoint = json.loads(encoded_checkpoint) if encoded_checkpoint else {}
                used = [
                    *(record.get("result") or {}).get("memory_used", []),
                    *(record.get("result") or {}).get("context_memory_used", []),
                    *(checkpoint.get("result") or {}).get("memory_used", []),
                    *(checkpoint.get("result") or {}).get("context_memory_used", []),
                ]
                if not any(
                    isinstance(item, dict) and item.get("id") in identities for item in used
                ):
                    continue
                affected.append(identity)
                for source in (record.get("saved") or {}, record.get("result") or {}):
                    report_id = source.get("report_id") if isinstance(source, dict) else None
                    if isinstance(report_id, str) and re.fullmatch(r"[a-f0-9]{32}", report_id):
                        reports.add(report_id)
                minimal = {
                    "id": identity,
                    "state": "invalidated",
                    "created_at": record.get("created_at"),
                    "updated_at": now(),
                    "input": {"question": "相关个人记忆已忘记，请重新研究"},
                    "result": None,
                    "saved": None,
                    "error_code": "MEMORY_FORGOTTEN_RESTART",
                    "stale_memory": True,
                }
                self.db.execute(
                    "UPDATE research_checkpoints SET record=?,checkpoint=NULL "
                    "WHERE namespace=? AND id=?",
                    (json.dumps(minimal, ensure_ascii=False), self.namespace, identity),
                )
        return {"affected_run_ids": affected, "report_ids": sorted(reports)}

    def invalidate_runs(self, identities):
        reports = set()
        with self.lock, self.db:
            for identity in identities:
                record = self.get(identity)
                for source in (record.get("saved") or {}, record.get("result") or {}):
                    report_id = source.get("report_id")
                    if isinstance(report_id, str) and re.fullmatch(r"[a-f0-9]{32}", report_id):
                        reports.add(report_id)
                minimal = dict(
                    id=identity,
                    state="invalidated",
                    created_at=record.get("created_at"),
                    updated_at=now(),
                    input={"question": "相关记忆已忘记，请重新研究"},
                    result=None,
                    saved=None,
                    error_code="MEMORY_FORGOTTEN_RESTART",
                    stale_memory=True,
                )
                self.db.execute(
                    "UPDATE research_checkpoints SET record=?,checkpoint=NULL "
                    "WHERE namespace=? AND id=?",
                    (json.dumps(minimal, ensure_ascii=False), self.namespace, identity),
                )
        return {"affected_run_ids": list(identities), "report_ids": sorted(reports)}

    def dependent_runs(self, identities):
        """派生上下文回链，不把旧报告或领域关系当独立证据。调用方负责闭包。"""
        identities = set(identities)
        affected = []
        with self.lock:
            rows = self.db.execute(
                "SELECT id,record,checkpoint FROM research_checkpoints WHERE namespace=?",
                (self.namespace,),
            ).fetchall()
            for identity, encoded, checkpoint in rows:
                record = json.loads(encoded)
                saved = json.loads(checkpoint) if checkpoint else {}
                dependencies = set((record.get("result") or {}).get("continued_from", []))
                dependencies.update((saved.get("result") or {}).get("continued_from", []))
                if dependencies & identities:
                    affected.append(identity)
        return affected

    def close(self):
        with self.lock:
            self.db.close()
