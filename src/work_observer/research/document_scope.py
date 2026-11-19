"""Explicit archive selection: None means available library, [] means no archive."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_models import PublicDocument


def normalize(ids):
    if ids is None:
        return None
    if (
        not isinstance(ids, list)
        or len(ids) > 20
        or any(not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{32}", key) for key in ids)
    ):
        raise ProbeError("INVALID_RESEARCH_DOCUMENT_SCOPE")
    return sorted(set(ids))


def validate(repository, ids):
    ids = normalize(ids)
    if ids is not None:
        with Session(repository.engine) as session:
            found = set(
                session.scalars(select(PublicDocument.id).where(PublicDocument.id.in_(ids)))
            )
        if found != set(ids):
            raise ProbeError("PUBLIC_DOCUMENT_NOT_FOUND")
    return ids
