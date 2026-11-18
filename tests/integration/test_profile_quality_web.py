"""完整画像审核API闭环，合成模型与合成人审动作仅验证机制。"""

import json
import re
import sqlite3

import pytest
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.quality.service import DIMENSIONS
from work_observer.storage.database import upgrade


class SyntheticModel:
    async def turn(self, history):
        if "补充领域" in history[0]["content"]:
            context = json.loads(history[-1]["content"])
            key = context["evidence"][0]["id"]
            name, args = (
                "finish_profile",
                {
                    "domains": [
                        {
                            "domain": "business_application",
                            "rationale": "合成业务应用研发",
                            "evidence_ids": [key],
                        }
                    ],
                    "interview_questions": ["想向招聘方了解，服务接口如何验收？"],
                },
            )
        else:
            outputs = [
                json.loads(row["output"])
                for row in history
                if row.get("type") == "function_call_output"
            ]
            if not outputs:
                name, args = "query_jobs", {}
            elif not any(row.get("evidence") for row in outputs):
                name, args = "read_job", {"job_id": outputs[0]["jobs"][0]["id"]}
            else:
                key = next(row["evidence"][0]["id"] for row in outputs if row.get("evidence"))
                name, args = (
                    "finish_research",
                    {
                        "claims": [
                            {
                                "category": category,
                                "requirement": requirement,
                                "basis": "direct",
                                "text": text,
                                "evidence_ids": [key],
                            }
                            for category, requirement, text in (
                                ("business", "unspecified", "客户服务业务"),
                                ("task", "unspecified", "开发RAG应用"),
                                ("deliverable", "unspecified", "交付接口"),
                                ("responsibility", "unspecified", "上线维护"),
                                ("ability", "required", "Python必备"),
                                ("tool", "preferred", "Docker加分"),
                            )
                        ],
                        "gaps": ["验收细则未知"],
                    },
                )
        call = {
            "type": "function_call",
            "call_id": str(len(history)),
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
        }
        return [call], call


@pytest.fixture
def web_profile(tmp_path):
    path = tmp_path / "app.db"
    upgrade(path)
    settings = Settings(
        database_path=path, raw_directory=tmp_path / "raw", model_name="synthetic-model"
    )
    with TestClient(
        create_app(settings, model=SyntheticModel(), reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        auth = {"X-WO-Token": token}
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成完整画像岗位",
                "company": "合成公司",
                "description": "客户服务业务。开发RAG应用并交付接口，负责上线维护。"
                "Python必备，Docker加分。",
                "external_id": "quality",
                "data_kind": "synthetic",
            },
        ).json()["job_id"]
        personal = client.post(
            "/api/memories",
            headers=auth,
            json={"kind": "preference", "content": "合成明确偏好：RAG开发"},
        ).json()
        profile = client.post("/api/profiles/" + job, headers=auth, json={}).json()
        assert profile["status"] == "completed"
        yield client, auth, settings, job, profile, personal


def review(packet, **updates):
    data = {
        "artifact_sha256": packet["artifact_sha256"],
        "reviewer": "合成HTTP核对",
        "reviewer_kind": "human",
        "decision": "pending",
        "note": "合成机制验证，不是真实人类标签",
        "dimensions": {key: {"rating": "pass", "reason": "合成原文对照"} for key in DIMENSIONS},
        "claim_reviews": [
            {
                "index": row["index"],
                "support": "supported",
                "requirement": "correct",
                "note": "合成逐条语义",
            }
            for row in packet["claims"]
        ],
        "domain_reviews": [
            {
                "index": row["index"],
                "support": "supported",
                "scope": "correct",
                "note": "合成领域核对",
            }
            for row in packet["domains"]
        ],
        "question_reviews": [
            {
                "index": row["index"],
                "direction": "correct",
                "relevance": "correct",
                "note": "合成面向招聘方的问题",
            }
            for row in packet["interview_questions"]
        ],
    }
    data.update(updates)
    return data


def test_profile_quality_http_packet_supplement_contract_and_agent_cannot_approve(web_profile):
    client, auth, _, _, profile, _ = web_profile
    base = "/api/profile-quality/analyses/" + profile["id"]
    packet = client.get(base).json()
    assert packet["approve_allowed"] and packet["title"] == "合成完整画像岗位"
    assert packet["data_kind"] == "synthetic"
    assert len(packet["domains"]) == len(packet["interview_questions"]) == 1
    assert "交付接口" in packet["source_texts"][0]["text"]
    assert client.post(base + "/reviews", json=review(packet)).status_code == 403
    missing = review(packet)
    missing.pop("domain_reviews")
    assert client.post(base + "/reviews", headers=auth, json=missing).status_code == 422
    incomplete = client.post(
        base + "/reviews", headers=auth, json=review(packet, domain_reviews=[], decision="approve")
    )
    assert incomplete.status_code == 400
    assert (
        client.post(
            base + "/reviews",
            headers=auth,
            json=review(packet, reviewer_kind="agent_assisted", decision="approve"),
        ).status_code
        == 400
    )
    accepted = client.post(base + "/reviews", headers=auth, json=review(packet, decision="approve"))
    assert accepted.status_code == 201 and accepted.json()["status"] == "approved"
    schema = client.get("/api/openapi.json").json()
    assert "ProfileQualityReviewInput" in schema["components"]["schemas"]
    assert 'id="page-profile-quality"' in client.get("/").text
    assert client.get("/assets/profile-quality.js").status_code == 200


def test_human_reject_profile_requires_new_analysis_without_rejecting_base_research(web_profile):
    client, auth, _, job, profile, _ = web_profile
    base = "/api/profile-quality/analyses/" + profile["id"]
    packet = client.get(base).json()
    source = client.get("/api/research/" + packet["source_run_id"]).json()
    agent = client.post(
        base + "/reviews",
        headers=auth,
        json=review(packet, reviewer_kind="agent_assisted", decision="reject"),
    )
    assert agent.status_code == 201 and not client.get("/api/profiles/" + job).json()["stale"]
    assert (
        client.post(
            base + "/reviews", headers=auth, json=review(packet, decision="reject")
        ).status_code
        == 201
    )
    assert client.get("/api/profiles/" + job).json()["stale"]
    assert (
        client.get("/api/research/" + packet["source_run_id"]).json()["result"] == source["result"]
    )
    assert client.get("/api/quality/runs/" + packet["source_run_id"]).json()["approve_allowed"]
    fresh = client.post("/api/profiles/" + job, headers=auth, json={}).json()
    assert fresh["id"] != profile["id"] and not fresh["stale"]
    rows = client.get("/api/profile-quality").json()["profiles"]
    assert len(rows) == 2 and {row["human_review"]["status"] for row in rows} == {
        "pending",
        "rejected",
    }


def test_personal_forget_erases_complete_profile_review_text_and_keeps_jd(web_profile):
    client, auth, settings, _, profile, personal = web_profile
    base = "/api/profile-quality/analyses/" + profile["id"]
    packet = client.get(base).json()
    marker = "SYNTHETIC_PRIVATE_PROFILE_HTTP_REVIEW"
    data = review(packet, reviewer_kind="agent_assisted", decision="reject", note=marker)
    for name in ("claim_reviews", "domain_reviews", "question_reviews"):
        for row in data[name]:
            row["note"] = marker
    saved = client.post(base + "/reviews", headers=auth, json=data).json()
    forgotten = client.delete("/api/memories/" + personal["id"], headers=auth)
    assert forgotten.status_code == 200
    assert saved["id"] in forgotten.json()["invalidated_profile_quality_review_ids"]
    assert client.get("/api/profile-quality").json()["profiles"] == []
    assert client.get(base).status_code in {400, 404}
    assert client.get("/api/overview").json()["jobs"] == 1
    path = settings.database_path.parent / "checkpoints.db"
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT record FROM profile_quality_reviews").fetchall()
        assert rows and all(
            marker not in encoded and json.loads(encoded)["status"] == "invalidated"
            for (encoded,) in rows
        )
