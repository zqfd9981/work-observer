"""Read selected job sources as known at a bounded historical cutoff."""

from copy import deepcopy

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.retrieval.catalog import Catalog
from work_observer.retrieval.enhanced import RetrievalService, normalized_time

VERSION = "historical-job-windows-v1"
POLICY = (
    "需要核对某个来源截止时点的岗位原文时，使用read_historical_job(job_id,as_of,start)。"
    "as_of必须有时区且不晚于本轮研究开始；仅限本轮岗位，不联网、不扩大范围。"
    "工具同时约束观察和入库时间，每次最多5600字，按next_start续读；引用保持原版本和字符位置。"
    "当时尚未入库或缺正文不表示网站没有该岗位或职责。来源截止不是网站发布时间。"
    "对照面板时分别读取两个明确截止；compare_history仅比较最近两个不同详情版本，"
    "不能代替指定时点的对照。read_job是本轮当前正文，不能冒充过去。"
    "单一时点原文、后来补齐和来源构成变化不能直接证明需求增减；"
    "区分正文变化、资料可用性、样本和解释变化，未读部分保持未知。"
)
TOOL = {
    "type": "function",
    "name": "read_historical_job",
    "strict": True,
    "description": "按明确来源截止分段读取本轮岗位的历史原文；同时约束观察与入库时间。",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "job_id": {"type": "string"},
            "as_of": {"type": "string", "description": "带时区的ISO时间，不晚于研究开始"},
            "start": {"type": "integer", "minimum": 0},
        },
        "required": ["job_id", "as_of", "start"],
    },
}


def proposals(base):
    result = deepcopy(base)
    next(row for row in result if row["name"] == "propose_research_memory")["parameters"][
        "properties"
    ]["supporting_tool"]["enum"].append(TOOL["name"])
    return result


def read(repository, job_id, as_of, start, allowed, frozen_at):
    if job_id not in allowed:
        raise ProbeError("RESEARCH_SCOPE_VIOLATION")
    cutoff = normalized_time(as_of)
    if cutoff is None or cutoff > normalized_time(frozen_at):
        raise ProbeError("RESEARCH_HISTORY_TIME_OUT_OF_SCOPE")
    if type(start) is not int or start < 0:
        raise ProbeError("INVALID_HISTORICAL_JOB_WINDOW")
    records, _, _ = RetrievalService(repository)._records(None, [job_id], cutoff)
    result = {
        "job_id": job_id,
        "as_of": cutoff,
        "research_cutoff": frozen_at,
        "start": start,
        "end": start,
        "next_start": None,
        "has_more": False,
        "evidence": [],
        "note": "仅表示当时本地已入库资料；来源截止不等于网站发布时间。",
    }
    if not records:
        return {
            **result,
            "status": "not_observed",
            "gap": "截止时尚无已入库观察，不能推断网站不存在该岗位。",
        }
    item = records[0]
    record = item["record"]
    result["job"] = {
        key: record.get(key) for key in ("title", "company_name_raw", "city", "source_published_at")
    }
    if not item["row"] or not record.get("description_text"):
        return {
            **result,
            "status": "body_unavailable",
            "gap": "截止时没有可读正文，不能判断未披露某项职责。",
        }
    document = item["row"][2]
    if Catalog(repository).document(document.id)["integrity"] != "verified":
        raise ProbeError("EVIDENCE_DOCUMENT_INTEGRITY_FAILED")
    text = record["description_text"]
    if item["row"][1].payload.get("description") != text:
        raise ProbeError("EVIDENCE_CONTENT_MISMATCH")
    if start > len(text):
        raise ProbeError("INVALID_HISTORICAL_JOB_WINDOW")
    end = min(start + 5600, len(text))
    evidence = []
    for position in range(start, end, 700):
        source = RetrievalService._evidence(item, position, 0, [], [])
        source.pop("retrieval")
        source["source_published_at"] = record.get("source_published_at")
        source["historical_cutoffs"] = [cutoff]
        evidence.append(source)
    return {
        **result,
        "status": "read",
        "end": end,
        "next_start": end if end < len(text) else None,
        "has_more": end < len(text),
        "full_text_length": len(text),
        "evidence": evidence,
    }
