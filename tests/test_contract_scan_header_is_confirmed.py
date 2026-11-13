"""Скан документа договора: распознана только шапка, в расчёт она входит после подтверждения.

Решение владельца 13.11.2026 «А»: таблицы со скана не читаются, номер и дата
договора, соглашения и акта, отчётный период акта — предложение, которое
пользователь проверяет и подтверждает. Распознавание подменено выдуманным
текстом: репозиторий публичный, сканы владельца в него не попадают, а прогон
не зависит от tesseract на машине.
"""
from __future__ import annotations

import pymupdf
import pytest

import developaid_contract_documents as documents
import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_contract_scan as scan
import developaid_monitor as monitor
import pdf_ocr
from tests.test_contract_card_confirms_and_chooses_links import CONTRACT, ROW
from tests.test_contract_fact_dates_ks6_periods_by_acts import WALLS, _row, card  # noqa: F401

ACT = ("Унифицированная форма № КС-2\n"
       "Договор подряда | № 12-ТСТ\n"
       "дата | 01.09.2025\n"
       "Номер документа Дата составления Отчетный период с по\n"
       "АКТ О ПРИЕМКЕ ВЫПОЛНЕННЫХ РАБОТ 2 03.02.2026 01.02.2026 03.02.2026\n"
       "Устройство стен м3 0,5 8 000,00 4 000,00\n")
AGREEMENT = ("Дополнительное соглашение\nк Договору подряда № 12-ТСТ от 01.09.2025\n"
             "г. Москва «01» февраля 2026 г.\n")
LETTER = "Сопроводительное письмо\nНаправляем документы на подписание.\n"


def scan_pdf(pages=1):
    """PDF без текстового слоя — как скан: только закрашенный прямоугольник."""
    document = pymupdf.open()
    for _ in range(pages):
        document.new_page().draw_rect(pymupdf.Rect(40, 40, 400, 400), fill=(0.5, 0.5, 0.5))
    return document.tobytes()


@pytest.fixture
def ocr(monkeypatch):
    """Распознавание, отдающее заданный текст по страницам, и учёт запрошенных страниц."""
    state = {"pages": [ACT], "asked": []}

    def text(data, *, dpi, page_indices, upright):
        (index,) = page_indices
        state["asked"].append((index, dpi, upright))
        return f"[стр. {index + 1}]\n" + state["pages"][index]
    monkeypatch.setattr(pdf_ocr, "unavailable_reason", lambda: None)
    monkeypatch.setattr(pdf_ocr, "text", text)
    return state


def test_an_act_scan_gives_its_number_date_and_period_and_no_table(ocr):
    got = documents.read(scan_pdf())
    assert got["act"] == {"number": "2", "date": "2026-02-03", "start": "2026-02-01", "finish": "2026-02-03",
                          "total": None, "positions": [], "table_total": None}
    assert got["contract"] == {"number": "12-ТСТ", "date": "2025-09-01"} and got["agreement"] is None
    assert got["estimates"] == [] and got["schedule"] is None and got["warnings"] == [scan.TABLES_NOT_READ]
    assert got["scan"]["page"] == 1 and got["scan"]["confirmed_at"] is None
    assert ocr["asked"] == [(0, scan.DPI, True)]


def test_an_unnumbered_agreement_is_found_past_a_cover_letter(ocr):
    ocr["pages"] = [LETTER, AGREEMENT, ACT]
    got = documents.read(scan_pdf(3))
    assert got["agreement"] == {"number": "б/н", "date": "2026-02-01"} and got["act"] is None
    assert got["scan"]["page"] == 2 and [index for index, *_ in ocr["asked"]] == [0, 1]


def test_a_scan_naming_no_document_says_so_and_a_missed_period_asks_for_it(ocr):
    ocr["pages"] = [LETTER, LETTER]
    got = documents.read(scan_pdf(2))
    assert got["contract"] is got["agreement"] is got["act"] is None
    assert got["warnings"][1].startswith("На первых 2 страницах скана не распознаны")
    ocr["pages"] = [ACT.replace(" 01.02.2026 03.02.2026", " 01.02.2026")]
    got = documents.read(scan_pdf())
    assert got["act"]["date"] is None and got["act"]["number"] == "2"
    assert "Дата акта и отчётный период по скану не распознаны" in got["warnings"][1]


def test_without_recognition_the_scan_is_refused_with_the_reason(monkeypatch):
    monkeypatch.setattr(pdf_ocr, "unavailable_reason", lambda: "нет программы распознавания")
    with pytest.raises(ValueError, match="это скан, а распознавание на сервере сейчас недоступно "
                                         r"\(нет программы распознавания\)"):
        documents.read(scan_pdf())


def test_an_unconfirmed_act_scan_dates_nothing_until_it_is_confirmed(card, ocr):
    row = _row(WALLS, summary=[("1", "2026-01-31", 2000.0), ("2", "2026-02-04", 4000.0)])
    sha = files.store("Учебный", ROW, "КС-2 2 скан.pdf", scan_pdf())["sha256"]
    listed = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(row))
    document = next(d for d in listed["documents"] if d["sha256"] == sha)
    assert document["warnings"][:2] == [scan.CHECK, scan.TABLES_NOT_READ] and "text" not in document["scan"]
    second = listed["fact"]["act_dates"][1]
    assert second["basis"].startswith("Дата подписания акта № 2 из сводной"), "непроверенный скан не датирует"
    values = {"contract_number": "12-ТСТ", "contract_date": "2025-09-01", "act_number": "2",
              "act_date": "2026-02-03", "act_start": "2026-01-30", "act_finish": "2026-02-03"}
    confirmed = files.confirm_scan("Учебный", ROW, sha, "act", values, "2026-02-04", fact.acts(row))
    second = confirmed["fact"]["act_dates"][1]
    assert (second["start"], second["end"], second["basis"]) == (
        "2026-01-30", "2026-02-03", "Отчётный период из акта КС-2 № 2")
    document = next(d for d in confirmed["documents"] if d["sha256"] == sha)
    assert document["title"] == "Акт КС-2 № 2 от 03.02.2026" and document["warnings"][1:] == [scan.TABLES_NOT_READ]
    assert document["warnings"][0].endswith("; исправлено вручную: начало отчётного периода.")


def test_confirming_checks_the_fields_and_the_contract_of_the_card(card, ocr):
    sha = files.store("Учебный", ROW, "скан.pdf", scan_pdf())["sha256"]
    act = {"contract_number": "12-ТСТ", "act_number": "2", "act_date": "2026-02-03",
           "act_start": "2026-02-04", "act_finish": "2026-02-03"}
    with pytest.raises(files.ContractFilesProblem, match="Начало отчётного периода позже его конца"):
        files.confirm_scan("Учебный", ROW, sha, "act", act)
    with pytest.raises(files.ContractFilesProblem, match="Впишите номер акта"):
        files.confirm_scan("Учебный", ROW, sha, "act", {**act, "act_number": ""})
    with pytest.raises(files.ContractFilesProblem, match="«03.02.2026» не прочитана"):
        files.confirm_scan("Учебный", ROW, sha, "act", {**act, "act_date": "03.02.2026"})
    with pytest.raises(files.ContractFilesProblem, match="В документе договор № 77-А"):
        files.confirm_scan("Учебный", ROW, sha, "contract", {"contract_number": "77-А", "contract_date": "2025-09-01"})
    with pytest.raises(files.ContractFilesProblem, match="Впишите дату дополнительного соглашения"):
        files.confirm_scan("Учебный", ROW, sha, "agreement", {"agreement_number": "5"})
    with pytest.raises(files.ContractFilesProblem, match="Выберите, что это за документ"):
        files.confirm_scan("Учебный", ROW, sha, "letter", {})
    text_pdf = next(d["sha256"] for d in files.listing("Учебный", CONTRACT)["documents"] if not d.get("scan"))
    with pytest.raises(files.ContractFilesProblem, match="прочитан из текста PDF"):
        files.confirm_scan("Учебный", ROW, text_pdf, "contract", {"contract_number": "12-ТСТ",
                                                                  "contract_date": "2025-09-01"})
    agreement = files.confirm_scan("Учебный", ROW, sha, "agreement", {"agreement_date": "2026-02-10"})
    document = next(d for d in agreement["documents"] if d["sha256"] == sha)
    assert document["agreement"] == {"number": "б/н", "date": "2026-02-10"} and document["act"] is None
    assert document["scan"]["kind"] == "agreement" and document["scan"]["corrected"] == [
        "номер соглашения", "дата соглашения"]


def test_a_foreign_number_does_not_refuse_the_scan_but_is_named(card, ocr):
    ocr["pages"] = [ACT.replace("12-ТСТ", "77-А")]
    sha = files.store("Учебный", ROW, "чужой скан.pdf", scan_pdf())["sha256"]
    document = next(d for d in files.listing("Учебный", CONTRACT)["documents"] if d["sha256"] == sha)
    assert "Номер договора из карточки в распознанном тексте не найден" in document["warnings"][0]


def test_a_confirmed_scan_is_not_recognised_again_by_a_newer_reader(card, ocr, monkeypatch):
    sha = files.store("Учебный", ROW, "скан.pdf", scan_pdf())["sha256"]
    files.confirm_scan("Учебный", ROW, sha, "act", {"act_number": "2", "act_date": "2026-02-03",
                                                     "act_start": "2026-02-01", "act_finish": "2026-02-03"})
    asked = len(ocr["asked"])
    monkeypatch.setattr(documents, "READER_VERSION", documents.READER_VERSION + 1)
    document = next(d for d in files.listing("Учебный", CONTRACT)["documents"] if d["sha256"] == sha)
    assert document["scan"]["confirmed_at"] and len(ocr["asked"]) == asked


def test_a_sideways_page_is_read_by_its_upright_turn(monkeypatch):
    readings = {0: "ыв ащ", 90: "Договор подряда " * 30, 270: "Договор " * 5}
    turns = []

    class Matrix:
        def __init__(self, *_):
            self.turn = 0

        def prerotate(self, turn):
            self.turn = turn
            return self

    class Page:
        def get_pixmap(self, dpi=None, matrix=None):
            turns.append(matrix.turn if matrix else 0)
            return type("Pixmap", (), {"tobytes": lambda _, *a: (matrix.turn if matrix else 0)})()

    class Document:
        page_count = 1

        def __getitem__(self, _):
            return Page()

        def close(self):
            pass

    import pymupdf as real
    monkeypatch.setattr(real, "open", lambda *a, **k: Document())
    monkeypatch.setattr(real, "Matrix", Matrix)
    monkeypatch.setattr(pdf_ocr, "_recognized", lambda png: readings[png])
    monkeypatch.setattr(pdf_ocr, "unavailable_reason", lambda: None)
    got = pdf_ocr.text(b"%PDF", dpi=300, page_indices=[0], upright=True)
    assert got == "[стр. 1]\n" + readings[90] and turns == [0, 90, 270]
    assert pdf_ocr.text(b"%PDF", dpi=300, page_indices=[0]) == "[стр. 1]\nыв ащ" and turns[3:] == [0]
