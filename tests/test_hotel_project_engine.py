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


def _run(kind: str = "hotel", preset: str | None = "hotel1", **over) -> dict:
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


def test_the_hotel_class_is_its_stars_not_a_housing_class() -> None:
    """Класс гостиничного проекта — звёздность (`hotel_stars`), а не «Комфорт»:
    пресет жилья у гостиницы ничего не считает. Незаданный класс — «не задан»."""
    _, result = _run()
    view = result["report"]["project_class"]
    assert (view["kind"], view["title"], view["label"]) == ("hotel", "Класс гостиницы", "5*")
    assert view["rows"] == []
    _, empty = _run(preset=None)
    assert empty["report"]["project_class"]["label"] == "не задан"
    _, mixed = _run("mixed", None)
    view = mixed["report"]["project_class"]
    assert (view["kind"], view["title"], view["label"]) == ("housing", "Класс проекта", "Комфорт")


def test_the_pdf_and_the_teaser_print_the_stars() -> None:
    pytest.importorskip("reportlab")
    from market_search.krt_requirements import pdf_text
    x = hotel_presets.apply_preset({**copy.deepcopy(core.DEFAULT_INPUTS),
                                    "project_kind": "hotel"}, "hotel1")
    t = copy.deepcopy(core.TEP_DEFAULT)
    bundle = core._run_authoritative_model(x, t, [], {})
    pdf = core._build_developaid_pdf({"result": bundle["consolidated"], "project_name": "Отель",
                                      "inputs": x, "tep": t})
    text = " ".join(pdf_text(pdf).split())
    assert "Класс гостиницы 5*" in text
    assert "Класс жилья" not in text and "Класс проекта" not in text
    # Стройку гостиницы считает её ставка — ставки СМР жилья в предпосылках нет.
    assert "тыс. ₽/м² наземной части" not in text
    teaser = " ".join(pdf_text(core.build_teaser_pdf(bundle, x, t, {})).split())
    assert "Класс гостиницы 5*" in teaser and "Комфорт" not in teaser


def test_no_bridge_limit_fee_for_a_loan_the_hotel_does_not_take() -> None:
    """Участок и проект гостиницы кредитует её кредит, БРИДЖа нет — значит, нет
    и платы за резервирование его лимита. Расходы на финансирование проекта —
    ровно проценты и комиссии кредита гостиницы."""
    _, result = _run(purchase_price_mln=500, land_rights_cost_mln=100)
    fin = result["finance"]
    totals = fin["hotel"]["totals"]
    assert fin["calculated_bridge_limit"] == 0
    assert fin["financing_cost"] == pytest.approx(
        totals["loan_interest"] + totals["loan_fee"], abs=1.0)


def test_the_hotel_debt_is_judged_by_its_own_dscr() -> None:
    """Показатель долга (`report_layout.debt_metric`) — DSCR кредита
    гостиницы, а не LLCR: ПФ у гостиницы нет. Без кредита и у пустой
    гостиницы показателя нет, и сказано почему."""
    _, result = _run()
    metric = result["report"]["layout"]["debt_metric"]
    assert metric["key"] == "dscr"
    assert metric["value"] == pytest.approx(result["finance"]["hotel"]["kpi"]["dscr_min"])
    _, cash = _run(hotel_financing="none")
    metric = cash["report"]["layout"]["debt_metric"]
    assert metric["key"] is None and "нет кредита" in metric["reason"]
    _, empty = _run(preset=None)
    metric = empty["report"]["layout"]["debt_metric"]
    assert metric["key"] is None and "не считается" in metric["reason"]


def _pnl_gaps(result: dict) -> dict[str, float]:
    s, fin = result["summary"], result["finance"]
    return {
        "EBITDA − проценты ≠ прибыль до налога":
            s["ebitda"] - s["financing_cost"] - s["profit_before_tax"],
        "выручка − расходы всего ≠ чистая прибыль":
            s["revenue"] - s["total_expenses"] - s["net_profit"],
        "структура расходов ≠ расходы всего":
            sum(e["value"] for e in result["report"]["expense_structure"]) - s["total_expenses"],
        "выручка − CAPEX − маркетинг − расходы объектов ≠ EBITDA":
            s["revenue"] - s["capex"] - s["commercial_costs"]
            - float(fin.get("nonres_costs") or 0.0) - s["ebitda"],
    }


def test_the_economics_lines_add_up_for_the_hotel() -> None:
    """Строки «Экономики проекта» сходятся и у гостиницы: её CAPEX — строка
    структуры расходов, её эксплуатация — расходы объекта вне ДДУ."""
    _, result = _run()
    gaps = _pnl_gaps(result)
    assert all(abs(v) < 1.0 for v in gaps.values()), gaps
    labels = [e["label"] for e in result["report"]["expense_structure"]]
    assert "Гостиница — здание, мебель и оборудование" in labels
    # Льгота 0 % на проживание: возмещение НДС стройки больше начисленного —
    # строка со знаком минус, а не пропажа из структуры.
    assert result["finance"]["vat"] < 0 and core.VAT_REFUND_LABEL in labels
    # Эксплуатация гостиницы — своей подписью: ДКП и «вне ДДУ» у неё нет.
    assert core.HOTEL_COSTS_LABEL in labels and core.NONRES_COSTS_LABEL not in labels
    assert result["report"]["nonres_costs_label"] == core.HOTEL_COSTS_LABEL
    assert result["summary"]["landscaping_gap"].startswith(
        "Благоустройства в расчёте нет: гостиничный проект")
    _, mixed = _run("mixed", None)
    assert "Гостиница — здание, мебель и оборудование" not in [
        e["label"] for e in mixed["report"]["expense_structure"]]


def test_the_economics_check_catches_a_missing_hotel_line() -> None:
    """Подделка: структура без строки гостиницы — проверка обязана покраснеть."""
    _, result = _run()
    forged = {**result, "report": {**result["report"], "expense_structure": [
        e for e in result["report"]["expense_structure"]
        if not e["label"].startswith("Гостиница")]}}
    assert abs(_pnl_gaps(forged)["структура расходов ≠ расходы всего"]) > 1.0


def test_preferential_rate_reads_the_project_key_rate() -> None:
    _, pref = _run()
    _, com = _run(hotel_financing="commercial", hotel_loan_spread_pp=4)
    assert (pref["finance"]["hotel"]["totals"]["loan_interest"]
            < com["finance"]["hotel"]["totals"]["loan_interest"])
