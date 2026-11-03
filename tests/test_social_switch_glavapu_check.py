"""Переключатель населения для соцобъектов на московском проекте с выгрузкой ГлавАПУ.

Прод 0.26.39 (владелец, 19.10.2026): при любом способе подсчёта жителей под
переключателем стояло «Места соцобъектов не пересчитаны … (приобъектные
машино-места: 17 против 16)», и места ДОО, школы и поликлиники не менялись.
Самопроверка пересчёта сверяла с выгрузкой и машино-места, которые
переключатель не трогает, а приобъектные валились на округлении печатной НП:
СПП встроенных × 0,9 дробная (1 695 × 0,9 = 1 525,5), выгрузка печатает её
целыми метрами (1 526), и ⌈ставка × 1 526⌉ даёт на место больше города.

Правило: переключатель читает вердикт только соцполовины сверки
(`social_matches_baseline`), а расхождение на границе округления входа — не
расхождение. Настоящее расхождение по соцобъектам — отказ простыми словами.

Запуск: python3 -m pytest tests/test_social_switch_glavapu_check.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser import chromium_or_skip, serve, wait_for_result  # noqa: E402

import main_legacy as core  # noqa: E402

PORT = 19817
ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "docs" / "projects" / "77_01_0006018_75_2026-09-09.json"


def _snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text("utf-8"))


def _baseline() -> dict:
    return dict(_snapshot()["inputs"]["_glavapu_import"]["normalized"])


def _areas(baseline: dict) -> dict:
    return {"apartment_area_sqm": baseline["apartment_area_sqm"],
            "residential_living_spp_sqm": baseline["residential_spp_sqm"],
            "ground_commercial_spp_sqm": baseline["ground_commercial_spp_sqm"],
            "apartment_count": baseline["apartment_units"]}


# Печатная НП встроенных округлена вверх: 1 695 × 0,9 = 1 525,5 → 1 526.
ROUNDED_UP = {"ground_commercial_spp_sqm": 1695.0, "ground_commercial_np_sqm": 1526.0}


def test_the_printed_area_rounding_is_not_a_mismatch() -> None:
    baseline = dict(_baseline(), **ROUNDED_UP)
    out = core.recalculate_from_glavapu_baseline(baseline, _areas(baseline))
    attached = next(x for x in out["self_check"]["checked"] if "приобъектные" in x["name"])
    # Без допуска формула на печатной НП даёт на место больше города.
    assert attached["recalculated"] == attached["baseline"] + 1, attached
    assert attached.get("within_rounding") is True
    assert out["self_check"]["matches_baseline"], out["self_check"]["mismatch"]


def test_a_parking_mismatch_does_not_block_the_social_half() -> None:
    """Не та строка НП — расхождение машино-мест, но соцполовина цела."""
    baseline = dict(_baseline(), ground_commercial_np_sqm=20000.0)
    check = core.recalculate_from_glavapu_baseline(baseline, _areas(baseline))["self_check"]
    assert not check["matches_baseline"]
    assert check["mismatch_by_scope"]["parking"] and not check["mismatch_by_scope"]["social"]
    assert check["social_matches_baseline"] is True


def test_a_social_mismatch_is_named_in_its_half() -> None:
    baseline = dict(_baseline(), required_kindergarten_places=30.0)
    check = core.recalculate_from_glavapu_baseline(baseline, _areas(baseline))["self_check"]
    assert check["social_matches_baseline"] is False
    assert any("места ДОО" in line for line in check["mismatch_by_scope"]["social"])


_SWITCH = """async ([data, patch])=>{
  Object.assign(data.inputs._glavapu_import.normalized, patch);
  applyProjectSnapshot(data);
  const wait=()=>new Promise(r=>setTimeout(r,100));
  for(let i=0;i<30&&!glavapuBaselineApplies();i++)await wait();
  syncTep(false);renderInputs();
  const keys=['kindergarten_places','school_places','clinic_capacity','underground_manual_spaces'];
  const before=Object.fromEntries(keys.map(k=>[k,inputs[k]]));
  const live=document.getElementById('f_social_population_method');
  live.value='flats_household';live.dispatchEvent(new Event('change'));
  const note=()=>(document.getElementById('socialPopulationNote')||{}).textContent||'';
  for(let i=0;i<60&&(!note()||note().startsWith('Пересчитываю'));i++)await wait();
  openTab('inputs');
  const group=document.querySelector('details[data-group="Социальная нагрузка"]');
  if(group)group.open=true;
  return {before,after:Object.fromEntries(keys.map(k=>[k,inputs[k]])),note:note(),
          field:document.getElementById('f_kindergarten_places').value};
}"""


def _switch(patch: dict) -> dict:
    """Настоящая страница на ширине телефона, снимок проекта с выгрузкой ГлавАПУ."""
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    from main_registry import app as registry_app  # noqa: PLC0415

    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 390, "height": 844})
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(f"{base}/", wait_until="domcontentloaded")
            wait_for_result(tab)
            got = tab.evaluate(_SWITCH, [_snapshot(), patch])
            got["note_visible"] = tab.locator("#socialPopulationNote").is_visible()
        finally:
            browser.close()
    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    return got


def test_the_switch_moves_the_places_when_the_printed_area_rounds_up() -> None:
    got = _switch(ROUNDED_UP)
    assert "не пересчитаны" not in got["note"], got["note"]
    for key in ("kindergarten_places", "school_places", "clinic_capacity"):
        assert got["after"][key] != got["before"][key], (key, got)
    assert got["field"] == str(got["after"]["kindergarten_places"])
    # Машино-места переключатель не трогает.
    assert got["after"]["underground_manual_spaces"] == got["before"]["underground_manual_spaces"]
    assert got["note_visible"] and "Пересчитано: места ДОО" in got["note"]


def test_a_real_social_mismatch_refuses_in_plain_words() -> None:
    got = _switch({"required_kindergarten_places": 30.0})
    for key in ("kindergarten_places", "school_places", "clinic_capacity"):
        assert got["after"][key] == got["before"][key], (key, got)
    note = got["note"]
    assert got["note_visible"] and note.startswith("Места соцобъектов не пересчитаны"), note
    assert "места ДОО" in note and "впишите" in note
    for jargon in ("ставк", "воспроизвод", "машино-мест"):
        assert jargon not in note, (jargon, note)


def test_a_parking_mismatch_does_not_stop_the_switch() -> None:
    """Пересчёт ТЭП на такой выгрузке откажет, а переключатель — нет: машино-места не его."""
    got = _switch({"ground_commercial_np_sqm": 20000.0})
    assert "не пересчитаны" not in got["note"], got["note"]
    assert got["after"]["kindergarten_places"] != got["before"]["kindergarten_places"], got


# --- Режим «Денежная компенсация» ------------------------------------------
# Владелец, 19.10.2026: «в режиме строительства всё работает, а если выбрана
# компенсация — пересчёт не работает, в том числе при изменении площади
# жилья». Поля пересчитывались, но таблица соцнагрузки при компенсации
# показывает строки «ДОО/СОШ/поликлиника — компенсация», а они читались прямо
# из выгрузки и стояли на её числах: менялся только итог.

_COMPENSATION = """async ([data, action, socialMode, patch])=>{
  Object.assign(data.inputs._glavapu_import.normalized, patch);
  applyProjectSnapshot(data);
  const wait=()=>new Promise(r=>setTimeout(r,100));
  for(let i=0;i<30&&!glavapuBaselineApplies();i++)await wait();
  const mode=document.getElementById('f_social_mode');
  mode.value=socialMode;mode.dispatchEvent(new Event('change'));
  await settledCalculate();
  const rows=()=>{
    const out={};
    document.querySelectorAll('#socialTable tr').forEach(tr=>{
      const c=[...tr.children].map(x=>x.textContent.replace(/\\s+/g,' ').trim());
      if(c.length===2)out[c[0]]=c[1];
    });
    return out;
  };
  const before=rows();
  const placesBefore=[inputs.kindergarten_places,inputs.school_places,inputs.clinic_capacity];
  if(action==='flats'){
    tepCellChanged('apartments','saleable',Number(tep.apartments.saleable)*1.3);
    const note=()=>(document.getElementById('tepDerivedNote')||{}).textContent||'';
    for(let i=0;i<60&&!note().startsWith('Пересчитано');i++)await wait();
  }else{
    const live=document.getElementById('f_social_population_method');
    live.value='flats_household';live.dispatchEvent(new Event('change'));
    const note=()=>(document.getElementById('socialPopulationNote')||{}).textContent||'';
    for(let i=0;i<60&&(!note()||note().startsWith('Пересчитываю'));i++)await wait();
  }
  await wait();
  const r=await settledCalculate();
  return {before,after:rows(),note:(document.getElementById('tepDerivedNote')||{}).textContent||'',
          placesBefore,places:[inputs.kindergarten_places,inputs.school_places,inputs.clinic_capacity],breakdown:r.summary.social_payment_breakdown.compensation,
          payment:r.summary.social_payment,field:inputs.social_compensation_mln};
}"""


def _compensation(action: str, mode: str = "Денежная компенсация",
                  patch: dict | None = None) -> dict:
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    from main_registry import app as registry_app  # noqa: PLC0415

    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 390, "height": 844})
            tab.goto(f"{base}/", wait_until="domcontentloaded")
            wait_for_result(tab)
            return tab.evaluate(_COMPENSATION, [_snapshot(), action, mode, patch or {}])
        finally:
            browser.close()


def _assert_compensation_rows_follow(got: dict) -> None:
    rows = ("ДОО — компенсация", "СОШ — компенсация", "Поликлиника — компенсация")
    for row in rows:
        assert row in got["before"], got["before"]
        assert got["after"][row] != got["before"][row], (row, got)
    assert got["after"]["Компенсация / всего"] != got["before"]["Компенсация / всего"]
    # Строки по объектам — доли той же суммы, что идёт в модель.
    assert abs(sum(got["breakdown"].values()) - got["field"]) < 0.01, got
    assert abs(got["payment"] - got["field"] * 1e6) < 1.0, got


def test_compensation_rows_follow_the_flats() -> None:
    _assert_compensation_rows_follow(_compensation("flats"))


def test_compensation_rows_follow_the_population_switch() -> None:
    _assert_compensation_rows_follow(_compensation("switch"))


def test_the_breakdown_splits_the_current_total_by_the_export_rates() -> None:
    baseline = _baseline()
    x = {"_glavapu_import": {"normalized": baseline}, "social_compensation_mln": 1760.829,
         "kindergarten_places": 51, "school_places": 104, "clinic_capacity": 22}
    got = core.social_compensation_breakdown(x)
    # Ставка за место из выгрузки × места проекта — так сумму набирает пересчёт.
    assert got["kindergarten_mln"] == round(273.828 / 24 * 51, 3)
    assert abs(sum(got.values()) - 1760.829) < 0.002
    # Мест нет — доли выгрузки; нет суммы — нули, а не числа выгрузки.
    no_places = core.social_compensation_breakdown(dict(x, kindergarten_places=0,
                                                        school_places=0, clinic_capacity=0))
    assert no_places["school_mln"] == round(1760.829 * 410.951 / 815.938, 3)
    assert set(core.social_compensation_breakdown(dict(x, social_compensation_mln=0)).values()) == {0.0}


def test_the_flats_recount_the_places_when_the_printed_area_rounds_up() -> None:
    """Добавка владельца: «при изменении площади жилья ничего не пересчитывается».

    Пересчёт ТЭП по выгрузке отказывал по тому же общему вердикту сверки, что
    и переключатель, а сверка приобъектных мест валилась на округлении
    печатной НП. В обоих режимах исполнения места идут за квартирами.
    """
    for mode in ("Строительство", "Денежная компенсация"):
        got = _compensation("flats", mode, ROUNDED_UP)
        assert "не сходится" not in got["note"], (mode, got["note"])
        assert all(now > was for now, was in zip(got["places"], got["placesBefore"])), (mode, got)
