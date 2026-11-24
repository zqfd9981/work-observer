"""Cross-source findings derived from the Agent's cited judgments, not keyword counts."""


def source_key(evidence):
    for field in ("job_id", "public_document_id", "document_id"):
        if evidence.get(field):
            return f"{field}:{evidence[field]}"
    return None


def aggregate_research(result):
    evidence = {row["id"]: row for row in result.get("evidence", [])}
    available = {row["id"]: row for row in result.get("scope", {}).get("jobs", [])}
    read_jobs = {row["job_id"] for row in evidence.values() if row.get("job_id") in available}
    groups = []
    for index, claim in enumerate(result.get("claims", [])):
        citations = list(dict.fromkeys(key for key in claim["evidence_ids"] if key in evidence))
        sources = {source_key(evidence[key]) for key in citations} - {None}
        kind = claim.get("aggregation", "none")
        if kind == "none":
            if claim.get("basis") != "synthesis" or len(sources) < 2:
                continue
            kind = "pattern"
        if kind in {"common", "difference", "calibration"} and len(sources) < 2:
            kind = "single_source"
        if not sources:
            continue
        groups.append({
            "claim_index": index,
            "kind": kind,
            "category": claim.get("category", "task"),
            "requirement": claim.get("requirement", "unspecified"),
            "evidence_ids": citations,
            "source_ids": sorted(sources),
            "job_ids": sorted({evidence[key]["job_id"] for key in citations
                               if evidence[key].get("job_id")}),
        })
    cited_sources = {key for group in groups for key in group["source_ids"]}
    if len(cited_sources) < 2 or not any(len(row["source_ids"]) >= 2 for row in groups):
        return None
    return {
        "groups": groups,
        "cited_sources": len(cited_sources),
        "cited_jobs": len({key for group in groups for key in group["job_ids"]}),
        "candidate_jobs": len(available),
        "available_details": sum(bool(row.get("has_detail")) for row in available.values()),
        "read_jobs": len(read_jobs),
        "missing_detail_ids": sorted(key for key, row in available.items()
                                     if not row.get("has_detail")),
        "unread_job_ids": sorted(key for key, row in available.items()
                                 if row.get("has_detail") and key not in read_jobs),
        "notice": "按引用的岗位去重，同一岗位多个片段只计一次；引用数不是需求频次或独立企业数。"
                  "聚合是Agent分析，引用存在不等于语义已核实。未提及不等于没有要求，样本不代表全市场。",
    }
