"""Save canonical map items as existing domain and relation candidates."""

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.knowledge.lineage import source_contexts
from work_observer.knowledge.models import DomainDefinition, WorkRelation
from work_observer.knowledge.service import DomainKnowledgeService, _record
from work_observer.knowledge.support import claim_support
from work_observer.memory.dependencies import DependencyAudit
from work_observer.reports.cognition import checked_map
from work_observer.storage.locks import exclusive


class ResearchKnowledgeService:
    def __init__(self, repository, store):
        self.repository, self.store = repository, store
        repository.bind_research_store(store)
        self.knowledge = DomainKnowledgeService(repository)

    def _source(self, run_id):
        run = self.store.get(run_id)
        result = run.get("result") or {}
        if result.get("status") != "completed" or not result.get("work_map"):
            raise ProbeError("KNOWLEDGE_WORK_MAP_REQUIRED")
        if not DependencyAudit(self.repository).run(run_id)["eligible"]:
            raise ProbeError("KNOWLEDGE_RESEARCH_SOURCE_STALE")
        return result, checked_map(result)

    def preview(self, run_id):
        result, value = self._source(run_id)
        with Session(self.repository.engine) as session:
            domains = list(session.scalars(select(DomainDefinition)))
            domain_keys = {row.id: row.domain_key for row in domains}
            relations = list(session.scalars(select(WorkRelation)))
            work_types = []
            for index, item in enumerate(value["work_types"]):
                saved = next(
                    (
                        row
                        for row in domains
                        if (row.source_context or {}).get("run_id") == run_id
                        and row.source_context.get("work_type_index") == index
                    ),
                    None,
                )
                work_types.append(
                    {
                        **item,
                        "supporting_claims": claim_support(result, item["claim_indices"]),
                        "index": index,
                        "saved_id": saved.id if saved else None,
                        "saved_status": saved.status if saved else None,
                    }
                )
            relation_items = {}
            for key, index_key in (
                ("ability_relations", "ability_relation_index"),
                ("work_relations", "work_relation_index"),
            ):
                relation_items[key] = []
                for index, item in enumerate(value.get(key, [])):
                    saved = next(
                        (
                            row
                            for row in relations
                            if row.source_run_id == run_id
                            and row.scope.get("research_map", {}).get(index_key) == index
                        ),
                        None,
                    )
                    relation_items[key].append(
                        {
                            **item,
                            "supporting_claims": claim_support(
                                result,
                                sorted(
                                    set(item["claim_indices"])
                                    | {
                                        i
                                        for row in value.get("comparisons", [])
                                        if key == "work_relations"
                                        and index in row["relation_indices"]
                                        for i in row["claim_indices"]
                                    }
                                ),
                            ),
                            "index": index,
                            **(
                                {
                                    "comparisons": [
                                        row
                                        for row in value.get("comparisons", [])
                                        if index in row["relation_indices"]
                                    ]
                                }
                                if key == "work_relations"
                                else {}
                            ),
                            "saved_id": saved.id if saved else None,
                            "saved_status": saved.status if saved else None,
                        }
                    )
        return {
            "run_id": run_id,
            "project_id": result.get("project_id"),
            "work_types": work_types,
            **relation_items,
            "scope_note": value["scope_note"],
            "unknowns": value["unknowns"],
            "domains": [
                {
                    "id": row.id,
                    "domain_key": row.domain_key,
                    "name": row.name,
                    "version": row.version,
                    "status": row.status,
                }
                for row in domains
                if row.status in {"active", "candidate"}
                and all(
                    context.get("project_id") in {None, result.get("project_id")}
                    for context in source_contexts(self.repository, row)
                )
            ],
            "relations": [
                {
                    "id": row.id,
                    "domain_id": row.domain_id,
                    "domain_key": domain_keys.get(row.domain_id),
                    "source_text": row.source_text,
                    "target_text": row.target_text,
                    "predicate": row.predicate,
                }
                for row in relations
                if row.status in {"active", "candidate", "conflicted"}
                and row.scope.get("project_id") in {None, result.get("project_id")}
            ],
            "notice": "从本次地图保留结构化候选；仍需核对，不自动采纳或改写原报告。",
        }

    def save(
        self,
        run_id,
        *,
        work_type_index=None,
        ability_relation_index=None,
        work_relation_index=None,
        domain_id=None,
        previous_domain_id=None,
        previous_relation_id=None,
    ):
        choices = [
            ("work_types", work_type_index),
            ("ability_relations", ability_relation_index),
            ("work_relations", work_relation_index),
        ]
        if sum(index is not None for _, index in choices) != 1:
            raise ProbeError("KNOWLEDGE_MAP_ITEM_REQUIRED")
        with exclusive(self.repository.engine.url.database):
            result, value = self._source(run_id)
            kind, index = next((key, index) for key, index in choices if index is not None)
            if type(index) is not int or not 0 <= index < len(value.get(kind, [])):
                raise ProbeError("KNOWLEDGE_MAP_ITEM_REQUIRED")
            item = value[kind][index]
            comparisons = [
                row
                for row in value.get("comparisons", [])
                if work_relation_index is not None and index in row["relation_indices"]
            ]
            claim_indices = sorted(
                set(item["claim_indices"])
                | {i for row in comparisons for i in row["claim_indices"]}
            )
            ids = list(
                dict.fromkeys(
                    key for i in claim_indices for key in result["claims"][i]["evidence_ids"]
                )
            )
            source = {row["id"]: row for row in result["evidence"]}
            evidence = [source[key] for key in ids]
            if work_type_index is not None:
                with Session(self.repository.engine) as session:
                    existing = next(
                        (
                            row
                            for row in session.scalars(select(DomainDefinition))
                            if (row.source_context or {}).get("run_id") == run_id
                            and row.source_context.get("work_type_index") == index
                            and row.previous_id == previous_domain_id
                        ),
                        None,
                    )
                    if existing:
                        return {"kind": "domain", "record": _record(existing)}
                    previous = (
                        session.get(DomainDefinition, previous_domain_id)
                        if previous_domain_id
                        else None
                    )
                    if previous_domain_id and previous is None:
                        raise ProbeError("DOMAIN_NOT_FOUND")
                    key = (
                        previous.domain_key
                        if previous
                        else "work_" + hashlib.sha256(f"{run_id}:{index}".encode()).hexdigest()[:24]
                    )
                context = {
                    "run_id": run_id,
                    "work_type_index": index,
                    "basis": item["basis"],
                    "claim_indices": item["claim_indices"],
                    "evidence_ids": ids,
                    "job_ids": sorted({ev["job_id"] for ev in evidence if ev.get("job_id")}),
                    "public_document_ids": sorted(
                        {
                            ev["public_document_id"]
                            for ev in evidence
                            if ev.get("public_document_id")
                        }
                    ),
                    "project_id": result.get("project_id"),
                    "scope_note": value["scope_note"],
                    "unknowns": value["unknowns"],
                    "next_check": item["next_check"],
                }
                record = self.knowledge.propose_domain(
                    key,
                    item["name"],
                    f"要解决的问题：{item['problem']}\n主要任务：{item['tasks']}\n交付物：{item['deliverables']}",
                    inclusion=f"主要任务：{item['tasks']}\n交付物：{item['deliverables']}",
                    exclusion=f"边界与反例：{item['boundary']}\n下一步验证：{item['next_check']}",
                    previous_id=previous_domain_id,
                    change_kind="revise" if previous_domain_id else "create",
                    source_context=context,
                )
                return {"kind": "domain", "record": record}
            if not domain_id:
                raise ProbeError("DOMAIN_NOT_FOUND")
            context = {
                "work_relation_index"
                if work_relation_index is not None
                else "ability_relation_index": index,
                "basis": item["basis"],
                "rationale": item["rationale"],
                "transfer_limit": item["transfer_limit"],
                "claim_indices": claim_indices,
                "scope_note": value["scope_note"],
                **({"comparisons": comparisons} if comparisons else {}),
            }
            if work_relation_index is not None:
                context["evidence_scope"] = (
                    "job"
                    if any(ev.get("job_id") for ev in evidence)
                    else "work_material"
                    if any(ev.get("evidence_kind") == "work_material" for ev in evidence)
                    else "public_context"
                )
            record = self.knowledge.propose_relation(
                domain_id,
                item["source_kind"] if work_relation_index is not None else "task",
                item["source_text"] if work_relation_index is not None else item["task"],
                item["target_kind"] if work_relation_index is not None else "ability",
                item["target_text"] if work_relation_index is not None else item["ability"],
                evidence,
                predicate=item["predicate"] if work_relation_index is not None else "supports",
                project_id=result.get("project_id"),
                source_run_id=run_id,
                conflict_ids=[previous_relation_id] if previous_relation_id else [],
                research_map=context,
            )
            return {"kind": "relation", "record": record}
