"""CSV和截图只产生待核对草稿，测试资料均明确合成且只进入临时库。"""

import asyncio
import hashlib
import json
import re
import struct
import zlib

import httpx
import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.import_drafts import ImportDraftService, commit_rows, csv_preview
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


def png():
    def chunk(kind, data):
        return (
            struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0\xff\xff\xff"))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def context(tmp_path):
    path = tmp_path / "imports.db"
    upgrade(path)
    repository = Repository(path)
    try:
        yield (
            repository,
            ImportDraftService(repository, tmp_path / "images"),
            RawArchive(tmp_path / "raw"),
        )
    finally:
        repository.close()


def test_csv_bom_multiline_validation_partial_commit_and_stable_ids(context):
    repo, _, archive = context
    text = (
        "\ufefftitle,company,description,external_id,data_kind\n"
        '合成岗位,模拟公司,"第一行Python\n第二行RAG",csv-1,synthetic\n'
        "缺正文,模拟公司,,csv-2,synthetic\n"
    )
    preview = csv_preview(text)
    assert preview["row_count"] == 2 and preview["valid_rows"] == 1
    assert repo.counts()["jobs"] == 0
    assert preview["rows"][0]["draft"]["description"] == "第一行Python\n第二行RAG"
    result = commit_rows(
        repo,
        archive,
        [{"row_number": row["row_number"], "jd": row["draft"]} for row in preview["rows"]],
    )
    assert result["status"] == "partial" and result["imported"] == result["failed"] == 1
    again = commit_rows(repo, archive, [{"row_number": 2, "jd": preview["rows"][0]["draft"]}])
    assert again["rows"][0]["stats"]["jobs_new"] == again["rows"][0]["stats"]["snapshots_new"] == 0
    assert repo.counts()["jobs"] == 1
    assert Catalog(repo).query()["jobs"][0]["source_published_at"] is None
    with pytest.raises(ProbeError, match="CSV_ROW_LIMIT"):
        csv_preview("title,company,description\n" + "岗位,公司,正文\n" * 21)
    with pytest.raises(ProbeError, match="INVALID_CSV_HEADERS"):
        csv_preview("title,company,description,security_id\n岗位,公司,正文,private")
    with pytest.raises(ProbeError, match="CSV_TOO_LARGE"):
        csv_preview("x" * 512001)


def test_image_requires_consent_configuration_and_explicit_review(context):
    repo, service, archive = context
    raw = png()
    asset = service.upload(raw, mime="image/png", data_kind="synthetic")
    assert "path" not in asset and asset["sha256"] == hashlib.sha256(raw).hexdigest()
    assert service.read(asset["id"])[1] == raw
    with pytest.raises(ProbeError, match="IMAGE_MODEL_CONSENT_REQUIRED"):
        asyncio.run(service.extract(asset["id"], Settings()))
    missing = asyncio.run(service.extract(asset["id"], Settings(), allow_model=True))
    assert missing["status"] == "failed" and missing["model_calls"] == 0
    assert missing["error_code"] == "MODEL_CONFIG_MISSING" and repo.counts()["jobs"] == 0
    fields = {
        "title": "合成岗位",
        "company": "模拟公司",
        "description": "合成截图人工转录Python",
        "data_kind": "synthetic",
        "import_asset_id": asset["id"],
    }
    with pytest.raises(ValidationError):
        ManualJD(**fields)
    with pytest.raises(ValidationError):
        ManualJD(title="合成", company="模拟", description="正文", ocr_reviewed=True)
    saved = import_jd(repo, archive, ManualJD(**fields, ocr_reviewed=True))
    job = repo.job(saved["job_id"])
    provenance = job["provenance"]["description_text"]
    assert provenance["input_kind"] == "image_manual_review"
    assert provenance["import_asset_id"] == asset["id"]
    document = Catalog(repo).document(provenance["document_id"])
    assert document["import_asset_id"] == asset["id"] and document["integrity"] == "verified"
    with pytest.raises(ProbeError, match="IMPORT_ASSET_DATA_KIND_MISMATCH"):
        import_jd(
            repo, archive, ManualJD(**{**fields, "data_kind": "user_provided"}, ocr_reviewed=True)
        )


def test_visual_extraction_is_one_fixed_request_and_never_auto_imports(context, monkeypatch):
    repo, service, archive = context
    asset = service.upload(png(), mime="image/png", data_kind="synthetic")
    seen = []

    def handle(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert payload["store"] is False and "tools" not in payload
        assert payload["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")
        fields = {
            key: None
            for key in (
                "title",
                "company",
                "description",
                "city",
                "salary",
                "education",
                "experience",
                "source_published_raw",
            )
        }
        fields.update(title="合成岗位", company="模拟公司", description="合成正文Python")
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(fields)}],
                    }
                ],
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    settings = Settings(
        model_base_url="https://model.example/v1",
        model_name="test-vision",
        model_api_key="never-print-test-key",
    )
    result = asyncio.run(service.extract(asset["id"], settings, allow_model=True))
    assert result["status"] == "draft_ready" and result["model_calls"] == len(seen) == 1
    assert result["asset"]["extraction_status"] == "extracted" and repo.counts()["jobs"] == 0
    assert "source_published_at" not in result["draft"]
    saved = import_jd(
        repo,
        archive,
        ManualJD(
            **result["draft"], data_kind="synthetic", import_asset_id=asset["id"], ocr_reviewed=True
        ),
    )
    assert (
        repo.job(saved["job_id"])["provenance"]["description_text"]["input_kind"]
        == "ocr_manual_review"
    )


def test_http_csv_image_and_binary_guards(tmp_path):
    path = tmp_path / "http.db"
    upgrade(path)
    settings = Settings(database_path=path, raw_directory=tmp_path / "raw")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        auth = {"X-WO-Token": token}
        assert (
            client.post(
                "/api/import-assets", content=png(), headers={"Content-Type": "image/png"}
            ).status_code
            == 403
        )
        uploaded = client.post(
            "/api/import-assets?data_kind=synthetic",
            content=png(),
            headers={**auth, "Content-Type": "image/png"},
        )
        assert uploaded.status_code == 201
        asset = uploaded.json()
        image = client.get(asset["image_url"])
        assert image.content == png() and image.headers["content-type"] == "image/png"
        assert (
            client.get(asset["image_url"], headers={"Sec-Fetch-Site": "cross-site"}).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/import-assets/{asset['id']}/extract",
                json={"allow_model": False},
                headers=auth,
            ).status_code
            == 400
        )
        failed = client.post(
            f"/api/import-assets/{asset['id']}/extract", json={"allow_model": True}, headers=auth
        ).json()
        assert failed["status"] == "failed" and failed["model_calls"] == 0
        assert (
            client.post(
                "/api/import-assets",
                content=b"<svg></svg>",
                headers={**auth, "Content-Type": "image/png"},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/import-assets",
                content=b"x" * 5000001,
                headers={**auth, "Content-Type": "image/png"},
            ).status_code
            == 400
        )
        preview = client.post(
            "/api/imports/csv/preview",
            json={
                "csv_text": "title,company,description,data_kind\n合成,模拟,正文Python,synthetic"
            },
            headers=auth,
        ).json()
        assert client.get("/api/jobs").json()["jobs"] == []
        saved = client.post(
            "/api/imports/csv/commit",
            json={"rows": [{"row_number": 2, "jd": preview["rows"][0]["draft"]}]},
            headers=auth,
        ).json()
        assert saved["imported"] == 1
