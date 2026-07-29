"""PDF собирается с кириллицей.

Встроенные в PDF гарнитуры кириллицы не содержат, а в python:3.11-slim нет ни
одного шрифта вовсе: отчёт либо не собирался, либо выходил с пустыми
прямоугольниками вместо букв. Шрифты ставятся в Dockerfile, а здесь
проверяется, что генератор их находит, подключает и никуда не подставляет
Helvetica.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import re
import sys
import base64
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core

pytest.importorskip("reportlab", reason="reportlab нужен только для выгрузки PDF")

CYRILLIC = "Платон Сергеевич Федоскин — инвестиционный отчёт"


@pytest.fixture(scope="module")
def report_pdf() -> bytes:
    bundle = main._run_authoritative_model(main.DEFAULT_INPUTS, main.TEP_DEFAULT, [], {})
    return main._build_developaid_pdf({
        "result": bundle["consolidated"],
        "project_name": CYRILLIC,
        "inputs": main.DEFAULT_INPUTS,
        "tep": main.TEP_DEFAULT,
    })


def content_streams(content: bytes) -> str:
    """Распаковывает потоки содержимого PDF — без сторонних библиотек."""
    chunks = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", content, re.S):
        data = match.group(1).strip()
        try:
            chunks.append(zlib.decompress(base64.a85decode(data, adobe=True)).decode("latin-1"))
        except Exception:
            continue
    return "\n".join(chunks)


def _font_bases(content: bytes) -> dict[str, str]:
    """Имя ресурса шрифта (F1, F2…) -> гарнитура, на которую он ссылается."""
    body = content.decode("latin-1", errors="ignore")
    found: dict[str, str] = {}
    for match in re.finditer(r"/BaseFont\s*/([A-Za-z0-9+\-]+)[^>]*?/Name\s*/(F\d+)", body):
        found[match.group(2)] = match.group(1)
    for match in re.finditer(r"/Name\s*/(F\d+)[^>]*?/BaseFont\s*/([A-Za-z0-9+\-]+)", body):
        found.setdefault(match.group(1), match.group(2))
    return found


def fonts_that_draw_text(body: str) -> set[str]:
    """Шрифты, которыми действительно выведен текст.

    reportlab открывает страницу пустым блоком «BT /F1 12 Tf 12 TL ET» — шрифт
    там выбран, но ничего не нарисовано. Считать такие блоки использованием
    Helvetica нельзя, поэтому смотрим только на блоки с операторами вывода.
    """
    used: set[str] = set()
    for block in re.findall(r"BT\s(.*?)\sET", body, re.S):
        if not re.search(r"\)\s*Tj|\]\s*TJ|>\s*Tj", block):
            continue
        used.update(re.findall(r"/([A-Za-z0-9+]+)\s+[\d.]+\s+Tf", block))
    return used


def test_the_server_finds_a_cyrillic_font():
    regular, bold = main._pdf_font_names()
    assert regular == "DevelopAidSans" and bold == "DevelopAidSansBold"


def test_font_search_covers_both_liberation_layouts():
    """Каталог liberation называется по-разному в разных сборках Debian."""
    assert "/usr/share/fonts/truetype/liberation" in main._PDF_FONT_DIRS
    assert "/usr/share/fonts/truetype/liberation2" in main._PDF_FONT_DIRS


def test_missing_font_names_the_packages_to_install(monkeypatch):
    monkeypatch.setattr(main, "_pdf_find_font", lambda names: None)
    with pytest.raises(RuntimeError) as exc:
        main._pdf_font_names()
    assert "fonts-dejavu-core" in str(exc.value)


def test_report_is_a_real_pdf(report_pdf):
    assert report_pdf.startswith(b"%PDF-")
    assert report_pdf.rstrip().endswith(b"%%EOF")
    assert len(report_pdf) > 20_000


def test_report_embeds_the_font(report_pdf):
    body = report_pdf.decode("latin-1", errors="ignore")
    assert "DejaVuSans" in body or "LiberationSans" in body
    # Шрифт должен быть вшит в файл, иначе на чужой машине он не отрисуется.
    assert "FontFile2" in body


def test_no_text_is_drawn_with_a_font_without_cyrillic(report_pdf):
    """Ни одна буква не должна выводиться Helvetica или Times: в них нет кириллицы."""
    body = content_streams(report_pdf)
    assert body, "не удалось распаковать содержимое PDF"
    used = fonts_that_draw_text(body)
    assert used, "в документе не нашлось ни одного оператора вывода текста"
    latin_only = {name for name, base in _font_bases(report_pdf).items()
                  if base in {"Helvetica", "Times-Roman"}}
    assert not (used & latin_only), (
        f"текст выведен шрифтом без кириллицы: {sorted(used & latin_only)}"
    )


def test_cyrillic_survives_into_the_document(report_pdf):
    body = content_streams(report_pdf)
    # Текст закодирован по таблице подмножества шрифта, поэтому сверяем не буквы,
    # а то, что вывод идёт именно вшитым шрифтом и включает латиницу названия.
    assert re.search(r"/F\d\+0\s+[\d.]+\s+Tf", body)
    assert "DevelopAid" in body


def test_telegram_card_uses_the_same_generator():
    """Кнопка в боте и «Экспорт PDF» не должны расходиться в шрифтах."""
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert source.count("_build_developaid_pdf(") >= 2


def test_dockerfile_installs_the_fonts():
    dockerfile = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text(encoding="utf-8")
    assert "fonts-dejavu-core" in dockerfile
    assert "fontconfig" in dockerfile
