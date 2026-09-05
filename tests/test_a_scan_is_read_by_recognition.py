"""Скан читается распознаванием, а отказ называет, чего не хватает.

Владелец прислал тизер на четырёх страницах и получил «в документе нет
текстового слоя — это скан. Распознать его здесь нечем» (04.09.2026). Нечем
было не везде: tesseract стоит в образе с 31.08.2026 — его туда положили ради
распоряжений о торгах, — и средство лежало в двух модулях от разбора.
"""

import subprocess

import document_intake as di
import pdf_ocr


class _Page:
    def __init__(self, png: bytes) -> None:
        self._png = png

    def get_pixmap(self, dpi: int = 200):  # noqa: ARG002
        page = self

        class _Pixmap:
            def tobytes(self, _kind: str) -> bytes:
                return page._png

        return _Pixmap()


class _Document:
    def __init__(self, count: int) -> None:
        self.page_count = count

    def __getitem__(self, index: int) -> _Page:
        return _Page(f"png-{index}".encode())


def _stub_ocr(monkeypatch, recognized: str, count: int = 4) -> list[int]:
    """Растеризатор и tesseract подменяются: в песочнице их может не быть."""
    import sys
    import types

    seen: list[int] = []
    module = types.ModuleType("pymupdf")
    module.open = lambda stream=None, filetype=None: _Document(count)  # noqa: ARG005
    monkeypatch.setitem(sys.modules, "pymupdf", module)
    monkeypatch.setattr(pdf_ocr.shutil, "which", lambda name: "/usr/bin/" + name)

    def fake_run(argv, input=None, capture_output=False, timeout=None):  # noqa: A002, ARG001
        seen.append(len(seen))
        return subprocess.CompletedProcess(argv, 0, recognized.encode(), b"")

    monkeypatch.setattr(pdf_ocr.subprocess, "run", fake_run)
    return seen


def _scan_pdf(pages: int = 4) -> bytes:
    """PDF из пустых страниц: текстового слоя нет, страницы есть."""
    from pypdf import PdfWriter
    import io

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_the_recognizer_needs_both_halves(monkeypatch):
    # tesseract в образе есть, а растеризатор не был объявлен нигде: проверка
    # половины отвечала «умеем» о том, чего нет, и распознавание умирало на
    # `import pymupdf`.
    import sys

    monkeypatch.setattr(pdf_ocr.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    monkeypatch.setattr(pdf_ocr, "_rasterizer_ready", lambda: False)
    assert pdf_ocr.available() is False
    assert "pymupdf" in pdf_ocr.unavailable_reason()

    monkeypatch.setattr(pdf_ocr, "_rasterizer_ready", lambda: True)
    monkeypatch.setattr(pdf_ocr.shutil, "which", lambda name: None)
    assert pdf_ocr.available() is False
    assert "tesseract" in pdf_ocr.unavailable_reason()


def test_the_rasterizer_is_declared():
    # Модуль звался из читателя распоряжений и не стоял в requirements: на
    # проде это «распознавание доступно» и ModuleNotFoundError следом.
    declared = open("requirements.txt", encoding="utf-8").read()
    assert "pymupdf" in declared


def test_the_order_reader_does_not_keep_its_own_copy():
    # Распознавание объявлено один раз: копию негде обновлять.
    from market_search import krt_tender_orders as orders

    assert orders.ocr_available is pdf_ocr.available
    assert orders.OcrUnavailable is pdf_ocr.Unavailable
    source = open("market_search/krt_tender_orders.py", encoding="utf-8").read()
    assert "tesseract" not in source.split('"""', 2)[2], "своя реализация вернулась"


def test_a_scan_becomes_text(monkeypatch):
    _stub_ocr(monkeypatch, "Площадь участка 1,42 га\nЦена 1 650 000 000 рублей")
    document = di.extract_text(_scan_pdf(), "тизер.pdf")
    assert document["scanned"] is True, "скан остаётся сканом"
    assert document["recognized"] is True
    assert "1,42 га" in document["text"]


def test_the_recognized_text_is_named_recognized(monkeypatch):
    # Цитата из распознанного ручается за смысл, а не за написание: цифра,
    # прочитанная неверно, выглядит как прочитанная верно.
    _stub_ocr(monkeypatch, "Площадь участка 1,42 га")
    document = di.extract_text(_scan_pdf(), "тизер.pdf")
    assert "распознаванием" in document["reason"]
    assert "не дословны" in document["reason"]
    assert "РАСПОЗНАВАНИЕМ" in di.intake_prompt(document)


def test_a_readable_document_is_not_recognized(monkeypatch):
    # Есть текстовый слой — распознавать нечего, и tesseract не зовётся.
    seen = _stub_ocr(monkeypatch, "не должно понадобиться")
    document = {"text": "x" * 5000}
    assert di.extract_text(b"", "пусто.pdf")["recognized"] is False
    assert not seen
    assert "РАСПОЗНАВАНИЕМ" not in di.intake_prompt(document)


def test_recognition_has_its_own_page_cap(monkeypatch):
    # Чтение текстового слоя стоит миллисекунды, распознавание — секунды на
    # страницу, и человек ждёт в окне.
    assert di.OCR_MAX_PAGES < di.MAX_PAGES
    seen = _stub_ocr(monkeypatch, "строка", count=30)
    document = di.extract_text(_scan_pdf(di.OCR_MAX_PAGES + 5), "толстый.pdf")
    assert len(seen) == di.OCR_MAX_PAGES
    assert f"первые {di.OCR_MAX_PAGES} страниц" in document["reason"]


def test_a_missing_recognizer_still_refuses_with_a_reason(monkeypatch):
    # «Не смогли» и «нечем» — разные ответы. Бот живёт на Render, и наш
    # Dockerfile там не собирается.
    monkeypatch.setattr(pdf_ocr.shutil, "which", lambda name: None)
    document = di.extract_text(_scan_pdf(), "скан.pdf")
    assert document["recognized"] is False
    assert "tesseract" in document["reason"]


def test_a_failing_recognizer_is_not_an_empty_document(monkeypatch):
    _stub_ocr(monkeypatch, "")

    def boom(*a, **k):
        raise RuntimeError("растр не собрался")

    monkeypatch.setattr(pdf_ocr, "text", boom)
    document = di.extract_text(_scan_pdf(), "скан.pdf")
    assert document["recognized"] is False
    assert "сорвалось" in document["reason"] and "растр не собрался" in document["reason"]
