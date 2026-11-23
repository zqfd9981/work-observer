"""Revisit an observation when sources or the reader's understanding change."""

import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from work_observer.collection.contracts import now
from work_observer.reports.industry import IndustryEvidence, body_hash
from work_observer.retrieval.catalog import Catalog
from work_observer.retrieval.enhanced import RetrievalService

DECISIONS = {"retain": "保留", "revise": "修正", "withdraw": "撤回", "unresolved": "仍未知"}


class IndustryRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    finding_index: int = Field(strict=True, ge=0)
    decision: Literal["retain", "revise", "withdraw", "unresolved"]
    reason: str = Field(min_length=5, max_length=800)
    interpretation: str = Field(min_length=1, max_length=1200)
    boundary: str = Field(min_length=1, max_length=600)
    evidence: list[IndustryEvidence] = Field(min_length=1, max_length=8)
    next_question: str = Field(min_length=5, max_length=600)


class IndustryEvolution:
    def __init__(self, service):
        self.service = service
        self.directory = service.directory / "evolution"

    def events(self, identity):
        self.service._path(identity)
        directory = self.directory / identity
        return sorted((json.loads(p.read_text(encoding="utf8")) for p in directory.glob("*.json")),
                      key=lambda row: (row["created_at"], row["id"]))

    def append(self, identity, event):
        self.service._path(identity)
        event = {**event, "id": uuid4().hex, "created_at": now()}
        directory = self.directory / identity
        directory.mkdir(parents=True, exist_ok=True)
        # Each decision is an independent file; concurrent saves cannot overwrite a prior decision.
        (directory / (event["id"] + ".json")).write_text(
            json.dumps(event, ensure_ascii=False, indent=2), encoding="utf8",
        )
        return event

    def candidates(self, job_ids):
        rows, _, _ = RetrievalService(self.service.repository)._records(None, job_ids, None)
        result = []
        for item in rows:
            record, original = item["record"], item["row"]
            body = record.get("description_text") or ""
            source = {
                "job_id": item["job_id"], "title": record.get("title") or "岗位名称未说明",
                "source": record.get("source"), "has_detail": bool(body),
                "document_id": original[2].id if original else None,
                "snapshot_id": original[1].id if original else None,
                "body_sha256": body_hash(body) if body else None,
                "observed_at": original[0].observed_at if original else None,
                "transport": original[2].transport if original else None,
            }
            verified = bool(body and original and Catalog(self.service.repository).document(
                original[2].id,
            )["integrity"] == "verified")
            source.update(eligible=verified, availability="verified" if verified else "unavailable")
            result.append({"source": source, "description": body if verified else ""})
        return result

    def decorate(self, report):
        events = self.events(report["id"])
        by_id = {s["job_id"]: s for s in report["sources"]}
        for index, finding in enumerate(report["findings"]):
            finding["initial_interpretation"] = finding["interpretation"]
            finding["decision"] = "initial"
            finding["history"] = []
            for ev in finding["evidence"]:
                ev["source"] = by_id[ev["job_id"]]
            for event in events:
                if event.get("kind") != "revision" or event["finding_index"] != index:
                    continue
                finding["history"].append(event)
                finding.update({key: event[key] for key in (
                    "interpretation", "boundary", "evidence", "decision", "next_question",
                )})
        candidates = self.candidates(list(by_id))
        current = {row["source"]["job_id"]: row for row in candidates}
        changes = []
        for key, old in by_id.items():
            new = current.get(key)
            if not new:
                kind = "岗位当前不可读"
            elif not old["has_detail"] and new["source"]["has_detail"]:
                kind = "原缺正文已补全"
            elif old["body_sha256"] != new["source"]["body_sha256"]:
                kind = "正文内容已变化"
            elif old["has_detail"] and not new["description"]:
                kind = "正文当前无法核验"
            else:
                continue
            changes.append({"job_id": key, "title": old["title"], "kind": kind,
                            "before_document_id": old["document_id"],
                            "after_document_id": new["source"]["document_id"] if new else None})
        for finding in report["findings"]:
            finding["needs_review"] = False
            for ev in finding["evidence"]:
                source = ev["source"]
                self.service.audit_source(source)
                new = current.get(ev["job_id"])
                if (not new or source["body_sha256"] != new["source"]["body_sha256"]
                        or source["availability"] != "verified"):
                    finding["needs_review"] = True
        report["evolution"] = {
            "checked_at": now(), "changes": changes, "candidates": candidates,
            "revisions": sum(e.get("kind") == "revision" for e in events),
            "pending_findings": sum(f["needs_review"] for f in report["findings"]),
            "inquiries": [e for e in events if e.get("kind") == "inquiry"],
            "notice": "自动检查本地归档；资料变化不等于行业趋势。修订记录的是认识变化，"
            "首轮摘要与样本保持原貌，当前判断见各观察卡片。",
        }
        return report

    def revise(self, identity, raw):
        data = IndustryRevisionInput.model_validate(raw)
        report = self.service.get(identity)
        if data.finding_index >= len(report["findings"]):
            raise ValueError("请选择这份观察中的结论。")
        previous = report["findings"][data.finding_index]
        if data.decision == "retain" and (
            data.interpretation != previous["interpretation"]
            or data.boundary != previous["boundary"]
        ):
            raise ValueError("修改了判断或适用范围，请选择修正。")
        scope = {s["job_id"] for s in report["sources"]}
        if any(ev.job_id not in scope for ev in data.evidence):
            raise ValueError("请选择本轮观察范围内的岗位；扩大样本请另建观察。")
        candidates = {row["source"]["job_id"]: row for row in report["evolution"]["candidates"]}
        evidence = []
        for ev in data.evidence:
            row = candidates.get(ev.job_id)
            start = row["description"].find(ev.quote) if row else -1
            if start < 0:
                raise ValueError("修订依据必须来自当前可核验的正文，请重新选择原文段落。")
            evidence.append({**ev.model_dump(), "start": start, "end": start + len(ev.quote),
                             "source": row["source"]})
        self.append(identity, {
            **data.model_dump(exclude={"evidence"}), "kind": "revision", "evidence": evidence,
            "previous_interpretation": previous["interpretation"],
            "previous_boundary": previous["boundary"], "previous_decision": previous["decision"],
            "origin": "reader_review", "change_type": "understanding_revision",
        })
        return self.service.get(identity)
