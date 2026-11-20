"""Local Word/PDF import through the same material and research entry points."""

import re
from io import BytesIO
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.document_text import DocumentTextError, extract_document_text
from work_observer.storage.database import upgrade


def word_bytes():
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>合成项目说明：接口开发与平台协作。</w:t></w:r></w:p>
<w:p><w:r><w:t>业务同事</w:t><w:tab/><w:t>负责验收</w:t><w:br/><w:t>上线责任尚未说明。</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>开发任务</w:t></w:r></w:p></w:tc>
<w:tc><w:p><w:r><w:t>Python接口</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>""",
        )
    return stream.getvalue()


def pdf_bytes(*, blank=False, encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    if not blank:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 30 750 Td (Synthetic project: Python API delivery.) Tj ET")
        page[NameObject("/Contents")] = content
    writer.add_blank_page(width=600, height=800)
    if encrypted:
        writer.encrypt("test-password")
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_document_extraction_preserves_word_table_and_pdf_page_context():
    word = extract_document_text(word_bytes(), "项目说明.docx")
    assert "业务同事\t负责验收\n上线责任尚未说明。" in word["text"]
    assert "开发任务\tPython接口" in word["text"]
    assert "图片、页眉页脚和批注未导入" in word["notice"]
    pdf = extract_document_text(pdf_bytes(), "project.pdf")
    assert "第 1 页\nSynthetic project: Python API delivery." in pdf["text"]
    assert "未提取到文字的页码：2" in pdf["notice"]
    with pytest.raises(DocumentTextError, match="扫描件"):
        extract_document_text(pdf_bytes(blank=True), "scan.pdf")
    with pytest.raises(DocumentTextError, match="加密"):
        extract_document_text(pdf_bytes(encrypted=True), "locked.pdf")
    with pytest.raises(DocumentTextError, match="DOCX"):
        extract_document_text(b"not a docx", "broken.docx")


def test_extract_save_and_choose_word_material_for_research(tmp_path):
    database = tmp_path / "documents.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        headers = {"X-WO-Token": token, "Content-Type": "application/octet-stream"}
        extracted = client.post(
            "/api/imports/documents/extract",
            params={"filename": "项目说明.docx"},
            content=word_bytes(),
            headers=headers,
        )
        assert extracted.status_code == 200
        data = extracted.json()
        assert client.get("/api/public-documents").json()["total"] == 0
        saved = client.post(
            "/api/work-materials",
            json={key: data[key] for key in ("title", "text", "source_name")},
            headers={"X-WO-Token": token},
        ).json()
        document = saved["document"]
        reread = client.get("/api/public-documents/" + document["id"]).json()
        assert reread["text"] == data["text"]
        project = client.post(
            "/api/projects",
            json={
                "title": "合成文件研究",
                "goal": "核对任务与验收",
                "job_ids": [],
                "public_document_ids": [document["id"]],
            },
            headers={"X-WO-Token": token},
        )
        assert project.status_code == 201
        assert project.json()["public_document_ids"] == [document["id"]]
        invalid = client.post(
            "/api/imports/documents/extract",
            params={"filename": "bad.pdf"},
            content=b"bad",
            headers=headers,
        )
        assert invalid.status_code == 422 and "PDF无法读取" in invalid.json()["message"]
