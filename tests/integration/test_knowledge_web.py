"""真实HTTP入口的领域知识闭环，资料为明确合成，不替代真实语义评估。"""

import re

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_unified_domain_review_relation_correction_and_collection_http(tmp_path):
    database = tmp_path / "knowledge-web.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        page = client.get("/")
        token = re.search(r'name="wo-token" content="([^"]+)"', page.text)[1]
        headers = {"X-WO-Token": token}
        assert 'id="page-knowledge"' in page.text
        assert client.get("/assets/knowledge.js").status_code == 200
        imported = client.post(
            "/api/import",
            headers=headers,
            json={
                "title": "合成知识验收岗位",
                "company": "合成公司",
                "description": "使用 Python 交付业务接口。",
                "external_id": "knowledge-web-test",
                "data_kind": "synthetic",
            },
        )
        assert imported.status_code == 201
        job = imported.json()["job_id"]
        search = client.post(
            "/api/retrieval/unified",
            headers=headers,
            json={"terms": ["Python"], "job_ids": [job], "public_document_ids": []},
        )
        assert search.status_code == 200
        assert search.json()["sample"]["denominator"] == 1
        evidence = search.json()["evidence"]
        assert evidence[0]["data_kind"] == "synthetic"
        domain = client.post(
            "/api/knowledge/domains",
            headers=headers,
            json={
                "domain_key": "api_delivery",
                "name": "接口交付",
                "definition": "开发可用的业务接口",
                "exclusion": "只凭标题不能归类",
            },
        )
        assert domain.status_code == 201
        identity = domain.json()["id"]
        assert domain.json()["status"] == "candidate"
        relation_body = {
            "domain_id": identity,
            "source_kind": "task",
            "source_text": "开发接口",
            "target_kind": "deliverable",
            "target_text": "业务接口",
            "evidence": evidence,
        }
        relation = client.post("/api/knowledge/relations", headers=headers, json=relation_body)
        assert relation.status_code == 201
        relation_id = relation.json()["id"]
        denied = client.post(
            f"/api/knowledge/relations/{relation_id}/review",
            headers=headers,
            json={"decision": "accept", "reason": "合成审核"},
        )
        assert denied.status_code == 400
        reviewed = client.post(
            f"/api/knowledge/domains/{identity}/review",
            headers=headers,
            json={"decision": "accept", "reason": "合成审核定义，非真实语义标注"},
        )
        assert reviewed.status_code == 200
        reviewed = client.post(
            f"/api/knowledge/relations/{relation_id}/review",
            headers=headers,
            json={"decision": "accept", "reason": "合成审核引用与范围"},
        )
        assert reviewed.status_code == 200
        collection = client.post(
            "/api/knowledge/collection",
            headers=headers,
            json={"domain_id": identity, "job_ids": [job], "limit": 1},
        )
        assert collection.json()["counts"]["matched"] == 1
        corrected = client.post(
            f"/api/knowledge/jobs/{job}/domains",
            headers=headers,
            json={"domain_ids": [], "reason": "合成用户要求暂不归类"},
        )
        assert corrected.status_code == 200
        collection = client.post(
            "/api/knowledge/collection",
            headers=headers,
            json={"domain_id": identity, "job_ids": [job]},
        )
        assert collection.json()["counts"]["excluded"] == 1
        assert collection.json()["jobs"][0]["classification"] == "user_corrected"
        forged = {**evidence[0], "quote": "伪造的原文"}
        invalid = client.post(
            "/api/knowledge/relations",
            headers=headers,
            json={**relation_body, "evidence": [forged]},
        )
        assert invalid.status_code == 400
        assert invalid.json()["error_code"] == "INVALID_MEMORY_EVIDENCE"
        schema = client.get("/api/openapi.json").json()
        assert "/api/retrieval/unified" in schema["paths"]


def test_knowledge_inputs_reject_extra_operations_and_missing_review_reason(tmp_path):
    database = tmp_path / "knowledge-invalid.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        headers = {"X-WO-Token": token}
        invalid = client.post(
            "/api/retrieval/unified",
            headers=headers,
            json={"terms": ["Python"], "sql": "DELETE FROM jobs"},
        )
        assert invalid.status_code == 422
        denied = client.post(
            "/api/knowledge/domains/missing/review",
            headers=headers,
            json={"decision": "accept", "reason": ""},
        )
        assert denied.status_code == 422
