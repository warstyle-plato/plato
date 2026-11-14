"""Этап 3 «Договоров»: факт по актам КС-2, сверка с КС-6а, натуральные объёмы и три процента работы.

Методика владельца 12.11.2026 (docs/contract_schedule_control.md): факт работ — объёмы актов КС-2,
накопительная КС-6а — сверка; работа меряется в своих единицах, деньги — вторичны; у работы три
процента — выполнение плана на дату, готовность и отклонение; готовность договора взвешена
стоимостью работ; отставание и просрочка считаются отдельно. Документы и ведомость выдуманы:
репозиторий публичный, документы владельца в него не попадают.
"""
from __future__ import annotations

import pytest

import developaid_contract_control as control
import developaid_contract_fact as fact
import developaid_contract_files as files
from tests.test_contract_card_confirms_and_chooses_links import CONTRACT, ROW
from tests.test_contract_control_reports_lag_and_forecast import LINE, _fact, _plan
from tests.test_contract_fact_prices_ks_by_the_edition import REGISTER_ROW, card  # noqa: F401

pytest.importorskip("pymupdf")
from tests.test_contract_fact_dates_ks6_periods_by_acts import act_pdf  # noqa: E402


def _volumes(quantity, unit="м3"):
    return [{"unit": unit, "quantity": quantity}]


# --- факт по КС-2 и сверка с КС-6а ----------------------------------------------------

def test_the_fact_is_the_acts_ks2_and_the_ks6a_only_reconciles_them(card):  # noqa: F811
    by_ks6a = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(REGISTER_ROW))
    assert by_ks6a["fact"]["source"] == "ks6a" and by_ks6a["fact"]["total"] == 5500.0
    assert by_ks6a["fact"]["source_note"] == "Актов КС-2 в карточке нет: факт взят из накопительной КС-6а."
    files.store("Учебный", ROW, "КС-2 2.pdf", act_pdf())
    got = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(REGISTER_ROW))
    done = got["fact"]
    # Акт № 2: стены 0,5 м3 по цене расчёта 8 000 ₽ за м3; доли строк ГПР 1.1 и 1.2 — 3/8 и 5/8.
    assert (done["source"], done["source_note"], done["total"], done["review"]) == ("ks2", "", 4000.0, [])
    assert [(x["code"], x["fact"], x["volumes"]) for x in done["lines"]] == [
        ("1.1", 1500.0, _volumes(0.1875)), ("1.2", 2500.0, _volumes(0.3125))]
    # КС-6а не добавляет факт: плиты и лестницы есть только в ней, и сверка это называет.
    reconciliation = done["reconciliation"]
    assert (reconciliation["same"], reconciliation["differs"], reconciliation["only_ks2"],
            reconciliation["only_ks6a"]) == (0, 1, 0, 4)
    assert reconciliation["rows"][0] == {"number": "1.1", "name": "Устройство стен", "unit": "м3", "ks2": 0.5,
                                         "ks6a": 0.75, "same": False}
    total = got["control"]["total"]
    assert (total["fact"], total["readiness"], total["plan_done"], total["incomplete"]) == pytest.approx(
        (4000.0, 4 / 11, 0.4, False))
    assert got["control"]["source"] == "ks2"


def test_the_same_act_uploaded_twice_counts_once(card):  # noqa: F811
    files.store("Учебный", ROW, "КС-2 2.pdf", act_pdf())
    files.store("Учебный", ROW, "КС-2 2 копия.pdf", act_pdf(twice=True))
    got = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(REGISTER_ROW))
    assert got["fact"]["source"] == "ks2" and got["fact"]["total"] == 4000.0


# --- натуральные объёмы и три процента ------------------------------------------------

def test_a_work_is_measured_by_its_volume_not_by_its_money():
    # 10 м3 из 20 к 05.03 — ровно по плану, хотя по цене КС вышло 300 ₽ из 500 ₽ плана.
    got = control.build(_plan("2026-03-05", LINE), _fact(("3.1", 300.0, _volumes(10.0))), None, "", "2026-03-05")
    (line,) = got["lines"]
    assert (line["basis"], line["state"], line["lag_days"], line["readiness"], line["plan_done"]) == (
        "volume", "on_plan", 0, 0.5, 1.0)
    assert line["deviation"] == -200.0 and line["volume"]["deviation"] == 0.0


def test_three_percents_of_a_work_and_its_volume_deviation():
    got = control.build(_plan("2026-03-05", LINE), _fact(("3.1", 300.0, _volumes(6.0))), None, "", "2026-03-05")
    (line,) = got["lines"]
    # План к 05.03 — 10 м3 из 20, факт 6 м3.
    assert (line["plan_share"], line["plan_done"], line["readiness"], line["percent"]) == pytest.approx(
        (0.5, 0.6, 0.3, -0.4))
    assert line["volume"]["deviation"] == pytest.approx(-4.0)
    early = control.build(_plan("2026-02-20", LINE), _fact(("3.1", 0.0, [])), None, "", "2026-02-20")["lines"][0]
    # До начала работы плана нет: процентов от нуля не бывает.
    assert (early["plan_done"], early["percent"], early["readiness"]) == (None, None, 0.0)


def test_a_work_in_different_units_is_measured_by_its_money_and_says_so():
    got = control.build(_plan("2026-03-05", LINE), _fact(("3.1", 300.0, _volumes(10.0, "т"))), None, "", "2026-03-05")
    (line,) = got["lines"]
    assert (line["basis"], line["volume"], line["readiness"], line["state"]) == ("money", None, 0.3, "behind")
    assert (got["total"]["by_volume"], got["total"]["by_money"]) == (0, 1)


def test_lag_and_overdue_are_counted_apart():
    # 12.03: срок работы (10.03) прошёл 2 дня назад, а 10 м3 из 20 план набрал ещё 05.03 — отставание 7 дней.
    got = control.build(_plan("2026-03-12", LINE), _fact(("3.1", 500.0, _volumes(10.0))), "2026-03-11",
                        "Указан вручную", "2026-03-12")
    (line,) = got["lines"]
    assert (line["state"], line["lag_days"], line["overdue_days"]) == ("behind", 7, 2)
    assert got["overdue"] == ["3.1"] and got["total"]["overdue_works"] == 1 and got["total"]["overdue_days"] == 1
    done = control.build(_plan("2026-03-12", LINE), _fact(("3.1", 1000.0, _volumes(20.0), "2026-03-11")),
                         "2026-03-11", "Указан вручную", "2026-03-12")
    # Законченная работа не просрочена: её опоздание — в окончании по КС против графика.
    assert (done["lines"][0]["overdue_days"], done["lines"][0]["late_days"], done["total"]["overdue_days"]) == (0, 1, 0)


def test_the_contract_readiness_is_weighted_by_the_cost_of_each_work():
    big = {**LINE, "code": "3.2", "amount": 3000.0, "volume": {"unit": "м2", "quantity": 30.0}}
    got = control.build(_plan("2026-03-20", LINE, big),
                        _fact(("3.1", 1200.0, _volumes(30.0), "2026-03-09"), ("3.2", 1000.0, _volumes(10.0))),
                        None, "", "2026-03-20")
    rows = {r["code"]: r for r in got["lines"]}
    # 3.1 сделана сверх объёма (30 из 20 м3) — учтена целиком, не полтора раза; 3.2 — треть.
    assert rows["3.1"]["state"] == "done" and rows["3.1"]["over"] and rows["3.2"]["readiness"] == pytest.approx(1 / 3)
    assert got["total"]["readiness"] == pytest.approx((1000 * 1 + 3000 / 3) / 4000)
    assert got["total"]["plan_done"] == pytest.approx(0.5)


def test_automatic_links_and_a_preliminary_fact_are_named_in_the_report():
    planned = _plan("2026-03-05", {**LINE, "auto": 2})
    # Позиция, разнесённая на две строки графика, — одна автоматическая связь: итог берёт счёт редакции.
    planned["editions"][0]["auto"] = 1
    got = control.build(planned, {**_fact(("3.1", 500.0, _volumes(10.0))), "preliminary": True}, None, "",
                        "2026-03-05")
    assert got["lines"][0]["auto"] == 2 and got["total"]["auto"] == 1
    assert got["preliminary"] and got["total"]["preliminary"]


# --- страница -------------------------------------------------------------------------

@pytest.mark.parametrize("width", [390, 1440])
def test_the_card_shows_the_ks2_fact_and_the_reconciliation_in_plain_words(card, width):  # noqa: F811
    from playwright.sync_api import expect

    from test_monitor_cumulative_controls import browser_page
    from tests.test_contract_card_confirms_and_chooses_links import _serve
    files.store("Учебный", ROW, "КС-2 2.pdf", act_pdf())
    with browser_page(width) as (page, _, errors):
        _serve(page, [], cut="2026-02-04", acts=fact.acts(REGISTER_ROW))
        page.locator("#contractsTab").click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        page.locator("#contractComparisonMethodology > details > summary").click()
        facts = page.locator(".contract-fact-audit")
        expect(page.locator("#contractComparisonInfo")).to_contain_text("Факт по КС-2 — по периодам выполнения.")
        state = facts.locator(".contract-fact-reconcile-state")
        expect(state).to_have_text("Акты КС-2 и накопительная КС-6а расходятся: позиций с разным объёмом — 1, "
                                   "только в актах КС-2 — 0, только в КС-6а — 4. Факт считается по актам КС-2.")
        facts.get_by_text("Сверка актов КС-2 с накопительной КС-6а (5)").click()
        first = facts.locator(".contract-fact-reconcile tbody tr").first.locator("td")
        expect(first.nth(2)).to_have_text("0,5")
        expect(first.nth(3)).to_have_text("0,75")
        expect(first.nth(4)).to_have_text("объём разный")
        assert first.nth(3).get_attribute("data-label") == "По КС-6а"
        expect(page.locator("#contractCardSummary")).to_contain_text("40 %")
        expect(page.locator("#contractCardSummary")).to_contain_text("Готовность сопоставленных работ: 36,4 %")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == []
