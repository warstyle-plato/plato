from __future__ import annotations

import io
import os
import re
import time
import zipfile
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from auction_search import archives, deadline as budget, reading
from auction_search.models import AuctionDocument


MAX_DOCUMENT_BYTES = 35 * 1024 * 1024
# Повтор загрузки: площадка отвечает через раз, и один запрос выдаёт её перебой
# за отсутствие документа. Измерено на лоте 33444 (13.09.2026): из 26 вложений
# четыре ответили HTTP 503 — «Сведения о земельных участках», «График КРТ»,
# «Схема границ», «Материалы градостроительного потенциала», — а лот 33452 за
# один заход отдал 0 документов, за следующий 26.
RETRIABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
DOWNLOAD_ATTEMPTS = 3
# Отступ растёт: перебой длится секунды, и три запроса подряд без паузы — это
# один запрос, посланный трижды.
RETRY_BACKOFF_SECONDS = (2.0, 5.0)
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


class DocumentTemporaryRefusal(DocumentExtractionError):
    """Площадка отказала временно: 503, таймаут, обрыв соединения.

    Вид отказа отдельный затем, что ответы разные. «Формат не поддержан» второй
    попытки не заслуживает — он не изменится; 503 заслуживает, и при следующем
    разборе лота такое вложение спрашивается снова, тогда как прочитанное
    берётся со склада. Без этого различия перебой площадки и её ответ «такого
    документа нет» на экране выглядят одинаково.
    """


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


def download_document(url: str, *, timeout: int = 25,
                      attempts: int = DOWNLOAD_ATTEMPTS,
                      deadline: float | None = None) -> tuple[bytes, str, bool]:
    """Вложение официальной ЭТП: сперва публично, при временном отказе — снова.

    Возвращает (байты, тип, шёл ли запрос под сессией). Требует площадка входа —
    это `DocumentAuthorizationRequired`, а не «документа нет».

    Повтор стоит здесь, а не у вызывающего, и он ОДИН: два механизма на одно
    явление в этом проекте всегда расходились. Повторяется только то, что имеет
    смысл повторять, — 503 и обрыв соединения; 401, 403 и 404 не повторяются
    вовсе, потому что второй такой же запрос получит тот же ответ.

    Число попыток называется в отказе: «HTTP 503» и «HTTP 503 после трёх
    попыток» — разные утверждения о площадке, и по первому нельзя понять,
    спрашивали ли мы её всерьёз.

    Срок сбора сильнее повтора: пауза, которая не укладывается в остаток,
    съедает время остальных вложений — тогда недобранным окажется весь лот, а
    не одно вложение.
    """
    total = max(1, int(attempts))
    tried = 0
    last = ""
    while tried < total:
        tried += 1
        try:
            return _download_once(url, timeout=budget.timeout(deadline, timeout))
        except DocumentTemporaryRefusal as exc:
            last = str(exc)
            if tried >= total:
                break
            pause = RETRY_BACKOFF_SECONDS[min(tried - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
            remaining = budget.left(deadline)
            if remaining is not None and remaining <= pause:
                break
            time.sleep(pause)
    raise DocumentTemporaryRefusal(
        f"{last}; попыток: {tried} из {total}")


def _download_once(url: str, *, timeout: float) -> tuple[bytes, str, bool]:
    """Один запрос к площадке. Временный отказ отличён от окончательного."""
    headers, authenticated = _request_headers(url)
    req = Request(safe_url(url), headers=headers)
    try:
        # Корни объявлены один раз (`trusted_roots`) и здесь берутся оттуда же,
        # чем ходят проба площадки и модуль рынка. Без них загрузка вложения
        # падала с `CERTIFICATE_VERIFY_FAILED` там, где проба того же хоста в
        # ту же минуту получала 200, — и документ выглядел недоступным.
        with urlopen(req, timeout=timeout, context=reading.trust()) as response:
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
        if exc.code in RETRIABLE_STATUS:
            raise DocumentTemporaryRefusal(f"площадка ответила HTTP {exc.code}") from exc
        raise DocumentExtractionError(f"document download failed: HTTP {exc.code}") from exc
    except OSError as exc:
        # Таймаут и обрыв соединения прежде уходили наружу СЫРЫМИ: `urllib`
        # бросает не наш класс, вызывающий его не ловит, и одно повисшее
        # вложение роняло разбор ЛОТА целиком — маршрут отвечал 502 «не удалось
        # прочитать официальный лот». Та же беда уже была у сбора: одна
        # недоступная карточка РАД снимала весь каталог.
        raise DocumentTemporaryRefusal(
            f"соединение не состоялось: {type(exc).__name__}: {exc}") from exc

    if _looks_like_login_page(final_url, content_type, data):
        raise DocumentAuthorizationRequired("official ETP redirected the document request to authentication")
    # Страница отказа приходит с кодом 200 и телом HTML — по содержимому это не
    # документ, и разбирать её как документ значит показать «формат не
    # поддержан» там, где нас просто не пустили.
    if "html" in content_type:
        refusal = reading.refusal_reason("", data[:4_000].decode("utf-8", errors="ignore"))
        if refusal:
            raise DocumentExtractionError(
                f"площадка ответила страницей отказа (примета: {refusal}), а не документом")
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


def _by_format(low_name: str, low_type: str, data: bytes, title: str) -> list[str]:
    """Текст по виду файла. Вид решают расширение, тип и первые байты."""
    if low_name.endswith(".docx") or "wordprocessingml.document" in low_type:
        return _docx_text(data)
    if low_name.endswith(".pdf") or low_type == "application/pdf" or data[:4] == b"%PDF":
        return _pdf_text(data)
    if low_name.endswith((".html", ".htm")) or "text/html" in low_type:
        parser = _HTMLText()
        parser.feed(data.decode("utf-8", errors="replace"))
        return parser.parts
    if low_name.endswith((".txt", ".csv")) or low_type.startswith("text/"):
        return _paragraphs(data.decode("utf-8", errors="replace"))
    if low_name.endswith(".xml"):
        # Выписку ЕГРН читает `egrn_archive`, а не текстовый разбор: у неё не
        # абзацы, а записи. Назвать это «формат не поддержан» значило бы выдать
        # чужой формат за наш пробел ровно там, где он прочитан другим путём.
        raise DocumentExtractionError("XML — не текстовый документ (выписки читает разбор ЕГРН)")
    raise DocumentExtractionError(f"unsupported document format: {title}")


def _zip_paragraphs(title: str, data: bytes) -> list[str]:
    """Текст архива: абзацы читаемых записей, а непрочитанные — названы.

    Каждый абзац подписан именем своей записи: архив лотовой документации
    несёт по десятку файлов, и «в каком из них это сказано» — часть ответа.
    Ни одной читаемой записи — это отказ с перечнем того, что внутри: пустой
    список абзацев читался бы как пустой документ.
    """
    try:
        opened = archives.open_zip(data)
    except archives.ArchiveProblem as exc:
        raise DocumentExtractionError(f"{title}: {exc}") from exc
    out: list[str] = []
    unread: list[str] = [f"{item['name']} — {item['reason']}" for item in opened.refused]
    for entry in opened.entries:
        try:
            part = _by_format(entry.name.lower(), "", entry.data, entry.name)
        except DocumentExtractionError as exc:
            unread.append(f"{entry.name} — {exc}")
            continue
        out.extend(f"[{entry.name}] {item}" for item in part)
    if not out:
        if unread:
            raise DocumentExtractionError(
                f"в архиве «{title}» нет читаемого текста: " + "; ".join(unread[:20]))
        raise DocumentExtractionError(f"архив «{title}» пуст")
    if unread:
        out.append("[архив] не прочитано: " + "; ".join(unread[:20]))
    return out


def extract_document_paragraphs(document: AuctionDocument, data: bytes | None = None, content_type: str = "") -> list[str]:
    """Extract text without OCR; scanned PDFs fail explicitly instead of inventing content."""
    if data is None:
        data, content_type, authenticated = download_document(document.url)
        document.access_status = "authenticated" if authenticated else "public"
        document.auth_required = False
    # Архив вложений читается по записям, а DOCX и ODT устроены архивом, но
    # документами и остаются: их разбирает свой читатель.
    if archives.looks_like_zip(data) and not archives.is_office_package(data):
        return _zip_paragraphs(document.title or document.url, data)
    return _by_format(document.url.lower(), (content_type or "").lower(), data,
                      document.title)
