"""研究审核的历史全文对照；引用位置不表示回答已覆盖原文语义。"""

import hashlib
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.collection.contracts import digest
from work_observer.storage.models import JobObservation, JobSnapshot, SourceDocument


def _job_versions(result, repository, evidence):
    from work_observer.research.historical_sources import historical_evidence_ids

    historical = historical_evidence_ids(repository, result) if repository is not None else set()
    versions = []
    for job in result.get("scope", {}).get("jobs", [])[:20]:
        documents = {}
        for item in evidence.values():
            if item.get("job_id") == job["id"] and item.get("id") in historical:
                documents.setdefault(item["document_id"], set()).update(item["historical_cutoffs"])
        frozen = (job.get("detail_source") or {}).get("document_id")
        versions.append({**job, "historical_cutoffs": sorted(documents.pop(frozen, set()))})
        versions.extend(
            {
                **job,
                "detail_source": {"document_id": identity},
                "historical_cutoffs": sorted(cutoffs),
            }
            for identity, cutoffs in documents.items()
        )
    return versions


def source_context(result, repository):
    """Use frozen documents and verified dated reads; never fill from the current job."""
    sources, characters, paragraphs = [], 0, 0
    evidence = {item["id"]: item for item in result.get("evidence", [])}
    jobs = result.get("scope", {}).get("jobs", [])
    for job in _job_versions(result, repository, evidence):
        source = {"job_id": job["id"], "title": job.get("title"), "units": []}
        if job.get("historical_cutoffs"):
            source["historical_cutoffs"] = job["historical_cutoffs"]
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
                title=snapshot.payload.get("title") or job.get("title"),
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
    archive_sources, archive_truncated = _archive_sources(
        result, repository, evidence, max(0, 600_000 - characters), max(0, 2000 - paragraphs)
    )
    sources.extend(archive_sources)
    return {
        "sources": sources,
        "scope_truncated": len(jobs) > 20 or archive_truncated,
        "notice": "按研究当时的原文版本核对任务、交付物、责任、条件限定及其他遗漏。"
        "明确读取的历史版本另列截止，不能用研究启动时的正文代替历史时点。"
        "判断编号仅表示其引用片段与该段相交，不表示回答已覆盖该段，也不表示语义支持。"
        + (
            "归档资料按本轮已读版本对照，超长正文只显示引用附近上下文并注明范围；"
            "用户粘贴资料及来源说明未经独立核实。"
            if archive_sources
            else "本面板只对照岗位正文；公开资料引用仍在逐条判断中核对。"
        ),
    }


def _merged(ranges):
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _archive_sources(result, repository, evidence, characters, paragraphs):
    from work_observer.connectors.public_documents import is_work_material
    from work_observer.connectors.public_models import PublicDocument

    identities = list(
        dict.fromkeys(
            item["public_document_id"]
            for item in evidence.values()
            if item.get("public_document_id")
        )
    )
    sources = []
    claims = result.get("claims", [])
    cited = {key for claim in claims for key in claim.get("evidence_ids", [])}
    cited.update(
        key
        for action in (result.get("application_plan") or {}).get("actions", [])
        for key in action.get("evidence_ids", [])
    )
    for identity in identities[:20]:
        source = {"public_document_id": identity, "title": "归档资料", "units": []}
        sources.append(source)
        if repository is None:
            source["state"] = "unavailable"
            continue
        with Session(repository.engine) as session:
            document = session.get(PublicDocument, identity)
            if document is None or not isinstance(document.text, str) or not document.text.strip():
                source["state"] = "unavailable"
                continue
            text = document.text
            bound = {
                key: item
                for key, item in evidence.items()
                if item.get("public_document_id") == identity
            }
            path = Path(document.path)
            try:
                intact = (
                    path.is_file()
                    and path.stat().st_size <= 10_000_000
                    and hashlib.sha256(path.read_bytes()).hexdigest() == document.sha256
                    and hashlib.sha256(text.encode()).hexdigest() == document.text_sha256
                    and all(
                        item.get("document_sha256", document.sha256) == document.sha256
                        and item.get("content_sha256", document.text_sha256) == document.text_sha256
                        for item in bound.values()
                    )
                )
            except OSError:
                intact = False
            source.update(
                title=document.title,
                evidence_kind="work_material" if is_work_material(document) else "public_document",
                observed_at=document.observed_at,
                document_sha256=document.sha256,
                text_sha256=document.text_sha256,
                full_text_length=len(text),
            )
            if not intact:
                source["state"] = "integrity_failed"
                continue
            valid = {}
            for key, item in bound.items():
                start, end = item.get("start"), item.get("end")
                if (
                    type(start) is int
                    and type(end) is int
                    and 0 <= start < end <= len(text)
                    and text[start:end] == item.get("quote")
                ):
                    valid[key] = (start, end)
            source["unresolved_evidence_ids"] = sorted(set(bound) - set(valid))
            budget = min(50_000, characters)
            complete = len(text) <= budget
            ranges = [(0, len(text))] if complete else []
            if not complete:
                for key in sorted(valid, key=lambda key: (key not in cited, valid[key][0])):
                    start, end = valid[key]
                    expanded = _merged([*ranges, (max(0, start - 300), min(len(text), end + 300))])
                    if sum(right - left for left, right in expanded) <= budget:
                        ranges = expanded
            source["context_kind"] = "full_text" if complete else "cited_windows"
            source["shown_ranges"] = []
            source["state"] = "available" if complete else "cited_windows"
            for left, right in ranges:
                shown_end = left
                for match in re.finditer(r"[^\r\n]+", text[left:right]):
                    if not match.group().strip():
                        shown_end = left + match.end()
                        continue
                    if paragraphs <= 0:
                        source["state"] = "display_limit"
                        complete = False
                        break
                    start, end = left + match.start(), left + match.end()
                    references = [
                        index
                        for index, claim in enumerate(claims)
                        if any(
                            key in valid and valid[key][0] < end and valid[key][1] > start
                            for key in claim.get("evidence_ids", [])
                        )
                    ]
                    source["units"].append(
                        {
                            "start": start,
                            "end": end,
                            "text": match.group(),
                            "claim_indices": references,
                        }
                    )
                    shown_end = end
                    paragraphs -= 1
                else:
                    shown_end = right
                if shown_end > left:
                    source["shown_ranges"].append({"start": left, "end": shown_end})
                if source["state"] == "display_limit":
                    break
            used = sum(row["end"] - row["start"] for row in source["shown_ranges"])
            characters -= used
            source["shown_characters"] = used
            source["complete"] = complete
            if not ranges:
                source["state"] = "display_limit" if not budget else "unresolved_citations"
    return sources, len(identities) > 20
