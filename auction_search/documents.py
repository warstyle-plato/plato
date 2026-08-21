from __future__ import annotations

import io
import re
import zipfile
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from auction_search.models import AuctionDocument


MAX_DOCUMENT_BYTES = 35 * 1024 * 1024
_ALLOWED_ETP_HOST_SUFFIXES = ("roseltorg.ru", "lot-online.ru")


class DocumentExtractionError(RuntimeError):
    pass


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        value = " ".join((data or "").split())
        if value:
            self.parts.append(value)


def _validate_official_url(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if not any(host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_ETP_HOST_SUFFIXES):
        raise DocumentExtractionError(f"unsupported/non-official document host: {host}")


def download_document(url: str, *, timeout: int = 25) -> tuple[bytes, str]:
    """Download an attachment only from an official supported ETP host."""
    _validate_official_url(url)
    req = Request(url, headers={"User-Agent": "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"})
    with urlopen(req, timeout=timeout) as response:
        content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_DOCUMENT_BYTES:
            raise DocumentExtractionError("auction document exceeds size limit")
        data = response.read(MAX_DOCUMENT_BYTES + 1)
        if len(data) > MAX_DOCUMENT_BYTES:
            raise DocumentExtractionError("auction document exceeds size limit")
    return data, content_type


def _paragraphs(text: str) -> list[str]:
    out: list[str] = []
    for chunk in re.split(r"[\r\n]+", text):
        value = " ".join(chunk.split())
        if value:
            out.append(value)
    return out


def _docx_text(data: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
    except Exception as exc:
        raise DocumentExtractionError(f"cannot read DOCX: {exc}") from exc
    root = ET.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for p in root.findall(".//w:p", ns):
        text = "".join((node.text or "") for node in p.findall(".//w:t", ns))
        text = " ".join(text.split())
        if text:
            paragraphs.append(text)
    return paragraphs


def _pdf_text(data: bytes) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentExtractionError("PDF extraction requires pypdf") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        paragraphs: list[str] = []
        for page_no, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            for item in _paragraphs(text):
                paragraphs.append(f"[стр. {page_no}] {item}")
        if not paragraphs:
            raise DocumentExtractionError("PDF contains no extractable text; likely a scan")
        return paragraphs
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError(f"cannot read PDF: {exc}") from exc


def extract_document_paragraphs(document: AuctionDocument, data: bytes | None = None, content_type: str = "") -> list[str]:
    """Extract text without OCR; scanned PDFs fail explicitly instead of inventing content."""
    if data is None:
        data, content_type = download_document(document.url)
    low_url = document.url.lower()
    low_type = (content_type or "").lower()
    if low_url.endswith(".docx") or "wordprocessingml.document" in low_type:
        return _docx_text(data)
    if low_url.endswith(".pdf") or low_type == "application/pdf" or data[:4] == b"%PDF":
        return _pdf_text(data)
    if low_url.endswith((".html", ".htm")) or "text/html" in low_type:
        parser = _HTMLText()
        parser.feed(data.decode("utf-8", errors="replace"))
        return parser.parts
    if low_url.endswith((".txt", ".csv")) or low_type.startswith("text/"):
        return _paragraphs(data.decode("utf-8", errors="replace"))
    raise DocumentExtractionError(f"unsupported document format: {document.title}")
