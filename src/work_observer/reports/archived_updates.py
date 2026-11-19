"""Observe existing archive versions through the document service; never fetch a URL."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.connectors.public_models import PublicDocument


def capture_archived(repository, enabled, identities=None):
    if not enabled:
        return {"enabled": False, "requested_ids": identities, "documents": []}
    from work_observer.research.document_scope import validate

    identities = validate(repository, identities)
    with Session(repository.engine) as session:
        query = select(PublicDocument).order_by(
            PublicDocument.observed_at.desc(), PublicDocument.id.desc()
        )
        if identities is not None:
            query = query.where(PublicDocument.id.in_(identities))
        selected = {}
        for row in session.scalars(query):
            if row.url not in selected:
                selected[row.url] = PublicDocumentService._metadata(row)
            if len(selected) > 2000:
                raise ProbeError("UPDATE_ARCHIVE_SCOPE_LIMIT_2000")
    return {"enabled": True, "requested_ids": identities, "documents": list(selected.values())}


def compare_archived(repository, before, after):
    a = before.get("archived_scope") or {}
    b = after.get("archived_scope") or {}
    observed = a.get("enabled") and b.get("enabled")
    result = {
        "status": "compared" if observed else "baseline_unavailable",
        "before_count": len(a.get("documents", [])),
        "after_count": len(b.get("documents", [])),
        "scope_rule_changed": a.get("requested_ids") != b.get("requested_ids"),
        "changes": [],
        "added": [],
        "removed": [],
        "observed_again": 0,
        "notice": (
            "只比较已归档的同来源版本。企业/技术说明的变化不能直接归为岗位职责变化；"
            "用户修订、提取变化和重复取得分别列示。归档时间不等于来源发布时间。"
        ),
    }
    if not observed:
        result["notice"] = "至少一侧未观察归档资料，不能由缺失基线推断新增、删除或内容未变。"
        return result
    left = {row["url"]: row for row in a["documents"]}
    right = {row["url"]: row for row in b["documents"]}
    result["added"] = [right[key] for key in sorted(right.keys() - left.keys())]
    result["removed"] = [left[key] for key in sorted(left.keys() - right.keys())]
    documents = PublicDocumentService(repository, ".")
    for url in sorted(left.keys() & right.keys()):
        old, new = left[url], right[url]
        if old == new:
            continue
        if old["integrity"] != "verified" or new["integrity"] != "verified":
            comparison = {
                "change_kind": "integrity_unavailable",
                "text_changed": None,
                "diff": "",
                "complete": False,
            }
        elif old["id"] == new["id"]:
            continue
        elif (old["observed_at"], old["id"]) >= (new["observed_at"], new["id"]):
            comparison = {
                "change_kind": "older_version_selected",
                "text_changed": None,
                "diff": "",
                "complete": False,
            }
        else:
            try:
                comparison = documents.compare(new["id"], old["id"])
            except ProbeError as exc:
                if exc.code not in {
                    "PUBLIC_DOCUMENT_INTEGRITY_FAILED",
                    "PUBLIC_DOCUMENT_NOT_FOUND",
                }:
                    raise
                comparison = {
                    "change_kind": "integrity_unavailable",
                    "text_changed": None,
                    "diff": "",
                    "complete": False,
                }
            if comparison["change_kind"] == "observed_again":
                result["observed_again"] += 1
                continue
        result["changes"].append({"before": old, "after": new, **comparison})
    return result
