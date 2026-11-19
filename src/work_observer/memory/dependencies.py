"""派生资格的只读、有界依赖审计；不通过recall/audit_result互调，不改历史。"""

import hashlib
import json
import sqlite3
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.knowledge.models import DomainDefinition, WorkRelation
from work_observer.storage.models import MemoryRecord
from work_observer.tracking.models import RetrievalStrategy


class DependencyAudit:
    """一次审计最多96个节点、12层；缺失、循环和不可核验依赖都拒绝默认复用。"""

    def __init__(self, repository, *, at=None, max_nodes=96, max_depth=12, excluded_runs=()):
        from work_observer.memory.service import _timestamp

        self.repository = repository
        self.at = _timestamp(at) or now()
        self.max_nodes, self.max_depth = max_nodes, max_depth
        self.stack, self.cache = set(), {}
        self.excluded_runs = set(excluded_runs)
        self.path = Path(
            getattr(
                repository,
                "research_store_path",
                Path(repository.engine.url.database).parent / "checkpoints.db",
            )
        )
        self.namespace = getattr(
            repository, "research_namespace", str(Path(repository.engine.url.database).resolve())
        )

    @staticmethod
    def _issue(kind, identity, reason):
        return {"kind": kind, "id": identity, "reason": reason}

    def _visit(self, kind, identity, callback, *, cache_key=None):
        key = (kind, identity if cache_key is None else cache_key)
        if key in self.stack:
            return [self._issue(kind, identity, "dependency_cycle")]
        if key in self.cache:
            return self.cache[key]
        if len(self.cache) + len(self.stack) >= self.max_nodes or len(self.stack) >= self.max_depth:
            return [self._issue(kind, identity, "dependency_budget_exceeded")]
        self.stack.add(key)
        try:
            result = callback()
            self.cache[key] = result
            return result
        finally:
            self.stack.remove(key)

    def _read(self, table, identity):
        if not self.path.is_file():
            return None
        try:
            with sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2
            ) as db:
                row = db.execute(
                    f"SELECT record FROM {table} WHERE namespace=? AND id=?",
                    (self.namespace, identity),
                ).fetchone()
                if not row or len(row[0]) > 4_000_000:
                    return None
                value = json.loads(row[0])
                return value if isinstance(value, dict) else None
        except (sqlite3.Error, OSError, ValueError):
            return None

    def _quality_rejection(self, identity, result):
        fingerprint = hashlib.sha256(
            json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        try:
            with sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2
            ) as db:
                if not db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='quality_reviews'"
                ).fetchone():
                    return []
                row = db.execute(
                    "SELECT record FROM quality_reviews WHERE namespace=? AND run_id=? "
                    "AND json_extract(record,'$.result_sha256')=? "
                    "AND json_extract(record,'$.decision') IN ('approve','reject') "
                    "ORDER BY json_extract(record,'$.created_at') DESC,id DESC LIMIT 1",
                    (self.namespace, identity, fingerprint),
                ).fetchone()
                if row and (review := json.loads(row[0])).get("decision") == "reject":
                    reason = (
                        "source_human_review_rejected"
                        if review.get("reviewer_kind") == "human"
                        else "source_agent_review_rejected"
                    )
                    return [self._issue("run", identity, reason)]
        except (sqlite3.Error, OSError, ValueError):
            return [self._issue("run", identity, "source_review_unavailable")]
        return []

    @staticmethod
    def _scope(result):
        scope = result.get("scope") or {}
        return {
            "job_ids": {
                row["id"]
                for row in scope.get("jobs", [])
                if isinstance(row, dict) and row.get("id")
            },
            "public_document_ids": set(scope.get("archived_public_ids", [])),
            "project_id": result.get("project_id"),
        }

    def _evidence(self, session, evidence, *, kind, identity, required=False, require_current=True):
        from work_observer.memory.service import MemoryService

        if not evidence:
            return [self._issue(kind, identity, "source_evidence_missing")] if required else []
        service = MemoryService(self.repository)
        try:
            canonical = service._validate_evidence(session, evidence)
            recorded = {item.get("id"): item for item in evidence}
            if any(
                recorded[item["id"]].get(key) is not None
                and recorded[item["id"]][key] != item.get(key)
                for item in canonical
                for key in ("document_sha256", "content_sha256")
            ):
                return [self._issue(kind, identity, "source_reference_changed")]
            if require_current and not service._sources_current(session, canonical):
                return [self._issue(kind, identity, "source_changed")]
        except (ProbeError, OSError, TypeError, KeyError):
            return [self._issue(kind, identity, "source_missing_or_invalid")]
        return []

    def memory(self, identity, *, version=None, job_ids=None, project_id=None, ignore_status=False):
        from work_observer.memory.service import _valid_at

        with Session(self.repository.engine) as session:
            row = session.get(MemoryRecord, identity) if isinstance(identity, str) else None
            if row is None:
                return self._summary([self._issue("memory", identity, "missing")])
            issues = []
            if not ignore_status and row.status != "active":
                issues.append(self._issue("memory", identity, row.status))
            if version is not None and row.version != version:
                issues.append(self._issue("memory", identity, "version_changed"))
            if not _valid_at(row, self.at):
                issues.append(self._issue("memory", identity, "outside_effective_time"))
            scope = None if job_ids is None else set(job_ids)
            if scope is not None:
                if row.scope == "project" and row.project_id != project_id:
                    issues.append(self._issue("memory", identity, "project_scope_mismatch"))
                if row.job_id and row.job_id not in scope:
                    issues.append(self._issue("memory", identity, "job_scope_mismatch"))
                if any(item.get("job_id") and item["job_id"] not in scope for item in row.evidence):
                    issues.append(self._issue("memory", identity, "evidence_scope_mismatch"))

            def intrinsic():
                found = self._evidence(
                    session,
                    row.evidence,
                    kind="memory",
                    identity=row.id,
                    required=row.kind == "knowledge",
                )
                if row.source_run_id:
                    found.extend(
                        self._run(
                            row.source_run_id, evidence_ids=[item["id"] for item in row.evidence]
                        )
                    )
                    source = self._read("research_checkpoints", row.source_run_id) or {}
                    source_evidence = {
                        item.get("id") for item in (source.get("result") or {}).get("evidence", [])
                    }
                    if any(item.get("id") not in source_evidence for item in row.evidence):
                        found.append(self._issue("memory", row.id, "source_run_evidence_mismatch"))
                return found

            issues.extend(self._visit("memory", row.id, intrinsic))
            if (
                row.source_run_id
                and scope is not None
                and not any(item.get("job_id") for item in row.evidence)
            ):
                source = self._read("research_checkpoints", row.source_run_id)
                source_scope = self._scope((source or {}).get("result") or {})
                if not scope <= source_scope["job_ids"]:
                    issues.append(self._issue("memory", identity, "derived_scope_not_covered"))
            if row.source_run_id and scope is not None:
                issues.extend(
                    self._inherited_scope(
                        row.source_run_id,
                        {
                            "job_ids": scope,
                            "project_id": project_id,
                        },
                    )
                )
            return self._summary(issues)

    def _scope_constraints(self, identity):
        def inspect():
            found, parents = [], set()
            record = self._read("research_checkpoints", identity) or {}
            result = record.get("result") or {}
            parents.update(result.get("continued_from", []))
            with Session(self.repository.engine) as session:
                for ref in [
                    *result.get("memory_used", result.get("memories", [])),
                    *result.get("context_memory_used", []),
                ]:
                    row = session.get(MemoryRecord, ref.get("id"))
                    if not row:
                        continue
                    if row.scope == "project" or row.job_id:
                        found.append(
                            {
                                "kind": "memory",
                                "id": row.id,
                                "project_id": row.project_id if row.scope == "project" else None,
                                "job_ids": [row.job_id] if row.job_id else [],
                            }
                        )
                    if row.source_run_id:
                        parents.add(row.source_run_id)
                for ref in result.get("knowledge_used", []):
                    if ref.get("kind") == "domain_definition":
                        definition = session.get(DomainDefinition, ref.get("id"))
                        if definition and (definition.source_context or {}).get("run_id"):
                            parents.add(definition.source_context["run_id"])
                        continue
                    if ref.get("kind") != "work_relation":
                        continue
                    row = session.get(WorkRelation, ref.get("id"))
                    if not row:
                        continue
                    found.append(
                        {
                            "kind": "knowledge",
                            "id": row.id,
                            "project_id": row.scope.get("project_id"),
                            "job_ids": row.scope.get("job_ids", []),
                        }
                    )
                    if row.source_run_id:
                        parents.add(row.source_run_id)
            for parent in sorted(parents):
                found.extend(self._scope_constraints(parent))
            return found

        return self._visit("scope", identity, inspect)

    def _inherited_scope(self, identity, scope):
        """缓存范围传递也计入同一次96节点预算，摘要不能洗掉用户记忆的范围。"""
        found = []
        for constraint in self._scope_constraints(identity):
            if "reason" in constraint:
                found.append(constraint)
                continue
            if constraint["project_id"] and constraint["project_id"] != scope["project_id"]:
                found.append(
                    self._issue(
                        constraint["kind"], constraint["id"], "inherited_project_scope_mismatch"
                    )
                )
            if not set(constraint["job_ids"]) <= scope["job_ids"]:
                found.append(
                    self._issue(
                        constraint["kind"], constraint["id"], "inherited_job_scope_mismatch"
                    )
                )
        return found

    def _run(self, identity, *, evidence_ids=None):
        if identity in self.excluded_runs:
            return [self._issue("run", identity, "review_source_excluded_from_context")]
        anchors = frozenset(evidence_ids) if evidence_ids else None

        def inspect():
            record = self._read("research_checkpoints", identity)
            if not record:
                return [self._issue("run", identity, "source_run_missing")]
            result = record.get("result") or {}
            if (
                record.get("state") not in {"finished", "completed"}
                or result.get("status") != "completed"
            ):
                return [self._issue("run", identity, "source_run_not_completed")]
            issues = self._result(result, evidence_ids=anchors)
            if anchors and not anchors <= {item.get("id") for item in result.get("evidence", [])}:
                issues.append(self._issue("run", identity, "source_run_evidence_mismatch"))
            issues.extend(self._quality_rejection(identity, result))
            project_id = result.get("project_id") or (record.get("input") or {}).get("project_id")
            if project_id:
                project = self._read("research_projects", project_id)
                if not project or project.get("state") != "active":
                    issues.append(self._issue("run", identity, "source_project_unavailable"))
                else:
                    step = next(
                        (
                            item
                            for item in project.get("steps", [])
                            if item.get("run_id") == identity
                        ),
                        None,
                    )
                    if not step or step.get("scope_version") != project.get("scope_version"):
                        issues.append(self._issue("run", identity, "source_project_scope_changed"))
            return issues

        return self._visit(
            "run",
            identity,
            inspect,
            cache_key=(identity, tuple(sorted(anchors))) if anchors else identity,
        )

    def _knowledge(self, session, ref, scope):
        identity, kind = ref.get("id"), ref.get("kind")
        if kind == "domain_definition":
            row = session.get(DomainDefinition, identity)
            if (
                not row
                or row.status != "active"
                or row.version != ref.get("version")
                or row.reviewed_at != ref.get("reviewed_at")
            ):
                return [self._issue("knowledge", identity, "domain_version_or_status_changed")]
            context = row.source_context or {}
            if context.get("run_id"):
                if (
                    not set(context.get("job_ids", [])) <= scope["job_ids"]
                    or not set(context.get("public_document_ids", []))
                    <= scope["public_document_ids"]
                ):
                    return [self._issue("knowledge", identity, "domain_source_scope_mismatch")]
                return [
                    *self._run(context["run_id"], evidence_ids=context.get("evidence_ids")),
                    *self._inherited_scope(context["run_id"], scope),
                ]
            return []
        if kind != "work_relation":
            return [self._issue("knowledge", identity, "unknown_knowledge_dependency")]
        row = session.get(WorkRelation, identity)
        if not row:
            return [self._issue("knowledge", identity, "relation_missing")]
        issues = []
        if row.status != "active" or row.reviewed_at != ref.get("reviewed_at"):
            issues.append(self._issue("knowledge", identity, "relation_version_or_status_changed"))
        if (
            row.scope.get("project_id")
            and row.scope["project_id"] != scope["project_id"]
            or not set(row.scope.get("job_ids", [])) <= scope["job_ids"]
            or not set(row.scope.get("public_document_ids", [])) <= scope["public_document_ids"]
        ):
            issues.append(self._issue("knowledge", identity, "relation_scope_mismatch"))

        def intrinsic():
            found = []
            domain = session.get(DomainDefinition, row.domain_id)
            if not domain or domain.status != "active":
                found.append(self._issue("knowledge", identity, "relation_domain_changed"))
            elif domain.source_context:
                found.extend(
                    self._knowledge(
                        session,
                        {
                            "id": domain.id,
                            "kind": "domain_definition",
                            "version": domain.version,
                            "reviewed_at": domain.reviewed_at,
                        },
                        scope,
                    )
                )
            for job_id in row.scope.get("job_ids", []):
                corrections = session.scalars(
                    select(MemoryRecord)
                    .where(
                        MemoryRecord.kind == "correction",
                        MemoryRecord.job_id == job_id,
                        MemoryRecord.status == "active",
                    )
                    .order_by(MemoryRecord.created_at.desc(), MemoryRecord.id)
                ).all()
                for correction in corrections:
                    prefix = "画像领域纠正："
                    if (
                        not correction.content.startswith(prefix)
                        or not self.memory(correction.id)["eligible"]
                    ):
                        continue
                    try:
                        values = json.loads(correction.content[len(prefix) :])
                        accepted = (
                            row.domain_id in values["definition_ids"]
                            if "definition_ids" in values
                            else domain.domain_key in values["domains"]
                        )
                        if not accepted:
                            found.append(
                                self._issue(
                                    "knowledge", identity, "relation_corrected_domain_mismatch"
                                )
                            )
                    except (ValueError, KeyError, TypeError):
                        found.append(
                            self._issue("knowledge", identity, "domain_correction_invalid")
                        )
                    break
            for items, required in ((row.evidence, True), (row.counterevidence, False)):
                batches = [items[start : start + 10] for start in range(0, len(items), 10)] or [[]]
                for batch in batches:
                    found.extend(
                        self._evidence(
                            session, batch, kind="knowledge", identity=identity, required=required
                        )
                    )
            for peer in session.scalars(
                select(WorkRelation).where(WorkRelation.status.in_({"candidate", "conflicted"}))
            ):
                if identity in peer.conflict_ids:
                    found.append(self._issue("knowledge", identity, "relation_conflict_pending"))
                    break
            if row.source_run_id:
                found.extend(
                    self.run(
                        row.source_run_id,
                        job_ids=row.scope.get("job_ids", []),
                        project_id=row.scope.get("project_id"),
                        evidence_ids=[item["id"] for item in [*row.evidence, *row.counterevidence]],
                    )["issues"]
                )
            return found

        issues.extend(self._visit("relation", identity, intrinsic))
        return issues

    def _result(self, result, *, evidence_ids=None):
        from work_observer.research.archive_versions import historical_evidence_ids
        from work_observer.research.historical_sources import historical_evidence_ids as job_history

        historical = historical_evidence_ids(self.repository, result) | job_history(
            self.repository, result
        )
        issues, scope = [], self._scope(result)
        refs = [
            *result.get("memory_used", result.get("memories", [])),
            *result.get("context_memory_used", []),
        ]
        for ref in refs:
            if not isinstance(ref, dict) or type(ref.get("version")) is not int:
                issues.append(
                    self._issue(
                        "memory",
                        ref.get("id") if isinstance(ref, dict) else None,
                        "unversioned_memory_dependency",
                    )
                )
                continue
            issues.extend(
                self.memory(
                    ref.get("id"),
                    version=ref["version"],
                    job_ids=scope["job_ids"],
                    project_id=scope["project_id"],
                )["issues"]
            )
        for identity in result.get("continued_from", []):
            issues.extend(self._run(identity))
            issues.extend(self._inherited_scope(identity, scope))
        with Session(self.repository.engine) as session:
            for ref in result.get("knowledge_used", []):
                issues.extend(self._knowledge(session, ref, scope))
            # 只复核可独立回查的正文；搜索摘要不能在此变成长期证据。
            for evidence in result.get("evidence", []):
                if evidence_ids is not None and evidence.get("id") not in evidence_ids:
                    continue
                if evidence.get("snapshot_id") or evidence.get("public_document_id"):
                    issues.extend(
                        self._evidence(
                            session,
                            [evidence],
                            kind="run_evidence",
                            identity=evidence.get("id"),
                            require_current=evidence.get("id") not in historical,
                        )
                    )
            strategy = result.get("strategy") or result.get("retrieval_strategy") or {}
            identity = strategy.get("id")
            if identity and identity != "literal-v1":
                row = session.get(RetrievalStrategy, identity)
                if not row or row.status != "active":
                    issues.append(self._issue("strategy", identity, "strategy_status_changed"))
                elif (
                    strategy.get("config_sha256")
                    and strategy["config_sha256"]
                    != hashlib.sha256(
                        json.dumps(row.config, sort_keys=True, ensure_ascii=False).encode()
                    ).hexdigest()
                ):
                    issues.append(
                        self._issue("strategy", identity, "strategy_configuration_changed")
                    )
        return issues

    def _summary(self, issues):
        unique = {json.dumps(item, sort_keys=True): item for item in issues}
        return {
            "eligible": not unique,
            "issues": list(unique.values())[:200],
            "checked_at": self.at,
            "visited_nodes": len(self.cache) + len(self.stack),
            "limits": {"nodes": self.max_nodes, "depth": self.max_depth},
        }

    def run(self, identity, *, job_ids=None, project_id=None, evidence_ids=None):
        issues = list(self._run(identity, evidence_ids=evidence_ids))
        if job_ids is not None:
            source = self._read("research_checkpoints", identity)
            scope = self._scope((source or {}).get("result") or {})
            if not set(job_ids) <= scope["job_ids"]:
                issues.append(self._issue("run", identity, "derived_scope_not_covered"))
            issues.extend(
                self._inherited_scope(identity, {"job_ids": set(job_ids), "project_id": project_id})
            )
        return self._summary(issues)

    def result(self, result):
        return self._summary(self._result(result))
