"""研究审核的历史全文对照；引用位置不表示回答已覆盖原文语义。"""

import hashlib
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.collection.contracts import digest
from work_observer.storage.models import JobObservation, JobSnapshot, SourceDocument


def source_context(result, repository):
    """Only use the frozen scope document, or a unique historical evidence identity."""
    sources, characters, paragraphs = [], 0, 0
    evidence = {item["id"]: item for item in result.get("evidence", [])}
    jobs = result.get("scope", {}).get("jobs", [])
    for job in jobs[:20]:
        source = {"job_id": job["id"], "title": job.get("title"), "units": []}
        sources.append(source)
        document_id = (job.get("detail_source") or {}).get("document_id")
        identities = {
            (item.get("snapshot_id"), item.get("document_id"))
            for item in evidence.values()
            if item.get("job_id") == job["id"]
            and item.get("snapshot_id")
            and item.get("document_id")
        }
        if not document_id and len(identities) == 1:
            _, document_id = next(iter(identities))
        if not document_id:
            source["state"] = "ambiguous_version" if identities else "no_frozen_detail"
            continue
        if repository is None:
            source["state"] = "unavailable"
            continue
        with Session(repository.engine) as session:
            snapshots = (
                session.scalars(
                    select(JobSnapshot)
                    .join(JobObservation, JobObservation.snapshot_id == JobSnapshot.id)
                    .where(
                        JobSnapshot.job_id == job["id"],
                        JobSnapshot.kind == "detail",
                        JobObservation.job_id == job["id"],
                        JobObservation.document_id == document_id,
                        JobObservation.kind == "detail",
                    )
                )
                .unique()
                .all()
            )
            document = session.get(SourceDocument, document_id)
            if len(snapshots) != 1 or document is None:
                source["state"] = "unavailable"
                continue
            snapshot = snapshots[0]
            path = Path(document.path)
            try:
                valid_archive = (
                    path.is_file()
                    and path.stat().st_size <= 10_000_000
                    and hashlib.sha256(path.read_bytes()).hexdigest() == document.sha256
                )
            except OSError:
                valid_archive = False
            if not valid_archive or digest(snapshot.payload) != snapshot.content_sha256:
                source["state"] = "integrity_failed"
                continue
            text = snapshot.payload.get("description")
            if not isinstance(text, str) or not text.strip():
                source["state"] = "unavailable"
                continue
            source.update(
                snapshot_id=snapshot.id,
                document_id=document.id,
                document_sha256=document.sha256,
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                observed_at=document.observed_at,
                data_kind=document.provenance.get("data_kind", "unknown"),
                source=document.provenance.get("source"),
                full_text_length=len(text),
            )
            if characters + len(text) > 600_000:
                source["state"] = "display_limit"
                continue
            characters += len(text)
            source["state"] = "available"
            for match in re.finditer(r"[^\r\n]+", text):
                if not match.group().strip():
                    continue
                if paragraphs >= 2000:
                    source["state"] = "display_limit"
                    break
                paragraphs += 1
                start, end = match.span()
                references = []
                for index, claim in enumerate(result.get("claims", [])):
                    for key in claim.get("evidence_ids", []):
                        item = evidence.get(key, {})
                        left, right = item.get("start"), item.get("end")
                        if (
                            item.get("job_id") == job["id"]
                            and item.get("snapshot_id") == snapshot.id
                            and item.get("document_id") == document.id
                            and type(left) is int
                            and type(right) is int
                            and 0 <= left < right <= len(text)
                            and text[left:right] == item.get("quote")
                            and left < end
                            and right > start
                        ):
                            references.append(index)
                            break
                source["units"].append(
                    {"start": start, "end": end, "text": match.group(), "claim_indices": references}
                )
    return {
        "sources": sources,
        "scope_truncated": len(jobs) > 20,
        "notice": "按研究当时的岗位正文逐段核对学历、年限、条件限定及其他遗漏。"
        "判断编号仅表示其引用片段与该段相交，不表示回答已覆盖该段，也不表示语义支持。"
        "本面板只对照岗位正文；公开资料引用仍在逐条判断中核对。",
    }
