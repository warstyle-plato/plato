"""Льготы по плате за ВРИ считаются по проекту, а не по флажку.

Владелец, 06.10.2026: «наш блок льготы должен обязательно её считать, если
включены объекты нежилья, а не опционно, и предлагать добавить её в расчёт
ВРИ суммой; и показывать количество создаваемых рабочих мест, как
калькулятор». Калькулятор ГлавАПУ даёт льготу за МПТ сам (1874-ПП) и льготу
за передачу квартир городу — галочкой; обе срезают плату за МКД.

Правило льготы за МПТ объявлено один раз — `mpt_calculator`; рабочие места —
по нормам калькулятора (лист «МПТ»), сверены с его выгрузкой до единицы.

Запуск: python3 -m pytest tests/test_vri_benefits_are_counted_for_the_project.py -q
"""

from __future__ import annotations

import copy
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "DEVELOPAID_WORKBOOK_CACHE",
             "NORMATIVES_WATCH", "NAGATINO_EGRN_READ"):
    os.environ.setdefault(_key, "0")

import mpt_calculator  # noqa: E402
import project_preset  # noqa: E402
import vri_benefits as vb  # noqa: E402

TODAY = date(2026, 10, 6)
OUTSIDE = {"recognized": ["77:05:0004001:1"],
           "territory": {"district": "Нагатино-Садовники", "inside_ttc": False,
                         "cadastral_quarter": "77:05:0004001"}}
OBJECTS = [{"key": "offices", "product": "offices", "label": "Офисы", "enabled": True},
           {"key": "standalone_retail", "product": "standalone_retail", "label": "ТЦ",
            "enabled": True}]


def _nagatino():
    preview = project_preset.build_preview(
        json.loads((ROOT / "presets" / "КРТ_Нагатино.json").read_text(encoding="utf-8")))
    inputs = dict(preview["inputs"], _cadastral_analysis=copy.deepcopy(OUTSIDE))
    return inputs, preview["tep"]


def test_every_non_residential_object_gets_its_relief_and_jobs() -> None:
    inputs, tep = _nagatino()
    got = vb.compute(inputs, tep, OBJECTS, today=TODAY)
    rows = {r["key"]: r for r in got["rows"]}
    kzatr = mpt_calculator.kzatr_for_quarter("2026-Q4")
    office = rows["offices"]
    assert office["kmest"] == 0.7 and "Нагатино-Садовники" in office["kmest_source"]
    assert office["benefit_mln"] == pytest.approx(
        1000 * office["area_sqm"] * kzatr * 0.7 / 1e6, rel=1e-6)
    assert office["jobs"] == int(office["area_sqm"] // 32)
    assert rows["standalone_retail"]["jobs"] == int(rows["standalone_retail"]["area_sqm"] // 45)
    # Встроенная коммерция: места есть, льготы нет — и сказано почему.
    built_in = rows["ground_commercial"]
    assert built_in["benefit_mln"] == 0 and built_in["jobs"] > 0
    assert "встроенные помещения" in built_in["blockers"][0]
    # Соцобъекты: Кмест 0,3, места — на 1000 мест.
    assert rows["school"]["kmest"] == 0.3 and rows["school"]["jobs"] == 118
    assert got["total_mln"] == pytest.approx(sum(r["benefit_mln"] for r in got["rows"]), abs=0.01)
    assert got["jobs_total"] == sum(r["jobs"] for r in got["rows"])
    assert got["suggestion"]["amount_mln"] == got["total_mln"]
    assert got["suggestion"]["applied"] is False


def test_jobs_follow_the_calculator_norms() -> None:
    """Лист «МПТ» калькулятора по Нагатино: офис 2 611, ТЦ 1 856 при НП 83 560,5 м²."""
    tep = {"offices": {"gns": 92845.0, "total_area": 83560.5},
           "standalone_retail": {"gns": 92845.0, "total_area": 83560.5}}
    got = vb.compute({"_cadastral_analysis": OUTSIDE}, tep, OBJECTS, today=TODAY)
    jobs = {r["key"]: r["jobs"] for r in got["rows"]}
    assert jobs == {"offices": 2611, "standalone_retail": 1856}


def test_inside_ttk_blocks_the_mpt_relief_but_keeps_jobs() -> None:
    inputs, tep = _nagatino()
    inputs["_cadastral_analysis"]["territory"]["inside_ttc"] = True
    got = vb.compute(inputs, tep, OBJECTS, today=TODAY)
    office = next(r for r in got["rows"] if r["key"] == "offices")
    assert office["benefit_mln"] == 0 and office["jobs"] > 0
    assert any("ТТК" in b for b in office["blockers"])


def test_unknown_place_is_named_not_assumed() -> None:
    """Нет района или ТТК — отказ называет недостающее, а не считает «вне ТТК»."""
    inputs, tep = _nagatino()
    inputs.pop("_cadastral_analysis")
    inputs.pop("_glavapu_import", None)
    got = vb.compute(inputs, tep, OBJECTS, today=TODAY)
    office = next(r for r in got["rows"] if r["key"] == "offices")
    assert office["benefit_mln"] == 0 and "нет района" in office["blockers"][0]
    inputs["_cadastral_analysis"] = {"territory": {"district": "Нагатино-Садовники"}}
    got = vb.compute(inputs, tep, OBJECTS, today=TODAY)
    office = next(r for r in got["rows"] if r["key"] == "offices")
    assert "ТТК" in office["blockers"][0]


def test_a_disabled_object_is_not_counted() -> None:
    inputs, tep = _nagatino()
    objects = [dict(OBJECTS[0], enabled=False), OBJECTS[1]]
    keys = {r["key"] for r in vb.compute(inputs, tep, objects, today=TODAY)["rows"]}
    assert "offices" not in keys and "standalone_retail" in keys


def test_flats_passed_to_the_city_give_the_calculator_relief() -> None:
    """Калькулятор: 10 тыс. м² × 190,46 = 1 904,6 млн ₽ (прогон его кода)."""
    inputs, tep = _nagatino()
    tep = copy.deepcopy(tep)
    tep["apartments"]["transfer"] = 10000.0
    got = vb.compute(inputs, tep, OBJECTS, today=TODAY)
    assert got["transfer_mln"] == pytest.approx(1904.6)
    assert got["total_mln"] == pytest.approx(got["mpt_mln"] + 1904.6, abs=0.001)


def test_moscow_oblast_has_no_moscow_relief() -> None:
    inputs, tep = _nagatino()
    got = vb.compute(dict(inputs, vri_region="mo"), tep, OBJECTS, today=TODAY)
    assert got["applicable"] is False and "московские" in got["reason"]


def test_the_applied_amount_is_recognised() -> None:
    inputs, tep = _nagatino()
    first = vb.compute(inputs, tep, OBJECTS, today=TODAY)
    inputs = dict(inputs, vri_relief_mode="amount", vri_relief_mln=first["total_mln"])
    assert vb.compute(inputs, tep, OBJECTS, today=TODAY)["suggestion"]["applied"] is True


# ------------------------------------------------------------------ движок --

@pytest.fixture(scope="module")
def core():
    import main as wrapper
    return wrapper.core


def _calc(core, inputs, tep):
    return core._calculate_economics(core.CalcRequest(inputs=inputs, tep=tep))


def test_the_engine_hands_the_benefits_out_without_changing_the_economics(core) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import golden_snapshot
    case = golden_snapshot.s_nagatino(core, ROOT)
    inputs = dict(case["inputs"], land_rights_cost_mln=5000.0, vri_required=True,
                  _cadastral_analysis=copy.deepcopy(OUTSIDE))
    tep = case["tep"]
    result = _calc(core, inputs, tep)
    benefits = result["vri"]["benefits"]
    assert benefits["applicable"] and benefits["total_mln"] > 0 and benefits["jobs_total"] > 0
    # Предложение, а не решение: льгота в экономику не вошла.
    assert result["vri"]["totals"]["relief"] == 0
    applied = dict(inputs, vri_relief_mode="amount", vri_relief_mln=1200.0)
    after = _calc(core, applied, tep)
    assert after["vri"]["totals"]["relief"] == pytest.approx(1200.0 * 1e6)


def test_a_broken_benefit_is_named_with_its_place(core, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("сломалось")
    monkeypatch.setattr(core.vri_benefits, "compute", boom)
    got = core.vri_benefits_for({}, {})
    assert got["applicable"] is False and "сломалось" in got["reason"]
    assert "test_vri_benefits_are_counted_for_the_project.py" in got["reason"]


# ---------------------------------------------------------------- страница --

def test_the_page_draws_the_table_and_the_button_writes_the_relief(core) -> None:
    import page_blocks

    inputs, tep = _nagatino()
    benefits = vb.compute(inputs, tep, OBJECTS, today=TODAY)
    prelude = ("let inputs={vri_relief_mode:'none',vri_relief_mln:0};"
               "let lastResult={vri:{benefits:%s}};let calls=[];"
               "function renderInputs(){calls.push('renderInputs')}"
               "function refreshGroupPeeks(){calls.push('peeks')}"
               "function calculate(){calls.push('calculate')}"
               % json.dumps(benefits, ensure_ascii=False))
    tail = ("const html=vriBenefitsHtml(lastResult.vri.benefits);applyVriBenefits();"
            "const note=vriReliefSourceNote();inputs.vri_relief_mln+=1;"
            "console.log(JSON.stringify({html,inputs,calls,note,stale:vriReliefSourceNote()}));")
    out, _ = page_blocks.run(prelude, tail)
    got = json.loads(out)
    html = got["html"]
    for text in ("Рабочие места", "Кмест", "Офисы", "ТЦ", "встроенные помещения",
                 "Добавить в расчёт ВРИ суммой", "1874-ПП"):
        assert text in html, text
    assert 'onclick="applyVriBenefits()"' in html
    # Кнопка вписала сумму режимом «Фиксированная сумма» и отметила источник.
    assert got["inputs"]["vri_relief_mode"] == "amount"
    assert got["inputs"]["vri_relief_mln"] == pytest.approx(benefits["total_mln"] + 1)
    assert got["inputs"]["_vri_relief_source"]["value"] == pytest.approx(benefits["total_mln"])
    assert got["calls"] == ["renderInputs", "peeks", "calculate"]
    assert "посчитанные по проекту" in got["note"]
    # Сумму правили руками — отметка «посчитано» больше не про неё.
    assert got["stale"] == ""


def test_the_vri_tab_has_the_card_before_the_result() -> None:
    import main_legacy as legacy
    page = legacy.PAGE
    vri = page.index('<div id="vri" class="panel">')
    card = page.index('id="vriBenefitsCard"')
    result = page.index('id="vriTabCard"')
    assert vri < card < result
