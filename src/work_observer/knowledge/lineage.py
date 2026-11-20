"""Resolve existing definition links without treating a merge as a new source."""

from sqlalchemy.orm import Session

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.knowledge.models import DomainDefinition


def source_contexts(repository, definition):
    pending, seen, contexts = [definition], set(), []
    with Session(repository.engine) as session:
        while pending:
            row = pending.pop()
            if row.id in seen:
                continue
            seen.add(row.id)
            context = row.source_context or {}
            if context.get("run_id"):
                contexts.append({**context, "definition_id": row.id})
                continue
            parents = (
                row.related_ids
                if row.change_kind in {"merge", "split"}
                else [row.previous_id]
                if row.previous_id
                else []
            )
            for identity in parents:
                parent = session.get(DomainDefinition, identity)
                if parent is None:
                    raise ProbeError("DOMAIN_NOT_FOUND")
                pending.append(parent)
    return contexts
