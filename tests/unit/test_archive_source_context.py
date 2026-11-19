"""Archive review uses the cited snapshot and distinguishes full text from excerpts."""

import asyncio
from copy import deepcopy
from pathlib import Path

from sqlalchemy.orm import Session
from test_public_documents import service as service

from work_observer.connectors import public_documents
from work_observer.connectors.public_models import PublicDocument
from work_observer.quality.source_context import source_context


def result_for(saved):
    return {
        "scope": {"jobs": []},
        "evidence": saved["evidence"],
        "claims": [{"evidence_ids": [saved["evidence"][0]["id"]]}],
    }


def test_material_shows_original_full_text_after_revision_without_changing_answer(service):
    text = "合成任务：整理资料。\n" + "合成正文" * 200 + "\n未被引用的审批限制。\n"
    saved = service.archive_text("合成工作说明", text, "合成来源")
    result = result_for(saved)
    before = deepcopy(result)
    service.revise_text(saved["document"]["id"], "合成新版", "新版本正文，不可替代原引用。")
    source = source_context(result, service.repository)["sources"][0]
    assert source["public_document_id"] == saved["document"]["id"]
    assert source["evidence_kind"] == "work_material" and source["complete"]
    assert source["shown_characters"] == source["full_text_length"] == len(text)
    assert source["title"] == "合成工作说明"
    assert any(
        unit["text"] == "未被引用的审批限制。" and not unit["claim_indices"]
        for unit in source["units"]
    )
    assert result == before


def test_public_web_archive_is_available_without_refetch(service, monkeypatch):
    async def fetch(url):
        return (
            200,
            {"content-type": "text/plain; charset=utf-8"},
            "合成公开说明\n具体执行步骤。".encode(),
        )

    monkeypatch.setattr(public_documents, "pinned_request", fetch)
    saved = asyncio.run(service.read("https://example.com/context"))

    async def forbidden(url):
        raise AssertionError("Review must use the local snapshot")

    monkeypatch.setattr(public_documents, "pinned_request", forbidden)
    source = source_context(result_for(saved), service.repository)["sources"][0]
    assert source["state"] == "available" and source["evidence_kind"] == "public_document"
    assert source["units"][1]["text"] == "具体执行步骤。"


def test_long_material_displays_cited_tail_context_and_never_calls_it_full_text(service):
    text = "合成占位段落\n" * 9000 + "尾部核验：保留失败记录。\n"
    saved = service.archive_text("合成长文", text)
    result = result_for(saved)
    start = text.index("尾部核验")
    evidence = dict(saved["evidence"][0])
    evidence.update(
        id=f"publicdoc:{saved['document']['id']}:{start}:{len(text)}",
        start=start,
        end=len(text),
        quote=text[start:],
    )
    result["evidence"] = [evidence]
    result["claims"][0]["evidence_ids"] = [evidence["id"]]
    source = source_context(result, service.repository)["sources"][0]
    assert source["state"] == "cited_windows" and not source["complete"]
    assert source["shown_characters"] < source["full_text_length"]
    assert any(
        "尾部核验" in unit["text"] and unit["claim_indices"] == [0] for unit in source["units"]
    )
    assert all(text[unit["start"] : unit["end"]] == unit["text"] for unit in source["units"])


def test_corrupt_archive_and_wrong_quote_are_visible_without_substituting_another_version(service):
    saved = service.archive_text("合成说明", "完整的合成正文。")
    result = result_for(saved)
    result["evidence"][0]["quote"] = "不存在于该版正文的内容"
    source = source_context(result, service.repository)["sources"][0]
    assert source["unresolved_evidence_ids"] and all(
        not unit["claim_indices"] for unit in source["units"]
    )
    with Session(service.repository.engine) as session:
        path = Path(session.get(PublicDocument, saved["document"]["id"]).path)
    path.write_bytes(b"corrupt synthetic archive")
    source = source_context(result, service.repository)["sources"][0]
    assert source["state"] == "integrity_failed" and source["units"] == []
