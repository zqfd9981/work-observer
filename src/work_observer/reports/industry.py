"""Source-bound industry observations, kept separate from recruitment facts."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.retrieval.catalog import Catalog
from work_observer.retrieval.enhanced import RetrievalService


class IndustryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    job_id: str = Field(pattern="^[a-f0-9]{32}$")
    quote: str = Field(min_length=8, max_length=1200)
    role: str = Field(default="原文依据，要求性质仍须结合上下文核对", max_length=150)


class IndustryFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=100)
    facet: str = Field(pattern="^(work|ability|threshold|change)$")
    basis: str = Field(default="synthesis", pattern="^(direct|synthesis|inference)$")
    interpretation: str = Field(min_length=1, max_length=1200)
    boundary: str = Field(min_length=1, max_length=600)
    evidence: list[IndustryEvidence] = Field(min_length=1, max_length=8)


class IndustryObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    question: str = Field(min_length=1, max_length=1500)
    summary: str = Field(min_length=1, max_length=2000)
    source_note: str = Field(default="", max_length=1000)
    job_ids: list[str] = Field(min_length=1, max_length=20)
    findings: list[IndustryFinding] = Field(min_length=1, max_length=10)
    unknowns: list[str] = Field(min_length=1, max_length=10)
    next_questions: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def bounded_scope(self):
        if (len(self.job_ids) != len(set(self.job_ids))
                or any(not re.fullmatch(r"[a-f0-9]{32}", key) for key in self.job_ids)):
            raise ValueError("请选择最多20个不同的已有岗位。")
        if any(ev.job_id not in self.job_ids for row in self.findings for ev in row.evidence):
            raise ValueError("观察引用的岗位必须包含在本次样本范围中。")
        if any(not text.strip() or len(text) > 1500
               for text in self.unknowns + self.next_questions):
            raise ValueError("未知与后续问题请填写完整文字，每条最多1500字。")
        return self


def body_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


class IndustryObservationService:
    def __init__(self, repository, reports_dir):
        self.repository = repository
        self.directory = Path(reports_dir) / "industry"

    def _path(self, identity):
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("请选择已保存的行业观察。")
        return self.directory / (identity + ".json")

    def listing(self):
        if not self.directory.exists():
            return []
        reports = [json.loads(path.read_text(encoding="utf8"))
                   for path in self.directory.glob("*.json")]
        return [{key: row[key] for key in ("id", "title", "created_at", "summary", "sample")}
                for row in sorted(reports, key=lambda row: row["created_at"], reverse=True)[:100]]

    def save(self, raw):
        data = IndustryObservationInput.model_validate(raw)
        records, _, _ = RetrievalService(self.repository)._records(None, data.job_ids, None)
        if set(data.job_ids) != {row["job_id"] for row in records}:
            raise ValueError("部分岗位已不可读取，请重新选择当前已有样本。")
        sources, bodies = {}, {}
        for row in records:
            key, record, original = row["job_id"], row["record"], row["row"]
            text = record.get("description_text") or ""
            doc = Catalog(self.repository).document(original[2].id) if original else None
            source = {
                "job_id": key, "title": record.get("title") or "岗位名称未说明",
                "source": record.get("source") or "unknown", "has_detail": bool(text),
                "eligible": bool(text and original and doc["integrity"] == "verified"),
                "document_id": original[2].id if original else None,
                "snapshot_id": original[1].id if original else None,
                "body_sha256": body_hash(text) if text else None,
                "observed_at": original[0].observed_at if original else max(
                    record.get("field_observed_at", {}).values(), default=None,
                ),
                "transport": original[2].transport if original else None,
                "notice": "取得通道不构成第二个独立招聘来源；观察时间不是职位发布时间。",
            }
            sources[key], bodies[key] = source, text
        findings = []
        for finding in data.findings:
            evidence = []
            for ev in finding.evidence:
                source, text = sources[ev.job_id], bodies[ev.job_id]
                start = text.find(ev.quote)
                if not source["eligible"] or start < 0:
                    raise ValueError("引用必须出自本次可核验的完整正文，不能用标题或改写句替代。")
                evidence.append({**ev.model_dump(), "start": start, "end": start+len(ev.quote)})
            findings.append({**finding.model_dump(exclude={"evidence"}), "evidence": evidence})
        observed = [row["observed_at"] for row in sources.values() if row["observed_at"]]
        report = {
            "id": uuid4().hex, "created_at": now(), "title": data.title,
            "question": data.question, "summary": data.summary, "source_note": data.source_note,
            "origin": "assisted_analysis", "origin_label": "基于已读归档的辅助研究，语义待核对",
            "sample": {
                "jobs": len(sources),
                "readable_details": sum(s["eligible"] for s in sources.values()),
                "missing_details": sum(not s["has_detail"] for s in sources.values()),
                "unverified_details": sum(s["has_detail"] and not s["eligible"]
                                          for s in sources.values()),
                "cited_jobs": len({ev["job_id"] for f in findings for ev in f["evidence"]}),
                "sources": dict(Counter(s["source"] for s in sources.values())),
                "observed_from": min(observed) if observed else None,
                "observed_to": max(observed) if observed else None,
                "notice": "这是已选招聘样本的横截面观察，非全行业占比或时间趋势；"
                "分类与工作线可重叠，缺正文不表示没有相关要求。",
            },
            "sources": list(sources.values()), "findings": findings,
            "unknowns": data.unknowns, "next_questions": data.next_questions,
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(report["id"]).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                            encoding="utf8")
        return self.get(report["id"])

    def get(self, identity):
        path = self._path(identity)
        if not path.is_file():
            raise ValueError("未找到这份行业观察。")
        report = json.loads(path.read_text(encoding="utf8"))
        for source in report["sources"]:
            available = False
            if source["eligible"]:
                try:
                    doc = Catalog(self.repository).document(source["document_id"])
                    version = next((row for row in doc["versions"]
                                    if row["snapshot_id"] == source["snapshot_id"]), None)
                    available = bool(doc["integrity"] == "verified" and version and body_hash(
                        version["payload"].get("description", ""),
                    ) == source["body_sha256"])
                except (ValueError, OSError, ProbeError):
                    available = False
            source["availability"] = "verified" if available else (
                "missing_detail" if not source["has_detail"] else "unavailable"
            )
        return report

    def inquiry(self, identity, finding_index, question, store):
        from work_observer.research.projects import ProjectService

        report = self.get(identity)
        if finding_index is not None and not 0 <= finding_index < len(report["findings"]):
            raise ValueError("请重新选择本观察中要继续核对的一条结论。")
        findings = ([report["findings"][finding_index]] if finding_index is not None
                    else report["findings"])
        job_ids = list(dict.fromkeys(ev["job_id"] for row in findings for ev in row["evidence"]))
        if any(source["availability"] != "verified" for source in report["sources"]
               if source["job_id"] in job_ids):
            raise ValueError("这条观察的原始正文暂不可核验，请先回查来源，不能换用其他资料冒充。")
        records, _, _ = RetrievalService(self.repository)._records(None, job_ids, None)
        if {row["job_id"] for row in records} != set(job_ids):
            raise ValueError("部分原岗位已不在当前可读范围，请先回查样本。")
        finding = findings[0] if finding_index is not None else None
        goal = (
            question + "\n\n起点：" + report["title"]
            + "\n原观察保存于：" + report["created_at"]
            + ("\n待核归纳：" + finding["interpretation"]
               + "\n原保留条件：" + finding["boundary"] if finding else "")
            + "\n上面的观察是辅助分析，不是独立证据。先回读所选JD，核对工作、交付物、"
            "能力与要求强度；保留未读、缺失与其他解释。来源或样本变化不能直接作为市场趋势。"
        )
        service = ProjectService(store)
        project = service.create(title="行业观察追问："+report["title"][:100], goal=goal,
                                 job_ids=job_ids, public_document_ids=[], max_public=0)
        project = service.add(project["id"], goal, revision=project["revision"],
                              coverage_mode="all", allow_public=False,
                              completion="回读选定JD，逐条说明观察的依据、反例与仍待核实的条件。")
        return {"project_id": project["id"], "job_ids": job_ids,
                "step_id": project["steps"][-1]["id"], "started": False}
