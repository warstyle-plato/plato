"""Льгота за МПТ (1874-ПП) считается из данных проекта и сразу уменьшает плату за ВРИ.

Владелец на проде 0.25.73: «Ничего не пересчиталось после того как убрал
льготу. МПТ не считается автоматом». Московский проект с офисами, ручная
льгота сменена со 100% на «Нет», плата за ВРИ 10,17 млрд ₽ — без льготы.
Причин было три:

- расчётная льгота шла в плату только в режиме «Требование КРТ», а «Нет»
  вне КРТ значило «никакой льготы» — отсутствие ручного ввода читалось как
  отказ (решение владельца 14.10.2026: во всех московских проектах; «Нет» —
  «нет ручной», отказ — отдельный режим);
- у проекта не было района: поля «Район участка» не было вовсе, район давал
  только разбор кадастра, и льгота молча выходила нулём;
- при льготе 100% «к оплате 0» прятало весь блок «Результат».

Плюс калькулятор по ДРУГОМУ участку: «Рассчитать и применить» заменяет
посчитанную по участку проекта льготу за МПТ (решение владельца 14.10.2026),
«Снять» возвращает её. Значение хранится вводными калькулятора и
пересчитывается движком — с происхождением, а не замороженным числом.

Запуск: python3 -m pytest tests/test_the_mpt_relief_counts_itself.py -q
"""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
for _key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "DEVELOPAID_WORKBOOK_CACHE",
             "NORMATIVES_WATCH", "NAGATINO_EGRN_READ"):
    os.environ.setdefault(_key, "0")

FEE_MLN = 10170.0
OTHER_PARCEL = {"category": "office", "district": "Хорошево-Мневники", "area_sqm": 20000.0,
                "mode": "new", "ttk_position": "outside", "cadastral_number": "",
                "kzatr": 166.23078, "kterm": 1.0}


@pytest.fixture(scope="module")
def core():
    import main as wrapper
    return wrapper.core


def _calc(core, inputs, tep):
    return core._calculate_economics(core.CalcRequest(inputs=inputs, tep=tep))


def _moscow_offices(core, **changes):
    """Нагатино вне режима КРТ: офисы и ТЦ, Москва, ручной льготы нет, района нет."""
    import golden_snapshot
    case = golden_snapshot.s_nagatino(core, ROOT)
    inputs = dict(case["inputs"], vri_required=True, vri_region="msk",
                  social_area_source="norm", vri_relief_mode="none",
                  land_rights_cost_mln=FEE_MLN)
    inputs.pop("_cadastral_analysis", None)
    inputs.pop("_glavapu_import", None)
    inputs.update(changes)
    return inputs, case["tep"]


def test_a_moscow_project_with_offices_gets_the_mpt_relief_without_a_hand_relief(core) -> None:
    inputs, tep = _moscow_offices(core, parking_district="Нагатино-Садовники",
                                  parking_inside_ttk="outside")
    result = _calc(core, inputs, tep)
    benefits = result["vri"]["benefits"]
    totals = result["vri"]["totals"]
    assert benefits["mpt_mln"] > 0, benefits.get("mpt_reason")
    assert totals["relief_basis"] == "project_benefits"
    expected = min(FEE_MLN, benefits["total_mln"]) * 1e6
    assert totals["relief"] == pytest.approx(expected, rel=1e-9)
    assert result["capex"]["land_rights"] == pytest.approx(FEE_MLN * 1e6 - expected, abs=1.0)
    assert totals["relief_source"] == "автоматически по участку проекта"


def test_the_district_typed_in_the_project_is_the_one_the_relief_reads(core) -> None:
    """Поле «Район участка» — то же `site_position`, что у нормы парковки."""
    assert "parking_district" in core.SITE_ONLY_INPUTS
    fields = {f[0]: f for group in core.FIELD_GROUPS for f in group[1]}
    options = [value for value, _ in fields["parking_district"][4]]
    assert options[0] == "" and "Нагатино-Садовники" in options
    inputs, tep = _moscow_offices(core, parking_district="Нагатино-Садовники",
                                  parking_inside_ttk="outside")
    territory = _calc(core, inputs, tep)["vri"]["benefits"]["territory"]
    assert territory["district"] == "Нагатино-Садовники"
    assert territory["district_source"] == "вписано в проекте"


def test_without_a_district_the_reason_is_named_in_the_result(core) -> None:
    inputs, tep = _moscow_offices(core)
    result = _calc(core, inputs, tep)
    benefits = result["vri"]["benefits"]
    assert benefits["mpt_mln"] == 0
    assert "район участка" in benefits["mpt_reason"]
    assert "Район участка" in benefits["mpt_reason"], "причина называет поле, где это взять"
    warnings = result["vri"].get("warnings") or []
    assert any("Льгота за МПТ" in w and "район участка" in w for w in warnings), warnings


def test_an_unknown_ttk_position_is_named_too(core) -> None:
    inputs, tep = _moscow_offices(core, parking_district="Нагатино-Садовники")
    benefits = _calc(core, inputs, tep)["vri"]["benefits"]
    assert benefits["mpt_mln"] == 0
    assert "положение участка относительно ТТК" in benefits["mpt_reason"]


def test_the_kzatr_quarter_follows_the_vri_obligation_date(core) -> None:
    inputs, tep = _moscow_offices(core, parking_district="Нагатино-Садовники",
                                  parking_inside_ttk="outside", vri_obligation_date="2026-08-15")
    kzatr = _calc(core, inputs, tep)["vri"]["benefits"]["kzatr"]
    assert kzatr["obligation_quarter"] == "2026-Q3"
    assert kzatr["quarter"] == "2026-Q3"
    later = dict(inputs, vri_obligation_date="2028-02-01")
    benefits = _calc(core, later, tep)["vri"]["benefits"]
    assert benefits["kzatr"]["obligation_quarter"] == "2028-Q1"
    # Кзатр 2028 года не опубликован: берётся последний опубликованный — и это сказано.
    assert benefits["kzatr"]["quarter"] != "2028-Q1"
    assert any("2028-Q1" in note and "не опубликован" in note for note in benefits["notes"])


def test_the_calculator_for_another_parcel_replaces_the_project_relief(core) -> None:
    import mpt_calculator

    base, tep = _moscow_offices(core, parking_district="Нагатино-Садовники",
                                parking_inside_ttk="outside")
    auto = _calc(core, base, tep)["vri"]["benefits"]
    override = {"payload": dict(OTHER_PARCEL), "cadastral": "77:08:0009005:12",
                "address": "Москва, Хорошёвское ш.", "applied_at": "2026-10-14T09:00:00Z"}
    result = _calc(core, dict(base, vri_mpt_override=override), tep)
    benefits = result["vri"]["benefits"]
    direct = mpt_calculator.calculate_mpt_benefit(mpt_calculator.MptInput(**OTHER_PARCEL))
    assert benefits["mpt_mln"] == pytest.approx(direct.benefit_rub / 1e6, abs=1e-3)
    assert benefits["mpt_mln"] != pytest.approx(auto["mpt_mln"])
    assert benefits["auto_mpt_mln"] == pytest.approx(auto["mpt_mln"])
    assert benefits["mpt_source"] == {"kind": "calculator",
                                      "text": "из калькулятора по участку 77:08:0009005:12"}
    totals = result["vri"]["totals"]
    assert totals["relief"] == pytest.approx(
        min(FEE_MLN, benefits["mpt_mln"] + benefits["transfer_mln"]) * 1e6, rel=1e-9)
    assert totals["relief_source"] == "из калькулятора по участку 77:08:0009005:12"
    # Снять — значит убрать вводную: возвращается посчитанная по участку проекта.
    back = _calc(core, base, tep)["vri"]["totals"]
    assert back["relief"] == pytest.approx(min(FEE_MLN, auto["total_mln"]) * 1e6, rel=1e-9)


def test_a_broken_calculator_input_is_named_not_zeroed_silently(core) -> None:
    base, tep = _moscow_offices(core)
    bad = {"payload": dict(OTHER_PARCEL, area_sqm=0), "cadastral": "77:08:0009005:12"}
    benefits = _calc(core, dict(base, vri_mpt_override=bad), tep)["vri"]["benefits"]
    assert benefits["override"]["error"]
    assert any("калькулятора МПТ не пересчитана" in n for n in benefits["notes"])


def test_moscow_oblast_has_no_project_relief(core) -> None:
    inputs, tep = _moscow_offices(core, vri_region="mo")
    totals = _calc(core, inputs, tep)["vri"]["totals"]
    assert totals["relief_basis"] == "none"
    assert totals["relief"] == 0


def test_a_full_relief_keeps_the_result_block_on_the_page() -> None:
    """«К оплате 0» не прячет «Результат»: до льготы − льгота = 0 видно."""
    import json

    import page_blocks
    vri = {"enabled": False, "region": "msk", "payment_mode": "lump", "rows": [], "warnings": [],
           "settings": {}, "benefits": None,
           "totals": {"gross": 10170e6, "relief": 10170e6, "amount": 0.0, "relief_basis": "percent"}}
    prelude = ("let inputs={};let lastResult={summary:{}};"
               "function renderVriBenefits(){} function renderKrtVriFooter(){} const window={};"
               "const nodes={};const document={getElementById:id=>"
               "(nodes[id]=nodes[id]||{id,style:{display:'x'},innerHTML:'',textContent:''})};")
    tail = ("renderVri(%s);"
            "console.log(JSON.stringify({card:nodes.vriTabCard.style.display,"
            "empty:nodes.vriTabEmpty.style.display,note:nodes.vriTabEmptyNote.textContent,"
            "text:nodes.vriTabTotals.innerHTML}));"
            % json.dumps(vri))
    out, _ = page_blocks.run(prelude, tail)
    got = json.loads(out)
    # Итоги видны, а строка под ними говорит, что плату сняла льгота, а не
    # «изменение не требуется» (владелец, 15.10.2026).
    assert got["card"] == "" and got["empty"] == "", got
    assert "снята льготой полностью" in got["note"] and "не требуется" not in got["note"], got
    assert "Обязательство до льготы" in got["text"] and "Льгота" in got["text"], got


def test_in_a_real_browser_the_relief_recounts_applies_survives_a_reload_and_clears(core) -> None:
    """Страница владельца: 100% → «Нет ручной» → калькулятор по другому участку → снять."""
    import json

    from browser import chromium_or_skip, serve
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import golden_snapshot
    import main_registry  # боевое приложение: калькулятор МПТ ставится им

    case = golden_snapshot.s_nagatino(core, ROOT)
    inputs = dict(case["inputs"], vri_required=True, vri_region="msk", social_area_source="norm",
                  land_rights_cost_mln=40000.0, parking_district="Нагатино-Садовники",
                  parking_inside_ttk="outside", vri_relief_mode="percent", vri_relief_pct=100)
    inputs.pop("_cadastral_analysis", None)
    inputs.pop("_glavapu_import", None)
    totals = "() => document.getElementById('vriTabTotals').innerText"
    seen: dict[str, object] = {}
    with serve(main_registry.app, 18394) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("() => window.__developaidBooted", timeout=60000)
        page.evaluate(
            "([x,t]) => {Object.keys(inputs).forEach(k=>delete inputs[k]);Object.assign(inputs,x);"
            "Object.keys(tep).forEach(k=>delete tep[k]);Object.assign(tep,t);"
            "renderInputs();calculate();openTab('vri');}", [inputs, case["tep"]])
        page.wait_for_function(
            "() => lastResult && lastResult.vri.totals.relief_basis==='percent'", timeout=60000)
        seen["full_visible"] = page.locator("#vriTabCard").is_visible()
        seen["full"] = page.evaluate(totals)
        # Владелец меняет 100% на «Нет» — тем же обработчиком поля, что и рукой.
        page.evaluate("() => {const el=document.getElementById('f_vri_relief_mode');"
                      " el.value='none'; el.onchange();}")
        page.wait_for_function(
            "() => lastResult.vri.totals.relief_basis==='project_benefits'", timeout=60000)
        seen["auto"] = page.evaluate(totals)
        seen["auto_relief"] = page.evaluate("() => lastResult.vri.totals.relief")
        # Калькулятор по другому участку: «Рассчитать и применить к плате за ВРИ».
        page.evaluate("() => {const d=document.getElementById('mpt-benefit-panel');"
                      " d.open=true; d.scrollIntoView();}")
        page.select_option("#mpt-category", "office")
        page.select_option("#mpt-district", "Хорошево-Мневники")
        page.select_option("#mpt-ttk", "outside")
        page.fill("#mpt-area", "20000")
        page.fill("#mpt-cadastral", "77:08:0009005:12")
        page.click("#mpt-apply")
        page.wait_for_function(
            "() => (lastResult.vri.benefits.mpt_source||{}).kind==='calculator'", timeout=60000)
        page.wait_for_timeout(300)
        seen["applied"] = page.evaluate(totals)
        seen["applied_relief"] = page.evaluate("() => lastResult.vri.totals.relief")
        seen["applied_box"] = page.locator("#mpt-applied").inner_text()
        # Применённая живёт в проекте и переживает перезагрузку.
        page.reload(wait_until="networkidle")
        page.wait_for_function("() => window.__developaidBooted && lastResult && lastResult.vri",
                               timeout=60000)
        seen["reloaded"] = page.evaluate(
            "() => [!!inputs.vri_mpt_override, (lastResult.vri.benefits.mpt_source||{}).kind]")
        page.evaluate("() => {openTab('vri');"
                      " document.getElementById('mpt-benefit-panel').open=true;}")
        page.click("#mpt-clear")
        page.wait_for_function(
            "() => (lastResult.vri.benefits.mpt_source||{}).kind==='auto'", timeout=60000)
        seen["cleared"] = page.evaluate(totals)
        seen["cleared_relief"] = page.evaluate("() => lastResult.vri.totals.relief")
        # Без района — причина видна в «Результате», а не только в строке таблицы.
        page.evaluate("() => {inputs.parking_district=''; calculate();}")
        page.wait_for_function(
            "() => lastResult.vri.totals.relief===0", timeout=60000)
        seen["missing_visible"] = page.locator("#vriTabWarnings").is_visible()
        seen["missing"] = page.locator("#vriTabWarnings").inner_text()
        browser.close()

    assert not errors, errors
    report = json.dumps(seen, ensure_ascii=False)
    assert seen["full_visible"], "при льготе 100% блок «Результат» спрятан"
    assert "Обязательство до льготы" in seen["full"] and "Сумма обязательства\t0" in seen["full"], report
    assert seen["auto_relief"] > 0, report
    assert "Льгота — автоматически по участку проекта" in seen["auto"], report
    assert "Льгота — из калькулятора по участку 77:08:0009005:12" in seen["applied"], report
    assert seen["applied_relief"] != seen["auto_relief"], report
    assert "Заменяет посчитанную" in seen["applied_box"], report
    assert seen["reloaded"] == [True, "calculator"], report
    assert "Льгота — автоматически по участку проекта" in seen["cleared"], report
    assert seen["cleared_relief"] == seen["auto_relief"], report
    assert seen["missing_visible"] and "не хватает: район участка" in seen["missing"], report


def test_the_book_takes_the_same_relief_and_names_where_the_mpt_came_from(core) -> None:
    """Книга: B82 — льгота движка (авто и из калькулятора), подпись — её источник."""
    import io

    import openpyxl
    import v4_inputs

    base, tep = _moscow_offices(core, parking_district="Нагатино-Садовники",
                                parking_inside_ttk="outside", land_rights_cost_mln=40000.0)
    override = {"payload": dict(OTHER_PARCEL), "cadastral": "77:08:0009005:12"}
    for inputs, words in ((base, "Льготы проекта: МПТ автоматически по участку проекта"),
                          (dict(base, vri_mpt_override=override),
                           "Льготы проекта: МПТ из калькулятора по участку 77:08:0009005:12")):
        engine = _calc(core, inputs, tep)["vri"]["totals"]["relief"] / 1e6
        assert engine > 0
        data, _name, _meta = core.build_project_workbook(inputs, tep, [], {}, project_name="проба")
        book = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
        assert float(v4_inputs.value(book, "B82")) == pytest.approx(engine, rel=1e-6)
        texts = {cell.value for sheet in book.worksheets for row in sheet.iter_rows()
                 for cell in row if isinstance(cell.value, str)}
        assert words in texts, words
