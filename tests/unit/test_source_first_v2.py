"""Synthetic v2 binding/reclassification regressions, not real semantic acceptance."""

from copy import deepcopy

import pytest

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.agent import TOOLS, method_fingerprint
from work_observer.research.source_first import (
    SourceAnswer,
    check_answer,
    register,
    resolve_answer,
    review_finding_history,
    review_findings,
    tools,
)
from work_observer.research.source_views import build_source_views


def sources(text, cuts=(), job="j1"):
    points = [0, *cuts, len(text)]
    evidence = {
        f"s{job}:{start}:{end}": {
            "id": f"s{job}:{start}:{end}",
            "job_id": job,
            "snapshot_id": "s" + job,
            "document_id": "doc" + job,
            "document_sha256": "a" * 64,
            "content_sha256": "b" * 64,
            "quote": text[start:end],
            "start": start,
            "end": end,
            "full_text_length": len(text),
        }
        for start, end in zip(points, points[1:], strict=False)
    }
    return evidence, build_source_views(list(evidence.values()))


def sentences(views):
    return [
        sentence
        for job in views["jobs"]
        for source in job["sources"]
        for sentence in source["sentences"]
    ]


def item(
    identity="F1", *, refs=(), facet="work_task", state="stated", actor="job_holder", supersedes=()
):
    return {
        "id": identity,
        "job_id": "j1",
        "facet": facet,
        "state": state,
        "actor": actor,
        "sentence_ids": list(refs),
        "supersedes": list(supersedes),
        "reason": "合成分项登记",
    }


def answer(binding_ids, *, unknown=(), text="合成自由判断，必须保持原样", basis="direct"):
    return SourceAnswer.model_validate(
        {
            "claims": [
                {
                    "category": "task",
                    "basis": basis,
                    "requirement": "unspecified",
                    "text": text,
                    "bindings": [
                        {"finding_id": identity, "sentence_ids": selected}
                        for identity, selected in binding_ids
                    ],
                }
            ],
            "gaps": ["合成保留缺口"],
            "unknown_finding_ids": list(unknown),
        }
    )


def test_strict_tools_require_exposed_fields_but_hide_derived_claim_fields():
    original = deepcopy(TOOLS)
    definitions = tools(TOOLS)
    finish = next(tool for tool in definitions if tool["name"] == "finish_research")
    claim = finish["parameters"]["$defs"]["SourceClaim"]
    assert set(claim["properties"]) == {"category", "basis", "requirement", "text", "bindings"}
    assert "unknown_finding_ids" in finish["parameters"]["required"]

    def verify(schema):
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                assert set(schema["required"]) == set(schema["properties"])
                assert schema["additionalProperties"] is False
            assert "default" not in schema
            for value in schema.values():
                verify(value)
        elif isinstance(schema, list):
            for value in schema:
                verify(value)

    for tool in definitions:
        if tool["name"] in {"finish_research", "record_source_findings"}:
            verify(tool["parameters"])
    finding = next(tool for tool in definitions if tool["name"] == "record_source_findings")
    assert "actor" in finding["parameters"]["$defs"]["SourceFinding"]["required"]
    assert TOOLS == original
    assert (
        method_fingerprint() == "39a1ac282065db07b44b5c0bc259599ceb2f05a626d0fe478885c43e397dff24"
    )


def test_declared_sentence_subset_avoids_unrelated_qualification_without_mutating_text():
    text = "岗位职责：\n搭建平台。\n任职要求：\n熟悉框架。"
    evidence, views = sources(text, (text.index("任职要求"),))
    task, qualification = [
        row for row in sentences(views) if row["text"].strip() in {"搭建平台。", "熟悉框架。"}
    ]
    findings = register(
        {"findings": [item(refs=[task["sentence_id"], qualification["sentence_id"]])]},
        views,
        [],
        {"j1"},
    )
    proposed = answer([("F1", [task["sentence_id"]])])
    before = proposed.model_dump()
    resolved, issues = resolve_answer(proposed, findings, evidence)
    assert issues == []
    assert proposed.model_dump() == before
    assert resolved.claims[0].text == proposed.claims[0].text
    assert resolved.claims[0].basis == proposed.claims[0].basis
    assert resolved.claims[0].requirement == proposed.claims[0].requirement
    assert resolved.claims[0].finding_ids == ["F1"]
    assert resolved.claims[0].evidence_ids == [task["evidence_id"]]
    assert resolved.claims[0].sentence_citations[0]["text"] == task["text"]
    legacy = SourceAnswer.model_validate(
        {
            "claims": [
                {
                    **before["claims"][0],
                    "bindings": [],
                    "finding_ids": ["F1"],
                    "evidence_ids": [task["evidence_id"]],
                }
            ],
            "gaps": [],
        }
    )
    assert any(
        issue["reason"] == "claim_sources_differ_from_findings"
        for issue in resolve_answer(legacy, findings, evidence)[1]
    )


def test_selected_sentence_must_belong_to_that_finding_and_be_read():
    evidence, views = sources("职责：\n搭建平台。\n维护接口。")
    body = [row for row in sentences(views) if "搭建" in row["text"] or "维护" in row["text"]]
    findings = register({"findings": [item(refs=[body[0]["sentence_id"]])]}, views, [], {"j1"})
    bad = answer([("F1", [body[1]["sentence_id"]])])
    assert (
        resolve_answer(bad, findings, evidence)[1][0]["reason"]
        == "binding_sentences_not_in_finding"
    )
    good = answer([("F1", [body[0]["sentence_id"]])])
    assert any(
        i["reason"] == "sentence_evidence_not_read" for i in resolve_answer(good, findings, {})[1]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", "other"),
        ("snapshot_id", "other"),
        ("document_sha256", "c" * 64),
        ("content_sha256", "d" * 64),
    ],
)
def test_same_offset_or_text_does_not_bypass_source_identity(field, value):
    evidence, views = sources("职责：\n搭建平台。")
    sentence = next(row for row in sentences(views) if "搭建" in row["text"])
    findings = register({"findings": [item(refs=[sentence["sentence_id"]])]}, views, [], {"j1"})
    altered = deepcopy(evidence)
    altered[sentence["evidence_id"]][field] = value
    issues = resolve_answer(answer([("F1", [sentence["sentence_id"]])]), findings, altered)[1]
    assert any(issue["reason"] == "sentence_source_identity_mismatch" for issue in issues)


def test_heading_context_is_part_of_declared_citation_coverage():
    text = "岗位职责：\n搭建平台。"
    evidence, views = sources(text, (len("岗位职责：\n"),))
    sentence = next(row for row in sentences(views) if "搭建" in row["text"])
    findings = register({"findings": [item(refs=[sentence["sentence_id"]])]}, views, [], {"j1"})
    proposed = answer([("F1", [sentence["sentence_id"]])])
    resolved, issues = resolve_answer(proposed, findings, evidence)
    assert issues == [] and set(resolved.claims[0].evidence_ids) == set(evidence)
    partial = {sentence["evidence_id"]: evidence[sentence["evidence_id"]]}
    assert any(row["is_context"] for row in resolve_answer(proposed, findings, partial)[1])


def test_qualification_cut_at_evidence_boundary_requires_both_unit_parts():
    text = "任职要求：\n熟悉容器和队列者优先。"
    evidence, views = sources(text, (text.index("优先"),))
    pieces = [row for row in sentences(views) if row["start"] >= len("任职要求：\n")]
    assert len(pieces) == 2 and pieces[0]["unit_id"] == pieces[1]["unit_id"]
    refs = [row["sentence_id"] for row in pieces]
    findings = register({"findings": [item(refs=refs, facet="qualification")]}, views, [], {"j1"})
    _, problems = resolve_answer(answer([("F1", refs[:1])]), findings, evidence)
    assert any(row["reason"] == "sentence_unit_requires_all_parts" for row in problems)
    resolved, problems = resolve_answer(answer([("F1", refs)]), findings, evidence)
    assert problems == [] and len(resolved.claims[0].sentence_citations) == 2
    assert (
        "".join(row["text"] for row in resolved.claims[0].sentence_citations)
        == "熟悉容器和队列者优先。"
    )


@pytest.mark.parametrize("flag", ["unit_complete_read", "unit_all_parts_shown"])
def test_partial_or_hidden_unit_cannot_be_selected(flag):
    evidence, views = sources("职责：\n搭建平台。")
    sentence = next(row for row in sentences(views) if "搭建" in row["text"])
    findings = register({"findings": [item(refs=[sentence["sentence_id"]])]}, views, [], {"j1"})
    findings[0]["citations"][0][flag] = False
    assert any(
        row["reason"] == "sentence_unit_not_completely_read_or_shown"
        for row in resolve_answer(answer([("F1", [sentence["sentence_id"]])]), findings, evidence)[
            1
        ]
    )


def test_unknown_has_typed_exit_without_becoming_positive_or_hiding_other_unknowns():
    evidence, views = sources("职责：\n搭建平台。")
    sentence = next(row for row in sentences(views) if "搭建" in row["text"])
    findings = register(
        {
            "findings": [
                item(refs=[sentence["sentence_id"]]),
                item("F2", facet="personal_coding_share", state="not_disclosed"),
                item("F3", facet="release_authority", state="not_disclosed"),
            ]
        },
        views,
        [],
        {"j1"},
    )
    good = answer([("F1", [sentence["sentence_id"]])], unknown=["F2"])
    checked = check_answer(good, findings, evidence, set())
    assert checked["binding_passed"] and checked["missing_unknown_finding_ids"] == ["F3"]
    assert len(review_findings(findings)) == 3
    bad = answer([("F2", [sentence["sentence_id"]])])
    issues = resolve_answer(bad, findings, evidence)[1]
    assert issues[0]["reason"] == "unknown_findings_belong_in_unknown_section"
    assert issues[0]["move_to_unknown_finding_ids"] == ["F2"]
    good.unknown_finding_ids = ["F1"]
    assert not check_answer(good, findings, evidence, set())["binding_passed"]


def test_reclassification_preserves_all_old_sentences_and_history_atomically():
    _, views = sources("职责：\n隔离执行代码。\n团队协作。")
    refs = [
        row["sentence_id"]
        for row in sentences(views)
        if "隔离" in row["text"] or "团队" in row["text"]
    ]
    old = register(
        {"findings": [item(refs=refs, facet="human_control", actor="human_operator")]},
        views,
        [],
        {"j1"},
    )
    before = deepcopy(old)
    corrected = item("F2", refs=refs, facet="execution_safety", actor="system", supersedes=["F1"])
    unknown = item("F3", facet="human_control", state="not_disclosed", actor="human_operator")
    updated = register({"findings": [corrected, unknown]}, views, old, {"j1"})
    assert old == before and not updated[0]["active"]
    assert updated[1]["sentence_ids"] == refs and updated[2]["state"] == "not_disclosed"
    history = review_finding_history(updated)
    assert history[0]["actor"] == "human_operator" and history[0]["superseded_by"] == "F2"
    assert history[0]["citations"] == review_findings(old)[0]["citations"]
    invalid = deepcopy(unknown)
    invalid["id"] = "F999"
    invalid["sentence_ids"] = ["forged"]
    with pytest.raises(ProbeError):
        register({"findings": [corrected, invalid]}, views, old, {"j1"})
    assert old == before
    dropped = deepcopy(corrected)
    dropped["sentence_ids"] = refs[:1]
    with pytest.raises(ProbeError, match="RECLASSIFICATION_MUST_PRESERVE_SOURCE"):
        register({"findings": [dropped]}, views, old, {"j1"})
    assert old == before


def test_conflict_identity_includes_actor_but_known_cannot_be_replaced_by_unknown():
    _, views = sources("职责：\nAgent执行任务。")
    ref = next(row["sentence_id"] for row in sentences(views) if "Agent" in row["text"])
    active = item(refs=[ref], facet="runtime_role", actor="agent")
    unknown = item("F2", facet="runtime_role", state="not_disclosed", actor="job_holder")
    values = register({"findings": [active, unknown]}, views, [], {"j1"})
    assert len(values) == 2
    denied_replacement = {**unknown, "id": "F3", "actor": "agent", "supersedes": ["F1"]}
    with pytest.raises(ProbeError, match="UNKNOWN_CANNOT_REPLACE_DISCLOSED"):
        register({"findings": [denied_replacement]}, views, values, {"j1"})


def test_legacy_anonymous_view_does_not_gain_actor_or_empty_history():
    _, views = sources("职责：\n搭建平台。")
    ref = next(row["sentence_id"] for row in sentences(views) if "搭建" in row["text"])
    rows = register({"findings": [item(refs=[ref])]}, views, [], {"j1"})
    legacy = deepcopy(rows)
    del legacy[0]["actor"]
    current = review_findings(rows)[0]
    assert current["actor"] == "job_holder"
    old = review_findings(legacy)[0]
    assert {
        key: value for key, value in current.items() if key not in {"actor", "actor_label"}
    } == old
    assert review_finding_history(legacy) == []


def test_v3_actor_only_correction_preserves_source_and_history_without_facet_detour():
    _, views = sources("平台运行：\nAgent执行实验。\nAgent汇总结果。")
    refs = [row["sentence_id"] for row in sentences(views) if "Agent" in row["text"]]
    old = register({"findings": [item(refs=refs, facet="runtime_role")]}, views, [], {"j1"})
    before = deepcopy(old)
    corrected = item("F2", refs=refs, facet="runtime_role", actor="agent", supersedes=["F1"])
    updated = register({"findings": [corrected]}, views, old, {"j1"})
    assert old == before
    assert not updated[0]["active"] and updated[0]["superseded_by"] == "F2"
    assert updated[1]["facet"] == "runtime_role" and updated[1]["actor"] == "agent"
    assert updated[1]["citations"] == old[0]["citations"]
    assert review_finding_history(updated)[0]["actor"] == "job_holder"
    dropped = {**corrected, "sentence_ids": refs[:1]}
    with pytest.raises(ProbeError, match="RECLASSIFICATION_MUST_PRESERVE_SOURCE"):
        register({"findings": [dropped]}, views, old, {"j1"})
    unknown = {**corrected, "state": "not_disclosed", "sentence_ids": []}
    with pytest.raises(ProbeError, match="UNKNOWN_CANNOT_REPLACE_DISCLOSED"):
        register({"findings": [unknown]}, views, old, {"j1"})
    changed_source = deepcopy(views)
    for row in sentences(changed_source):
        row["document_sha256"] = "c" * 64
    with pytest.raises(ProbeError, match="RECLASSIFICATION_MUST_PRESERVE_SOURCE"):
        register({"findings": [corrected]}, changed_source, old, {"j1"})
    with pytest.raises(ProbeError):
        register(
            {"findings": [corrected, {**corrected, "id": "F3", "reason": " "}]}, views, old, {"j1"}
        )
    assert old == before


@pytest.mark.parametrize("basis", ["synthesis", "inference", "direct"])
def test_v3_heterogeneous_analysis_is_not_a_semantic_comparability_approval(basis):
    ev1, _ = sources("岗位职责：\n搭建平台。")
    ev2, _ = sources("服务对象：\n服务企业知识库。", job="j2")
    evidence = {**ev1, **ev2}
    views = build_source_views(list(evidence.values()))
    first = next(row["sentence_id"] for row in sentences(views) if "搭建" in row["text"])
    second = next(row["sentence_id"] for row in sentences(views) if "服务企业" in row["text"])
    findings = register(
        {
            "findings": [
                item(refs=[first]),
                {**item("F2", refs=[second], facet="business_context"), "job_id": "j2"},
            ]
        },
        views,
        [],
        {"j1", "j2"},
    )
    proposed = answer([("F1", [first]), ("F2", [second])], basis=basis)
    original = proposed.model_dump()
    checked = check_answer(proposed, findings, evidence, set())
    assert checked["binding_passed"] is (basis != "direct")
    assert checked["semantic_approval"] is False
    assert checked["analysis_notes"] == [
        {
            "index": 0,
            "sides": [
                {"finding_id": "F1", "job_id": "j1", "facet": "work_task", "actor": "job_holder"},
                {
                    "finding_id": "F2",
                    "job_id": "j2",
                    "facet": "business_context",
                    "actor": "job_holder",
                },
            ],
            "notice": "多维分析，不表示同口径单维可比；仍须语义核对",
        }
    ]
    assert proposed.model_dump() == original
    if basis == "direct":
        assert any(
            row["reason"] == "multi_job_direct_claim_requires_analysis"
            for row in checked["claim_finding_issues"]
        )
    else:
        missing_side = deepcopy(proposed)
        missing_side.claims[0].bindings[1].finding_id = "F999"
        assert not check_answer(missing_side, findings, evidence, set())["binding_passed"]
        forged_sentence = deepcopy(proposed)
        forged_sentence.claims[0].bindings[1].sentence_ids = [first]
        assert not check_answer(forged_sentence, findings, evidence, set())["binding_passed"]


def test_v3_heterogeneous_analysis_does_not_relax_complete_unit_or_source_hash():
    ev1, _ = sources("岗位职责：\n搭建平台。")
    text = "执行安全：\n系统执行代码时须人工审批。"
    ev2, _ = sources(text, (text.index("须人工"),), job="j2")
    evidence = {**ev1, **ev2}
    views = build_source_views(list(evidence.values()))
    first = next(row["sentence_id"] for row in sentences(views) if "搭建" in row["text"])
    pieces = [
        row["sentence_id"]
        for row in sentences(views)
        if row["job_id"] == "j2" and not row["heading_heuristic"]
    ]
    assert len(pieces) == 2
    findings = register(
        {
            "findings": [
                item(refs=[first]),
                {
                    **item("F2", refs=pieces, facet="execution_safety", actor="system"),
                    "job_id": "j2",
                },
            ]
        },
        views,
        [],
        {"j1", "j2"},
    )
    proposed = answer([("F1", [first]), ("F2", pieces[:1])], basis="inference")
    checked = check_answer(proposed, findings, evidence, set())
    assert not checked["binding_passed"]
    assert any(
        row["reason"] == "sentence_unit_requires_all_parts"
        for row in checked["claim_finding_issues"]
    )
    proposed.claims[0].bindings[1].sentence_ids = pieces
    assert check_answer(proposed, findings, evidence, set())["binding_passed"]
    wrong_hash = deepcopy(evidence)
    for row in wrong_hash.values():
        if row["job_id"] == "j2":
            row["content_sha256"] = "c" * 64
    assert not check_answer(proposed, findings, wrong_hash, set())["binding_passed"]


def test_v3_finish_description_has_no_base_citation_shortcut_and_notes_are_not_input():
    finish = next(tool for tool in tools(TOOLS) if tool["name"] == "finish_research")
    assert "E1" not in finish["description"]
    assert "bindings" in finish["description"]
    assert "analysis_notes" not in str(finish["parameters"])
