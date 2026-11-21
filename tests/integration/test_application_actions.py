"""Synthetic runs verify action provenance and resumption, not advice quality."""

import asyncio
import json
from copy import deepcopy

import pytest
from test_projects import EvidenceModel
from test_projects import setup as setup

from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.service import MemoryService
from work_observer.quality.reviews import QualityReviewService
from work_observer.reports.results import render
from work_observer.research import applications
from work_observer.research.agent import TOOLS, ModelClient, method_fingerprint, research

PROJECT = "a" * 32


def profile(repo):
    return MemoryService(repo).create(
        "preference",
        applications.PREFIX
        + json.dumps(
            {"background": "合成接口开发经历", "goal": "合成可展示项目", "constraints": ""}
        ),
        scope="project",
        project_id=PROJECT,
    )


class ActionModel(EvidenceModel, ModelClient):
    def __init__(self, memory_id, *, bad=None, cancel=False, plan=True):
        super().__init__()
        self.memory_id, self.bad, self.cancel, self.plan = memory_id, bad, cancel, plan
        self.tools = []

    async def turn(self, history):
        calls, response = await super().turn(history)
        if response["name"] == "finish_research":
            if self.cancel:
                raise asyncio.CancelledError()
            args = json.loads(response["arguments"])
            if self.plan:
                args["application_plan"] = {
                    "background_memory_id": "b" * 32
                    if self.bad == "background"
                    else self.memory_id,
                    "actions": [
                        {
                            "title": "合成接口练习",
                            "task_or_ability": "Python接口开发",
                            "deliverable": "合成接口与验证记录",
                            "completion_check": "按已说明的请求检查正常与错误响应",
                            "evidence_ids": ["missing" if self.bad == "citation" else "E1"],
                            "assumptions": ["测试环境与具体接口范围待明确"],
                        }
                    ],
                    "open_questions": ["合成可投入时间尚未说明"],
                }
            response["arguments"] = json.dumps(args)
        return calls, response


def test_actions_finish_with_claims_in_same_three_calls_and_export(setup):
    repo, store, job = setup
    note = profile(repo)
    model = ActionModel(note["id"])
    result = asyncio.run(
        research(
            repo,
            "根据背景建议合成项目",
            Settings(),
            job_ids=[job],
            project_id=PROJECT,
            max_calls=3,
            model=model,
            allow_proposals=False,
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 3
    assert result["application_actions_version"] == applications.VERSION
    plan = result["application_plan"]
    assert plan["background_memory_id"] == note["id"] and plan["background_version"] == 1
    assert plan["goal"] == "合成可展示项目" and plan["constraints"] == ""
    assert plan["actions"][0]["evidence_ids"] == [result["evidence"][0]["id"]]
    assert model.contexts[0]["application_background"]["memory_id"] == note["id"]
    finish = next(row for row in model.tools if row["name"] == "finish_research")
    assert "application_plan" in finish["parameters"]["properties"]
    assert "application_plan" not in TOOLS[-1]["parameters"]["properties"]
    before = deepcopy(result)
    markdown = render(result)
    assert "应用行动（研究建议，效果尚未验证）" in markdown
    assert "完成检查（建议）" in markdown and "[E1](#e1)" in markdown
    assert result == before
    packet = QualityReviewService(store, repo).packet(result["run_id"])
    assert packet["application_plan"] == plan and packet["application_evidence"]
    assert "不表示" in packet["application_notice"]


@pytest.mark.parametrize("bad", ["background", "citation"])
def test_bad_binding_is_rejected_without_publishing_plan_or_resetting_calls(setup, bad):
    repo, _, job = setup
    note = profile(repo)
    result = asyncio.run(
        research(
            repo,
            "合成应用",
            Settings(),
            job_ids=[job],
            project_id=PROJECT,
            max_calls=3,
            model=ActionModel(note["id"], bad=bad),
            allow_proposals=False,
        )
    )
    assert result["status"] == "incomplete" and result["model_calls"] == 3
    assert "application_plan" not in result and result["claims"] == []
    assert result["trace"][-1]["validation"] == "citation_or_coverage_rejected"


def test_background_from_another_project_does_not_enable_actions(setup):
    repo, _, job = setup
    note = profile(repo)
    model = ActionModel(note["id"], plan=False)
    result = asyncio.run(
        research(
            repo,
            "普通合成调查",
            Settings(),
            job_ids=[job],
            project_id="b" * 32,
            max_calls=3,
            model=model,
            allow_proposals=False,
        )
    )
    assert result["status"] == "completed" and "application_actions_version" not in result
    assert "application_background" not in model.contexts[0]
    assert (
        "application_plan"
        not in next(tool for tool in model.tools if tool["name"] == "finish_research")[
            "parameters"
        ]["properties"]
    )


@pytest.mark.parametrize("old_method", [False, True])
def test_resume_preserves_feature_selection_method_and_remaining_budget(
    setup, monkeypatch, old_method
):
    repo, store, job = setup
    note = profile(repo)
    real_background = applications.background
    if old_method:
        monkeypatch.setattr(applications, "background", lambda *args: None)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "合成应用续接",
                Settings(),
                job_ids=[job],
                project_id=PROJECT,
                max_calls=4,
                model=ActionModel(note["id"], cancel=True),
                allow_proposals=False,
            )
        )
    run = store.list()[0]
    frozen = store.load_checkpoint(run["id"])
    monkeypatch.setattr(applications, "background", real_background)
    assert frozen["result"]["model_calls"] == 3
    result = asyncio.run(
        research(
            repo,
            "合成应用续接",
            Settings(),
            checkpoint=(store, run["id"]),
            resume=True,
            model=ActionModel(note["id"], plan=not old_method),
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 4
    assert result["research_method_sha256"] == frozen["result"]["research_method_sha256"]
    assert ("application_actions_version" in result) is not old_method
    assert store.load_checkpoint(run["id"])["max_calls"] == 4


def test_action_schema_extends_dialogue_without_changing_base_contract():
    from work_observer.research.dialogue import tools

    base = tools(TOOLS)
    modified = applications.tools(base)
    finish = next(row for row in modified if row["name"] == "finish_research")["parameters"]
    assert "revisions" in finish["properties"] and "application_plan" in finish["properties"]
    assert "application_plan" not in base[-1]["parameters"]["properties"]
    action = finish["$defs"]["Action"]
    assert "hypothesis" in action["required"]
    assert "default" not in action["properties"]["hypothesis"]
    for name in ("comparison_conditions", "comparison_rows"):
        assert name in action["required"] and "default" not in action["properties"][name]
    assert set(finish["$defs"]["ComparisonCase"]["required"]) == {"condition", "input", "expected"}
    assert "observed" not in finish["$defs"]["ComparisonCase"]["properties"]
    assert method_fingerprint() != method_fingerprint(application_actions=True)


def test_changed_background_stops_resumption_before_another_model_call(setup):
    repo, store, job = setup
    note = profile(repo)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "合成应用变更",
                Settings(),
                job_ids=[job],
                project_id=PROJECT,
                max_calls=4,
                model=ActionModel(note["id"], cancel=True),
                allow_proposals=False,
            )
        )
    run = store.list()[0]
    before = store.load_checkpoint(run["id"])
    data = json.loads(note["content"][len(applications.PREFIX) :])
    data["goal"] = "合成新目标"
    MemoryService(repo).revise(note["id"], applications.PREFIX + json.dumps(data))
    model = ActionModel(note["id"])
    with pytest.raises(ProbeError, match="RESEARCH_MEMORY_CHANGED_RESTART"):
        asyncio.run(
            research(
                repo,
                "合成应用变更",
                Settings(),
                checkpoint=(store, run["id"]),
                resume=True,
                model=model,
            )
        )
    assert model.contexts == []
    assert (
        store.load_checkpoint(run["id"])["result"]["model_calls"] == before["result"]["model_calls"]
    )


def test_legacy_application_background_is_readable_but_ambiguous_fields_are_not_guessed(setup):
    repo, _, _ = setup
    memory = MemoryService(repo)
    text = (
        "个人应用背景（用户自述）：\n已有经历或能力：合成经历\n"
        "本次目标：合成目标\n投入与限制：未说明，不作假设"
    )
    note = memory.create("preference", text, scope="project", project_id=PROJECT)
    assert applications.background([note], PROJECT)["constraints"] == ""
    assert applications.background([note], "b" * 32) is None
    assert (
        applications.background([{**note, "content": text + "\n本次目标：重复标签"}], PROJECT)
        is None
    )
