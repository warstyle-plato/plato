from __future__ import annotations

import io
import os
import re
import zipfile
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from auction_search.models import AuctionDocument


MAX_DOCUMENT_BYTES = 35 * 1024 * 1024
_ALLOWED_ETP_HOST_SUFFIXES = ("roseltorg.ru", "lot-online.ru")
_USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"

# Optional service-account sessions. Values are raw Cookie headers and must be
# injected as runtime secrets, never committed. Public requests remain the
# default; the cookie is used only when configured for that platform.
_COOKIE_ENV_BY_SUFFIX = {
    "roseltorg.ru": "AUCTION_ROSELTORG_COOKIE",
    "lot-online.ru": "AUCTION_LOTONLINE_COOKIE",
}


class DocumentExtractionError(RuntimeError):
    pass


class DocumentAuthorizationRequired(DocumentExtractionError):
    """The official ETP requires an authenticated participant/session."""


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        value = " ".join((data or "").split())
        if value:
            self.parts.append(value)


def _official_suffix(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for suffix in _ALLOWED_ETP_HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return suffix
    raise DocumentExtractionError(f"unsupported/non-official document host: {host}")


def _request_headers(url: str) -> tuple[dict[str, str], bool]:
    suffix = _official_suffix(url)
    headers = {"User-Agent": _USER_AGENT}
    env_name = _COOKIE_ENV_BY_SUFFIX.get(suffix)
    cookie = (os.getenv(env_name or "", "") if env_name else "").strip()
    if cookie:
        headers["Cookie"] = cookie
        return headers, True
    return headers, False


def _looks_like_login_page(final_url: str, content_type: str, data: bytes) -> bool:
    path = (urlparse(final_url).path or "").lower()
    if any(marker in path for marker in ("login", "signin", "auth", "authorization")):
        return True
    if "html" not in content_type:
        return False
    sample = data[:24_000].decode("utf-8", errors="ignore").lower()
    # A document endpoint returning an HTML login form with HTTP 200 is common.
    return (
        ("type=\"password\"" in sample or "type='password'" in sample)
        and any(marker in sample for marker in ("войти", "авторизац", "login", "пароль"))
    )


def safe_url(url: str) -> str:
    """Тот же адрес, пригодный для запроса: пробелы и кириллица — процентами.

    Площадка кладёт в ссылку имя файла как есть: «/file/get/…/name/Территория,
    Лотовая документация.1700483.pdf» — с пробелом и кириллицей. `urllib` на
    таком адресе не делает запроса вовсе, а отвечает «URL can't contain control
    characters», и разбор лота падает целиком (экран владельца, 02.09.2026).
    Читатель при этом ни при чём: адрес честный, просто незакодированный.

    Уже закодированное не кодируется второй раз (`safe` держит проценты), иначе
    «%20» превратилось бы в «%2520» и площадка отдала бы 404.
    """
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme:
        return str(url or "").strip()
    return urlunparse(parsed._replace(
        path=quote(parsed.path, safe="/%:@!$&'()*+,;=~-._"),
        query=quote(parsed.query, safe="/%:@!$&'()*+,;=~-._?"),
    ))


def download_document(url: str, *, timeout: int = 25) -> tuple[bytes, str, bool]:
    """Download an official ETP attachment, public-first.

    Returns (bytes, content_type, authenticated_session_used). If the platform
    requires login and no valid service-account session is available, raises
    DocumentAuthorizationRequired rather than treating the document as missing.
    """
    headers, authenticated = _request_headers(url)
    req = Request(safe_url(url), headers=headers)
    try:
        with urlopen(req, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_DOCUMENT_BYTES:
                raise DocumentExtractionError("auction document exceeds size limit")
            data = response.read(MAX_DOCUMENT_BYTES + 1)
            if len(data) > MAX_DOCUMENT_BYTES:
                raise DocumentExtractionError("auction document exceeds size limit")
            final_url = response.geturl()
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise DocumentAuthorizationRequired("official ETP requires authentication for this document") from exc
        raise DocumentExtractionError(f"document download failed: HTTP {exc.code}") from exc

    if _looks_like_login_page(final_url, content_type, data):
        raise DocumentAuthorizationRequired("official ETP redirected the document request to authentication")
    return data, content_type, authenticated


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
        data, content_type, authenticated = download_document(document.url)
        document.access_status = "authenticated" if authenticated else "public"
        document.auth_required = False
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
