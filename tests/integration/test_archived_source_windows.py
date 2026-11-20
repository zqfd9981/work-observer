"""Read mixed job/background archives by identity, then continue beyond the first excerpt."""

import asyncio
import json
from copy import deepcopy

import pytest
from test_source_first_research import source_workspace as source_workspace
from test_work_materials import MaterialModel

from work_observer.config import Settings
from work_observer.connectors import public_documents
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.memory.service import MemoryService
from work_observer.research import archived_sources
from work_observer.research.agent import PROPOSAL_TOOLS, method_fingerprint, research
from work_observer.retrieval.catalog import Catalog


class WindowModel:
    def __init__(self, *, interrupt=False):
        self.interrupt = interrupt
        self.contexts = []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        scope = context["fixed_scope"]
        if not outputs and scope["jobs"]:
            name, args = "read_job", {"job_id": scope["jobs"][0]["id"]}
        elif not any("document" in row for row in outputs):
            document = scope["public_document_titles"][0]
            assert document["title_not_evidence"] is True
            name, args = "read_archived_document", {"document_id": document["id"], "start": 0}
        elif self.interrupt:
            raise asyncio.CancelledError()
        elif outputs[-1].get("has_more"):
            name, args = (
                "read_archived_document",
                {"document_id": outputs[-1]["document"]["id"], "start": outputs[-1]["next_start"]},
            )
        else:
            evidence = outputs[-1]["evidence"][-1]
            assert "平台团队审批" in evidence["quote"]
            name, args = (
                "finish_research",
                dict(
                    claims=[
                        dict(
                            category="business",
                            basis="direct",
                            requirement="unspecified",
                            text="合成产品说明：上线操作需由平台团队审批。",
                            evidence_ids=[evidence["id"]],
                        )
                    ],
                    gaps=["公司产品说明不能证明该岗位由个人审批上线。"],
                ),
            )
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(len(history))
        )
        return [call], call


def document(repo, tmp_path):
    return PublicDocumentService(repo, tmp_path / "materials").archive_text(
        "公司产品背景目录中的特殊标题",
        "产品介绍。" + "正文描述。" * 1200 + "上线操作需由平台团队审批。",
        "合成出处，未经独立核实",
    )["document"]


@pytest.mark.parametrize("origin", ["manual", "public"])
def test_mixed_sources_show_catalog_and_read_selected_tail_without_guessing_or_network(
    source_workspace, tmp_path, monkeypatch, origin
):
    repo, store, jobs = source_workspace
    selected = document(repo, tmp_path)
    if origin == "public":
        text = PublicDocumentService(repo, tmp_path / "materials").document(selected["id"])["text"]

        async def fetch(url):
            return 200, {"content-type": "text/plain; charset=utf-8"}, text.encode()

        monkeypatch.setattr(public_documents, "pinned_request", fetch)
        selected = asyncio.run(
            PublicDocumentService(repo, tmp_path / "public").read(
                "https://example.com/company-product"
            )
        )["document"]
    outside = PublicDocumentService(repo, tmp_path / "materials").archive_text(
        "未选资料", "不能进入本轮"
    )

    async def forbidden(*args):
        raise AssertionError("Local archive reads cannot make a network request")

    monkeypatch.setattr(public_documents, "pinned_request", forbidden)
    model = WindowModel()
    result = asyncio.run(
        research(
            repo,
            "岗位与产品背景",
            Settings(),
            job_ids=jobs[:1],
            public_document_ids=[selected["id"]],
            coverage_mode="question",
            max_calls=4,
            model=model,
        )
    )
    assert result["status"] == "completed", result
    assert result["model_calls"] == 4 and result["public_reads"] == 0
    assert [row["tool"] for row in result["trace"]] == [
        "read_job",
        "read_archived_document",
        "read_archived_document",
        "finish_research",
    ]
    assert result["archived_sources_version"] == archived_sources.VERSION
    assert {row["id"] for row in result["scope"]["public_document_titles"]} == {selected["id"]}
    assert outside["document"]["id"] not in result["scope"]["archived_public_ids"]
    reference = result["claims"][0]["evidence_ids"][0]
    evidence = next(row for row in result["evidence"] if row["id"] == reference)
    assert (
        evidence["start"] >= 5600
        and evidence["quote"]
        == PublicDocumentService(repo, tmp_path / "materials").document(selected["id"])["text"][
            evidence["start"] : evidence["end"]
        ]
    )
    saved = MemoryService(repo).create(
        "knowledge",
        result["claims"][0]["text"],
        evidence=[evidence],
        source_run_id=result["run_id"],
        origin="agent",
    )
    assert (
        saved["evidence"][0]["evidence_kind"]
        == {"manual": "work_material", "public": "public_document"}[origin]
    )
    assert store.get(result["run_id"])["result"]["claims"] == result["claims"]


def test_reader_scope_windows_and_archive_integrity_are_enforced(source_workspace, tmp_path):
    repo, _, jobs = source_workspace
    selected = document(repo, tmp_path)
    for identity, start, code in [
        (selected["id"], True, "INVALID_PUBLIC_DOCUMENT_WINDOW"),
        (selected["id"], -1, "INVALID_PUBLIC_DOCUMENT_WINDOW"),
        (selected["id"], 100000, "INVALID_PUBLIC_DOCUMENT_WINDOW"),
        ("f" * 32, 0, "RESEARCH_SCOPE_VIOLATION"),
    ]:
        with pytest.raises(ProbeError, match=code):
            archived_sources.read(repo, identity, start, [selected["id"]])
    first = archived_sources.read(repo, selected["id"], 0, [selected["id"]])
    assert len(first["evidence"]) == 8 and first["next_start"] == 5600
    assert all(len(ev["quote"]) <= 700 for ev in first["evidence"])
    # Reuse the canonical archive validator for late-window references.
    MemoryService(repo).create("knowledge", "合成窗口引用", evidence=first["evidence"][:1])
    from sqlalchemy.orm import Session

    from work_observer.connectors.public_models import PublicDocument

    with Session(repo.engine) as session:
        path = session.get(PublicDocument, selected["id"]).path
    from pathlib import Path

    Path(path).write_text("changed", encoding="utf-8")
    with pytest.raises(ProbeError, match="PUBLIC_DOCUMENT_INTEGRITY_FAILED"):
        archived_sources.read(repo, selected["id"], 5600, [selected["id"]])
    assert Catalog(repo).evidence(jobs[0])
    original = deepcopy(PROPOSAL_TOOLS)
    assert (
        "read_archived_document"
        in archived_sources.proposals(PROPOSAL_TOOLS)[0]["parameters"]["properties"][
            "supporting_tool"
        ]["enum"]
    )
    assert PROPOSAL_TOOLS == original


@pytest.mark.parametrize("legacy", [False, True])
def test_resume_keeps_frozen_sources_method_and_remaining_budget(
    source_workspace, tmp_path, legacy
):
    repo, store, _ = source_workspace
    selected = document(repo, tmp_path)
    # An old checkpoint uses the already supported search tool and remains readable.
    if legacy:
        # Keep the synthetic legacy model's search term in the material body.
        selected = PublicDocumentService(repo, tmp_path / "materials").archive_text(
            "旧归档", "checkpoint任务"
        )["document"]
    run = store.create(
        dict(
            question="checkpoint",
            job_ids=[],
            public_document_ids=[selected["id"]],
            coverage_mode="question",
            max_calls=4,
            timeout=180,
        )
    )
    kwargs = dict(
        job_ids=[],
        public_document_ids=[selected["id"]],
        coverage_mode="question",
        max_calls=4,
        checkpoint=(store, run["id"]),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "checkpoint",
                Settings(),
                model=MaterialModel(interrupt=True) if legacy else WindowModel(interrupt=True),
                **kwargs,
            )
        )
    frozen = store.load_checkpoint(run["id"])
    if legacy:
        frozen["result"].pop("archived_sources_version")
        frozen["history"][0]["content"] = frozen["history"][0]["content"].replace(
            archived_sources.POLICY, ""
        )
        frozen["result"]["research_method_sha256"] = method_fingerprint(
            coverage_mode="question", public_only=True, work_materials=True
        )
        store.checkpoint(run["id"], frozen)
    original_hash = frozen["result"]["research_method_sha256"]
    PublicDocumentService(repo, tmp_path / "materials").archive_text("后补资料", "不能扩大本轮范围")
    result = asyncio.run(
        research(
            repo,
            "checkpoint",
            Settings(),
            resume=True,
            model=MaterialModel() if legacy else WindowModel(),
            **kwargs,
        )
    )
    assert result["status"] == "completed", result
    assert result["model_calls"] == (3 if legacy else 4)
    assert result["research_method_sha256"] == original_hash
    assert result["scope"]["archived_public_ids"] == [selected["id"]]
    assert bool(result.get("archived_sources_version")) != legacy
