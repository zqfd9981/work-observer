"""Small reading aids for ordinary research, derived only from evidence already read."""

import json
from collections import defaultdict

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.source_views import build_source_views


def job_window(evidence, start=None, *, limit=8):
    """Read existing frozen fragments around a character position without changing citations."""
    start = 0 if start is None else start
    if type(start) is not int or start < 0:
        raise ProbeError("INVALID_JOB_SOURCE_WINDOW")
    ordered = sorted(evidence, key=lambda row: row["start"])
    length = max((row.get("full_text_length", row["end"]) for row in ordered), default=0)
    available_end = max((row["end"] for row in ordered), default=0)
    selected = [row for row in ordered if row["end"] > start][:limit]
    first = selected[0]["start"] if selected else min(start, length)
    end = selected[-1]["end"] if selected else first
    return {
        "start": first,
        "end": end,
        "full_text_length": length,
        "next_start": end if selected and end < available_end else None,
        "has_more": bool(selected and end < available_end),
        "evidence": selected,
        "note": "按定位位置所在片段返回原文，引用与字符位置保持不变。"
        "next_start可继续读取后面的片段；正文未读到的范围仍保留未知，不能当作没有要求。",
    }


def job_windows(pool, reads):
    """Read small windows from several frozen JDs, preserving each one's continuation."""
    if (
        not isinstance(reads, list)
        or not 1 <= len(reads) <= 6
        or any(
            not isinstance(row, dict)
            or set(row) != {"job_id", "start"}
            or not isinstance(row["job_id"], str)
            for row in reads
        )
    ):
        raise ProbeError("INVALID_JOB_READ_BATCH")
    if any(row["job_id"] not in pool for row in reads):
        raise ProbeError("RESEARCH_SCOPE_VIOLATION")
    evidence, windows = [], []
    per_job_limit = min(8, 24 // len(reads))
    for request in reads:
        window = job_window(pool[request["job_id"]], request["start"], limit=per_job_limit)
        evidence.extend(window["evidence"])
        windows.append(
            {
                "job_id": request["job_id"],
                **{key: value for key, value in window.items() if key != "evidence"},
            }
        )
    return {
        "evidence": evidence,
        "windows": windows,
        "note": "本次合计最多24个原始片段，每份最多8个，不表示已读全文；"
        "多份JD的has_more为true时，用read_jobs携带各份next_start继续批读；"
        "只剩一份时也可用read_job续读。",
    }


def reading_guide(evidence, returned_ids):
    touched = {
        (row["job_id"], row["snapshot_id"])
        for row in evidence
        if row["id"] in returned_ids and row.get("job_id") and row.get("snapshot_id")
    }
    if not touched:
        return None
    rows = [row for row in evidence if (row.get("job_id"), row.get("snapshot_id")) in touched]
    receipts = {row["id"]: row for row in rows}
    view = build_source_views(rows)

    def reference(identity):
        return receipts[identity].get("citation_key") or identity

    def heading(row):
        return {
            "text": row["text"],
            "start": row["start"],
            "end": row["end"],
            "citation_key": reference(row["evidence_id"]),
        }

    guides, remaining, omitted_sources = [], 12000, 0
    for job in view["jobs"]:
        for source in job["sources"]:
            units = defaultdict(list)
            headings = []
            for sentence in source["sentences"]:
                units[sentence["unit_id"]].append(sentence)
                if sentence["heading_heuristic"]:
                    headings.append(heading(sentence.get("heading_span", sentence)))
            guide = {
                "job_id": job["job_id"],
                "snapshot_id": source["snapshot_id"],
                "coverage": source["coverage"],
                "issues": source["issues"],
                "headings": [],
                "passages": [],
                "omitted_headings": 0,
                "omitted_passages": 0,
            }
            size = len(json.dumps(guide, ensure_ascii=False))
            if size > remaining:
                omitted_sources += 1
                continue
            remaining -= size
            for row in headings:
                size = len(json.dumps(row, ensure_ascii=False))
                if size > remaining:
                    guide["omitted_headings"] += 1
                    continue
                guide["headings"].append(row)
                remaining -= size
            for parts in units.values():
                identities = list(dict.fromkeys(part["evidence_id"] for part in parts))
                complete = all(
                    part["unit_complete_read"] and part["unit_all_parts_shown"] for part in parts
                )
                if len(identities) == 1 and complete:
                    continue
                passage = {
                    "text": "".join(part["text"] for part in parts),
                    "start": parts[0]["start"],
                    "end": parts[-1]["end"],
                    "citation_keys": [reference(identity) for identity in identities],
                    "headings": [heading(row) for row in parts[0]["context"]],
                    "complete_read": complete,
                }
                size = len(json.dumps(passage, ensure_ascii=False))
                if size > remaining:
                    guide["omitted_passages"] += 1
                    continue
                guide["passages"].append(passage)
                remaining -= size
            guides.append(guide)
    return {
        "sources": guides,
        "omitted_sources": omitted_sources,
        "source_view_truncated": view["truncated"] or not view["all_sentences_shown"],
        "note": (
            "只整理本轮实际已读的岗位原文；标题按字面定位，不自动判定职责或资格性质。"
            "passages连接跨引用片段的连续语句，或标出边缘未读完整的语句；"
            "跨片段条件须一起核对，引用列出的全部citation_keys，不能只取前半句漏掉优先、例外或否定。"
            "complete_read只表示该语句的已读字符连续完整，不表示语义已核实；"
            "coverage.gaps是尚未读到的范围，不可当作没有要求。"
            "分句仅按标点和换行定位，跨句修饰仍须结合上下文。"
            "同一正文的不同方向须分别解释；‘专攻之一’不能变成每人承担全部方向，"
            "章节中的团队或运行角色也不能直接改成应聘者的组织权限。"
            "这些是原文定位辅助，不是新来源、模型摘要或新增核对步骤；"
            "按问题需要补读原文或提交回答，无须为这些提示额外登记分项。"
        ),
    }
