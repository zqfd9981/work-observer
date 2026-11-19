"""Bounded comparisons of explicitly selected archived snapshots, without fetching."""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.connectors.public_models import PublicDocument

VERSION = "archive-versions-v2"
KNOWN_VERSIONS = {"archive-versions-v1", VERSION}
POLICY_V1 = (
    "archive_version_pairs列出本轮所选同一资料的历史快照，不是来源新发布或真实业务变化。"
    "compare_archived_versions仅比较本轮已选的两个快照，不联网、不扩大范围。"
    "问题涉及版本差异时，优先直接调用此工具，不必为已知版本重复查范围或登记计划。"
    "返回的变化类型、完整性和时间由程序计算；引用只是首个差异附近的原文片段，"
    "其他差异需按问题检索，不能把片段当全文。区分用户改稿、网页响应、换行和文本提取变化。"
    "明确写哪两个归档版本在比较，保存时间不能冒充发布时间；"
    "同一原始文件重新提取出的文本不同，不能解释为岗位、能力或业务真实变化。"
    "两版都须引用，交付物或责任推断保留推断性质。历史对照可回看，不自动成为当前有效知识。"
)
POLICY = POLICY_V1 + (
    "程序事实已由archive_comparisons单独展示，claims侧重解释其意义和边界；"
    "哈希、长度、保存时间等程序元数据不能标成文档原文明示，相关归纳或解释用synthesis/inference。"
    "direct仅用于引用片段实际明示的内容。claims.text和gaps用读者可理解的中文，"
    "不写source_published_at、source_note、raw_changed、complete等内部字段名；"
    "将其解释为发布时间未知、原始文件未变、差异对照不完整等。"
)


def policy(version):
    if version not in KNOWN_VERSIONS:
        raise ProbeError("RESEARCH_METHOD_CHANGED_NEW_RUN_REQUIRED")
    return POLICY_V1 if version == "archive-versions-v1" else POLICY


TOOL = {
    "type": "function",
    "name": "compare_archived_versions",
    "description": "对照所选同一资料的两个归档快照；返回变化类型及两版可引用片段，最多比较两组。",
    "parameters": {
        "type": "object",
        "properties": {
            "earlier_id": {"type": "string"},
            "later_id": {"type": "string"},
        },
        "required": ["earlier_id", "later_id"],
        "additionalProperties": False,
    },
    "strict": True,
}


def pairs(repository, identities):
    grouped = defaultdict(list)
    with Session(repository.engine) as session:
        for row in session.execute(
            select(
                PublicDocument.id,
                PublicDocument.url,
                PublicDocument.title,
                PublicDocument.observed_at,
            ).where(PublicDocument.id.in_(identities))
        ):
            grouped[row.url].append(row)
    result = []
    for rows in grouped.values():
        rows.sort(key=lambda row: (row.observed_at, row.id))
        for earlier, later in zip(rows, rows[1:], strict=False):
            result.append(
                {
                    "earlier_id": earlier.id,
                    "later_id": later.id,
                    "title": later.title,
                    "earlier_saved_at": earlier.observed_at,
                    "later_saved_at": later.observed_at,
                }
            )
    return result[:20]


def compare(repository, earlier_id, later_id, allowed):
    if earlier_id == later_id or not {earlier_id, later_id} <= set(allowed):
        raise ProbeError("RESEARCH_SCOPE_VIOLATION")
    # compare only reads local files; archive_root is not used by this operation.
    comparison = PublicDocumentService(repository, ".").compare(later_id, earlier_id)
    if any(comparison[key]["content_state"] != "body_text" for key in ("earlier", "later")):
        raise ProbeError("PUBLIC_DOCUMENT_BODY_REQUIRED")
    with Session(repository.engine) as session:
        earlier, later = (session.get(PublicDocument, key) for key in (earlier_id, later_id))
        prefix = 0
        for left, right in zip(earlier.text, later.text, strict=False):
            if left != right:
                break
            prefix += 1
        evidence = []
        for document in (earlier, later):
            start = max(0, min(prefix - 160, len(document.text) - 700))
            end = min(start + 700, len(document.text))
            item = PublicDocumentService._evidence(document)[0]
            item.update(
                id=f"publicdoc:{document.id}:{start}:{end}",
                start=start,
                end=end,
                quote=document.text[start:end],
            )
            evidence.append(item)
    # Keep only comparison facts in the persistent answer. Raw source fragments
    # enter the ordinary citation registry and retain their original identities.
    comparison.pop("diff")
    for key in ("earlier", "later"):
        # Later uploads outside this run must not appear in its frozen context.
        comparison[key].pop("latest_document_id", None)
        comparison[key].pop("previous_document_id", None)
    comparison["evidence_ids"] = [item["id"] for item in evidence]
    return {
        "comparison": comparison,
        "evidence": evidence,
        "evidence_note": "仅提供首个差异附近的两版片段；完整差异范围与引用片段覆盖不同。",
    }


def historical_evidence_ids(repository, result):
    """Validate frozen pair bindings before auditing historical sources as history.

    This exemption is only for a research result. Memory's own source-current
    check stays unchanged, so old claims cannot become current knowledge by it.
    """
    if result.get("archive_versions_version") not in KNOWN_VERSIONS:
        return set()
    allowed = set((result.get("scope") or {}).get("archived_public_ids", []))
    evidence = {row.get("id"): row for row in result.get("evidence", [])}
    valid = set()
    with Session(repository.engine) as session:
        for record in result.get("archive_comparisons", [])[:2]:
            before, after = record.get("earlier", {}), record.get("later", {})
            ids = {before.get("id"), after.get("id")}
            if len(ids) != 2 or not ids <= allowed:
                continue
            rows = [session.get(PublicDocument, item.get("id")) for item in (before, after)]
            if any(row is None for row in rows):
                continue
            if rows[0].url != rows[1].url or (rows[0].observed_at, rows[0].id) >= (
                rows[1].observed_at,
                rows[1].id,
            ):
                continue
            if any(
                any(
                    item.get(key) != getattr(row, key)
                    for key in ("sha256", "text_sha256", "observed_at", "url")
                )
                for item, row in zip((before, after), rows, strict=True)
            ):
                continue
            refs = record.get("evidence_ids", [])
            if not refs or any(ref not in evidence for ref in refs):
                continue
            if {evidence[ref].get("public_document_id") for ref in refs} != ids:
                continue
            valid.update(refs)
    return valid
