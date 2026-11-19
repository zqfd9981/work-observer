"""统一检索岗位原文、已归档公开材料与有效派生知识；不将摘要当独立证据。"""

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import MAX_BYTES, PublicDocumentService
from work_observer.connectors.public_models import PublicDocument
from work_observer.memory.service import MemoryService
from work_observer.retrieval.catalog import Catalog
from work_observer.retrieval.enhanced import RetrievalService, normalized_time, validated_terms
from work_observer.storage.models import Job
from work_observer.text_match import match_text


def intact(document):
    path = Path(document.path)
    try:
        return (
            path.is_file()
            and path.stat().st_size <= MAX_BYTES
            and hashlib.sha256(path.read_bytes()).hexdigest() == document.sha256
            and hashlib.sha256(document.text.encode()).hexdigest() == document.text_sha256
        )
    except OSError:
        return False


class UnifiedRetrieval:
    """有界上下文、完整来源计数、明确可冻结的资料范围。"""

    def __init__(self, repository, alias_groups=None):
        self.repository = repository
        self.alias_groups = alias_groups

    def search(
        self,
        terms,
        *,
        filters=None,
        job_ids=None,
        public_document_ids=None,
        project_id=None,
        as_of=None,
        limit=10,
        aliases=True,
        include_knowledge=True,
    ):
        terms = validated_terms(terms)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ProbeError("INVALID_RETRIEVAL_LIMIT")
        if public_document_ids is not None and (
            not isinstance(public_document_ids, list)
            or len(public_document_ids) > 5000
            or any(not isinstance(item, str) for item in public_document_ids)
        ):
            raise ProbeError("INVALID_PUBLIC_DOCUMENT_SCOPE")
        cutoff = normalized_time(as_of)
        retrieval = RetrievalService(self.repository, alias_groups=self.alias_groups)
        jobs = retrieval.search(
            terms, filters=filters, job_ids=job_ids, as_of=cutoff, limit=20, aliases=aliases
        )
        expanded = jobs["expanded_terms"]
        evidence, excluded_integrity = [], []
        catalog = Catalog(self.repository)
        for item in jobs["evidence"]:
            if catalog.document(item["document_id"])["integrity"] == "verified":
                evidence.append({**item, "evidence_kind": "job_original", "derived": False})
            else:
                excluded_integrity.append(item["document_id"])
        statement = select(PublicDocument).order_by(
            PublicDocument.observed_at.desc(), PublicDocument.id.desc()
        )
        if public_document_ids is not None:
            statement = statement.where(PublicDocument.id.in_(public_document_ids))
        if cutoff:
            statement = statement.where(PublicDocument.observed_at <= cutoff)
        public_count, public_matches, seen_urls = 0, set(), set()
        with Session(self.repository.engine) as session:
            for row in session.scalars(statement):
                # 默认当前口径每个URL仅取最新材料；显式ID允许重放旧版本。
                if public_document_ids is None and row.url in seen_urls:
                    continue
                seen_urls.add(row.url)
                public_count += 1
                if not intact(row):
                    excluded_integrity.append(row.id)
                    continue
                chunks = []
                for start in range(0, len(row.text), 600):
                    quote = row.text[start : start + 700]
                    folded = match_text(quote)
                    hits = [term for term in expanded if match_text(term) in folded]
                    if hits:
                        chunks.append(
                            (sum(folded.count(match_text(t)) for t in hits), start)
                        )
                if chunks:
                    public_matches.add(row.id)
                for score, start in sorted(chunks, key=lambda item: (-item[0], item[1]))[:20]:
                    item = PublicDocumentService._evidence(row)[0]
                    end = min(start + 700, len(row.text))
                    item.update(
                        id=f"publicdoc:{row.id}:{start}:{end}",
                        start=start,
                        end=end,
                        quote=row.text[start:end],
                    )
                    evidence.append(
                        {
                            **item,
                            "derived": False,
                            "scope_note": item["source_note"]
                            if item["evidence_kind"] == "work_material"
                            else "公开材料描述发布者业务，不能据此认定某岗位具体职责。",
                            "retrieval": {"score": score},
                        }
                    )
            scoped_jobs = (
                list(session.scalars(select(Job.id))) if job_ids is None else list(job_ids)
            )
        evidence.sort(key=lambda item: (-item.get("retrieval", {}).get("score", 0), item["id"]))
        # 每份原始资料先有一条代表片段，避免长官网正文挤掉短JD。
        source_seen, diversified = set(), []
        for item in evidence:
            source_id = (item.get("job_id"), item.get("public_document_id"))
            diversified.append((source_id in source_seen, item))
            source_seen.add(source_id)
        evidence = [item for _, item in sorted(diversified, key=lambda row: row[0])]
        selected, characters = [], 0
        for item in evidence:
            if len(selected) >= limit or characters + len(item["quote"]) > 7000:
                continue
            selected.append(item)
            characters += len(item["quote"])
        knowledge = []
        if include_knowledge:
            recalled = MemoryService(self.repository).recall(
                " ".join(terms), scoped_jobs, project_id=project_id, at=cutoff, kinds=["knowledge"]
            )
            allowed_public = set(public_document_ids) if public_document_ids is not None else None
            for item in recalled:
                if item["kind"] != "knowledge":
                    continue
                if allowed_public is not None and any(
                    ev.get("public_document_id") not in allowed_public
                    for ev in item["evidence"]
                    if ev.get("public_document_id")
                ):
                    continue
                memory_size = len(item["content"]) + sum(
                    len(value.get("quote", "")) for value in item.get("evidence", [])
                )
                if memory_size > 3000:
                    continue
                while characters + memory_size > 7000 and len(selected) > 1:
                    characters -= len(selected.pop()["quote"])
                if characters + memory_size > 7000:
                    continue
                characters += memory_size
                knowledge.append(
                    {
                        **item,
                        "derived": True,
                        "evidence_kind": "derived_knowledge",
                        "independent_source": False,
                    }
                )
        return {
            "terms": terms,
            "expanded_terms": expanded,
            "sample": jobs["sample"],
            "matching_jobs": jobs["matching_jobs"],
            "public_scope_total": public_count,
            "matching_public_documents": len(public_matches),
            "evidence": selected,
            "knowledge": knowledge,
            "excluded_integrity_ids": sorted(set(excluded_integrity)),
            "context_characters": characters,
            "context_limit": 7000,
            "truncated": len(evidence) > len(selected),
            "scope": {
                "job_ids": job_ids,
                "public_document_ids": public_document_ids,
                "project_id": project_id,
                "as_of": cutoff,
            },
            "rules": (
                "岗位分母独立于公开资料和派生知识；来源计数先于分页。"
                "知识只回链原文，不是新增独立证据。"
                "检索比较统一大小写和同形部首，引用仍保留原文。"
            ),
        }
