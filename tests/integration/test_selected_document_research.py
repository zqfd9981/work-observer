"""Explicit original-document scope across retrieval, project steps and resumption."""

import asyncio
import json

import pytest
from test_source_first_research import source_workspace as source_workspace
from test_web import poll
from test_web import web as web

from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.memory.service import MemoryService
from work_observer.research.agent import research
from work_observer.research.materials import material_state
from work_observer.research.projects import ProjectService, execute_project


def documents(repo, tmp_path):
    service = PublicDocumentService(repo, tmp_path / "raw")
    return [
        service.archive_text(f"合成说明{label}", f"接口任务：{label}。", "合成资料")["document"][
            "id"
        ]
        for label in ("限定原文", "未选原文")
    ]


class SelectedModel:
    def __init__(self, interrupt=False):
        self.interrupt = interrupt
        self.history = []

    async def turn(self, history):
        self.history = history
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = "search_archived_sources", {"terms": ["接口"]}
        else:
            if self.interrupt:
                raise asyncio.CancelledError()
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "text": "资料说明了接口任务。",
                            "category": "task",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "evidence_ids": [outputs[0]["evidence"][0]["id"]],
                        }
                    ],
                    "gaps": ["任务执行结果未知。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_selected_archive_does_not_receive_unselected_memory_quotes(source_workspace, tmp_path):
    repo, _, _ = source_workspace
    first, other = documents(repo, tmp_path)
    result = asyncio.run(
        research(
            repo,
            "接口",
            Settings(),
            job_ids=[],
            public_document_ids=[other],
            model=SelectedModel(),
            max_calls=2,
            coverage_mode="question",
        )
    )
    memory = MemoryService(repo)
    candidate = memory.create(
        "knowledge",
        result["claims"][0]["text"],
        evidence=result["evidence"],
        source_run_id=result["run_id"],
    )
    memory.activate(candidate["id"])
    assert memory.recall("接口", [])
    assert memory.recall("接口", [], public_document_ids=[first]) == []
    model = SelectedModel()
    result = asyncio.run(
        research(
            repo,
            "接口",
            Settings(),
            job_ids=[],
            public_document_ids=[first],
            model=model,
            max_calls=2,
            coverage_mode="question",
        )
    )
    assert result["status"] == "completed"
    assert "未选原文" not in json.dumps(model.history, ensure_ascii=False)


def test_model_only_sees_selected_archive_and_resume_cannot_expand_it(source_workspace, tmp_path):
    repo, store, _ = source_workspace
    first, other = documents(repo, tmp_path)
    options = dict(job_ids=[], max_calls=3, coverage_mode="question")
    run = store.create({"question": "接口", "public_document_ids": [first], **options})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "接口",
                Settings(),
                checkpoint=(store, run["id"]),
                public_document_ids=[first],
                model=SelectedModel(True),
                **options,
            )
        )
    with pytest.raises(ProbeError, match="RESEARCH_INPUT_CHANGED"):
        asyncio.run(
            research(
                repo,
                "接口",
                Settings(),
                checkpoint=(store, run["id"]),
                public_document_ids=[other],
                resume=True,
                model=SelectedModel(),
                **options,
            )
        )
    PublicDocumentService(repo, tmp_path / "raw").archive_text(
        "合成新资料", "接口任务：新加入未选资料。"
    )
    model = SelectedModel()
    result = asyncio.run(
        research(
            repo,
            "接口",
            Settings(),
            checkpoint=(store, run["id"]),
            resume=True,
            model=model,
            **options,
        )
    )
    assert result["status"] == "completed"
    assert result["scope"]["archived_public_ids"] == [first]
    assert {ev["public_document_id"] for ev in result["evidence"]} == {first}
    assert "未选原文" not in json.dumps(model.history, ensure_ascii=False)


def test_project_retains_selection_and_unrelated_new_archive_does_not_refresh_materials(
    source_workspace, tmp_path
):
    repo, store, jobs = source_workspace
    first, other = documents(repo, tmp_path)
    service = ProjectService(store)
    project = service.create("合成指定资料", "接口", [], public_document_ids=[first], max_rounds=3)
    for question in ("接口", "接口继续"):
        project = service.add(project["id"], question, revision=project["revision"], offline=True)
        project = asyncio.run(
            execute_project(service, project["id"], repo, Settings(), max_steps=1)
        )
        step = project["steps"][-1]
        assert step["public_document_ids"] == [first]
        assert store.get(step["run_id"])["result"]["scope"]["archived_public_ids"] == [first]
    before = material_state(repo, "接口", job_ids=[], public_document_ids=[first])
    PublicDocumentService(repo, tmp_path / "raw").archive_text(
        "合成无关新增", "接口任务：其他资料。"
    )
    assert material_state(repo, "接口", job_ids=[], public_document_ids=[first]) == before
    # Adding a job via the existing form must preserve the selected archive.
    project = service.revise(
        project["id"], revision=project["revision"], goal="接口", job_ids=jobs[:1]
    )
    assert project["public_document_ids"] == [first]
    assert project["steps"][0]["public_document_ids"] == [first]
    project = service.revise(
        project["id"],
        revision=project["revision"],
        goal="接口",
        job_ids=[],
        public_document_ids=[other],
    )
    assert project["public_document_ids"] == [other]
    assert project["scope_history"][-1]["public_document_ids"] == [first]


def test_api_selection_validated_and_empty_is_not_all(web):
    client, headers, _, _ = web
    ids = [
        client.post(
            "/api/work-materials",
            headers=headers,
            json={"title": f"合成资料{i}", "text": f"接口任务：{i}。"},
        ).json()["document"]["id"]
        for i in range(2)
    ]
    response = client.post(
        "/api/projects",
        headers=headers,
        json={"title": "合成", "goal": "接口", "job_ids": [], "public_document_ids": [ids[0]]},
    )
    assert response.status_code == 201
    project = response.json()
    kept = client.patch(
        "/api/projects/" + project["id"],
        headers=headers,
        json={"revision": project["revision"], "goal": "接口追问", "job_ids": []},
    ).json()
    assert kept["public_document_ids"] == [ids[0]]
    for selection in ([ids[0]], [], None):
        run = client.post(
            "/api/research",
            headers=headers,
            json={
                "question": "接口",
                "job_ids": [],
                "offline": True,
                "public_document_ids": selection,
            },
        )
        result = poll(client, run.json()["id"])["result"]
        assert set(result["scope"]["archived_public_ids"]) == set(
            ids if selection is None else selection
        )
    for selection in (["x"], ["f" * 32], ids * 11):
        response = client.post(
            "/api/research",
            headers=headers,
            json={
                "question": "接口",
                "job_ids": [],
                "offline": True,
                "public_document_ids": selection,
            },
        )
        assert response.status_code in {400, 404, 422}
