"""Local recall cases prompted by existing BOSS JDs; no model or market accuracy claims.

The short, anonymized fixtures retain the distinction between an enterprise
knowledge-base Agent, a cockpit cloud Agent and an unrelated Agent work line.
"""

import pytest

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.research.agent import Claim
from work_observer.research.orchestration import investigate, outcomes
from work_observer.retrieval.enhanced import RetrievalService
from work_observer.retrieval.unified import UnifiedRetrieval
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def library(tmp_path):
    path = tmp_path / "focused.db"
    upgrade(path)
    repo, archive = Repository(path), RawArchive(tmp_path / "raw")

    def add_job(key, text, title="合成岗位", **kwargs):
        return import_jd(repo, archive, ManualJD(
            title=title, company="合成公司" + key, external_id=key,
            description=text, data_kind="synthetic", **kwargs,
        ))["job_id"]

    def add_doc(key, text):
        return PublicDocumentService(repo, tmp_path / "public").archive_text(
            "合成背景资料" + key, text, "合成资料，仅作功能检查。",
        )["document"]["id"]

    yield repo, add_job, add_doc
    repo.close()


def request(anchors, *, retry=None, jobs=None, docs=None):
    return {"objective": "比较不同工作线中的记忆与上下文任务。", "missing_context": [],
            "tasks": [{"intent": "compare", "question": "这两份工作的记忆任务差在哪？",
                       "completion": "分别找到两份岗位的原文，并保留业务与责任边界。",
                       "queries": [{"terms": ["Agent"], "required_terms": anchors,
                                    "reason": "泛词Agent不能替代问题中的记忆主题。"}],
                       "retry_queries": [{"terms": ["Agent"],
                                          "required_terms": retry or anchors,
                                          "reason": "换成另一份JD使用的上下文表述补查。"}],
                       "source_job_ids": jobs or [], "source_document_ids": docs or []}]}


def run(repo, plan, jobs, documents=(), previous=None,
        original_question="这两份工作的记忆任务差在哪？", inherited_constraints=()):
    return investigate(
        repo, plan, original_question=original_question,
        scope={"jobs": [{"id": key, "title": "合成选定岗位" + str(index)}
                        for index, key in enumerate(jobs)],
               "filters": {}, "archived_public_ids": list(documents)},
        project_id=None, as_of=None, aliases={}, previous=previous,
        inherited_constraints=inherited_constraints,
    )


def test_topic_anchor_filters_before_top_k_and_never_uses_title_as_body(library):
    repo, add, doc = library
    for index in range(12):
        add(str(index), "Agent " * 30 + "负责内容发布与工具建设。")
        doc(str(index), "Agent " * 30 + "介绍内容创作。")
    target = add("memory", "设计Agent记忆模块与状态管理流程。")
    public = doc("memory", "Agent Memory支持历史对话查询。")
    add("title-only", "Agent负责工具集成。", title="合成Agent记忆工程师")
    groups = {"记忆": ["Memory"]}
    result = UnifiedRetrieval(repo, alias_groups=groups).search(
        ["Agent"], required_terms=["记忆"], limit=2, include_knowledge=False,
    )
    assert {row.get("job_id") or row.get("public_document_id")
            for row in result["evidence"]} == {target, public}
    assert result["required_terms"] == ["记忆"]
    assert result["matching_jobs"] == result["matching_public_documents"] == 1
    first = RetrievalService(repo, alias_groups=groups).search(
        ["Agent"], required_terms=["记忆"], limit=1,
    )
    assert first["evidence"][0]["job_id"] == target


def test_extra_background_sources_do_not_fill_missing_comparison_side(library):
    repo, add, doc = library
    first = add("knowledge", "负责Agent记忆模块、任务拆解与状态管理。")
    second = add("cockpit", "负责Agent工具协议适配，打通车控能力。")
    background = [doc("one", "Agent记忆存储说明。"), doc("two", "Agent记忆检索说明。")]
    result = run(repo, request(["记忆"]), [first, second], background)
    task = result["tasks"][0]
    assert task["candidate_sources"] == 3
    assert task["missing_source_keys"] == [second]
    assert task["retrieval_status"] == "comparison_needs_other_source"
    assert task["retried"] is False  # Identical retries are not new investigations.
    claims = [Claim(category="task", basis="direct", requirement="unspecified",
                    text="合成资料中的记忆说明。", evidence_ids=[row["id"]])
              for row in result["evidence"]]
    values = [{"task_index": 0, "status": "answered", "answer": "两侧已查全。",
               "claim_indices": list(range(len(claims))), "questions": []}]
    with pytest.raises(ValueError, match="每一侧"):
        outcomes(values, result, claims, {row["id"]: row for row in result["evidence"]})


def test_retry_uses_changed_anchor_and_keeps_each_selected_job(library):
    repo, add, _ = library
    first = add("knowledge", "设计Agent记忆模块与状态管理流程。")
    second = add("cockpit", "负责Agent上下文工程，端云同步上下文管理。")
    result = run(repo, request(["记忆"], retry=["上下文"]), [first, second])
    task = result["tasks"][0]
    assert task["retried"] and not task["missing_source_keys"]
    assert task["retrieval_status"] == "candidates_need_reading"
    assert {tuple(row["required_terms"]) for row in task["attempts"]} == {
        ("记忆",), ("上下文",),
    }
    assert {row["target_id"] for row in task["attempts"] if row.get("target_id")} == {
        first, second,
    }
    assert {row["job_id"] for row in result["evidence"]} == {first, second}


def test_target_ids_cannot_widen_scope_or_replace_a_missing_side(library):
    repo, add, _ = library
    first = add("one", "Agent记忆模块。")
    second = add("two", "Agent工具调用。")
    other = add("other", "Agent记忆模块。")
    with pytest.raises(ValueError, match="冻结范围"):
        run(repo, request(["记忆"], jobs=[first, other]), [first, second])
    result = run(repo, request(["记忆"]), [first, second])
    with pytest.raises(ValueError, match="原来的对比对象"):
        run(repo, request(["记忆"], jobs=[first]), [first, second], previous=result)


def test_multiple_anchors_are_conjunctive_and_keep_original_quote(library):
    repo, add, _ = library
    add("memory-only", "Agent Memory持久化存储。")
    target = add("both", "Agent Memory通过function calling读取历史数据。")
    result = UnifiedRetrieval(repo, alias_groups={"记忆": ["Memory"],
                                                 "工具调用": ["function calling"]}).search(
        ["Agent"], required_terms=["记忆", "工具调用"], include_knowledge=False,
    )
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["job_id"] == target
    assert result["evidence"][0]["quote"] == "Agent Memory通过function calling读取历史数据。"


def test_user_scope_filters_unknowns_and_is_inherited_until_explicitly_released(library):
    repo, add, _ = library
    shanghai = add("sh", "Agent记忆模块。", city="上海")
    beijing = add("bj", "Agent记忆模块。", city="北京")
    unknown = add("unknown", "Agent记忆模块。")
    jobs = [shanghai, beijing, unknown]
    plan = request(["记忆"])
    plan["tasks"][0]["intent"] = "understand"
    plan["constraints"] = [{"field": "city", "value": "上海", "source_text": "只看上海"}]
    initial = run(repo, plan, jobs, original_question="只看上海，记忆任务具体做什么？")
    assert initial["effective_scope"]["job_ids"] == [shanghai]
    assert initial["scope_unknown_job_ids"] == [unknown]
    assert initial["scope_excluded_job_ids"] == [beijing]
    assert {row["job_id"] for row in initial["evidence"]} == {shanghai}
    followup = request(["记忆"])
    followup["tasks"][0]["intent"] = "understand"
    inherited = run(repo, followup, jobs, original_question="那具体需要哪些能力？",
                    inherited_constraints=initial["constraints"])
    assert inherited["constraints"] == initial["constraints"]
    assert inherited["effective_scope"]["job_ids"] == [shanghai]
    followup["released_constraints"] = [{"field": "city", "source_text": "这次不限城市"}]
    released = run(repo, followup, jobs, original_question="这次不限城市，都看看记忆任务",
                   inherited_constraints=initial["constraints"])
    assert set(released["effective_scope"]["job_ids"]) == set(jobs)
    assert not released["constraints"]


def test_conditions_cannot_be_invented_or_bypassed_in_final_citations(library):
    repo, add, doc = library
    first = add("sh", "Agent记忆模块。", city="上海")
    other = add("bj", "Agent记忆模块。", city="北京")
    background = doc("background", "Agent记忆模块。")
    plan = request(["记忆"])
    plan["tasks"][0]["intent"] = "understand"
    plan["constraints"] = [{"field": "city", "value": "北京", "source_text": "只看上海"}]
    with pytest.raises(ValueError, match="保留用户原话"):
        run(repo, plan, [first, other], original_question="只看上海")
    plan["constraints"] = [{"field": "source", "value": "manual",
                            "source_text": "只看手工导入"}]
    result = run(repo, plan, [first], [background], original_question="只看手工导入")
    assert result["effective_scope"]["public_document_ids"] == []
    assert {row["job_id"] for row in result["evidence"]} == {first}
    forged_evidence = {"other": {"id": "other", "job_id": other, "document_id": "other"}}
    claims = [Claim(category="task", basis="direct", requirement="unspecified",
                    text="别的岗位的记忆工作。", evidence_ids=["other"])]
    with pytest.raises(ValueError, match="明确条件之外"):
        outcomes([{"task_index": 0, "status": "answered", "answer": "工作解释。",
                   "claim_indices": [0], "questions": []}], result, claims, forged_evidence)
