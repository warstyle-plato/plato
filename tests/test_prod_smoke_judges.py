"""Судьи проверки прода (`scripts/prod_smoke.py`) падают на подделке.

Проверка, которая зеленеет на тизере с 10 участками из 20, ничего не ловит:
именно так тизер КРТ Нагатино и уехал на прод. Здесь каждый судья получает
настоящую поломку — PDF, собранный ReportLab с кириллицей, книгу openpyxl,
снимок отрисованного «Итога» — и обязан её назвать; исправный вариант обязан
пройти.

Запуск: python3 -m pytest tests/test_prod_smoke_judges.py -q
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("prod_smoke", ROOT / "scripts" / "prod_smoke.py")
smoke = importlib.util.module_from_spec(_spec)
sys.modules["prod_smoke"] = smoke
_spec.loader.exec_module(smoke)

REF = smoke.load_reference()
NUMBERS = REF["cadastral_numbers"]


# --- эталон -----------------------------------------------------------------

def test_the_reference_is_the_nagatino_preset_and_its_egrn_land_extracts():
    preset = json.loads((ROOT / REF["preset"]).read_text(encoding="utf-8"))
    assert NUMBERS == preset["project"]["cadastral_numbers"]
    assert len(NUMBERS) == len(set(NUMBERS)) == 20
    lands = sorted(p.stem.replace("_", ":") for p in (ROOT / "reference_data/krt/egrn").glob("*.xml")
                   if "land_record" in p.read_text(encoding="utf-8"))
    assert sorted(NUMBERS) == lands, "эталон разошёлся с выписками ЕГРН на земельные участки"


# --- 1. автозагрузка --------------------------------------------------------

def _lookup(count: int, area_each: float = 18.686 / 20) -> dict:
    return {"results": [{"found": i < count, "cadastral_number": n, "area_ha": area_each}
                        for i, n in enumerate(NUMBERS)]}


def test_autoload_passes_twenty_of_twenty():
    assert smoke.judge_autoload(_lookup(20), REF).status == smoke.OK


def test_autoload_names_the_missing_parcels():
    check = smoke.judge_autoload(_lookup(10), REF)
    assert check.status == smoke.FAIL
    assert NUMBERS[15] in check.detail and "площадь" in check.detail


# --- 2. тизер ---------------------------------------------------------------

def _font() -> str:
    for directory in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu",
                      "/usr/share/fonts/truetype/liberation"):
        for name in ("DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
            if (Path(directory) / name).exists():
                return str(Path(directory) / name)
    pytest.fail("нет шрифта с кириллицей — тизер на проде тоже не собрался бы")


def _teaser_pdf(listed: int, caption: str = "") -> bytes:
    """Страница паспорта участка, как её печатает `teaser_pdf._site_rows`."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    if "SmokeSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("SmokeSans", _font()))
    out = io.BytesIO()
    pdf = canvas.Canvas(out)
    pdf.setFont("SmokeSans", 10)
    lines = ["Девелоперский проект", "Информация по земельному участку",
             f"Кадастровые номера ({listed}) {', '.join(NUMBERS[:6])} … и ещё {listed - 6} — в полном отчёте",
             "Площадь участка 18,69 га"]
    if caption:
        lines.append(caption)
    for i, line in enumerate(lines):
        pdf.drawString(40, 800 - 16 * i, line)
    pdf.showPage()
    pdf.save()
    return out.getvalue()


def test_the_teaser_with_ten_of_twenty_parcels_is_red():
    check = smoke.judge_teaser_response(200, "application/pdf", _teaser_pdf(10), REF)
    assert check.status == smoke.FAIL
    assert "10 участков из 20" in check.detail


def test_the_teaser_with_all_twenty_parcels_is_green():
    caption = "Территория из 20 участков: 77:05:0004001:2046 … · границы ЕГРН"
    check = smoke.judge_teaser_response(200, "application/pdf", _teaser_pdf(20, caption), REF)
    assert check.status == smoke.OK, check.detail


def test_the_map_caption_admits_undrawn_contours():
    caption = "Территория из 20 участков · контур нарисован для 12 из 20: нет в ЕГРН"
    check = smoke.judge_teaser_response(200, "application/pdf", _teaser_pdf(20, caption), REF)
    assert check.status == smoke.FAIL and "12 контуров из 20" in check.detail


def test_a_raw_reportlab_dump_is_red_even_with_http_200():
    text = "Кадастровые номера (20)\nLayoutError: Flowable <Table@0x7f> too large on page 2"
    check = smoke.judge_teaser(text, REF)
    assert check.status == smoke.FAIL and "сырой дамп" in check.detail


def test_a_refusal_that_is_not_a_pdf_is_red():
    body = b'{"detail":"Traceback (most recent call last): reportlab.platypus.doctemplate.LayoutError"}'
    check = smoke.judge_teaser_response(500, "application/json", body, REF)
    assert check.status == smoke.FAIL and "сырой дамп" in check.detail


# --- 3. выгрузка торгов -----------------------------------------------------

COMMENT = "Комментарий Платона: чем интересен, чем опасен, что пишут"
PARCEL = ("https://nspd.gov.ru/map?thematic=PKK&zoom=17"
          "&coordinate_x=4184314.62&coordinate_y=7508348.33")


def _auction_book(comments: list[str | None], links: list[str | None]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Выборка"
    ws.append(["Раздел", "Название", "Кадастровые номера", "Статус", COMMENT, "Источник"])
    for i, (comment, link) in enumerate(zip(comments, links), start=2):
        ws.append(["Торги", f"Лот {i}", f"77:01:0001058:{i}", "Приём заявок", comment, "https://etp"])
        if link:
            ws.cell(i, 3).hyperlink = link
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_the_export_with_comments_and_parcel_links_is_green():
    book = _auction_book(["Чем интересен: ПСН 2 256 м²", "Комментария нет: разбор ещё в очереди",
                          "Чем опасен: обременение"], [PARCEL] * 3)
    check = smoke.judge_auction_export(book, REF)
    assert check.status == smoke.OK, check.detail


def test_the_export_with_empty_comments_is_red():
    book = _auction_book([None, None, "Чем интересен: ТЦ"], [PARCEL] * 3)
    check = smoke.judge_auction_export(book, REF)
    assert check.status == smoke.FAIL and "содержателен лишь у 1 строк из 3" in check.detail


def test_a_raw_exception_is_not_an_honest_reason():
    raw = "Разбор не удался: HTTPException: Вопрос слишком длинный: 4551 знаков при пределе 4000."
    book = _auction_book([raw, raw, "Чем интересен: ТЦ"], [PARCEL] * 3)
    check = smoke.judge_auction_export(book, REF)
    assert check.status == smoke.FAIL and "HTTPException" in check.detail


def test_a_raw_exception_is_red_even_when_most_rows_are_fine():
    raw = "Разбор не удался: HTTPException: Вопрос слишком длинный: 4551 знаков при пределе 4000."
    book = _auction_book(["Чем интересен: ТЦ", "Чем опасен: аренда", raw], [PARCEL] * 3)
    check = smoke.judge_auction_export(book, REF)
    assert check.status == smoke.FAIL and "сырое исключение вместо ответа у 1 строк" in check.detail


def test_the_general_nspd_map_is_not_a_parcel_link():
    book = _auction_book(["Чем интересен"] * 2, ["https://nspd.gov.ru/map?thematic=PKK", PARCEL])
    check = smoke.judge_auction_export(book, REF)
    assert check.status == smoke.FAIL and "общая карта" in check.detail


def test_a_parcel_without_a_link_needs_a_reason():
    book = _auction_book(["Чем интересен"] * 2, [None, PARCEL])
    check = smoke.judge_auction_export(book, REF)
    assert check.status == smoke.FAIL and "ни причины" in check.detail


def test_the_export_without_a_comment_column_is_red():
    wb = openpyxl.Workbook()
    wb.active.append(["Раздел", "Название"])
    wb.active.append(["Торги", "Лот"])
    out = io.BytesIO()
    wb.save(out)
    check = smoke.judge_auction_export(out.getvalue(), REF)
    assert check.status == smoke.FAIL and "колонки «Комментарий…» нет" in check.detail


# --- 4. книга v4 ------------------------------------------------------------

def _workbook(labels: list[str], sheet: str = "Вводные") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for i, label in enumerate(labels, start=1):
        ws.cell(i, 10, label)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


TEP_WITH_OSZ = {"offices": {"gns": 92730}, "standalone_retail": {"gns": 92730}}


def test_the_book_with_both_osz_garages_is_green():
    book = _workbook(["Офисы — мест в своём подземном", "ТЦ / ОСЗ — мест в своём подземном"])
    assert smoke.judge_workbook(book, TEP_WITH_OSZ, REF).status == smoke.OK


def test_the_book_that_lost_an_osz_garage_is_red():
    check = smoke.judge_workbook(_workbook(["ТЦ / ОСЗ — мест в своём подземном"]), TEP_WITH_OSZ, REF)
    assert check.status == smoke.FAIL and "Офисы — мест в своём подземном" in check.detail


def test_the_osz_rows_are_not_required_without_osz():
    tep = {"offices": {"gns": 0}, "apartments": {"gns": 1000}}
    assert smoke.judge_workbook(_workbook(["Квартиры"]), tep, REF).status == smoke.OK


def test_the_book_without_the_inputs_sheet_is_red():
    check = smoke.judge_workbook(_workbook([], sheet="ОТЧЕТ"), TEP_WITH_OSZ, REF)
    assert check.status == smoke.FAIL and "«Вводные» нет" in check.detail


# --- 5. «Итог» --------------------------------------------------------------

TOTAL = "суммарной площади в ГНС"
CORE = "суммарной площади МКД в ГНС"
UNIT_ROWS = [["Выручка", "120 000 млн ₽", "916,6", "м² продаваемой площади", "—"],
             ["CAPEX", "60 000 млн ₽", "274,2", f"м² {TOTAL}", "458,1"],
             ["Маркетинг и продажи", "3 000 млн ₽", "13,7", f"м² {TOTAL}", "22,9"],
             ["EBITDA", "5 000 млн ₽", "38,8", "м² продаваемой площади", "—"],
             ["Проценты и комиссии", "9 000 млн ₽", "41,1", f"м² {TOTAL}", "68,7"],
             ["Налог на прибыль", "0 млн ₽", "0", f"м² {TOTAL}", "0"],
             ["НДС", "4 000 млн ₽", "18,3", f"м² {TOTAL}", "30,5"],
             ["Полные расходы", "71 000 млн ₽", "327,2", f"м² {TOTAL}", "711,4"],
             ["Чистая прибыль", "-5 000 млн ₽", "-41,4", "м² продаваемой площади", "—"]]


def _itog(unit_rows=None, headers=None, **changes) -> dict:
    """Снимок «Итога» в раскладке решения 4: каждая строка — на свою базу."""
    params = {
        "Полная себестоимость": f"711,4 тыс. ₽/м² прод. · 327,2 тыс. ₽/м² {TOTAL}",
        "Строительная себестоимость": f"467,8 тыс. ₽/м² прод. · 300,1 тыс. ₽/м² {CORE}",
        "EBITDA на метр": "38,8 тыс. ₽/м² прод.",
        "Чистая прибыль на метр": "-41,4 тыс. ₽/м² прод.",
    }
    params.update(changes)
    cells = UNIT_ROWS if unit_rows is None else unit_rows
    return {"params": params,
            "unit_headers": headers or ["ПОКАЗАТЕЛЬ", "ВСЕГО", "ТЫС. ₽/М² СВОЕЙ БАЗЫ", "БАЗА",
                                        "ТЫС. ₽/М² ПРОД."],
            "unit_cells": cells, "unit_rows": len(cells), "text": "ИТОГ …"}


def test_the_itog_with_each_row_on_its_own_base_is_green():
    check = smoke.judge_itog(_itog(), REF)
    assert check.status == smoke.OK, check.detail


def test_a_per_metre_number_without_its_divider_is_red():
    check = smoke.judge_itog(_itog(**{"EBITDA на метр": "38,8 тыс. ₽"}), REF)
    assert check.status == smoke.FAIL and "EBITDA на метр" in check.detail


def test_a_second_half_without_its_divider_is_red():
    check = smoke.judge_itog(_itog(**{"Полная себестоимость": "711,4 тыс. ₽/м² прод. · 327,2 тыс. ₽"}), REF)
    assert check.status == smoke.FAIL and "Полная себестоимость" in check.detail


def test_a_profit_on_the_wrong_base_is_red():
    """Прибыль на суммарную площадь — подделка: решение 4 делит её на продаваемую."""
    check = smoke.judge_itog(_itog(**{"Чистая прибыль на метр": f"-41,4 тыс. ₽/м² {TOTAL}"}), REF)
    assert check.status == smoke.FAIL and "база не та" in check.detail


def test_a_cost_missing_its_total_area_half_is_red():
    check = smoke.judge_itog(_itog(**{"Полная себестоимость": "711,4 тыс. ₽/м² прод."}), REF)
    assert check.status == smoke.FAIL and "Полная себестоимость" in check.detail


def test_a_base_outside_the_glossary_is_red():
    """Прежняя подпись «ГНС» — не база словаря, а не «какая-нибудь подпись»."""
    check = smoke.judge_itog(_itog(**{"EBITDA на метр": "38,8 тыс. ₽/м² ГНС"}), REF)
    assert check.status == smoke.FAIL and "не из словаря" in check.detail


def test_the_layout_before_decision_four_is_red():
    old = _itog(headers=["Показатель", "Всего", "тыс. ₽ / м² ГНС", "тыс. ₽ / м² продаваемой"],
                **{"EBITDA на метр": "38,8 тыс. ₽/м² прод. · 30,0 тыс. ₽/м² ГНС"})
    check = smoke.judge_itog(old, REF)
    assert check.status == smoke.FAIL
    assert "EBITDA на метр" in check.detail and "колонки" in check.detail


def test_a_unit_row_on_the_wrong_base_is_red():
    rows = [list(r) for r in UNIT_ROWS]
    rows[0][3] = f"м² {TOTAL}"
    check = smoke.judge_itog(_itog(unit_rows=rows), REF)
    assert check.status == smoke.FAIL and "«Выручка»" in check.detail


def test_an_empty_itog_is_red_not_skipped():
    check = smoke.judge_itog({"params": {}, "unit_headers": [], "unit_rows": 0}, REF)
    assert check.status == smoke.FAIL


# --- выкат ------------------------------------------------------------------

def test_the_deploy_is_recognised_by_commit_and_by_version_only_when_commit_is_empty():
    sha = "0c9a8e0a11e3b0ab8bf89380a05541abb4bfcd09"
    assert smoke.deployed({"commit": sha, "version": "0.24.57"}, sha, "0.24.57")[0]
    assert not smoke.deployed({"commit": "3b2219f6", "version": "0.24.57"}, sha, "0.24.57")[0]
    ok, note = smoke.deployed({"commit": "", "version": "0.24.57"}, sha, "0.24.57")
    assert ok and "пустой commit" in note
    assert not smoke.deployed({"commit": "", "version": "0.24.56"}, sha, "0.24.57")[0]


def test_the_summary_names_failures_and_skips():
    checks = [smoke.Check("2. Тизер PDF", smoke.FAIL, "20", "10", "тизер называет 10 участков из 20"),
              smoke.Check("5. Страница «Итог»", smoke.SKIP, "Итог", "401", "нужен ключ владельца")]
    text = smoke.summary_markdown(checks, "https://developaid.ru",
                                  {"version": "0.24.57", "commit": "0c9a8e0a11e3"}, "#541")
    assert "❌" in text and "⚪ пропущено" in text
    assert "| Проверка | Итог | Ожидалось | Получено | Версия прода | Последний слитый PR |" in text
    assert "0.24.57 (0c9a8e0a11e3)" in text and "#541" in text
