"""Тип проекта «Гостиница» — на отрисованной странице.

Мерится то, что видит человек: переключатель типа открывает своё окно и блок
«Гостиница», группы жилья пропадают, пустая гостиница называет недостающие
поля, а не рисует нули; кнопка ориентира заполняет поля и подписывает каждое
ячейкой книги; правка руками снимает подпись; карточка отчёта печатает ровно
то, что вернул движок на тех же вводных (отдельный запрос /calculate).

Запуск: python3 -m pytest tests/test_hotel_project_on_the_page.py -q
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18995

STATE = r"""() => {
  const card = document.getElementById('hotelReportCard');
  const notes = {};
  document.querySelectorAll('[data-field^="hotel_"]').forEach(w => {
    const n = w.querySelector('.hint');
    notes[w.dataset.field] = n ? {cls: n.className, text: n.textContent} : null;
  });
  return {
    groups: [...document.querySelectorAll('#inputGroups details[data-group]')].map(d => d.dataset.group),
    cardHidden: card.hidden,
    cardText: document.getElementById('hotelReportBody').textContent,
    rows: [...card.querySelectorAll('.hotel-kpi tbody tr')].map(tr => [...tr.cells].map(c => c.textContent.trim())),
    usaliYears: [...card.querySelectorAll('.hotel-usali thead th')].slice(1).map(th => th.textContent.trim()),
    usaliRevenue: [...card.querySelectorAll('.hotel-usali tr[data-key="revenue"] td')].slice(1).map(td => td.textContent.trim()),
    expected: lastResult.report.hotel && lastResult.report.hotel.rows
      ? lastResult.report.hotel.rows.map(r => [r.label, hotelCell(r)]) : [],
    tiles: [...document.querySelectorAll('#reportKpi .kpi span')].map(s => s.innerText.trim()),
    notes, inputs, tep,
    header: {
      hotelBox: getComputedStyle(document.getElementById('hotelClassBox')).display,
      classBox: getComputedStyle(document.getElementById('projectClassBox')).display,
      hotelClass: document.getElementById('hotelClassSelect').value,
      blockStars: (document.getElementById('h_hotel_stars') || {}).value,
    },
    params: [...document.querySelectorAll('#projectParamsTable tr')].map(tr => [...tr.cells].map(c => c.textContent.trim())),
    hotel: lastResult.report.hotel,
    hotelKeys: Object.keys(inputs).filter(k => k.startsWith('hotel_') && k !== 'hotel_origins'),
  };
}"""


def _post(base: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base.rstrip("/") + "/calculate", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


@pytest.fixture(scope="module")
def walk() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("() => typeof lastResult !== 'undefined' && lastResult")
            out["mixed"] = page.evaluate(STATE)
            page.evaluate("() => applyProjectKind('hotel')")
            out["dialog"] = page.evaluate(
                "() => [document.getElementById('projectKindDialogTitle').textContent,"
                " document.getElementById('projectKindDialog').style.display,"
                " document.getElementById('projectKindDialogBody').textContent]")
            page.evaluate("() => closeProjectKindDialog()")
            page.wait_for_function("() => lastResult.report && lastResult.report.hotel")
            out["empty"] = page.evaluate(STATE)
            page.evaluate(
                "() => document.querySelector('.hotel-preset[data-preset=dombai] button').click()")
            page.wait_for_function("() => lastResult.report.hotel && lastResult.report.hotel.computed")
            state = page.evaluate(STATE)
            state["engine"] = _post(base, {"inputs": state["inputs"], "tep": state["tep"],
                                           "rates": []})
            out["dombai"] = state
            page.evaluate("""() => {
              const el = document.getElementById('h_hotel_adr_rub');
              el.value = 25000; el.onchange();
            }""")
            # Ждём новый расчёт, а не только снятую подпись: подпись снимается
            # сразу, а результат приходит после запроса.
            page.wait_for_function(
                "before => lastResult.report.hotel && lastResult.report.hotel.computed"
                " && lastResult.report.hotel.rows.find(r => r.label === 'Выручка за срок').value !== before",
                arg=next(r["value"] for r in state["hotel"]["rows"] if r["label"] == "Выручка за срок"))
            out["manual"] = page.evaluate(STATE)
            # Класс из шапки — то же поле `hotel_stars`, что в блоке «Гостиница».
            page.evaluate("""() => {
              const s = document.getElementById('hotelClassSelect');
              s.value = '4'; s.onchange();
            }""")
            page.wait_for_function(
                "() => lastResult.report.project_class && lastResult.report.project_class.label === '4*'")
            out["stars"] = page.evaluate(STATE)
            page.evaluate("() => { applyProjectKind('mixed'); }")
            page.wait_for_function("() => !lastResult.report.hotel")
            out["back"] = page.evaluate(STATE)
            out["errors"] = errors
            page.close()
    return out


def test_the_kind_switch_opens_the_hotel_dialog(walk) -> None:
    title, display, body = walk["dialog"]
    assert title == "Гостиничный проект" and display == "flex"
    assert "блок «Гостиница»" in body and "льготный" in body
    assert walk["errors"] == []


def test_a_hotel_project_shows_the_hotel_block_instead_of_housing(walk) -> None:
    groups = walk["empty"]["groups"]
    assert groups[0] == "Гостиница"
    assert not {"Продажи", "Социальная нагрузка", "Подземный паркинг", "МФОЦ / офисы"} & set(groups)
    assert {"Сделка и сроки", "Строительство", "Финансирование"} <= set(groups)
    assert "Гостиница" not in walk["mixed"]["groups"]
    assert "Гостиница" not in walk["back"]["groups"]


def test_an_empty_hotel_names_what_is_missing_not_zeros(walk) -> None:
    state = walk["empty"]
    assert state["cardHidden"] is False
    assert state["hotel"]["computed"] is False
    assert "Гостиница не считается: не заданы" in state["cardText"]
    assert "ADR — средняя цена номера" in state["cardText"]
    # Пустые поля гостиницы не превращаются в нули: в вводных их нет вовсе.
    assert state["hotelKeys"] == []
    adr = state["notes"]["hotel_adr_rub"]
    assert "hotel-empty" in adr["cls"] and "Домбай 5*" in adr["text"] and "UAI 5*" in adr["text"]
    tax = state["notes"]["hotel_property_tax_pct"]
    assert "hotel-default" in tax["cls"] and "НК РФ" in tax["text"]


def test_the_preset_fills_fields_with_their_cells(walk) -> None:
    state = walk["dombai"]
    occ = state["notes"]["hotel_occ_start_pct"]
    assert "hotel-origin" in occ["cls"]
    assert occ["text"] == "ориентир: Домбай 5*, Предпосылки!E393"
    assert state["inputs"]["hotel_occ_start_pct"] == pytest.approx(47.0)
    assert state["inputs"]["hotel_origins"]["adr_rub"]["cells"]


def test_the_card_prints_what_the_engine_returned(walk) -> None:
    state = walk["dombai"]
    engine_rows = state["engine"]["report"]["hotel"]["rows"]
    assert [row[0] for row in state["rows"]] == [row["label"] for row in engine_rows]
    assert [row[1] for row in state["rows"]] == [cell for _, cell in state["expected"]]
    for shown, row in zip(state["hotel"]["rows"], engine_rows):
        if isinstance(row["value"], (int, float)):
            assert shown["value"] == pytest.approx(row["value"], rel=1e-9)
    years = state["engine"]["report"]["hotel"]["usali"]["years"]
    assert state["usaliYears"] == [str(y) for y in years]
    assert len(state["usaliRevenue"]) == len(years)
    assert "Кредит гостиницы — пик" in state["tiles"]
    assert "LLCR (расчётный)" not in state["tiles"]


def test_a_manual_edit_drops_the_origin(walk) -> None:
    state = walk["manual"]
    assert state["inputs"]["hotel_adr_rub"] == 25000
    assert "hotel-manual" in state["notes"]["hotel_adr_rub"]["cls"]
    # Остальные поля остались ориентиром.
    assert "hotel-origin" in state["notes"]["hotel_occ_start_pct"]["cls"]
    before = next(r for r in walk["dombai"]["hotel"]["rows"] if r["label"] == "Выручка за срок")
    after = next(r for r in state["hotel"]["rows"] if r["label"] == "Выручка за срок")
    assert after["value"] > before["value"]


def test_the_header_class_of_a_hotel_is_its_stars(walk) -> None:
    """Класс в шапке гостиничного проекта — звёздность, класс жилья спрятан;
    у жилого проекта — наоборот."""
    for name in ("empty", "dombai"):
        header = walk[name]["header"]
        assert header["hotelBox"] != "none" and header["classBox"] == "none", name
    assert walk["empty"]["header"]["hotelClass"] == ""
    assert walk["dombai"]["header"]["hotelClass"] == "5"
    for name in ("mixed", "back"):
        header = walk[name]["header"]
        assert header["hotelBox"] == "none" and header["classBox"] != "none", name


def test_the_key_parameters_name_the_stars_not_a_housing_class(walk) -> None:
    assert walk["empty"]["params"][0] == ["Класс гостиницы", "не задан"]
    params = walk["dombai"]["params"]
    assert params[0] == ["Класс гостиницы", "5*"]
    labels = [row[0] for row in params]
    # Метры продаваемой площади и цена квартир у гостиницы были бы нулями.
    assert not {"Продаваемая площадь", "Средняя цена м² квартир", "EBITDA на метр",
                "Строительство соцобъектов", "Социальная компенсация"} & set(labels)
    keys = walk["dombai"]["hotel"]["rows"]
    rooms = next(r for r in keys if r["label"] == "Номерной фонд")["value"]
    assert ["Номерной фонд", f"{rooms:,.0f}".replace(",", "\u00a0")] in params
    for name in ("mixed", "back"):
        assert walk[name]["params"][0] == ["Класс проекта", "Комфорт"], name


def test_the_header_class_edits_the_hotel_field(walk) -> None:
    state = walk["stars"]
    assert state["inputs"]["hotel_stars"] == "4"
    assert state["header"]["hotelClass"] == "4" and state["header"]["blockStars"] == "4"
    assert "hotel-manual" in state["notes"]["hotel_stars"]["cls"]
    assert state["params"][0] == ["Класс гостиницы", "4*"]

