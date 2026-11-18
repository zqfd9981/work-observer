"""资料核对真实HTTP服务集成；正文和1像素图片均为合成机制材料。"""

import base64
import re

import pytest
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


@pytest.fixture
def quality_web(tmp_path):
    settings = Settings(database_path=tmp_path / "app.db", raw_directory=tmp_path / "raw")
    upgrade(settings.database_path)
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        yield client, {"X-WO-Token": token}, settings


def add_image_jd(client, auth):
    uploaded = client.post(
        "/api/import-assets?data_kind=synthetic",
        content=PNG,
        headers={**auth, "Content-Type": "image/png"},
    )
    assert uploaded.status_code == 201
    asset_id = uploaded.json()["id"]
    data = {
        "title": "合成截图岗位",
        "company": "合成公司",
        "description": "合成😀正文：掌握 Python 并交付服务。",
        "external_id": "image",
        "data_kind": "synthetic",
        "import_asset_id": asset_id,
        "ocr_reviewed": True,
    }
    imported = client.post("/api/import", json=data, headers=auth)
    assert imported.status_code == 201
    return asset_id, imported.json()["job_id"], data


def test_http_duplicate_review_requires_token_exposes_basis_and_never_merges_jobs(quality_web):
    client, auth, _ = quality_web
    _, image_job, data = add_image_jd(client, auth)
    data = {
        key: value for key, value in data.items() if key not in {"import_asset_id", "ocr_reviewed"}
    }
    data["external_id"] = "text"
    text_job = client.post("/api/import", json=data, headers=auth).json()["job_id"]
    assert client.post("/api/data-quality/duplicates/scan", json={}).status_code == 403
    scanned = client.post("/api/data-quality/duplicates/scan", json={}, headers=auth)
    assert scanned.status_code == 200 and scanned.json()["matching_pairs"] == 1
    pair = scanned.json()["candidates"][0]
    assert pair["basis"]["reasons"] == ["normalized_body_equal"]
    reviewed = client.post(
        "/api/data-quality/duplicates/review",
        headers=auth,
        json={
            "left_job_id": image_job,
            "right_job_id": text_job,
            "decision": "linked",
            "reason": "合成机制验收，人工关联并保留来源",
        },
    )
    assert reviewed.status_code == 201 and reviewed.json()["version"] == 1
    assert client.get("/api/data-quality/duplicates/reviews").json()[0]["decision"] == "linked"
    assert client.get("/api/overview").json()["jobs"] == 2


def test_http_region_exact_span_image_roundtrip_and_withdrawal(quality_web):
    client, auth, _ = quality_web
    asset_id, job, data = add_image_jd(client, auth)
    target = client.get("/api/data-quality/screenshot-targets").json()["targets"][0]
    assert target["asset_id"] == asset_id and target["job_id"] == job
    quote = "掌握 Python"
    start = data["description"].index(quote)
    payload = {
        "asset_id": asset_id,
        "job_id": job,
        "snapshot_id": target["snapshot_id"],
        "document_id": target["document_id"],
        "bbox": [0.1, 0.1, 0.9, 0.7],
        "start": start,
        "end": start + len(quote),
        "quote": quote,
        "reviewed": True,
    }
    no_review = client.post(
        "/api/data-quality/regions", headers=auth, json={**payload, "reviewed": False}
    )
    assert no_review.status_code == 400
    assert no_review.json()["error_code"] == "REGION_MANUAL_REVIEW_REQUIRED"
    created = client.post("/api/data-quality/regions", headers=auth, json=payload)
    assert created.status_code == 201 and created.json()["integrity"] == "verified"
    assert created.json()["is_ocr_detected_region"] is False
    assert client.get(created.json()["image_url"]).content == PNG
    listed = client.get("/api/data-quality/regions?job_id=" + job).json()
    assert listed[0]["quote"] == quote and listed[0]["start"] == start
    withdrawn = client.post(
        "/api/data-quality/regions/" + created.json()["id"] + "/withdraw", headers=auth
    )
    assert withdrawn.json()["status"] == "withdrawn"
    assert client.get(created.json()["image_url"]).content == PNG


def test_http_quality_page_assets_schema_and_invalid_bbox_contract(quality_web):
    client, auth, _ = quality_web
    assert 'id="page-data-quality"' in client.get("/").text
    script = client.get("/assets/data-quality.js")
    assert script.status_code == 200 and "pointerdown" in script.text
    schema = client.get("/api/openapi.json").json()
    assert "/api/data-quality/duplicates/scan" in schema["paths"]
    assert "ScreenshotRegionInput" in schema["components"]["schemas"]
    asset_id, job, _ = add_image_jd(client, auth)
    target = client.get("/api/data-quality/screenshot-targets").json()["targets"][0]
    invalid = client.post(
        "/api/data-quality/regions",
        headers=auth,
        json={
            "asset_id": asset_id,
            "job_id": job,
            "snapshot_id": target["snapshot_id"],
            "document_id": target["document_id"],
            "bbox": [0, 0, 1, 1],
            "start": True,
            "end": 2,
            "quote": "合成",
            "reviewed": "true",
        },
    )
    assert invalid.status_code == 422
