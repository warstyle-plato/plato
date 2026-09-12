"""Переданные муниципалитету метры: не продаются и уменьшают плату за ВРИ.

В Подмосковье есть условия, при которых застройщик передаёт муниципалитету
какое-то количество метров и на их стоимость уменьшает плату за смену ВРИ
(владелец, 19.08.2026). До сих пор колонка «передаваемая» в таблице ТЭП была
справочной: вписанное в неё число не двигало ни выручку, ни плату — ни в
движке, ни в книге.

Два правила, из которых это собрано:

* переданные метры строятся, но не продаются — ГНС и общая площадь остаются,
  продаваемая уменьшается на переданное;
* сумма зачёта берётся из соглашения, а не считается нами по цене продажи:
  муниципалитет засчитывает по своей оценке, и она другая. Поэтому это
  отдельная вводная, а не производная от площади.

Запуск: python3 -m pytest tests/test_transfer_to_the_municipality.py -q
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import page_blocks  # noqa: E402
import v4_inputs  # noqa: E402

import main as wrapper  # noqa: E402

core = wrapper.core

BASE = {**core.DEFAULT_INPUTS, "vri_required": True, "land_rights_cost_mln": 1000.0}


def _summary(extra: dict) -> dict:
    return core.calculate(core.CalcRequest(
        inputs={**BASE, **extra}, tep=copy.deepcopy(core.TEP_DEFAULT)))["summary"]


def test_the_offset_lowers_the_vri_payment():
    """Зачёт 300 млн ₽ уменьшает обязательство ровно на 300 млн ₽."""
    gross = core.vri_relief({}, 1000e6)[1]
    assert gross == pytest.approx(1000e6)
    relief, net = core.vri_relief({"vri_transfer_offset_mln": 300.0}, 1000e6)
    assert relief == pytest.approx(300e6)
    assert net == pytest.approx(700e6)


def test_the_offset_adds_up_with_the_relief():
    """Льгота и зачёт — разные основания: складываются, а не заменяют друг друга."""
    relief, net = core.vri_relief(
        {"vri_relief_mode": "amount", "vri_relief_mln": 200.0,
         "vri_transfer_offset_mln": 300.0}, 1000e6)
    assert relief == pytest.approx(500e6)
    assert net == pytest.approx(500e6)


def test_the_offset_never_makes_the_payment_negative():
    relief, net = core.vri_relief({"vri_transfer_offset_mln": 5000.0}, 1000e6)
    assert relief == pytest.approx(1000e6)
    assert net == 0.0


def test_the_offset_reaches_the_model():
    """Через вводные — до прибыли: 300 млн ₽ зачёта видно в результате."""
    without = _summary({})
    with_offset = _summary({"vri_transfer_offset_mln": 300.0})
    assert with_offset["net_profit"] > without["net_profit"]
    assert "vri_transfer_offset_mln" in core.DEFAULT_INPUTS
    labels = [name for group in core.FIELD_GROUPS for name, *_ in group[1]]
    assert "vri_transfer_offset_mln" in labels, "поля нет на вкладке «Вводные»"


def _tep_cell(edits):
    """Гоняет НАСТОЯЩУЮ правку ячейки страницы через node.

    Прежде проверка держала форму записи — `tep[key].saleable=Math.max(0` — и
    падала, когда арифметику переставили, ничего не сказав о том, что
    сломалось (ничего). Утверждение здесь другое: ГНС на месте, продаваемая
    меньше на переданное, полезная не меньше. Это видно, и это гоняется.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = page_blocks.tep_cell_stand() + (
        "tep={apartments:{label:'Квартиры',gns:31000,total_area:27900,"
        "useful:20150,saleable:20150,transfer:0,units:336}};\n"
        + "".join(f"tepCellChanged('apartments','{col}',{value});\n"
                  for col, value in edits)
        + "process.stdout.write(JSON.stringify("
          "{row:tep.apartments,note:tepRefillNote.apartments||''}));"
    )
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:900]
    return json.loads(done.stdout)


def test_the_transferred_metres_leave_the_saleable_area():
    """Метры строятся, но не продаются: ГНС на месте, продаваемая меньше."""
    got = _tep_cell([("transfer", 5000)])
    row = got["row"]
    assert row["gns"] == 31000 and row["total_area"] == 27900, row
    assert row["transfer"] == 5000
    assert row["saleable"] == 15150, row
    # Полезная — построенная площадь, и передача её не уменьшает: метры
    # построены и полезны, просто не наши (владелец, 10.09.2026).
    assert row["useful"] == 20150, row
    assert "не продаются" in got["note"]


def test_the_note_names_the_whole_transfer_not_the_change():
    """«Пишешь 5.000 она пишет то 0 то 4000» (владелец, 10.09.2026).

    Подпись считалась от ДЕЛЬТЫ: вписал 1 000, потом 5 000 — и на экране
    «переданные 4 000» при поле 5 000. Дельту помнить не нужно вовсе.
    """
    got = _tep_cell([("transfer", 1000), ("transfer", 5000)])
    assert got["row"]["saleable"] == 15150, got["row"]
    assert got["row"]["useful"] == 20150, got["row"]
    assert "5000" in got["note"].replace("\u00a0", "").replace(" ", ""), got["note"]
    assert "4000" not in got["note"].replace("\u00a0", "").replace(" ", ""), got["note"]


def test_editing_a_neighbour_cell_does_not_return_the_given_metres():
    """Правка ГНС затирала продаваемую полным числом из пропорции.

    Переданное при этом оставалось в своей колонке — и молча возвращалось в
    продажу: строка выглядела верной, а метры города продавались.
    """
    got = _tep_cell([("transfer", 5000), ("gns", 31000)])
    assert got["row"]["transfer"] == 5000
    assert got["row"]["saleable"] == 15150, got["row"]


def test_a_typed_saleable_area_is_the_net_one():
    """Вписанная продаваемая — НЕТТО: ГНС считается от полной площади.

    Иначе ГНС теряет переданные метры, которые строятся, и строительный объём
    выходит меньше стройки.
    """
    got = _tep_cell([("transfer", 5000), ("saleable", 15150)])
    row = got["row"]
    assert row["saleable"] == 15150 and row["transfer"] == 5000, row
    assert row["useful"] == 20150, row
    assert abs(row["gns"] - 31000) < 1, row


def test_the_workbook_gets_the_offset_too():
    """Книга должна платить столько же, сколько движок.

    Строку в шаблон не вставить — поедут все ссылки, — а формулы листов ВРИ и
    ОТЧЁТ вычитают из платы именно ячейку льготы. Поэтому зачёт ложится туда же
    суммой: у книги и движка одна плата к оплате, и `audit_plato_workbook` их
    сводит без расхождения.
    """
    import io

    openpyxl = pytest.importorskip("openpyxl")
    inputs = {**BASE, "vri_relief_mode": "amount", "vri_relief_mln": 200.0,
              "vri_transfer_offset_mln": 300.0}
    content, _, missing = core.build_project_workbook(
        inputs, copy.deepcopy(core.TEP_DEFAULT), [], {}, project_name="Проверка")
    assert not [item for item in missing if "vri" in item], missing
    book = openpyxl.load_workbook(io.BytesIO(content))
    assert v4_inputs.inputs(book)["B82"].value == pytest.approx(500.0)

    # Столько же остаётся к оплате в движке: 1 000 − 200 льготы − 300 зачёта.
    _, net = core.vri_relief(inputs, 1000e6)
    assert net == pytest.approx(500e6)


def test_the_workbook_builds_on_the_reduced_saleable_area():
    """Книга берёт продаваемую из ТЭП — значит переданное в неё не попадает.

    Лист ТЭП книги v4 собирается формулами из «Вводных»: ГНС и продаваемая
    приходят отдельными ячейками. Передали метры городу — продаваемая меньше,
    ГНС на месте: строят столько же, продают меньше.
    """
    import io

    openpyxl = pytest.importorskip("openpyxl")

    def cells(tep):
        content, _, _ = core.build_project_workbook(
            {**BASE}, tep, [], {}, project_name="Проверка")
        sheet = v4_inputs.inputs(openpyxl.load_workbook(io.BytesIO(content)))
        return sheet["W88"].value, sheet["Z88"].value

    plain = copy.deepcopy(core.TEP_DEFAULT)
    handed = copy.deepcopy(core.TEP_DEFAULT)
    handed["apartments"]["saleable"] -= 10000
    handed["apartments"]["transfer"] = 10000

    gns_before, saleable_before = cells(plain)
    gns_after, saleable_after = cells(handed)
    assert gns_before == gns_after, "ГНС не меняется: метры строятся"
    assert saleable_before - saleable_after == pytest.approx(10000)


def _with_transfer(area: float = 5000.0):
    tep = copy.deepcopy(core.TEP_DEFAULT)
    row = tep["apartments"]
    row["useful"] = row["saleable"]
    row["transfer"] = area
    row["saleable"] = row["useful"] - area
    return tep


def test_in_a_real_browser_the_report_names_the_transferred_metres():
    """«В отчёте вообще нет указания на передаваемую!» (владелец, 10.09.2026).

    Штуки так подписаны с 04.09 («из них передано N»), метры — нет, и таблица
    читалась так, будто продано всё построенное. Таблицу рисует `renderResult`
    — функция на полторы тысячи строк, стендом её не позвать, — поэтому мерим
    то, что видно: живую страницу в настоящем Chromium. На умолчаниях передача
    есть: садик на 250 мест уходит городу целиком.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright недоступен")
    import threading
    import time

    chrome = next(iter(sorted(
        Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)
    if chrome is None or not chrome.exists():
        pytest.skip("chromium в образе не найден")
    import uvicorn

    port = 8791
    server = uvicorn.Server(uvicorn.Config(
        wrapper.app, host="127.0.0.1", port=port, log_level="error"))
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
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            page.evaluate("() => calculate()")
            page.wait_for_function(
                "() => (document.getElementById('reportTep')||{}).innerHTML"
                "&& document.getElementById('reportTep').innerHTML.includes('Итого')",
                timeout=120_000)
            table = page.evaluate("() => document.getElementById('reportTep').innerHTML")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=15)

    assert not errors, errors
    body = table[table.index("<tbody>"):table.index("</tbody>")]
    foot = table[table.index("<tfoot>"):]
    # Строка и итог названы порознь: одна приписка на обе половины закрыла бы
    # проверку второй половины молча.
    assert "передано городу" in body, (
        "у строки переданные метры не названы — читается как «продано всё»")
    assert "передано городу" in foot, "итог таблицы молчит о переданном"


def test_the_print_names_the_transferred_metres():
    """Отчёт носят в банк, и расходиться с экраном ему нельзя."""
    pytest.importorskip("reportlab", reason="reportlab нужен только для PDF")
    from market_search.krt_requirements import pdf_text

    inputs = dict(core.DEFAULT_INPUTS)
    tep = _with_transfer()
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    data = core._build_developaid_pdf({
        "result": bundle["consolidated"], "project_name": "Передача городу",
        "inputs": inputs, "tep": tep,
    })
    assert data and len(data) > 20_000, "PDF не собрался"
    text = pdf_text(data)
    assert "Передаётся городу" in text, "колонка переданного не напечатана"
    assert "но не продаются" in text, "не сказано, что переданное не продаётся"


def test_without_a_transfer_the_print_keeps_the_short_table():
    """Постоянный столбец нулей — шум, а не полнота.

    На умолчаниях колонка стоит почти всегда, и это верно: садик передаётся
    городу целиком, то есть число в ней настоящее. Проверять надо проект, где
    передавать нечего вовсе — без соцобъектов.
    """
    pytest.importorskip("reportlab", reason="reportlab нужен только для PDF")
    from market_search.krt_requirements import pdf_text

    inputs = {**core.DEFAULT_INPUTS, "kindergarten_places": 0, "school_places": 0,
              "clinic_capacity": 0, "social_dou_gba_sqm": 0,
              "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0}
    tep = copy.deepcopy(core.TEP_DEFAULT)
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    given = sum(float(row.get("transfer") or 0)
                for row in bundle["consolidated"]["tep"]["rows"])
    assert given == 0, f"передавать нечего, а в строках {given} м²"
    data = core._build_developaid_pdf({
        "result": bundle["consolidated"], "project_name": "Без передачи",
        "inputs": inputs, "tep": tep,
    })
    text = pdf_text(data)
    assert "Передаётся городу" not in text


def test_the_social_object_is_named_as_transferred():
    """Соцобъект передаётся городу целиком — и в отчёте это сказано.

    Умолчания несут садик на 250 мест: его 4 500 м² строятся и не продаются,
    и до сих пор отчёт об этом молчал.
    """
    pytest.importorskip("reportlab", reason="reportlab нужен только для PDF")
    from market_search.krt_requirements import pdf_text

    inputs = dict(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    rows = {row["key"]: row for row in bundle["consolidated"]["tep"]["rows"]}
    assert float(rows["kindergarten"]["transfer"]) > 0, "садик не помечен переданным"
    data = core._build_developaid_pdf({
        "result": bundle["consolidated"], "project_name": "Садик городу",
        "inputs": inputs, "tep": tep,
    })
    assert "Передаётся городу" in pdf_text(data)
