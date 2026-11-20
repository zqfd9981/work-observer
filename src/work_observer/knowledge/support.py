"""Recover canonical claim context for saved map knowledge without copying stored history."""

from work_observer.memory.dependencies import DependencyAudit


def claim_support(result, indices):
    evidence = {row["id"]: row for row in result.get("evidence", [])}
    claims = result.get("claims", [])
    output = []
    for index in sorted({i for i in indices if type(i) is int and 0 <= i < len(claims)}):
        claim = claims[index]
        output.append(
            {
                "claim_index": index,
                **{
                    key: claim.get(key)
                    for key in ("text", "category", "basis", "requirement", "evidence_ids")
                },
                "source_references": [
                    {
                        key: evidence[identity].get(key)
                        for key in (
                            "id",
                            "job_id",
                            "public_document_id",
                            "snapshot_id",
                            "document_id",
                            "title",
                            "company",
                            "start",
                            "end",
                            "evidence_kind",
                        )
                    }
                    for identity in claim.get("evidence_ids", [])
                    if identity in evidence
                ],
            }
        )
    return output


def research_support(repository, run_id, indices, *, at=None):
    if not run_id or not indices:
        return []
    auditor = DependencyAudit(repository, at=at)
    record = auditor._read("research_checkpoints", run_id) or {}
    result = record.get("result") or {}
    if (
        record.get("state") == "invalidated"
        or result.get("status") != "completed"
        or record.get("updated_at", "") > auditor.at
    ):
        return []
    return claim_support(result, indices)
