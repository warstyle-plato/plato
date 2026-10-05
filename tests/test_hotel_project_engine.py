"""Тип проекта «Гостиница» в движке: один расчёт, одни деньги на все поверхности.

Обещания:
* гостиница — отдельный тип проекта; у жилого и нежилого проекта её статей,
  строки ТЭП и итога нет вовсе;
* жильё, соцнагрузка и объекты в гостиничном проекте не считаются, но
  названы остатком;
* CAPEX считает движок один раз (здание = ГНС × ставка, FF&E = номера ×
  ставка) и отдаёт расчёту гостиницы; банк ПФ гостиницу не кредитует;
* налог на прибыль, NPV и IRR капитала сводки — ровно те, что у расчёта
  гостиницы: правило одно (`developaid_finance_math`);
* незаполненная гостиница не считается нулями — итог называет пустые поля.

Запуск: python3 -m pytest tests/test_hotel_project_engine.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hotel_presets  # noqa: E402
import main_legacy as core  # noqa: E402

_CACHE: dict = {}


def _run(kind: str = "hotel", preset: str | None = "dombai", **over) -> dict:
    key = (kind, preset, tuple(sorted(over.items())))
    if key not in _CACHE:
        x = copy.deepcopy(core.DEFAULT_INPUTS)
        t = copy.deepcopy(core.TEP_DEFAULT)
        x["project_kind"] = kind
        if preset:
            x = hotel_presets.apply_preset(x, preset)
        x.update(over)
        _CACHE[key] = (x, core._run_authoritative_model(x, t, [], {})["consolidated"])
    return _CACHE[key]


def test_hotel_is_a_project_kind_of_its_own() -> None:
    assert dict(core.PROJECT_KINDS)["hotel"] == "Гостиница"
    assert core.without_housing({"project_kind": "hotel"})
    assert core.without_housing({"project_kind": "nonresidential"})
    assert not core.without_housing({"project_kind": "mixed"})
    assert not core.is_nonresidential({"project_kind": "hotel"})


def test_a_mixed_project_has_no_hotel_at_all() -> None:
    x, result = _run("mixed", None)
    assert result["finance"].get("hotel") is None
    assert result["report"]["hotel"] is None
    assert "hotel" not in result["capex"] and "hotel_ffe" not in result["capex"]
    assert not any(row.get("key") == "hotel" for row in result["tep"]["rows"])


def test_capex_is_counted_once_by_the_engine() -> None:
    x, result = _run()
    hotel = result["finance"]["hotel"]
    building = x["hotel_gba_sqm"] * x["hotel_cost_th_per_sqm"] * 1000
    ffe = x["hotel_keys"] * x["hotel_ffe_th_per_key"] * 1000
    assert result["capex"]["hotel"] == pytest.approx(building)
    assert result["capex"]["hotel_ffe"] == pytest.approx(ffe)
    total = sum(float(v) for k, v in result["capex"].items() if k != "total")
    assert hotel["kpi"]["capex"] == pytest.approx(result["capex"]["total"], rel=1e-9)
    assert total == pytest.approx(result["capex"]["total"], rel=1e-6)


def test_the_bank_pf_does_not_lend_to_the_hotel() -> None:
    _, result = _run()
    fin = result["finance"]
    assert fin["pf_draw_total"] == 0
    assert sum(float(r.get("bridge_draw", 0) or 0) for r in fin["rows"]) == 0
    assert result["report"]["layout"]["project_finance"] is False
    assert result["report"]["layout"]["housing"] is False
    assert result["report"]["layout"]["hotel"] is True
    draws = sum(float(r.get("nonres_loan_draw", 0) or 0) for r in fin["rows"])
    assert draws == pytest.approx(fin["hotel"]["totals"]["loan_draw"])


def test_tax_npv_and_irr_are_the_hotel_numbers() -> None:
    _, result = _run()
    kpi = result["finance"]["hotel"]["kpi"]
    summary = result["summary"]
    assert result["finance"]["profit_tax"] == pytest.approx(kpi["profit_tax"], rel=1e-9)
    assert summary["npv"] == pytest.approx(kpi["npv_project"], rel=1e-9)
    assert summary["npv_equity"] == pytest.approx(kpi["npv_equity"], rel=1e-9)
    assert summary["irr_equity"] == pytest.approx(kpi["irr_equity"], rel=1e-9)


def test_leftovers_name_housing_and_objects() -> None:
    x, result = _run(offices_enabled=True)
    left = result["summary"]["project_kind_leftovers"]
    assert any(item.startswith("Квартиры") for item in left)
    assert "МФОЦ / офисы: объект включён" in left
    assert result["revenue"].get("offices", 0) == 0
    assert result["capex"].get("offices", 0) == 0


def test_the_hotel_is_the_project_tep() -> None:
    x, result = _run()
    row = next(r for r in result["tep"]["rows"] if r.get("key") == "hotel")
    assert row["gns"] == pytest.approx(x["hotel_gba_sqm"])
    flats = next(r for r in result["tep"]["rows"] if r.get("key") == "apartments")
    assert flats.get("excluded") and not flats.get("gns")


def test_an_empty_hotel_is_named_not_zeroed() -> None:
    _, result = _run(preset=None)
    hotel = result["finance"]["hotel"]
    assert hotel["computed"] is False
    assert "ADR — средняя цена номера" in hotel["missing"]
    report = result["report"]["hotel"]
    assert report["computed"] is False and report["rows"] == []


def test_the_scenario_moves_the_hotel_revenue() -> None:
    _, base = _run()
    _, low = _run(scenario_revenue_multiplier=0.9)
    assert (low["finance"]["hotel"]["totals"]["department_revenue"]
            == pytest.approx(base["finance"]["hotel"]["totals"]["department_revenue"] * 0.9,
                             rel=1e-9))


def test_preferential_rate_reads_the_project_key_rate() -> None:
    _, pref = _run()
    _, com = _run(hotel_financing="commercial", hotel_loan_spread_pp=4)
    assert (pref["finance"]["hotel"]["totals"]["loan_interest"]
            < com["finance"]["hotel"]["totals"]["loan_interest"])
