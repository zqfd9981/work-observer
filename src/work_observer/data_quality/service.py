"""有界疑似重复发现、追加人工审核及人工截图区域引用。"""

import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from work_observer.collection.contracts import digest, now
from work_observer.connectors.import_drafts import ImportDraftService
from work_observer.connectors.import_models import ImportAsset
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.data_quality.models import DuplicateReview, ScreenshotRegion
from work_observer.memory.service import MemoryService
from work_observer.storage.models import Job, JobObservation, JobSnapshot, SourceDocument


def _normal(value):
    return re.sub(r"\W+", "", (value or "").casefold())


def _shingles(value):
    value = _normal(value)[:8000]
    return {value[i : i + 3] for i in range(max(0, len(value) - 2))}


def _job(row):
    return {
        "id": row.id,
        "title": row.title,
        "company": row.company_name_raw,
        "city": row.city,
        "source": row.source,
        "job_url": row.job_url,
        "description_preview": (row.description_text or "")[:1200],
        "description_length": len(row.description_text or ""),
        "detail_state": row.detail_state,
    }


def _pair(left, right):
    if left == right:
        raise ProbeError("DUPLICATE_SELF_LINK_DENIED")
    left, right = sorted((left, right))
    return left, right, left + ":" + right


def _fingerprint(row):
    return digest({**_job(row), "full_text": row.description_text})


class DataQualityService:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _get_job(session, identity):
        row = session.get(Job, identity)
        if row is None:
            raise ProbeError("JOB_NOT_FOUND")
        return row

    @staticmethod
    def _basis(left, right, cache=None):
        cache = cache or {
            row.id: {
                "body": _normal(row.description_text),
                "shingles": _shingles(row.description_text),
                "sha": _fingerprint(row),
            }
            for row in (left, right)
        }
        title_ratio = SequenceMatcher(None, _normal(left.title), _normal(right.title)).ratio()
        a, b = cache[left.id]["shingles"], cache[right.id]["shingles"]
        body_ratio = len(a & b) / len(a | b) if a and b else 0
        same_body = bool(a and b and cache[left.id]["body"] == cache[right.id]["body"])
        same_url = bool(left.job_url and left.job_url == right.job_url)
        same_company = bool(
            _normal(left.company_name_raw)
            and _normal(left.company_name_raw) == _normal(right.company_name_raw)
        )
        conflicts = [
            {"field": key, "left": getattr(left, key), "right": getattr(right, key)}
            for key in (
                "company_name_raw",
                "title",
                "city",
                "salary_raw",
                "education_raw",
                "experience_raw",
            )
            if getattr(left, key)
            and getattr(right, key)
            and getattr(left, key) != getattr(right, key)
        ]
        reasons = []
        if same_body:
            reasons.append("normalized_body_equal")
        elif body_ratio >= 0.55 and title_ratio >= 0.7:
            reasons.append("body_and_title_similar")
        if same_url and (body_ratio >= 0.2 or title_ratio >= 0.7 and same_company):
            reasons.append("same_saved_url")
        return {
            "left_sha256": cache[left.id]["sha"],
            "right_sha256": cache[right.id]["sha"],
            "body_similarity": round(body_ratio, 4),
            "title_similarity": round(title_ratio, 4),
            "same_company_name": same_company,
            "reasons": reasons,
            "conflicts": conflicts,
            "method": "local-text-shingles-v1",
            "body_sample_character_limit": 8000,
            "body_sample_truncated": len(cache[left.id]["body"]) > 8000
            or len(cache[right.id]["body"]) > 8000,
            "is_confirmed_identity": False,
        }

    def duplicates(self, job_ids=None, *, limit=50):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ProbeError("INVALID_DUPLICATE_LIMIT")
        if job_ids is not None and (not isinstance(job_ids, list) or not 1 <= len(job_ids) <= 300):
            raise ProbeError("INVALID_DUPLICATE_SCOPE")
        with Session(self.repository.engine) as session:
            statement = select(Job)
            if job_ids is not None:
                statement = statement.where(Job.id.in_(job_ids))
            total = session.scalar(select(func.count()).select_from(statement.subquery()))
            rows = session.scalars(statement.order_by(Job.id).limit(300)).all()
            # 预计算每岗文本签名，比较仍有硬范围上限；没有使用top-k当完整分母。
            candidates = []
            cache = {
                row.id: {
                    "body": _normal(row.description_text),
                    "shingles": _shingles(row.description_text),
                    "sha": _fingerprint(row),
                }
                for row in rows
            }
            reviews = self._latest_reviews(session)
            for index, left in enumerate(rows):
                for right in rows[index + 1 :]:
                    basis = self._basis(left, right, cache)
                    if not basis["reasons"]:
                        continue
                    _, _, key = _pair(left.id, right.id)
                    review = reviews.get(key)
                    candidates.append(
                        {
                            "left": _job(left),
                            "right": _job(right),
                            "basis": basis,
                            "review": self._review_record(review, left, right) if review else None,
                        }
                    )
            candidates.sort(
                key=lambda row: (
                    bool(row["review"]),
                    -row["basis"]["body_similarity"],
                    row["left"]["id"],
                    row["right"]["id"],
                )
            )
            return {
                "candidates": candidates[:limit],
                "scope_total": total,
                "scanned_jobs": len(rows),
                "matching_pairs": len(candidates),
                "truncated": total > len(rows) or len(candidates) > limit,
                "note": "只提出疑似重复；相同标题或公司名称本身不确认身份。"
                "人工关联也不删除、合并或改写原岗位。",
            }

    @staticmethod
    def _latest_reviews(session):
        rows = session.scalars(
            select(DuplicateReview).order_by(DuplicateReview.version.desc())
        ).all()
        result = {}
        for row in rows:
            result.setdefault(row.pair_key, row)
        return result

    @staticmethod
    def _review_record(row, left, right):
        return {
            key: getattr(row, key)
            for key in (
                "id",
                "version",
                "previous_id",
                "left_job_id",
                "right_job_id",
                "decision",
                "reason",
                "basis",
                "created_at",
            )
        } | {
            "stale": row.basis.get("left_sha256") != _fingerprint(left)
            or row.basis.get("right_sha256") != _fingerprint(right)
        }

    def reviews(self):
        with Session(self.repository.engine) as session:
            result = []
            for row in self._latest_reviews(session).values():
                left = self._get_job(session, row.left_job_id)
                right = self._get_job(session, row.right_job_id)
                result.append(
                    {
                        **self._review_record(row, left, right),
                        "left": _job(left),
                        "right": _job(right),
                    }
                )
            return result

    def review_duplicate(self, left_id, right_id, decision, reason):
        if decision not in {"linked", "distinct", "withdrawn"}:
            raise ProbeError("INVALID_DUPLICATE_DECISION")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1200:
            raise ProbeError("DUPLICATE_REVIEW_REASON_REQUIRED")
        left_id, right_id, key = _pair(left_id, right_id)
        with Session(self.repository.engine) as session, session.begin():
            left, right = [self._get_job(session, identity) for identity in (left_id, right_id)]
            previous = session.scalar(
                select(DuplicateReview)
                .where(DuplicateReview.pair_key == key)
                .order_by(DuplicateReview.version.desc())
                .limit(1)
            )
            basis = self._basis(left, right)
            if (
                previous
                and previous.decision == decision
                and previous.reason == reason.strip()
                and previous.basis == basis
            ):
                return self._review_record(previous, left, right)
            row = DuplicateReview(
                id=uuid4().hex,
                pair_key=key,
                version=previous.version + 1 if previous else 1,
                previous_id=previous.id if previous else None,
                left_job_id=left_id,
                right_job_id=right_id,
                decision=decision,
                reason=reason.strip(),
                basis=basis,
                created_at=now(),
            )
            session.add(row)
            session.flush()
            return self._review_record(row, left, right)

    def screenshot_targets(self):
        with Session(self.repository.engine) as session:
            rows = session.execute(
                select(JobObservation, JobSnapshot, SourceDocument, Job)
                .join(JobSnapshot, JobObservation.snapshot_id == JobSnapshot.id)
                .join(SourceDocument, JobObservation.document_id == SourceDocument.id)
                .join(Job, JobObservation.job_id == Job.id)
                .where(JobObservation.kind == "detail")
                .order_by(JobObservation.observed_at.desc())
                .limit(1000)
            ).all()
            targets, seen = [], set()
            for observation, snapshot, document, job in rows:
                asset_id = document.provenance.get("import_asset_id")
                key = (snapshot.id, document.id)
                if not asset_id or key in seen:
                    continue
                seen.add(key)
                asset = session.get(ImportAsset, asset_id)
                if not asset:
                    continue
                targets.append(
                    {
                        "asset_id": asset.id,
                        "image_sha256": asset.sha256,
                        "image_url": f"/api/import-assets/{asset.id}/image",
                        "data_kind": asset.data_kind,
                        "job_id": job.id,
                        "title": snapshot.payload.get("title") or job.title,
                        "snapshot_id": snapshot.id,
                        "document_id": document.id,
                        "text": snapshot.payload.get("description", ""),
                        "observed_at": observation.observed_at,
                    }
                )
            return {
                "targets": targets[:200],
                "truncated": len(targets) > 200 or len(rows) >= 1000,
                "note": "仅列出已通过图片原图关联、人工核对保存的岗位正文；区域坐标须人工选择。",
            }

    def _validate_region(
        self, session, *, asset_id, job_id, snapshot_id, document_id, start, end, quote
    ):
        document = session.get(SourceDocument, document_id)
        if not document or document.provenance.get("import_asset_id") != asset_id:
            raise ProbeError("REGION_IMAGE_SOURCE_MISMATCH")
        asset, _ = ImportDraftService(self.repository, Path(".")).read(asset_id)
        evidence = MemoryService(self.repository)._validate_evidence(
            session,
            [
                {
                    "id": f"{snapshot_id}:{start}:{end}",
                    "job_id": job_id,
                    "snapshot_id": snapshot_id,
                    "document_id": document_id,
                    "start": start,
                    "end": end,
                    "quote": quote,
                }
            ],
            job_id,
        )[0]
        return asset, evidence

    def create_region(
        self,
        *,
        asset_id,
        job_id,
        snapshot_id,
        document_id,
        bbox,
        start,
        end,
        quote,
        reviewed=False,
        note="",
    ):
        if reviewed is not True:
            raise ProbeError("REGION_MANUAL_REVIEW_REQUIRED")
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(
                type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1
                for value in bbox
            )
            or not bbox[0] < bbox[2]
            or not bbox[1] < bbox[3]
        ):
            raise ProbeError("INVALID_REGION_BBOX")
        bbox = [float(value) for value in bbox]
        if not isinstance(note, str) or len(note) > 1200:
            raise ProbeError("INVALID_REGION_NOTE")
        with Session(self.repository.engine) as session, session.begin():
            asset, evidence = self._validate_region(
                session,
                asset_id=asset_id,
                job_id=job_id,
                snapshot_id=snapshot_id,
                document_id=document_id,
                start=start,
                end=end,
                quote=quote,
            )
            signature = digest(
                {
                    "asset_sha": asset["sha256"],
                    "document_id": document_id,
                    "snapshot_id": snapshot_id,
                    "bbox": bbox,
                    "start": start,
                    "end": end,
                }
            )
            old = session.scalar(
                select(ScreenshotRegion).where(ScreenshotRegion.signature == signature)
            )
            if old:
                return self._region_record(old, session)
            row = ScreenshotRegion(
                id=uuid4().hex,
                asset_id=asset_id,
                job_id=job_id,
                snapshot_id=snapshot_id,
                document_id=document_id,
                image_sha256=asset["sha256"],
                document_sha256=evidence["document_sha256"],
                content_sha256=evidence["content_sha256"],
                bbox=bbox,
                start=start,
                end=end,
                quote=quote,
                note=note.strip(),
                selection_method="manual_reviewed_region",
                status="active",
                signature=signature,
                created_at=now(),
            )
            session.add(row)
            session.flush()
            return self._region_record(row, session)

    def _region_record(self, row, session):
        reasons = []
        asset_row = session.get(ImportAsset, row.asset_id)
        try:
            asset, evidence = self._validate_region(
                session,
                asset_id=row.asset_id,
                job_id=row.job_id,
                snapshot_id=row.snapshot_id,
                document_id=row.document_id,
                start=row.start,
                end=row.end,
                quote=row.quote,
            )
            if (
                asset["sha256"] != row.image_sha256
                or evidence["document_sha256"] != row.document_sha256
                or evidence["content_sha256"] != row.content_sha256
            ):
                reasons.append("recorded_hash_changed")
        except (ProbeError, OSError):
            reasons.append("source_missing_or_changed")
        job, snapshot = session.get(Job, row.job_id), session.get(JobSnapshot, row.snapshot_id)
        if job and snapshot and job.description_text != snapshot.payload.get("description"):
            reasons.append("historical_job_version")
        return {
            key: getattr(row, key)
            for key in (
                "id",
                "asset_id",
                "job_id",
                "snapshot_id",
                "document_id",
                "image_sha256",
                "document_sha256",
                "content_sha256",
                "bbox",
                "start",
                "end",
                "quote",
                "note",
                "selection_method",
                "status",
                "created_at",
            )
        } | {
            "data_kind": asset_row.data_kind if asset_row else "unknown",
            "image_url": f"/api/import-assets/{row.asset_id}/image",
            "integrity": "verified"
            if not any(reason != "historical_job_version" for reason in reasons)
            else "missing_or_changed",
            "warnings": reasons,
            "coordinate_space": "normalized_xyxy_top_left",
            "is_ocr_detected_region": False,
        }

    def regions(self, job_id=None):
        statement = select(ScreenshotRegion)
        if job_id:
            statement = statement.where(ScreenshotRegion.job_id == job_id)
        with Session(self.repository.engine) as session:
            return [
                self._region_record(row, session)
                for row in session.scalars(
                    statement.order_by(ScreenshotRegion.created_at.desc()).limit(300)
                )
            ]

    def withdraw_region(self, identity):
        with Session(self.repository.engine) as session, session.begin():
            row = session.get(ScreenshotRegion, identity)
            if row is None:
                raise ProbeError("REGION_NOT_FOUND")
            row.status = "withdrawn"
            session.flush()
            return self._region_record(row, session)
