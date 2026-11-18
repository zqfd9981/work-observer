"""CSV草稿及截图的明确上传、抽取、人工核对入口。"""

from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.routing import Route

from work_observer.connectors.import_drafts import (
    MAX_IMAGE,
    ImportDraftService,
    commit_rows,
    csv_preview,
)
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.storage.archive import RawArchive


class CSVPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = Field(min_length=1, max_length=512000)


class CSVCommitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[dict] = Field(min_length=1, max_length=20)


class ImageExtractInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow_model: bool = Field(default=False, strict=True)


def import_routes(
    *, repository, settings, credentials, response, read_json, busy, operation_lock, import_lock
):
    def service():
        return ImportDraftService(repository(), settings.raw_directory / "import_assets")

    async def preview_csv(request):
        data = CSVPreviewInput.model_validate(await read_json(request))
        return response(csv_preview(data.csv_text))

    async def import_csv(request):
        data = CSVCommitInput.model_validate(await read_json(request))

        def save():
            with import_lock:
                return commit_rows(
                    repository(), RawArchive(settings.raw_directory, credentials), data.rows
                )

        return response(await run_in_threadpool(save))

    async def upload_image(request):
        size, chunks = 0, []
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_IMAGE:
                raise ProbeError("IMPORT_IMAGE_TOO_LARGE")
            chunks.append(chunk)
        return response(
            service().upload(
                b"".join(chunks),
                mime=request.headers.get("content-type"),
                data_kind=request.query_params.get("data_kind", "user_provided"),
            ),
            201,
        )

    async def get_image(request):
        metadata, raw = service().read(request.path_params["id"])
        return Response(raw, media_type=metadata["mime"], headers={"Content-Disposition": "inline"})

    async def extract_image(request):
        data = ImageExtractInput.model_validate(await read_json(request))
        if busy():
            return response(
                {"error_code": "RESEARCH_BUSY", "message": "已有研究或抽取正在进行，请稍后再试。"},
                409,
            )
        async with operation_lock:
            return response(
                await service().extract(
                    request.path_params["id"], settings, allow_model=data.allow_model
                )
            )

    return [
        Route("/api/imports/csv/preview", preview_csv, methods=["POST"]),
        Route("/api/imports/csv/commit", import_csv, methods=["POST"]),
        Route("/api/import-assets", upload_image, methods=["POST"]),
        Route("/api/import-assets/{id}/image", get_image),
        Route("/api/import-assets/{id}/extract", extract_image, methods=["POST"]),
    ]
