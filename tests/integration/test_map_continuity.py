"""A reopened map investigation retains reasoning and later claim corrections."""

import asyncio
import json
from copy import deepcopy

import pytest
from test_dialogue_revisions import ConversationModel
from test_source_first_research import source_workspace as source_workspace
from test_work_relations import ComparedJobMap

from work_observer.config import Settings
from work_observer.research.agent import research
from work_observer.research.projects import ProjectService, _map_context, execute_project
from work_observer.research.store import ResearchStore


@pytest.mark.parametrize("explicit_reply", [True, False])
def test_reopened_question_reuses_map_and_corrections_with_or_without_explicit_reply(
    source_workspace, explicit_reply
):
    repo, store, jobs = source_workspace
    service = ProjectService(store)
    project = service.create("合成地图续问", "比较接口工作", jobs[:2], max_calls=12, max_rounds=3)
    project = service.add(
        project["id"],
        "比较接口工作",
        revision=project["revision"],
        approach="work_map",
        max_calls=4,
    )
    project = asyncio.run(
        execute_project(
            service, project["id"], repo, Settings(), model=ComparedJobMap(), max_steps=1
        )
    )
    original_step = project["steps"][0]
    original = deepcopy(store.get(original_step["run_id"])["result"])
    project = service.add(
        project["id"],
        "核实接口任务的责任",
        revision=project["revision"],
        reply_to_step_id=original_step["id"],
        coverage_mode="question",
        max_calls=3,
    )
    model = ConversationModel()
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=model, max_steps=1)
    )
    initial_context = model.contexts[0]["project_context"]
    old = next(
        row for row in initial_context["previous_findings"] if row["run_id"] == original["run_id"]
    )
    assert len(old["work_map"]["work_relations"]) == 2
    assert old["work_map"]["comparisons"][0]["relation_indices"] == [0, 1]
    assert old["work_map"]["comparisons"][0]["previous_index"] == 0
    assert old["work_map"]["unknowns"][0]["text"] == original["work_map"]["unknowns"][0]
    assert "source_text" not in old["work_map"]["work_relations"][0]
    assert "精通" in old["derived_claims"][1]["text"]
    changed = store.get(project["steps"][1]["run_id"])["result"]
    assert changed["cognition_revisions"][0]["previous_run_id"] == original["run_id"]
    store.close()
    reopened = ResearchStore(store.path, store.namespace)
    try:
        service = ProjectService(reopened)
        project = service.add(
            project["id"],
            "继续核实原图的迁移条件" if explicit_reply else "精通分布式设计的规模适用范围是什么",
            revision=project["revision"],
            reply_to_step_id=original_step["id"] if explicit_reply else None,
            approach="work_map",
            max_calls=4,
        )
        step = service.claim(project["id"])
        context = service.context(project["id"], step, repo)
        old = next(
            row for row in context["previous_findings"] if row["run_id"] == original["run_id"]
        )
        revised_index = changed["cognition_revisions"][0]["previous_claim_index"]
        claim = next(
            row for row in old["derived_claims"] if row["previous_claim_index"] == revised_index
        )
        assert claim["followup_decisions"][0]["decision"] == "revise"
        assert claim["reuse_status"] == "has_provisional_followup"
        assert old["work_map"]["comparisons"][0]["transfer_conditions"] == "核实个人分工与规模"
        assert old["work_map"]["omitted"] == dict.fromkeys(old["work_map"]["omitted"], 0)
        assert len(json.dumps(context, ensure_ascii=False)) <= 14000
        assert reopened.get(original["run_id"])["result"] == original
        assert service.usage(project)["calls"] == 6
        if not explicit_reply:
            class ContentAwareMap(ComparedJobMap):
                async def turn(self, history):
                    carried = json.loads(history[1]["content"])["project_context"]
                    source = next(
                        row for row in carried["previous_findings"]
                        if row["run_id"] == original["run_id"]
                    )
                    assert source["work_map"]["comparisons"][0]["transfer_conditions"] == (
                        "核实个人分工与规模"
                    )
                    preserved = next(
                        row for row in source["derived_claims"]
                        if row["previous_claim_index"] == revised_index
                    )
                    assert preserved["followup_decisions"][0]["run_id"] == changed["run_id"]
                    assert preserved["text"] == original["claims"][revised_index]["text"]
                    return await super().turn(history)

            result = asyncio.run(
                research(
                    repo,
                    step["question"],
                    Settings(),
                    job_ids=step["job_ids"],
                    project_id=project["id"],
                    approach="work_map",
                    conversation_context=context,
                    checkpoint=(reopened, step["run_id"]),
                    max_calls=4,
                    model=ContentAwareMap(),
                )
            )
            assert result["status"] == "completed", result
            assert {original["run_id"], changed["run_id"]} <= set(result["continued_from"])
            assert len([row for row in result["trace"] if row["tool"] == "read_job"]) == 2
            assert result["model_calls"] == 4
            assert reopened.get(original["run_id"])["result"] == original
    finally:
        reopened.close()


def test_map_context_keeps_original_indices_and_discloses_rows_missing_their_claims():
    result = dict(
        claims=[dict(text="原任务", evidence_ids=["a"]), dict(text="原能力", evidence_ids=["b"])],
        evidence=[dict(id="a"), dict(id="b")],
        work_map=dict(
            version="existing-map",
            scope_note="合成范围",
            work_types=[],
            ability_relations=[
                dict(
                    task="任务",
                    ability="能力",
                    rationale="原解释",
                    claim_indices=[0, 1],
                    transfer_limit="待核实",
                )
            ],
            unknowns=["尚缺资料"],
        ),
    )
    item = dict(derived_claims=[dict(previous_claim_index=1, text="原能力")])
    context = dict(previous_findings=[item])
    _map_context(context, item, result)
    assert not item["work_map"]["ability_relations"]
    assert item["work_map"]["omitted"]["ability_relations"] == 1
    assert item["work_map"]["unknowns"] == [dict(previous_index=0, text="尚缺资料")]
    # The source is not truncated, reindexed, or rewritten to make it fit.
    result["work_map"]["ability_relations"][0]["rationale"] = "原解释" * 300
    full = deepcopy(result)
    item = dict(derived_claims=[dict(previous_claim_index=i) for i in (0, 1)])
    context = dict(previous_findings=[item], other="x" * 13000)
    _map_context(context, item, result)
    assert len(json.dumps(context, ensure_ascii=False)) <= 14000
    assert item["work_map"]["omitted"]["ability_relations"] == 1
    assert result == full
