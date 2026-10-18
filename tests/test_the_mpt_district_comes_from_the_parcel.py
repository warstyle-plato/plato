"""Льгота за МПТ на КРТ Нагатино считается сама: район и ТТК — из участка.

Владелец на проде 0.25.76: «По льготе ВРИ посмотрел проект Нагатино. Ну там
ничего явно не считается автоматически по льготе». Плата 10,17 млрд ₽, льгота
0, в карточке — «не хватает: район участка».

Причина: проект Нагатино собран из пресета. Пресет ставит номера участков в
поле участка и снимает ЕГРН, но разбор кадастра (ГлавАПУ) не запускает — ТЭП
пришёл из пресета, и штатный расчёт его бы перебил. А район и признак ТТК для
льготы (`site_position`) даёт только разбор. Номера у проекта есть, разбора
нет — и льгота выходила нулём до ручного выбора района.

Теперь страница, увидев причину «нет района/ТТК» при известных номерах,
спрашивает разбор сама, кладёт его в `_cadastral_analysis` и пересчитывает.

Второе на снимке: «Доля от суммы — 100» рядом с «Нет ручной» читалась как
льгота на всю плату. Поля доли и суммы теперь заперты и подписаны, когда
режим их не читает.

Ответ разбора — записанный ответ прода `/cadastral/analyze` по 20 номерам
Нагатино (15.10.2026): Нагатино-Садовники, за ТТК.

Запуск: python3 -m pytest tests/test_the_mpt_district_comes_from_the_parcel.py -q
"""

from __future__ import annotations

import copy
import json
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
ANALYSIS = json.loads((ROOT / "tests" / "fixtures" / "nagatino_cadastral_analysis.json")
                      .read_text("utf-8"))
NUMBERS = json.loads((ROOT / "scripts" / "prod_smoke_reference.json")
                     .read_text("utf-8"))["cadastral_numbers"]


@pytest.fixture(scope="module")
def core():
    import main as wrapper
    return wrapper.core


def _nagatino_as_saved(core):
    """Проект Нагатино, как он лежит у владельца: из пресета, КРТ, без разбора.

    Льгота — в старом формате: «Нет» и оставшиеся от прежнего выбора 100%.
    """
    import golden_snapshot
    case = golden_snapshot.s_nagatino(core, ROOT)
    inputs = dict(case["inputs"], vri_required=True, vri_region="msk",
                  social_area_source="manual", vri_relief_mode="none", vri_relief_pct=100,
                  land_rights_cost_mln=FEE_MLN, parking_district="", parking_inside_ttk="",
                  _cadastral_query=", ".join(NUMBERS))
    inputs.pop("_cadastral_analysis", None)
    inputs.pop("_glavapu_import", None)
    return inputs, case["tep"]


def _calc(core, inputs, tep):
    return core._calculate_economics(core.CalcRequest(inputs=inputs, tep=tep))


def test_the_recorded_analysis_is_the_nagatino_parcel() -> None:
    assert ANALYSIS["recognized"] == NUMBERS or sorted(ANALYSIS["recognized"]) == sorted(NUMBERS)
    assert ANALYSIS["territory"]["district"] == "Нагатино-Садовники"
    assert ANALYSIS["territory"]["inside_ttc"] is False
    assert ANALYSIS["territory"]["inside_ttc_known"] is True


def test_without_the_analysis_the_saved_project_has_no_district(core) -> None:
    """Так было на проде: номера есть, района нет — льгота 0 и причина."""
    inputs, tep = _nagatino_as_saved(core)
    result = _calc(core, inputs, tep)
    assert result["vri"]["totals"]["relief_basis"] == "project_benefits"
    assert result["vri"]["totals"]["relief"] == 0
    assert "район участка" in result["vri"]["benefits"]["mpt_reason"]


def test_the_parcel_analysis_gives_the_district_and_ttk_and_the_relief_counts(core) -> None:
    import site_position

    inputs, tep = _nagatino_as_saved(core)
    inputs["_cadastral_analysis"] = copy.deepcopy(ANALYSIS)
    place = site_position.site_position(inputs)
    assert place["district"] == "Нагатино-Садовники"
    assert place["inside_ttc"] is False
    assert place["district_source"] == site_position.ANALYSIS_DISTRICT_SOURCE

    result = _calc(core, inputs, tep)
    benefits, totals = result["vri"]["benefits"], result["vri"]["totals"]
    assert not benefits.get("mpt_reason"), benefits.get("mpt_reason")
    assert benefits["mpt_mln"] > 0
    # Старое «Нет»/100% — это «нет ручной»: действует посчитанная, а не доля.
    assert totals["relief_basis"] == "project_benefits"
    assert totals["relief"] == pytest.approx(min(FEE_MLN, benefits["total_mln"]) * 1e6, rel=1e-9)
    assert totals["amount"] == pytest.approx(totals["gross"] - totals["relief"], abs=1.0)


def test_the_page_asks_for_the_parcel_only_when_the_district_is_missing() -> None:
    import page_blocks

    def wanted(inputs: dict, benefits: dict, basis: str = "project_benefits") -> bool:
        prelude = ("let inputs=%s;let cadastralAnalysis=null;" % json.dumps(inputs, ensure_ascii=False))
        tail = "console.log(JSON.stringify(sitePositionWanted(%s,%s)));" % (
            json.dumps(benefits, ensure_ascii=False), json.dumps(basis))
        return page_blocks.run_json(prelude, tail)

    reason = {"mpt_reason": "не хватает: район участка"}
    base = {"vri_region": "msk", "_cadastral_query": NUMBERS[0]}
    assert wanted(base, reason) is True
    assert wanted(dict(base, _cadastral_analysis=ANALYSIS), reason) is False
    assert wanted(dict(base, parking_district="Нагатино-Садовники",
                       parking_inside_ttk="outside"), reason) is False
    assert wanted(base, {}) is False
    assert wanted(base, reason, "percent") is False
    assert wanted(dict(base, vri_region="mo"), reason) is False


def test_relief_share_and_sum_are_locked_when_the_mode_does_not_read_them() -> None:
    import page_blocks

    def idle(mode: str, field: str) -> str:
        prelude = "let inputs=%s;" % json.dumps({"vri_relief_mode": mode})
        return page_blocks.run_json(prelude, "console.log(JSON.stringify(vriReliefFieldIdle(%s)));"
                                    % json.dumps(field))

    assert "нет ручной" in idle("none", "vri_relief_pct")
    assert idle("percent", "vri_relief_pct") == ""
    assert "не применять" in idle("off", "vri_relief_mln")
    assert idle("amount", "vri_relief_mln") == ""
    assert idle("none", "vri_relief_mode") == ""


def test_in_a_real_browser_the_saved_nagatino_gets_the_relief_without_hand_input(core) -> None:
    """Сохранённый проект (старое «Нет»/100%, без района) → после загрузки МПТ посчитана."""
    from browser import chromium_or_skip, serve, wait_for_result
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_registry

    inputs, tep = _nagatino_as_saved(core)
    asked: list[str] = []
    seen: dict[str, object] = {}

    def analyze(route) -> None:
        asked.append(route.request.post_data or "")
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(ANALYSIS, ensure_ascii=False))

    with serve(main_registry.app, 18396) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.route("**/cadastral/analyze", analyze)
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("() => window.__developaidBooted", timeout=60000)
        # Проект лежит в браузере в старом формате — и открывается заново.
        page.evaluate(
            "([x,t]) => {Object.keys(inputs).forEach(k=>delete inputs[k]);Object.assign(inputs,x);"
            "Object.keys(tep).forEach(k=>delete tep[k]);Object.assign(tep,t);"
            "persistLocalSilently();}", [inputs, tep])
        page.reload(wait_until="networkidle")
        page.wait_for_function("() => window.__developaidBooted && lastResult && lastResult.vri",
                               timeout=60000)
        page.evaluate("() => openTab('vri')")
        page.wait_for_function("() => lastResult.vri.totals.relief>0", timeout=60000)
        wait_for_result(page)
        seen["totals"] = page.evaluate("() => lastResult.vri.totals")
        seen["benefits"] = page.evaluate(
            "() => ({mpt:lastResult.vri.benefits.mpt_mln,total:lastResult.vri.benefits.total_mln,"
            "reason:lastResult.vri.benefits.mpt_reason||''})")
        seen["district"] = page.evaluate(
            "() => ((inputs._cadastral_analysis||{}).territory||{}).district")
        seen["result"] = page.evaluate("() => document.getElementById('vriTabTotals').innerText")
        seen["pct_disabled"] = page.evaluate(
            "() => document.getElementById('f_vri_relief_pct').disabled")
        seen["pct_hint"] = page.evaluate(
            "() => (document.getElementById('f_vri_relief_pct').parentNode"
            ".querySelector('.vri-relief-idle')||{}).textContent||''")
        seen["mode"] = page.evaluate("() => document.getElementById('f_vri_relief_mode').value")
        # Повторный расчёт не спрашивает разбор второй раз.
        page.evaluate("() => settledCalculate()")
        browser.close()

    assert not errors, errors
    report = json.dumps(seen, ensure_ascii=False)
    totals = seen["totals"]
    assert len(asked) == 1, asked
    assert NUMBERS[0] in asked[0]
    assert seen["district"] == "Нагатино-Садовники", report
    assert totals["relief_basis"] == "project_benefits", report
    assert seen["benefits"]["mpt"] > 0 and not seen["benefits"]["reason"], report
    assert totals["relief"] == pytest.approx(
        min(totals["gross"], seen["benefits"]["total"] * 1e6), rel=1e-6), report
    assert totals["amount"] < totals["gross"], report
    assert "Льгота — автоматически по участку проекта" in seen["result"], report
    assert seen["mode"] == "none", report
    assert seen["pct_disabled"] is True and "Не читается" in seen["pct_hint"], report
