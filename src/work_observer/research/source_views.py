"""Bounded, literal views of already-read Catalog evidence; no semantic classification.

Offsets use Python string positions, as Catalog does. ``fully_read`` only means every
character of this version's JD body was read. ``all_sentences_shown`` separately
records display completeness. Neither proves that a fact exists or is absent.
The caller must pass actual read evidence, never unvisited search/list results.
"""

import hashlib
import re
from collections import defaultdict

_SEPARATORS = re.compile(r"[。；！？;!?](?:\r\n|[\r\n])*|\r\n|[\r\n]")
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


def _heading(text):
    stripped = text.strip()
    if not stripped or len(stripped) > 100:
        return None
    if stripped.endswith(("：", ":")) or _HEADING.search(stripped):
        prefix = re.match(r"^(#{1,6})\s", stripped)
        return len(prefix[1]) if prefix else 2
    if stripped in {"岗位职责", "岗位要求", "任职要求", "工作内容", "业务背景"}:
        return 1
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


def _parts(block, rows):
    """Split literal spans, then keep each citation inside one original evidence."""
    text, base = block["text"], block["start"]
    cursor = 0
    for stop in [match.end() for match in _SEPARATORS.finditer(text)] + [len(text)]:
        while cursor < stop:
            absolute = base + cursor
            candidates = [row for row in rows if row["start"] <= absolute < row["end"]]
            row = max(candidates, key=lambda item: (item["end"], item["id"]))
            end = min(base + stop, row["end"])
            value = text[cursor : end - base]
            if value.strip():
                yield row, absolute, end, value
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
            for row, start, end, text in _parts(block, rows):
                line_start = start == 0 or (
                    start > block["start"] and block["text"][start - block["start"] - 1] in "\r\n"
                )
                level = _heading(text) if line_start else None
                if level is not None:
                    headings = [heading for heading in headings if heading["level"] < level]
                if displayed >= max_sentences:
                    source["truncated"] = result["truncated"] = True
                    source["all_sentences_shown"] = result["all_sentences_shown"] = False
                    continue
                identity = hashlib.sha256(f"{row['id']}:{start}:{end}".encode()).hexdigest()[:24]
                sentence = {
                    "sentence_id": identity,
                    "evidence_id": row["id"],
                    "start": start,
                    "end": end,
                    "text": text,
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
                            "level": level,
                            "heuristic": True,
                        }
                    )
    result["jobs"] = list(jobs.values())
    result["sentence_count"] = displayed
    result["accepted_evidence_count"] = sum(len(rows) for rows in grouped.values())
    return result
