"""Подземная часть не выдаётся за ГНС, и итог называет обе базы.

«Просто ГНС и подземная — это смешно, ГНС — наружные стены, где они под
землёй?» (владелец, 04.09.2026). Он прав: ГНС — наземная площадь здания,
внутренний термин DevelopAid, и у подземного паркинга с кладовыми её нет
вовсе. Число в их строке — площадь подземного этажа, то есть другая величина
под тем же именем, а «Итого» складывало обе.

«Вообще по-хорошему убрать, у неё своя экономика подземелья» (там же). Убрано
по существу: `project_gns_sqm` — наземная площадь, подземная стоит рядом своим
числом, строительный объём — их сумма, и он назван там, где считается: общие
статьи (ИРД, проектирование, подготовка, сети, благоустройство, сдача,
содержание) идут от него, и подписи их ставок это говорят.

Деньги при этом не двигаются: CAPEX считается на своих базах (`core_above_gns`,
`core_under_gns`, их сумма), `project_gns_sqm` не читает ни одна статья — ни в
движке, ни в книге, где `ТЭП!C36` читает единственная ячейка `ОТЧЕТ!G6`, и её
саму не читает никто. Двигаются удельные: полная себестоимость на метр 307,2
вместо 240,7 на умолчаниях — это и есть смысл правки.

Разложение берётся у движка (`core_under_gns`): второй счёт той же величины на
экране однажды разошёлся бы с первым, и обе строки выглядели бы верными.

Запуск: python3 -m pytest tests/test_the_underground_is_not_called_above_ground.py -q
"""

from __future__ import annotations

import copy
import re
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PORT = 18247


def _renderer() -> str:
    """Кусок отрисовки ТЭП — по своим границам, а не по соседней строке."""
    start = core.PAGE.index(" const underGns=Number(r.tep.core_under_gns")
    end = core.PAGE.index("const REPORT_SECTIONS", start)
    return core.PAGE[start:end]


def _report() -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    return core._run_authoritative_model(x, t, [], {})["consolidated"]


# --- движок ------------------------------------------------------------------

def test_the_engine_hands_over_the_underground_base() -> None:
    """Подземная база приезжает готовой, вместе со строками ТЭП."""
    tep = _report()["tep"]
    under = float(tep["core_under_gns"])
    assert under > 0, "проверять нечего: на этих вводных подземной части нет"
    rows = {row["key"]: float(row["gns"]) for row in tep["rows"]}
    assert under == pytest.approx(sum(rows[key] for key in core.UNDERGROUND_PRODUCTS))
    assert float(tep["total"]["gns"]) > under, "итог обязан быть больше своей части"


def test_the_underground_list_is_declared_once() -> None:
    """Список подземных строк не переписан на странице руками."""
    assert core.UNDERGROUND_PRODUCTS == ("underground_parking", "storage")
    assert "__DEVELOPAID_UNDERGROUND_PRODUCTS__" not in core.PAGE, "плейсхолдер не подставлен"
    piece = _renderer()
    for key in core.UNDERGROUND_PRODUCTS:
        assert f"'{key}'" not in piece and f'"{key}"' not in piece, (
            f"{key} вписан в отрисовку руками — копию негде обновлять")
    assert "UNDERGROUND_PRODUCTS" in piece


def test_the_screen_does_not_add_up_the_underground_itself() -> None:
    """Разложение берётся у движка, а не собирается по строкам таблицы."""
    piece = _renderer()
    assert "r.tep.core_under_gns" in piece
    assert not re.search(r"UNDERGROUND_PRODUCTS\.includes\([^)]*\)\s*\?\s*sum", piece)
    head = piece[:piece.index("const isUnder")]
    assert "reduce" not in head and "forEach" not in head, (
        "подземная часть суммируется на экране — это второй счёт той же величины")


def test_the_pdf_split_counts_the_storage_too() -> None:
    """Кладовые лежат под землёй, и подпись отчёта не относит их к наземной."""
    tep = {"total": {"gns": 100.0}, "core_under_gns": 30.0,
           "rows": [{"key": "underground_parking", "gns": 20.0},
                    {"key": "storage", "gns": 10.0}]}
    assert core._underground_sqm(tep) == pytest.approx(30.0)
    assert core._above_ground_sqm(tep) == pytest.approx(70.0)
    # Запасной путь для отчётов, собранных до появления базы, считает так же.
    old = {"total": {"gns": 100.0}, "rows": tep["rows"]}
    assert core._underground_sqm(old) == pytest.approx(30.0)


def test_the_money_does_not_read_the_construction_volume() -> None:
    """`project_gns_sqm` — подпись, а не база: статьи считаются от своих."""
    source = Path(ROOT / "main_legacy.py").read_text(encoding="utf-8")
    body = source[source.index("    amounts = {"):source.index("\n    amounts[\"author_supervision\"]")]
    assert "project_gns_sqm" not in body, (
        "статья CAPEX считается от строительного объёма — тогда правка базы двигает деньги")
    for base in ("core_total_gns", "core_above_gns", "core_under_gns"):
        assert base in body, base


# --- книга -------------------------------------------------------------------

def test_the_book_stops_calling_the_underground_above_ground() -> None:
    """Подписи книги переименованы, и ни одна не осталась неопознанной."""
    import copy as _copy
    import io as _io

    import openpyxl

    data, _name, report = core.build_project_workbook(
        _copy.deepcopy(core.DEFAULT_INPUTS), _copy.deepcopy(core.TEP_DEFAULT),
        None, None, project_name="Подписи ГНС")
    book = openpyxl.load_workbook(_io.BytesIO(data))
    assert book["ТЭП"]["C3"].value == "ГНС / подземная площадь, м²"
    assert book["ТЭП"]["A36"].value == "ИТОГО ПРОЕКТ — строительный объём"
    assert book["ОТЧЕТ"]["F6"].value == "Строительный объём"
    # Формула под подписью осталась прежней: переименование методику не двигает.
    assert book["ОТЧЕТ"]["G6"].value == "='ТЭП'!C36"
    assert not [one for one in (report.get("missing") or []) if "подпись" in str(one)], report


def test_an_unrecognised_label_is_named_out_loud() -> None:
    """Не опознали прежнюю подпись — это missing, а не тихий пропуск."""
    missing: list[str] = []
    core._v4_rename_labels("<x:c r=\"C3\"><x:v>ничего похожего</x:v></x:c>", "ТЭП", missing)
    assert missing and "C3" in missing[0], missing


# --- живая страница ----------------------------------------------------------

def test_in_a_real_browser_the_table_names_both_bases() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright недоступен")
    chrome = next(iter(sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)
    if chrome is None or not chrome.exists():
        pytest.skip("chromium в образе не найден")
    import uvicorn
    import main as wrapper

    server = uvicorn.Server(uvicorn.Config(wrapper.app, host="127.0.0.1", port=PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(400):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
            page.evaluate("() => calculate()")
            page.wait_for_function(
                "() => (document.getElementById('reportTep')||{}).innerHTML"
                "&& document.getElementById('reportTep').innerHTML.includes('Итого')",
                timeout=120_000)
            table = page.evaluate("() => document.getElementById('reportTep').innerHTML")
            note = page.evaluate("() => document.getElementById('reportTepNote').textContent")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=15)

    assert not errors, errors

    # Числа берутся из самой таблицы: страница считает подземную часть на своих
    # вводных, и сверять её с отдельным прогоном значит сверять два проекта.
    def number(text: str) -> float:
        return float(text.replace("\xa0", "").replace("&nbsp;", "")
                     .replace(" ", "").replace(",", "."))

    assert "ГНС наземная, м²" in table and "Подземная, м²" in table, (
        "колонка не разделена — две величины под одним именем")
    foot = table[table.index("<tfoot>"):]
    totals = re.findall(r"<th>([\d\s&nbsp;\xa0,\.]+?)</th>", foot)
    assert len(totals) >= 2, foot
    above, under = number(totals[0]), number(totals[1])
    assert under > 0, "проверять нечего: на умолчаниях подземной части нет"

    volume = re.search(r"Строительный объём — ([\d\s&nbsp;\xa0,\.]+?) м²", note)
    assert volume, note
    assert above + under == pytest.approx(number(volume.group(1)), rel=1e-6), (
        above, under, volume.group(1))
    assert "наземной ГНС" in note and "суммарной поэтажной" in note, note


def test_the_base_of_the_unit_figures_is_the_above_ground_area() -> None:
    """`project_gns_sqm` — наземная; обе половины стоят рядом с ней."""
    summary = _report()["summary"]
    above = float(summary["project_gns_sqm"])
    under = float(summary["underground_gns_sqm"])
    volume = float(summary["construction_volume_sqm"])
    assert under > 0, "проверять нечего: на умолчаниях подземной части нет"
    assert above + under == pytest.approx(volume)
    assert above == pytest.approx(volume - under)
    # Удельные считаются на наземной, а не на объёме: иначе правка не сделана.
    expenses = float(summary["total_expenses"])
    assert summary["full_cost_per_gns_th"] != pytest.approx(expenses / volume / 1000, rel=1e-9)


def test_the_shared_rates_say_they_are_on_the_construction_volume() -> None:
    """Ставки общих статей умножаются на объём — подпись обязана это сказать.

    Ловушка ровно здесь: статья считается от `core_total_gns` (наземная плюс
    подземная), а подсказка звала базу «ГНС». После того как ГНС стала
    наземной, человек вписал бы ставку на наземный метр, а движок применил бы
    её к объёму, который на пятую часть больше.
    """
    hints = {name: hint for _group, fields in core.FIELD_GROUPS
             for name, _title, hint, *_rest in fields}
    for key in ("ird_th_per_sqm", "design_p_th_per_sqm", "design_rd_th_per_sqm",
                "preparation_th_per_sqm", "utilities_th_per_sqm",
                "landscaping_th_per_sqm", "commissioning_th_per_sqm",
                "site_maintenance_th_per_sqm"):
        assert "строительного объёма" in hints[key], (key, hints[key])
    # У СМР базы свои, и они названы своими именами.
    assert "наземной части" in hints["main_above_th_per_sqm"]
    assert "подземной части" in hints["main_under_th_per_sqm"]
