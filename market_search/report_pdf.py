"""PDF отчёта кабинета — печать документа, а не снимок экрана.

Кнопка звала `window.print()`, и всё, что можно было сделать, делалось
стилями. Одного стилями сделать нельзя: **номеров страниц**. Поля страницы
(`@page`) браузеры понимают, а margin-boxes с `counter(page)` — ни Chrome, ни
Safari; номера ставит только сам браузер, своим колонтитулом, вместе с адресом
страницы и датой, и выключить половину этого нельзя.

Поэтому PDF печатает сервер тем же Chromium, который уже стоит в образе ради
ГлавАПУ: у `page.pdf()` есть свой шаблон колонтитула, а в нём `pageNumber` и
`totalPages`.

Печатается **та же разметка**, что человек видит: браузер присылает готовый
`#out`, сервер оборачивает его в документ с тем же стилем страницы. Ничего не
пересчитывается — иначе на одни данные было бы два расчёта, и разошлись бы они
молча. Правило то же, что у отчёта движка: поверхности считают один раз.

Картинки внутри разметки зашиваются в документ данными. Chromium в этом
документе — не браузер человека: у него нет ни сессии, ни адреса нашего
сервера, и «/land/basemap?...» он бы не открыл. Вместо похода по сети байты
берутся у того же кода, который отдал бы их по этому адресу.
"""

from __future__ import annotations

import base64
import re
import threading
from typing import Any, Callable

import browser_launch

# Печать держит одного Chromium за раз: рядом живёт браузер ГлавАПУ, и каждый
# стоит трёхсот-четырёхсот мегабайт. Отчёт печатают редко, очередь дешевле
# памяти.
_PDF_LOCK = threading.Semaphore(1)
_PDF_QUEUE_SECONDS = 120.0
_PDF_TIMEOUT_MS = 90_000

_SRC_RE = re.compile(r'src="(/[^"]+)"')
_MIME = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}


class PdfUnavailable(RuntimeError):
    """Печать не состоялась. Это ответ, а не повод отдать пустой файл."""


def inline_assets(html: str, fetch: Callable[[str], tuple[bytes, str] | None]) -> str:
    """Заменить локальные `src` на данные.

    Не пришло — ссылка остаётся как была: картинка в PDF не отрисуется, но
    остальной документ напечатается. Молча подставлять пустоту нельзя: карта
    пустого места и карта, которая не пришла, выглядят одинаково.
    """

    def replace(match: re.Match[str]) -> str:
        url = match.group(1)
        try:
            found = fetch(url)
        except Exception:
            found = None
        if not found:
            return match.group(0)
        raw, mime = found
        return 'src="data:' + mime + ";base64," + base64.b64encode(raw).decode("ascii") + '"'

    return _SRC_RE.sub(replace, html)


def document(body: str, *, style: str, title: str) -> str:
    """Документ под печать: та же разметка и тот же стиль, что на экране.

    `.printfoot` гасится: колонтитул рисует сам Chromium своим шаблоном, и два
    колонтитула на одной странице — это не «надёжнее», это две подписи.
    """
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        f"<title>{escape(title)}</title><style>{style}</style>"
        # Один и тот же стиль обслуживает экран и печать, а тут печать — всегда.
        "<style>.printfoot{display:none !important}"
        "body{background:#fff}main{max-width:none;padding:0}</style>"
        f"</head><body><main>{body}</main></body></html>"
    )


def escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def footer_template(text: str) -> str:
    """Колонтитул Chromium: имя отчёта слева, номер страницы справа.

    Свои стили сюда не доезжают — шаблон рисуется в отдельном документе, и
    оформление в нём пишется руками. Размер задан в пикселях: `pt` Chromium в
    колонтитуле трактует по-своему, и восемь пунктов приезжали втрое крупнее.
    """
    return (
        '<div style="width:100%;font-size:8px;color:#5b6b7d;'
        'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'padding:0 12mm;display:flex;justify-content:space-between;">'
        f"<span>{escape(text)}</span>"
        '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span>'
        "</div>"
    )


def render(html: str, *, footer: str, executable_path: str | None = None) -> bytes:
    """Напечатать документ и вернуть байты PDF."""
    from playwright.sync_api import sync_playwright

    if not _PDF_LOCK.acquire(timeout=_PDF_QUEUE_SECONDS):
        raise PdfUnavailable("Печать занята другим отчётом — попробуйте через минуту")
    try:
        launch: dict[str, Any] = {
            # Контейнер уже изолирован, а песочница Chromium в нём не
            # поднимается — тот же набор, что у браузера ГлавАПУ.
            "args": ["--no-sandbox", "--disable-dev-shm-usage"],
        }
        with sync_playwright() as playwright:
            # Запуск общий с ГлавАПУ: Playwright при headless берёт отдельную
            # сборку `chromium_headless_shell`, а в образе её может не быть —
            # и тогда падает не только печать. Отступление по способам живёт
            # в одном месте, а не копией здесь.
            browser = browser_launch.launch(
                playwright,
                args=launch["args"],
                **({"executable_path": executable_path} if executable_path else {}),
            )
            try:
                page = browser.new_page()
                page.set_default_timeout(_PDF_TIMEOUT_MS)
                # Ничего не грузим по сети: картинки уже зашиты данными, а за
                # чем ещё документ пошёл бы — того ему знать не положено.
                page.route("**/*", lambda route: route.abort()
                           if route.request.url.startswith("http") else route.continue_())
                page.set_content(html, wait_until="load")
                return page.pdf(
                    format="A4",
                    print_background=True,
                    display_header_footer=True,
                    header_template="<span></span>",
                    footer_template=footer_template(footer),
                    margin={"top": "14mm", "bottom": "18mm", "left": "12mm", "right": "12mm"},
                )
            finally:
                browser.close()
    except PdfUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — причина уходит человеку в чат
        raise PdfUnavailable(f"Chromium не напечатал отчёт: {exc}") from exc
    finally:
        _PDF_LOCK.release()


def local_mime(url: str) -> str:
    for suffix, mime in _MIME.items():
        if url.split("?")[0].lower().endswith(suffix):
            return mime
    return "application/octet-stream"
