"""合成样例验证重复审核与截图坐标机制；不证明图中文字的语义正确。"""

import base64
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.connectors.import_drafts import ImportDraftService
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.data_quality.models import DuplicateReview
from work_observer.data_quality.service import DataQualityService
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import row_fingerprints, upgrade
from work_observer.storage.models import SourceDocument
from work_observer.storage.repository import Repository

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


@pytest.fixture
def quality(tmp_path):
    db = tmp_path / "quality.db"
    upgrade(db)
    repo = Repository(db)
    archive = RawArchive(tmp_path / "raw", [])
    service = DataQualityService(repo)
    yield service, repo, archive, tmp_path
    repo.close()


def add(repo, archive, identifier, body, **fields):
    return import_jd(
        repo,
        archive,
        ManualJD(
            title="合成AI岗位",
            company="合成公司",
            external_id=identifier,
            description=body,
            data_kind="synthetic",
            **fields,
        ),
    )["job_id"]


def image_job(quality):
    service, repo, archive, tmp_path = quality
    images = ImportDraftService(repo, tmp_path / "images")
    asset = images.upload(PNG, data_kind="synthetic")
    job = add(
        repo,
        archive,
        "image",
        "合成😀截图正文：必须掌握 Python。",
        import_asset_id=asset["id"],
        ocr_reviewed=True,
    )
    target = service.screenshot_targets()["targets"][0]
    evidence = Catalog(repo).evidence(job)[0]
    return (
        {
            "asset_id": asset["id"],
            "job_id": job,
            "snapshot_id": evidence["snapshot_id"],
            "document_id": evidence["document_id"],
            "bbox": [0.1, 0.2, 0.8, 0.7],
            "start": evidence["start"],
            "end": evidence["end"],
            "quote": evidence["quote"],
            "reviewed": True,
            "note": "合成机制样例，非图中文字正确性验收",
        },
        target,
        images,
    )


def test_same_title_is_insufficient_and_body_similarity_exposes_conflicting_fields(quality):
    service, repo, archive, _ = quality
    left = add(
        repo,
        archive,
        "left",
        "负责研究RAG检索与评估系统，必须掌握Python，交付可运行服务。",
        city="上海",
    )
    right = add(
        repo,
        archive,
        "right",
        "负责研究RAG检索与评估系统，必须掌握Python，交付可运行服务。",
        city="北京",
    )
    other = add(repo, archive, "other", "负责行政排班，整理纸质合同，安排仓库盘点。", city="上海")
    scanned = service.duplicates()
    assert scanned["matching_pairs"] == 1
    candidate = scanned["candidates"][0]
    assert {candidate["left"]["id"], candidate["right"]["id"]} == {left, right}
    assert other not in {candidate["left"]["id"], candidate["right"]["id"]}
    assert candidate["basis"]["reasons"] == ["normalized_body_equal"]
    assert candidate["basis"]["conflicts"][0]["field"] == "city"
    assert candidate["basis"]["is_confirmed_identity"] is False


def test_cross_input_duplicate_review_is_append_only_idempotent_and_preserves_sources(quality):
    service, repo, archive, tmp_path = quality
    region, target, _ = image_job(quality)
    text_job = add(repo, archive, "text", target["text"])
    with sqlite3.connect(tmp_path / "quality.db") as db:
        before = row_fingerprints(db)
        original = {
            name: spec
            for name, spec in before.items()
            if name not in {"duplicate_reviews", "screenshot_regions"}
        }
    first = service.review_duplicate(
        region["job_id"], text_job, "linked", "人工核对截图与文本，保留两来源"
    )
    again = service.review_duplicate(
        text_job, region["job_id"], "linked", "人工核对截图与文本，保留两来源"
    )
    assert again["id"] == first["id"]
    second = service.review_duplicate(
        text_job, region["job_id"], "distinct", "进一步核对后认为是不同岗位"
    )
    assert second["version"] == 2 and second["previous_id"] == first["id"]
    assert service.reviews()[0]["decision"] == "distinct"
    with Session(repo.engine) as session:
        assert len(session.scalars(select(DuplicateReview)).all()) == 2
    with sqlite3.connect(tmp_path / "quality.db") as db:
        assert row_fingerprints(db, original) == original
    assert service.duplicates()["candidates"][0]["review"]["decision"] == "distinct"


def test_duplicate_review_marks_changed_basis_stale_and_rejects_self_link(quality):
    service, repo, archive, _ = quality
    a, b = [add(repo, archive, identity, "维护RAG服务和Python接口。") for identity in ("a", "b")]
    service.review_duplicate(a, b, "linked", "人工核对后关联")
    add(repo, archive, "b", "新版本工作职责变为业务运营。")
    assert service.reviews()[0]["stale"]
    with pytest.raises(ProbeError, match="DUPLICATE_SELF_LINK_DENIED"):
        service.review_duplicate(a, a, "linked", "不能自我关联")
    with pytest.raises(ProbeError, match="DUPLICATE_REVIEW_REASON_REQUIRED"):
        service.review_duplicate(a, b, "linked", " ")


def test_region_requires_manual_review_and_real_image_source_link(quality):
    service, _, _, _ = quality
    payload, target, images = image_job(quality)
    assert target["asset_id"] == payload["asset_id"] and "😀" in target["text"]
    with pytest.raises(ProbeError, match="REGION_MANUAL_REVIEW_REQUIRED"):
        service.create_region(**{**payload, "reviewed": False})
    another = images.upload(PNG, data_kind="synthetic")
    with pytest.raises(ProbeError, match="REGION_IMAGE_SOURCE_MISMATCH"):
        service.create_region(**{**payload, "asset_id": another["id"]})
    for bbox in (
        [0, 0, 0, 1],
        [0, 1, 1, 0],
        [0, 0, 1.1, 1],
        [True, 0, 1, 1],
        [0, float("nan"), 1, 1],
    ):
        with pytest.raises(ProbeError, match="INVALID_REGION_BBOX"):
            service.create_region(**{**payload, "bbox": bbox})
    with pytest.raises(ProbeError, match="INVALID_MEMORY_EVIDENCE"):
        service.create_region(**{**payload, "quote": "伪造截图文字"})


def test_region_roundtrip_rechecks_image_and_exact_quote_and_is_not_ocr_coordinates(quality):
    service, repo, _, _ = quality
    payload, _, images = image_job(quality)
    row = service.create_region(**payload)
    assert row["integrity"] == "verified" and row["bbox"] == payload["bbox"]
    assert row["is_ocr_detected_region"] is False
    assert row["selection_method"] == "manual_reviewed_region"
    assert service.create_region(**payload)["id"] == row["id"]
    reopened = DataQualityService(Repository(Path(repo.engine.url.database)))
    try:
        assert reopened.regions(payload["job_id"])[0]["quote"] == payload["quote"]
    finally:
        reopened.repository.close()
    with Session(repo.engine) as session:
        from work_observer.connectors.import_models import ImportAsset

        image_path = Path(session.get(ImportAsset, payload["asset_id"]).path)
    original = image_path.read_bytes()
    image_path.write_bytes(b"tampered")
    assert service.regions()[0]["integrity"] == "missing_or_changed"
    with pytest.raises(ProbeError, match="IMPORT_ASSET_INTEGRITY_FAILED"):
        images.read(payload["asset_id"])
    image_path.write_bytes(original)
    with Session(repo.engine) as session:
        document = session.get(SourceDocument, payload["document_id"])
        Path(document.path).write_text("changed", encoding="utf-8")
    assert service.regions()[0]["integrity"] == "missing_or_changed"


def test_region_historical_version_and_withdrawal_retain_original_image(quality):
    service, repo, archive, _ = quality
    payload, _, images = image_job(quality)
    row = service.create_region(**payload)
    add(repo, archive, "image", "更新后的合成正文。")
    historical = service.regions()[0]
    assert historical["integrity"] == "verified"
    assert historical["warnings"] == ["historical_job_version"]
    assert service.withdraw_region(row["id"])["status"] == "withdrawn"
    assert service.regions()[0]["quote"] == payload["quote"]
    assert images.read(payload["asset_id"])[1] == PNG
