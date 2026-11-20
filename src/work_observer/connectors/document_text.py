"""Extract local document text without network or model calls."""

from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_TEXT = 100_000
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentTextError(ValueError):
    pass


def _paragraph(node):
    parts = []
    for child in node.iter():
        if child.tag == W + "t":
            parts.append(child.text or "")
        elif child.tag == W + "tab":
            parts.append("\t")
        elif child.tag in {W + "br", W + "cr"}:
            parts.append("\n")
    return "".join(parts)


def _word_text(raw):
    try:
        with ZipFile(BytesIO(raw)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 8 * 1024 * 1024:
                raise DocumentTextError("Word正文过大，请拆分文件后上传。")
            document = archive.read(info)
        if b"<!DOCTYPE" in document or b"<!ENTITY" in document:
            raise DocumentTextError("无法读取这个Word文件，请另存为新的DOCX后重试。")
        body = ElementTree.fromstring(document).find(W + "body")
        if body is None:
            raise DocumentTextError("Word文件没有可读取的正文。")
        lines = []
        for block in body:
            if block.tag == W + "p":
                lines.append(_paragraph(block))
            elif block.tag == W + "tbl":
                for row in block.findall(W + "tr"):
                    lines.append(
                        "\t".join(
                            " / ".join(_paragraph(p) for p in cell.iter(W + "p"))
                            for cell in row.findall(W + "tc")
                        )
                    )
        return "\n".join(lines), "已提取Word正文与表格；图片、页眉页脚和批注未导入。"
    except (BadZipFile, KeyError, ElementTree.ParseError, RuntimeError) as error:
        raise DocumentTextError("Word文件无法读取，请使用未加密的DOCX文件。") from error


def _pdf_text(raw):
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted:
            raise DocumentTextError("暂不读取加密PDF，请先在本机另存为未加密文件。")
        if len(reader.pages) > 100:
            raise DocumentTextError("PDF超过100页，请只保留研究相关的页面。")
        pages, empty_pages, length = [], [], 0
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            length += len(text)
            if length > MAX_TEXT:
                raise DocumentTextError("提取的正文超过10万字，请拆分文件。")
            if not text:
                empty_pages.append(number)
            pages.append(f"第 {number} 页\n{text}" if text else "")
        if not any(pages):
            raise DocumentTextError(
                "没有提取到文字。这可能是扫描件，请先识别文字，或粘贴相关原文。"
            )
        note = "已按页提取PDF文字；图表和版式不保留，请对照原文件核对。"
        if empty_pages:
            note += "未提取到文字的页码：" + "、".join(map(str, empty_pages)) + "。"
        return "\n\n".join(pages), note
    except DocumentTextError:
        raise
    except Exception as error:
        raise DocumentTextError(
            "PDF无法读取，请检查文件是否损坏，或另存为新的PDF后重试。"
        ) from error


def extract_document_text(raw, filename):
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1][:300]
    if not raw or len(raw) > MAX_DOCUMENT_BYTES:
        raise DocumentTextError("请选择8MB以内的Word或PDF文件。")
    suffix = PurePosixPath(filename).suffix.casefold()
    if suffix == ".docx":
        text, notice = _word_text(raw)
    elif suffix == ".pdf":
        text, notice = _pdf_text(raw)
    else:
        raise DocumentTextError("此入口支持DOCX和PDF；旧版DOC请先另存为DOCX。")
    text = text.strip()
    if not text:
        raise DocumentTextError("文件没有可提取的正文，请检查内容后重试。")
    if len(text) > MAX_TEXT:
        raise DocumentTextError("提取的正文超过10万字，请拆分文件。")
    return {
        "title": filename,
        "text": text,
        "notice": notice,
        "source_name": f"用户上传文件：{filename}；{notice}"[:500],
        "full_text_length": len(text),
    }
