"""Optional public research using synthetic search and local HTML, with no network."""

import hashlib
import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.collection.contracts import now
from work_observer.config import Settings
from work_observer.connectors import public_documents
from work_observer.connectors.public_search import PublicSearch
from work_observer.storage.database import upgrade


class PublicCareerModel:
    async def turn(self, history):
        context = json.loads(history[1]["content"])
        career = context["project_context"]["career_evidence"]
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        evidence = [ev for output in outputs for ev in output.get("evidence", [])]
        if not outputs:
            name, args = "read_job", {"job_id": context["fixed_scope"]["jobs"][0]["id"]}
        elif career["public_research_policy"] and not any(ev.get("url") for ev in evidence):
            name, args = "search_public_web", {"query": "合成平台的任务执行记录"}
        elif career["public_research_policy"] and not any(
            ev.get("public_document_id") for ev in evidence
        ):
            name, args = "read_public_document", {"url": "https://example.com/career-platform"}
        elif career["selected_material"] and not any(
            ev.get("public_document_id") for ev in evidence
        ):
            name, args = (
                "read_archived_document",
                {
                    "document_id": career["selected_material"]["document_id"],
                    "start": 0,
                },
            )
        else:
            claims = [
                {
                    "category": "task",
                    "basis": "direct",
                    "requirement": "unspecified",
                    "text": "合成岗位负责Python接口开发与测试。",
                    "evidence_ids": [evidence[0]["id"]],
                }
            ]
            body = next((ev for ev in evidence if ev.get("public_document_id")), None)
            if body:
                claims.append(
                    {
                        "category": "business",
                        "basis": "direct",
                        "requirement": "unspecified",
                        "text": "合成平台说明提供任务执行记录与失败定位线索。",
                        "evidence_ids": [body["id"]],
                    }
                )
            name, args = (
                "finish_research",
                {
                    "claims": claims,
                    "gaps": ["公开产品说明不能证明开发者具有业务验收决定权。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_public_opt_in_retains_body_without_turning_business_into_job_requirements(
    tmp_path, monkeypatch
):
    requests = {"search": 0, "read": 0}

    async def search(self, query):
        requests["search"] += 1
        quote = "合成搜索生成线索：平台提供任务执行记录，需读取正文核对。"
        digest = hashlib.sha256(quote.encode()).hexdigest()
        return {
            "evidence": [
                {
                    "id": "public:" + digest,
                    "job_id": None,
                    "snapshot_id": None,
                    "document_id": None,
                    "content_sha256": digest,
                    "document_sha256": None,
                    "title": "合成产品官方说明",
                    "quote": quote,
                    "company": "公开资料",
                    "url": "https://example.com/career-platform",
                    "publisher": "example.com",
                    "source": "public_web",
                    "evidence_kind": "search_answer",
                    "provider_synthesized": True,
                    "source_note": "本地合成搜索线索，不是已取得的网页正文。",
                    "start": 0,
                    "end": len(quote),
                    "full_text_length": len(quote),
                    "mode": "synthetic",
                    "response_origin": "synthetic",
                    "transport": "local_test",
                    "observed_at": now(),
                    "source_published_at": None,
                }
            ]
        }

    async def fetch(url):
        requests["read"] += 1
        assert url == "https://example.com/career-platform"
        return (
            200,
            {"content-type": "text/html; charset=utf-8"},
            (
                "<html><title>合成产品官方说明</title><main>合成平台提供任务执行记录与失败定位线索。"
                "本资料只演示产品行为，未描述某个岗位的个人验收决定权。</main></html>"
            ).encode(),
        )

    monkeypatch.setattr(PublicSearch, "search", search)
    monkeypatch.setattr(public_documents, "pinned_request", fetch)
    database = tmp_path / "public-career.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, model=PublicCareerModel(), reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        auth = {"X-WO-Token": token}
        job = client.post(
            "/api/import",
            json={
                "title": "合成接口岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "负责Python接口开发与测试。其他业务背景未说明。",
            },
            headers=auth,
        ).json()["job_id"]
        identity = client.post(
            "/api/career",
            json={
                "title": "合成公开背景调查",
                "goal": "区分产品能力与个人责任",
                "background": "合成背景，无真实业务项目。",
                "job_ids": [job],
            },
            headers=auth,
        ).json()["id"]
        local = run_stage(client, identity, auth, "role")
        assert requests == {"search": 0, "read": 0} and local["budget"]["max_public"] == 0
        researched = run_stage(client, identity, auth, "role", allow_public=True)
        assert requests == {"search": 1, "read": 1}
        assert researched["results"][0]["result"]["status"] == "completed"
        assert researched["results"][0]["allow_public"] is True
        assert len(researched["results"][0]["result"]["claims"]) == 2
        assert len(researched["requirements"]) == 1
        assert researched["usage"]["public"] == 2 and researched["budget"]["max_public"] == 8
        body_id = researched["discovered_materials"][0]["id"]
        assert "失败定位线索" in client.get("/api/public-documents/" + body_id).json()["text"]
        searched = client.get(f"/api/career/{identity}/search", params={"q": "失败定位线索"}).json()
        assert any(
            ev.get("public_document_id") == body_id for ev in searched["originals"]["evidence"]
        )
        attached = client.post(
            f"/api/career/{identity}/materials/attach", json={"document_id": body_id}, headers=auth
        ).json()
        assert not attached["discovered_materials"] and len(attached["materials"]) == 1
        reused = run_stage(
            client,
            identity,
            auth,
            "ask",
            material_id=body_id,
            question="产品说明是否证明了个人验收责任？",
            allow_public=False,
        )
        assert requests == {"search": 1, "read": 1}
        assert reused["results"][0]["result"]["public_searches"] == 0
        assert any(
            ev.get("public_document_id") == body_id
            for ev in reused["results"][0]["result"]["evidence"]
        )
        offline = run_stage(client, identity, auth, "role", allow_public=True, offline=True)
        assert offline["results"][0]["result"]["status"] == "evidence_only"
        assert requests == {"search": 1, "read": 1}
        for _ in range(2):
            run_stage(client, identity, auth, "role", allow_public=True)
        assert requests == {"search": 3, "read": 3}
        limited = client.post(
            f"/api/career/{identity}/prepare",
            json={"kind": "role", "allow_public": True},
            headers=auth,
        )
        assert limited.status_code == 422 and "公开补查额度" in limited.json()["message"]
        continued = run_stage(client, identity, auth, "role", allow_public=False)
        assert continued["results"][0]["result"]["status"] == "completed"
        assert requests == {"search": 3, "read": 3}
