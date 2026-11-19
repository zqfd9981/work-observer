"""有界资料/口径指纹：判断等待步骤是否真的获得了新材料，不把重复观察当增量。"""

import hashlib
import json
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_models import PublicDocument
from work_observer.memory.service import MemoryService
from work_observer.retrieval.catalog import Catalog, Filters
from work_observer.storage.models import JobSnapshot


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def material_state(
    repository, question, *, job_ids=None, filters=None, project_id=None, public_document_ids=None
):
    from work_observer.research.document_scope import validate

    public_document_ids = validate(repository, public_document_ids)
    from work_observer.research.agent import method_fingerprint

    catalog = Catalog(repository)
    scope = catalog.query(Filters.model_validate(filters or {}), job_ids=job_ids, limit=20)
    jobs = []
    for job in scope["jobs"]:
        evidence = catalog.evidence(job["id"], limit=1)
        entry = {"job_id": job["id"], "has_detail": bool(evidence)}
        if evidence:
            item = evidence[0]
            if catalog.document(item["document_id"])["integrity"] != "verified":
                raise ProbeError("RESEARCH_SOURCE_INTEGRITY_FAILED")
            entry.update(
                snapshot_id=item["snapshot_id"],
                content_sha256=item["content_sha256"],
                document_sha256=item["document_sha256"],
            )
        jobs.append(entry)
    with Session(repository.engine) as session:
        identities = [entry["job_id"] for entry in jobs]
        history = session.execute(
            select(JobSnapshot.id, JobSnapshot.content_sha256)
            .where(JobSnapshot.job_id.in_(identities))
            .order_by(JobSnapshot.created_at.desc(), JobSnapshot.id)
            .limit(2000)
        ).all()
        history_count = session.scalar(
            select(func.count()).select_from(JobSnapshot).where(JobSnapshot.job_id.in_(identities))
        )
        latest = {}
        latest_ids = {}
        for row in session.scalars(
            select(PublicDocument)
            .where(
                PublicDocument.id.in_(public_document_ids)
                if public_document_ids is not None
                else True
            )
            .order_by(PublicDocument.observed_at.desc(), PublicDocument.id.desc())
            .limit(5000)
        ):
            source_key = row.id if public_document_ids is not None else row.final_url
            if source_key not in latest:
                latest[source_key] = {"url": row.final_url, "sha256": row.text_sha256}
                latest_ids[source_key] = row.id
            if len(latest) == 500:
                break
    memories = MemoryService(repository).recall(
        question,
        [j["job_id"] for j in jobs],
        project_id=project_id,
        public_document_ids=public_document_ids,
    )
    from work_observer.knowledge.service import DomainKnowledgeService
    from work_observer.memory.service import _tokens

    # 与研究工具复用资格、范围和展示上限；不把未审核或域外关系当新材料。
    terms = list(
        dict.fromkeys(
            [
                *re.findall(r"[a-zA-Z0-9_+#.-]{2,100}", question),
                *re.findall(r"[\u4e00-\u9fff]{2,100}", question),
                *sorted(_tokens(question)),
            ]
        )
    )[:10]
    knowledge = DomainKnowledgeService(repository).browse_for_research(
        terms or [question[:100]],
        job_ids=[j["job_id"] for j in jobs],
        public_document_ids=list(latest_ids.values()),
        project_id=project_id,
    )
    knowledge_basis = {
        "terms": terms,
        "dependencies": sorted(knowledge["dependencies"], key=lambda row: (row["kind"], row["id"])),
        "source_run_ids": sorted(knowledge["source_run_ids"]),
        "limits": knowledge["limits"],
    }
    basis = {
        "jobs": sorted(jobs, key=lambda entry: entry["job_id"]),
        "history_count": history_count,
        "history_sha256": _digest(sorted([list(row) for row in history])),
        "public_count": len(latest),
        "public_sha256": _digest(sorted(latest.values(), key=lambda row: row["url"])),
        "memory_versions": [{"id": m["id"], "version": m["version"]} for m in memories],
        "method_sha256": method_fingerprint(),
        "knowledge_sha256": _digest(knowledge_basis),
        "knowledge_dependencies": knowledge_basis["dependencies"],
        "knowledge_limits": knowledge_basis["limits"],
    }
    return {"signature": _digest(basis), "basis": basis}
