"""Выручка без себестоимости обязана быть названа.

Себестоимость строительства считается от ГНС. Продукт с количеством, но без
площади приносит выручку бесплатно и завышает прибыль и LLCR. На реальном
проекте так и вышло: 833 кладовые без площади дали 1,03 млрд ₽ выручки —
7,5% от всей — и подняли LLCR с 1,116 до 1,186.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core

CODE = "REVENUE_WITHOUT_COST_BASIS"


def project(storage_units: float):
    tep = copy.deepcopy(main.TEP_DEFAULT)
    tep["apartments"].update(gns=21415, total_area=21415, useful=13920, saleable=13920, units=201)
    tep["ground_commercial"].update(gns=1367, total_area=1367, useful=1230, saleable=1230, units=0)
    tep["underground_parking"].update(gns=3185, total_area=3185, units=91)
    tep["storage"].update(units=storage_units, gns=0, total_area=0)
    inputs = {**main.DEFAULT_INPUTS, "project_class": "business",
              "apartment_price_th": 650, "commercial_price_th": 650,
              "parking_price_th": 5000, "purchase_price_mln": 700,
              "land_rights_cost_mln": 1270}
    return inputs, tep


def anomalies(storage_units: float):
    inputs, tep = project(storage_units)
    bundle = main._run_authoritative_model(inputs, tep, [], {})
    request = main.AgentChatRequest(message="аномалии", inputs=inputs, tep=tep, rates=[], phasing={})
    return main._tool_find_anomalies(request, bundle, "all")["anomalies"], bundle


def test_units_without_area_are_flagged():
    found, _ = anomalies(833)
    match = next((item for item in found if item["code"] == CODE), None)
    assert match, [item["code"] for item in found]
    assert match["severity"] == "high"
    assert match["evidence"]["product"] == "storage"
    assert match["evidence"]["units"] == 833
    assert match["evidence"]["revenue_mln"] == pytest.approx(1030, rel=0.02)
    assert match["evidence"]["revenue_share_pct"] == pytest.approx(7.5, abs=0.3)


def test_message_names_the_consequence():
    found, _ = anomalies(833)
    message = next(item["message"] for item in found if item["code"] == CODE)
    assert "833" in message
    assert "LLCR" in message
    # Запятые в тексте не должны съедаться форматированием числа.
    assert "учтена, а себестоимость" in message


def test_silent_when_every_product_has_area():
    found, _ = anomalies(0)
    assert not [item for item in found if item["code"] == CODE]


def test_the_flagged_revenue_really_moves_llcr():
    """Проверяем не текст, а следствие: без этих единиц LLCR заметно ниже."""
    _, with_storage = anomalies(833)
    _, without = anomalies(0)
    high = with_storage["consolidated"]["summary"]["llcr"]
    low = without["consolidated"]["summary"]["llcr"]
    assert high - low > 0.05, f"{high:.3f} против {low:.3f}"


def test_products_with_area_are_never_flagged():
    """Паркинг тоже продаётся штуками, но у него есть ГНС — его трогать нельзя."""
    found, _ = anomalies(0)
    assert not [item for item in found
                if item["code"] == CODE and item["evidence"].get("product") == "underground_parking"]


def test_every_import_path_resets_the_territory():
    """Любые новые данные участка обнуляют прежние — одним правилом, а не по месту.

    ГлавАПУ не считает кладовые, поэтому сервер выбрасывает storage из карты
    соответствия. Страница дописывала ТЭП поверх прежней, и 833 кладовые чужого
    проекта пережили импорт московского участка.
    """
    page = main.PAGE
    assert "function resetTerritoryData(options)" in page
    for entry in ("async function applyGlavapu()",
                  "async function applyMo(options)",
                  "async function applyTelegramManualTep(manual,options)"):
        body = page[page.index(entry):]
        body = body[:body.index("\n\n")] if "\n\n" in body[:3000] else body[:3000]
        assert "resetTerritoryData(" in body, entry


def test_reset_clears_products_and_markers():
    page = main.PAGE
    body = page[page.index("function resetTerritoryData(options)"):]
    body = body[:body.index("async function applyGlavapu()")]
    assert "Object.keys(tep).forEach" in body
    for marker in ("_glavapu_import", "_manual_tep_import", "_mo_calc", "_cadastral_analysis"):
        assert marker in page[page.index("const TERRITORY_MARKERS"):page.index("const TERRITORY_MARKERS") + 200]
    assert "inputs.retail_enabled=false;" in body
    assert "inputs.above_parking_enabled=false;" in body


def test_reset_keeps_the_analyst_assumptions():
    """Цены, себестоимость и ставки — не данные участка, их стирать нельзя."""
    page = main.PAGE
    keys = page[page.index("const TERRITORY_INPUT_KEYS"):page.index("const TERRITORY_MARKERS")]
    for assumption in ("apartment_price_th", "main_above_th_per_sqm", "pf_spread_pp",
                       "discount_rate_pct", "project_class", "construction_months"):
        assert assumption not in keys, assumption


def test_silent_mo_recalc_keeps_the_phasing():
    """Правка плотности — тот же участок: настроенную очерёдность терять нельзя."""
    page = main.PAGE
    assert "resetTerritoryData({keepPhasing:silent})" in page
    assert "if(!keepPhasing)phasing=makeDefaultPhasing(1);" in page


def test_server_drops_storage_when_glavapu_is_silent():
    """Обратная сторона: сервер не выдумывает кладовые, если их нет в таблице."""
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert 'tep_mapping.pop("storage", None)' in source
    assert 'tep_mapping.pop("offices", None)' in source
