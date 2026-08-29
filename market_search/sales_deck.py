"""Свод продаж презентацией: слайд — это раздел отчёта.

«Выгрузка отчёта в PDF или PPT для презентации маркетингу… страниц PDF = слайд
или раздел PDF = слайд» (владелец, 27.08.2026). Разделы и страницы у нас
совпадают — раздел свода печатается со своей страницы, — поэтому вопрос решён
одним ответом: слайд отвечает разделу.

Второй вёрстки здесь нет и быть не может. Собрать колоду «по тем же данным»
значит завести вторую реализацию отчёта о продажах: она разошлась бы с экраном
молча, и обе выглядели бы верными — ровно то, что уже ловилось в боте, в отчёте
о рынке и в книге. Поэтому на слайд уходит СНИМОК того же раздела, снятый с той
же разметки, которой печатается PDF. Арифметики в этом модуле нет ни одной:
числа посчитал сервер один раз, когда собирал свод.

Текстом на слайде остаётся то, что текстом и должно быть: заголовок раздела и
вывод под ним — их правят руками при подготовке к встрече. Картинкой остаётся
то, что картинка: график и таблица.
"""

from __future__ import annotations

import io
import re
from typing import Any

import browser_launch

from . import report_pdf

# Ширина, с которой снимаются разделы. Уже экрана намеренно: колода читается с
# проектора, и таблица шириной в тысячу двести точек на нём — сетка серых
# полос.
_SHOT_WIDTH = 1180
_SHOT_SCALE = 2
_SHOT_TIMEOUT_MS = 90_000

# Слайд 16:9. Дюймы, потому что в них считает сам формат.
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5


class DeckUnavailable(RuntimeError):
    """Колода не собралась. Это ответ, а не повод отдать пустой файл."""


def deck_document(body: str, *, style: str) -> str:
    """Тот же документ, что уходит в печать, — но под снимок раздела.

    Заголовок раздела гасится: на слайде он живёт настоящим текстом, который
    правят руками, и снятый картинкой он стоял бы вторым.
    """
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        f"<style>{style}</style>"
        "<style>"
        ".printfoot{display:none !important}"
        f"body{{background:#fff;width:{_SHOT_WIDTH}px}}"
        "main{max-width:none;padding:0}"
        ".card{border:0;padding:0;margin:0}"
        ".salesnav{display:none !important}"
        ".noprint{display:none !important}"
        ".switch{display:none !important}"
        ".salesblock{border-top:0;margin:0;padding:0}"
        ".blockhead h3{display:none}"
        "details>summary{list-style:none;font-weight:600;margin:10px 0 2px}"
        "</style>"
        f"</head><body><main>{body}</main></body></html>"
    )


def _text(node: Any, selector: str) -> str:
    found = node.query_selector(selector)
    return (found.inner_text() if found else "").strip()


def shots(html: str, *, style: str, executable_path: str | None = None) -> list[dict[str, Any]]:
    """Снимки разделов: заголовок, картинка, вывод под ней.

    Раскрытия открываются — свёрнутая таблица на слайде это таблица, которой
    нет, а раскрыть её на проекторе нечем.
    """
    from playwright.sync_api import sync_playwright

    if not report_pdf._PDF_LOCK.acquire(timeout=report_pdf._PDF_QUEUE_SECONDS):
        raise DeckUnavailable("Браузер занят другим отчётом — попробуйте через минуту")
    try:
        with sync_playwright() as playwright:
            browser = browser_launch.launch(
                playwright,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                **({"executable_path": executable_path} if executable_path else {}),
            )
            try:
                page = browser.new_page(
                    viewport={"width": _SHOT_WIDTH, "height": 900},
                    device_scale_factor=_SHOT_SCALE)
                page.set_default_timeout(_SHOT_TIMEOUT_MS)
                # Ничего не грузим по сети: картинки уже зашиты данными.
                page.route("**/*", lambda route: route.abort()
                           if route.request.url.startswith("http") else route.continue_())
                page.set_content(deck_document(html, style=style), wait_until="load")
                page.evaluate("()=>document.querySelectorAll('details')"
                              ".forEach(d=>d.setAttribute('open',''))")
                out: list[dict[str, Any]] = []
                # Разметка приходит содержимым карточки, а не карточкой: у
                # `main` прямые дети — шапка, плашки, разделы и подпись под
                # ними. Промахнувшийся селектор здесь не «пустой слайд», а
                # снимок всего отчёта одной картинкой, поэтому промах называется
                # вслух, а не заменяется тем, что нашлось.
                tiles = page.query_selector("main > .kv")
                if tiles is None:
                    raise DeckUnavailable(
                        "В своде не нашлось плашки ключевых чисел — разметка не та")
                out.append({"title": "Ключевые числа",
                            "png": tiles.screenshot(type="png"),
                            "note": _text(page, "main > .sumup")})
                for section in page.query_selector_all("section.salesblock"):
                    head = section.query_selector(".blockhead h3")
                    out.append({
                        "title": head.inner_text().strip() if head else "Раздел",
                        "png": section.screenshot(type="png"),
                        "note": _text(section, ".sumup"),
                    })
                # На чём посчитано: источники с датами и то, чего в выгрузках не
                # нашлось. На бумаге это мелкий шрифт под отчётом, на слайде —
                # свой лист: колода живёт отдельно от экрана, и оговорка,
                # оставшаяся на экране, до зала не доедет.
                basis = [node.inner_text().strip()
                         for node in page.query_selector_all("main > .muted")]
                basis = [line for line in basis if line]
                if basis:
                    out.append({"title": "На чём посчитано", "lines": basis})
                return out
            finally:
                browser.close()
    except DeckUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — причина уходит человеку на экран
        raise DeckUnavailable(f"Chromium не снял разделы: {exc}") from exc
    finally:
        report_pdf._PDF_LOCK.release()


def build(pages: list[dict[str, Any]], *, title: str, subtitle: str, footer: str) -> bytes:
    """Колода из снятых разделов. Ни одного числа здесь не считается."""
    try:
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.util import Emu, Inches, Pt
    except ImportError as exc:  # noqa: BLE001
        raise DeckUnavailable(
            "В образе нет python-pptx — презентацию собрать нечем") from exc
    if not pages:
        raise DeckUnavailable("Собирать нечего: в своде нет ни одного раздела")

    deck = Presentation()
    deck.slide_width = Inches(SLIDE_W_IN)
    deck.slide_height = Inches(SLIDE_H_IN)
    blank = deck.slide_layouts[6]
    ink = RGBColor(0x16, 0x20, 0x2B)
    dim = RGBColor(0x5B, 0x6B, 0x7D)

    def caption(slide, text: str, *, top: float, size: int, colour: RGBColor, bold: bool):
        box = slide.shapes.add_textbox(Inches(0.6), Inches(top),
                                       Inches(SLIDE_W_IN - 1.2), Inches(0.6))
        frame = box.text_frame
        frame.word_wrap = True
        run = frame.paragraphs[0].add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = colour
        return box

    # Титул: чей отчёт и на какую дату. Лист, отделившийся от колоды, обязан
    # сам говорить, чей он, — на слайде это верно так же, как на бумаге.
    first = deck.slides.add_slide(blank)
    caption(first, title, top=2.6, size=34, colour=ink, bold=True)
    caption(first, subtitle, top=3.9, size=16, colour=dim, bold=False)
    caption(first, footer, top=6.6, size=11, colour=dim, bold=False)

    for page in pages:
        slide = deck.slides.add_slide(blank)
        caption(slide, page["title"], top=0.42, size=24, colour=ink, bold=True)
        raw = page.get("png")
        if raw:
            slide.shapes.add_picture(io.BytesIO(raw), *_fit(raw, Emu))
        for index, line in enumerate(page.get("lines") or []):
            caption(slide, line, top=1.4 + index * 0.5, size=13, colour=dim, bold=False)
        note = (page.get("note") or "").strip()
        if note:
            slide.notes_slide.notes_text_frame.text = note
    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def _fit(png: bytes, emu: Any) -> tuple[Any, Any, Any, Any]:
    """Вписать снимок в поле слайда, сохранив пропорции.

    Высокий раздел (длинная таблица) ужимается по высоте и встаёт по центру:
    растянуть его на всю ширину значит обрезать низ, а обрезанная таблица
    читается как таблица, которая кончилась.
    """
    width, height = _png_size(png)
    frame_w, frame_h = SLIDE_W_IN - 1.2, SLIDE_H_IN - 1.7
    scale = min(frame_w / (width / 96 / _SHOT_SCALE), frame_h / (height / 96 / _SHOT_SCALE))
    shown_w = width / 96 / _SHOT_SCALE * scale
    shown_h = height / 96 / _SHOT_SCALE * scale
    left = (SLIDE_W_IN - shown_w) / 2
    top = 1.25 + (frame_h - shown_h) / 2
    inch = 914_400
    return (emu(int(left * inch)), emu(int(top * inch)),
            emu(int(shown_w * inch)), emu(int(shown_h * inch)))


def _png_size(png: bytes) -> tuple[int, int]:
    """Размер PNG из его же заголовка: Pillow здесь не нужен ради двух чисел."""
    if len(png) < 24 or png[:8] != b"\x89PNG\r\n\x1a\n":
        raise DeckUnavailable("Снимок раздела пришёл не картинкой")
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


def file_name(title: str) -> str:
    """Имя файла: то же правило, что у PDF отчёта."""
    keep = "".join(ch for ch in title if ch.isalnum() or ch in " -_")[:80].strip()
    return re.sub(r"\s+", " ", keep) or "sales"
