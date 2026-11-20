"""A normal read-and-answer receives literal reading help with no extra model turn."""

import asyncio
import json

from test_source_first_research import source_workspace as source_workspace

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.research.agent import research
from work_observer.storage.archive import RawArchive


class GuidedModel:
    async def turn(self, history):
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            context = json.loads(history[1]["content"])
            name, arguments = "read_job", {"job_id": context["fixed_scope"]["jobs"][0]["id"]}
        else:
            data = outputs[-1]
            passage = next(
                row
                for row in data["reading_guide"]["sources"][0]["passages"]
                if "商科复合教育" in row["text"]
            )
            assert passage["complete_read"] and len(passage["citation_keys"]) == 2
            self.guide = data["reading_guide"]
            name, arguments = (
                "finish_research",
                dict(
                    claims=[
                        dict(
                            category="ability",
                            basis="direct",
                            requirement="preferred",
                            text="该合成岗位原文写具备商科复合教育背景更佳。",
                            evidence_ids=passage["citation_keys"],
                        )
                    ],
                    gaps=[],
                ),
            )
        call = dict(
            type="function_call",
            name=name,
            arguments=json.dumps(arguments),
            call_id=str(len(history)),
        )
        return [call], call


def test_standard_question_gets_cross_chunk_condition_without_registration_or_new_calls(
    source_workspace,
    tmp_path,
):
    repo, store, _ = source_workspace
    text = "岗位职责\n负责接口开发。\n" + "背景说明。" * 134
    text += "\n任职资格\n本科及以上学历；具备商科复合教育背景更佳\n加分项\n有产品孵化经历。"
    job = import_jd(
        repo,
        RawArchive(tmp_path / "reading-raw"),
        ManualJD(
            title="合成阅读岗位",
            company="合成公司",
            description=text,
            data_kind="synthetic",
        ),
    )["job_id"]
    model = GuidedModel()
    result = asyncio.run(
        research(
            repo,
            "教育背景要求如何区分",
            Settings(),
            job_ids=[job],
            coverage_mode="question",
            max_calls=2,
            model=model,
        )
    )
    assert result["status"] == "completed", result
    assert result["model_calls"] == 2 and len(result["claims"][0]["evidence_ids"]) == 2
    assert model.guide["sources"][0]["coverage"]["fully_read"]
    assert store.get(result["run_id"])["result"]["claims"] == result["claims"]
    assert repo.job(job)["current"]["description_text"] == text
