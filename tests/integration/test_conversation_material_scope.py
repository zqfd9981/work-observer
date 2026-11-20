import re
from pathlib import Path

from starlette.testclient import TestClient
from test_source_first_research import source_workspace as source_workspace

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.research.projects import ProjectService


def test_existing_material_selection_uses_metadata_and_preserves_sources_budget_and_history(
    source_workspace,
):
    repo, store, jobs = source_workspace
    root = Path(repo.engine.url.database).parent
    document = PublicDocumentService(repo, root / "raw").archive_text(
        "合成接口说明",
        "合成工作资料：平台团队协作核对接口。",
        "合成来源",
    )["document"]
    projects = ProjectService(store)
    project = projects.create(
        "合成现有资料选择",
        "保留原研究目标",
        jobs[:1],
        public_document_ids=[document["id"]],
        max_calls=12,
    )
    with TestClient(
        create_app(
            Settings(database_path=root / "app.db", raw_directory=root / "raw"),
            reports_dir=root / "reports",
        ),
        base_url="http://127.0.0.1",
    ) as client:
        headers = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        path = "/api/projects/" + project["id"]
        initial = client.get(path).json()
        assert initial["scope_materials"]["jobs"][0]["id"] == jobs[0]
        assert initial["scope_materials"]["jobs"][0]["has_detail"]
        assert "description_text" not in initial["scope_materials"]["jobs"][0]
        assert initial["scope_materials"]["documents"][0]["title"] == "合成接口说明"
        assert initial["scope_materials"]["documents"][0]["observed_at"]
        library = client.get("/api/public-documents?q=合成&limit=20&offset=0").json()
        assert document["id"] in {row["id"] for row in library["documents"]}
        before_jobs = client.get("/api/overview").json()["jobs"]
        response = client.patch(
            path,
            headers=headers,
            json={
                "revision": initial["revision"],
                "goal": initial["goal"],
                "job_ids": [jobs[1]],
                "public_document_ids": [],
            },
        )
        assert response.status_code == 200, response.text
        current = client.get(path).json()
        assert current["job_ids"] == [jobs[1]] and current["public_document_ids"] == []
        assert current["scope_materials"]["jobs"][0]["id"] == jobs[1]
        assert current["scope_materials"]["documents"] == []
        assert current["goal"] == initial["goal"] and current["budget"] == initial["budget"]
        assert current["scope_history"][-1]["job_ids"] == jobs[:1]
        assert current["scope_history"][-1]["public_document_ids"] == [document["id"]]
        assert current["usage"]["calls"] == 0 and not current["steps"]
        assert client.get("/api/overview").json()["jobs"] == before_jobs
        assert client.get("/api/public-documents").json()["total"] == library["total"]
