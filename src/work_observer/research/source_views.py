"""Bounded, literal views of already-read Catalog evidence; no semantic classification.

Offsets use Python string positions, as Catalog does. ``fully_read`` only means every
character of this version's JD body was read. ``all_sentences_shown`` separately
records display completeness. Neither proves that a fact exists or is absent.
The caller must pass actual read evidence, never unvisited search/list results.
"""

import hashlib
import json
import re
from collections import defaultdict
from copy import deepcopy

_SEPARATORS = re.compile(r"[。；！？;!?](?:\r\n|[\r\n])*|\r\n|[\r\n]")
_SOURCE_FIELDS = ("document_id", "document_sha256", "content_sha256")
_LAYER_LABELS = {
    "job_description": "招聘正文（已读原文）",
    "list_summary": "列表摘要（不是招聘全文）",
}
_LAYER_ALIASES = {
    "job_description": "job_description",
    "description_text": "job_description",
    "detail": "job_description",
    "jd": "job_description",
    "list_summary": "list_summary",
    "summary": "list_summary",
    "title": "list_summary",
}
_HEADING = re.compile(
    r"^(?:#{1,6}\s+|(?:方向|岗位方向|研究方向)[一二三四五六七八九十\d：:、\s]"
    r"|[一二三四五六七八九十]+[、.．].{0,50}(?:方向|职责|要求|背景)$)"
)
_SECTION_HEADINGS = {"岗位职责", "岗位要求", "任职要求", "工作内容", "业务背景"}
_PRIORITY_HEADINGS = {"优先加分项", "优先条件", "优先项", "加分项"}


def _literal_section(text):
    return text.strip().rstrip("：:") in _SECTION_HEADINGS | _PRIORITY_HEADINGS


def _heading(text):
    stripped = text.strip()
    if not stripped or len(stripped) > 100:
        return None
    if stripped.rstrip("：:") in _PRIORITY_HEADINGS:
        return 3
    if stripped.rstrip("：:") in _SECTION_HEADINGS:
        return 2
    if stripped.endswith(("：", ":")) or _HEADING.search(stripped):
        prefix = re.match(r"^(#{1,6})\s", stripped)
        return len(prefix[1]) if prefix else 2
    return None


def _ranges(rows):
    """Merge overlapping/adjacent ranges, checking their literal overlap."""
    blocks = []
    conflict = False
    for row in sorted(rows, key=lambda item: (item["start"], item["end"], item["id"])):
        start, end, text = row["start"], row["end"], row["quote"]
        if not blocks or start > blocks[-1]["end"]:
            blocks.append({"start": start, "end": end, "text": text})
            continue
        previous = blocks[-1]
        overlap = min(end, previous["end"]) - start
        if (
            previous["text"][start - previous["start"] : start - previous["start"] + overlap]
            != text[:overlap]
        ):
            conflict = True
        if end > previous["end"]:
            previous["text"] += text[overlap:]
            previous["end"] = end
    return blocks, conflict


def _parts(block, rows, total):
    """Split literal spans, then keep each citation inside one original evidence."""
    text, base = block["text"], block["start"]
    cursor = 0
    separator_stops = {match.end() for match in _SEPARATORS.finditer(text)}
    for stop in sorted(separator_stops | {len(text)}):
        unit_start, unit_end = base + cursor, base + stop
        complete = (cursor > 0 or base == 0) and (stop in separator_stops or block["end"] == total)
        while cursor < stop:
            absolute = base + cursor
            candidates = [row for row in rows if row["start"] <= absolute < row["end"]]
            row = max(candidates, key=lambda item: (item["end"], item["id"]))
            end = min(base + stop, row["end"])
            value = text[cursor : end - base]
            if value.strip():
                yield row, absolute, end, value, unit_start, unit_end, complete
            cursor = end - base


def build_source_views(evidence, *, max_evidence=60, max_sentences=200):
    """Return ``jobs[].sources[].sentences`` with exact spans and stable IDs.

    Each sentence carries its original ``evidence_id`` and heuristic heading
    ``context`` (only within contiguous read text). Headings locate text; they do
    not assign duties. Unknown/malformed structures are excluded with ``issues``.
    Limits cannot exceed 60 evidence / 200 sentences. Coverage is computed from
    validated read ranges, independently of sentence display truncation. Explicit
    summary layers never count as a fully-read JD; gaps are half-open intervals.
    At most 42,000 input quote characters are processed (60 Catalog chunks);
    additional rows get an explicit limit issue. Whitespace-only lines have no
    standalone citation. No body or heading text is fetched from outside input.

    ``unit_*`` describes one separator-delimited span before evidence slicing,
    not a proven semantic unit. All its evidence pieces share a unit ID based on
    job/version/layer/absolute bounds. ``unit_complete_read`` is false when an
    unknown block edge might cut that span; those bounds then describe only the
    observed fragment. ``unit_all_parts_shown`` independently checks that the
    displayed pieces cover the entire observed unit without gaps. Display caps
    or omitted whitespace-only evidence pieces can make it false. Cross-sentence
    qualifications still require review. Existing sentence IDs are unchanged.
    Optional source hashes/IDs are copied from each actual evidence, never filled
    into a sentence from another row. Conflicting nonempty identities within a
    version/layer block the entire source's citations; absent metadata is None.
    """
    if type(max_evidence) is not int or not 1 <= max_evidence <= 60:
        raise ValueError("max_evidence must be between 1 and 60")
    if type(max_sentences) is not int or not 1 <= max_sentences <= 200:
        raise ValueError("max_sentences must be between 1 and 200")
    result = {
        "jobs": [],
        "issues": [],
        "truncated": False,
        "all_sentences_shown": True,
        "sentence_count": 0,
        "accepted_evidence_count": 0,
    }
    if not isinstance(evidence, (list, tuple)):
        result["issues"].append({"code": "invalid_evidence_collection"})
        result["all_sentences_shown"] = False
        return result
    grouped = defaultdict(list)
    limited_sources = set()
    input_truncated = len(evidence) > max_evidence
    result["truncated"] = input_truncated
    result["all_sentences_shown"] = not input_truncated
    if input_truncated:
        result["issues"].append({"code": "evidence_limit", "omitted": len(evidence) - max_evidence})
    accepted_chars = 0
    for index, row in enumerate(evidence[:max_evidence]):
        code = None
        if not isinstance(row, dict):
            code = "invalid_evidence_structure"
        elif not all(
            isinstance(row.get(key), str) and row[key] for key in ("id", "job_id", "snapshot_id")
        ):
            code = "missing_source_identity"
        elif not isinstance(row.get("quote"), str):
            code = "invalid_quote"
        elif not all(type(row.get(key)) is int for key in ("start", "end", "full_text_length")):
            code = "invalid_offsets"
        elif not 0 <= row["start"] <= row["end"] <= row["full_text_length"] or row["end"] - row[
            "start"
        ] != len(row["quote"]):
            code = "invalid_offsets"
        elif not row["quote"].strip():
            code = "empty_body_no_evidence"
        elif any(
            row.get(key) is not None and not isinstance(row[key], str) for key in _SOURCE_FIELDS
        ):
            code = "invalid_source_metadata"
        layer = None
        if code is None:
            supplied_layer = row.get("source_layer", row.get("field", "job_description"))
            layer = _LAYER_ALIASES.get(supplied_layer) if isinstance(supplied_layer, str) else None
            if layer is None:
                code = "unknown_source_layer"
            elif accepted_chars + len(row["quote"]) > 42_000:
                code = "read_text_limit"
                result["truncated"] = True
                limited_sources.add((row["job_id"], row["snapshot_id"], layer))
        if code:
            result["issues"].append({"index": index, "code": code})
            result["all_sentences_shown"] = False
            continue
        grouped[(row["job_id"], row["snapshot_id"], layer)].append(row)
        accepted_chars += len(row["quote"])

    jobs, displayed = {}, 0
    for (job_id, snapshot_id, layer), rows in grouped.items():
        limited = input_truncated or (job_id, snapshot_id, layer) in limited_sources
        job = jobs.setdefault(job_id, {"job_id": job_id, "sources": []})
        blocks, conflict = _ranges(rows)
        lengths = {row["full_text_length"] for row in rows}
        total = next(iter(lengths)) if len(lengths) == 1 else None
        issues = []
        if conflict:
            issues.append("conflicting_overlap")
        if total is None:
            issues.append("conflicting_full_text_length")
        source_metadata = {}
        for key in _SOURCE_FIELDS:
            values = {row[key] for row in rows if row.get(key)}
            source_metadata[key] = next(iter(values)) if len(values) == 1 else None
            if len(values) > 1:
                issues.append("conflicting_" + key)
        intervals = [{"start": b["start"], "end": b["end"]} for b in blocks]
        gaps, cursor = [], 0
        if total is not None:
            for block in blocks:
                if cursor < block["start"]:
                    gaps.append({"start": cursor, "end": block["start"]})
                cursor = block["end"]
            if cursor < total:
                gaps.append({"start": cursor, "end": total})
        source = {
            "snapshot_id": snapshot_id,
            **source_metadata,
            "source_layer": layer,
            "label": _LAYER_LABELS[layer],
            "sentences": [],
            "issues": issues,
            "coverage": {
                "intervals": intervals,
                "read_chars": sum(b["end"] - b["start"] for b in blocks),
                "full_text_length": total,
                "gaps": gaps,
                "fully_read": total is not None
                and not gaps
                and not issues
                and layer == "job_description",
            },
            "all_sentences_shown": not limited and not issues,
            "truncated": limited,
            "context_notice": "标题/方向仅作已读范围内的启发式定位，不推断岗位职责或适用范围。",
        }
        job["sources"].append(source)
        if issues:
            result["all_sentences_shown"] = False
            continue
        for block in blocks:
            headings = []
            for row, start, end, text, unit_start, unit_end, complete in _parts(block, rows, total):
                line_start = start == 0 or (
                    start > block["start"] and block["text"][start - block["start"] - 1] in "\r\n"
                )
                inline_section = (
                    start > block["start"]
                    and block["text"][start - block["start"] - 1] in "。；！？;!?"
                    and _literal_section(text)
                )
                level = _heading(text) if line_start or inline_section else None
                if level is not None:
                    headings = [heading for heading in headings if heading["level"] < level]
                if displayed >= max_sentences:
                    source["truncated"] = result["truncated"] = True
                    source["all_sentences_shown"] = result["all_sentences_shown"] = False
                    continue
                identity = hashlib.sha256(f"{row['id']}:{start}:{end}".encode()).hexdigest()[:24]
                unit_id = hashlib.sha256(
                    json.dumps([job_id, snapshot_id, layer, unit_start, unit_end]).encode()
                ).hexdigest()[:24]
                sentence = {
                    "sentence_id": identity,
                    "evidence_id": row["id"],
                    "job_id": job_id,
                    "snapshot_id": snapshot_id,
                    **{key: row.get(key) or None for key in _SOURCE_FIELDS},
                    "start": start,
                    "end": end,
                    "text": text,
                    "unit_id": unit_id,
                    "unit_start": unit_start,
                    "unit_end": unit_end,
                    "unit_complete_read": complete,
                    "context": [dict(heading) for heading in headings],
                    "heading_heuristic": level is not None,
                    "read_boundary_start": start == block["start"] and start > 0,
                    "read_boundary_end": end == block["end"] and end < total,
                    "evidence_boundary_start": start == row["start"] and start > block["start"],
                    "evidence_boundary_end": end == row["end"] and end < block["end"],
                }
                source["sentences"].append(sentence)
                displayed += 1
                if level is not None:
                    headings.append(
                        {
                            "text": text,
                            "start": start,
                            "end": end,
                            "evidence_id": row["id"],
                            "job_id": job_id,
                            "snapshot_id": snapshot_id,
                            **{key: row.get(key) or None for key in _SOURCE_FIELDS},
                            "level": level,
                            "heuristic": True,
                        }
                    )
        units = defaultdict(list)
        for sentence in source["sentences"]:
            units[sentence["unit_id"]].append(sentence)
        for parts in units.values():
            cursor = parts[0]["unit_start"]
            for part in parts:
                if part["start"] != cursor:
                    break
                cursor = part["end"]
            all_shown = cursor == parts[0]["unit_end"]
            for part in parts:
                part["unit_all_parts_shown"] = all_shown
    result["jobs"] = list(jobs.values())
    result["sentence_count"] = displayed
    result["accepted_evidence_count"] = sum(len(rows) for rows in grouped.values())
    return result


def model_source_view(view):
    """Compact repeated provenance; original read evidence remains in this run's history.

    This projection is for model transport, never a registration/validation input.
    Each sentence/context keeps its evidence_id, literal text and offsets. The
    removed job/version/document fields are available on that exact evidence,
    not inferred from a group's metadata (which may contain missing identities).
    Coverage, truncation, boundaries and unit completeness remain unchanged.
    Return a deep copy: persisted source findings and canonical views retain all
    original provenance, including absent fields on individual evidence rows.
    """
    compact = deepcopy(view)
    compact["format"] = "source-view-compact-v1"
    compact["provenance_notice"] = (
        "分句及标题上下文的来源身份按各自evidence_id回查本研究已读evidence（可在此前阅读响应）；"
        "原文、位置、完整性与截断标记均保留。分组摘要不能补全单条来源缺失字段。"
    )
    for job in compact["jobs"]:
        for source in job["sources"]:
            for sentence in source["sentences"]:
                for span in (sentence, *sentence["context"]):
                    for field in ("job_id", "snapshot_id", *_SOURCE_FIELDS):
                        span.pop(field, None)
    return compact
