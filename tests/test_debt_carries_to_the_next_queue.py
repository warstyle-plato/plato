"""Непогашенный долг очереди переходит в ПФ следующей — но не любой ценой.

Решение владельца (27.08.2026) и его же ответы на четыре вопроса:

- долг переносят сразу в ПФ следующей очереди по генеральному соглашению;
- лимит принимающей очереди он НЕ съедает: банк переносит обязательство, а не
  выдаёт новые деньги;
- капитализация лимит по-прежнему не выбирает (решение от 04.08.2026);
- долг ОБЯЗАН появиться в знаменателе LLCR принявшей очереди. Иначе первая
  перестанет быть дефолтной, во второй долг не появится, и обе покажут
  покрытие, которого нет, — два достоверных на вид отчёта на одних вводных;
- ограничений по доле и сроку не вводим: это индивидуальные условия.

И условие, ради которого всё затевалось: **перенос допустим, только если
общий LLCR проекта выдерживается**. Не выдерживается — банку это не нужно, он
просто оттягивает дефолт, и модель обязана оставить дефолт на месте и сказать
почему.

Запуск: python3 -m pytest tests/test_debt_carries_to_the_next_queue.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def _bundle(price: float, purchase: float, *, carry: bool) -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(purchase_price_mln=purchase, project_start="2027-01-01",
                  ird_months=12, construction_months=24, apartment_price_th=price)
    tep = {key: dict(row) for key, row in core.TEP_DEFAULT.items()}
    phasing = {
        "enabled": True, "mode": "phased", "user_enabled": True,
        "phase_count": 2, "phase_gap_months": 12,
        "phases": [{"name": "О1", "start_offset_months": 0, "construction_months": 24},
                   {"name": "О2", "start_offset_months": 12, "construction_months": 24}],
        # Первая очередь мала, а земля и социалка на ней целиком: ровно тот
        # перекос, из-за которого она не гасит свой ПФ при здоровом проекте.
        "products": {key: [35, 65] for key in
                     ("apartments", "ground_commercial", "underground_parking")},
        "shared_cash": {}, "shared_allocation": {}, "social_objects": [],
        "carry_debt_forward": carry,
    }
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing))


@pytest.fixture(scope="module")
def healthy() -> dict:
    """Проект, который в целом долг обслуживает, а первая очередь — нет."""
    bundle = _bundle(700, 12000, carry=True)
    carry = bundle.get("debt_carry") or {}
    assert carry.get("applied") is True, (
        "предохранитель: на этих вводных перенос обязан сработать, иначе тест "
        "проверяет не ту ветку")
    return bundle


def test_the_debt_leaves_the_queue_that_could_not_repay_it(healthy):
    first = healthy["phases"][0]["result"]["finance"]
    assert first["ending_pf"] == pytest.approx(0.0), (
        "долг остался и на передавшей очереди — она по-прежнему выглядит дефолтной")
    assert first["debt_carried_out"] > 0


def test_the_debt_appears_in_the_queue_that_took_it(healthy):
    """Прямое требование владельца: долг обязан появиться."""
    second = healthy["phases"][1]["result"]["finance"]
    first = healthy["phases"][0]["result"]["finance"]
    assert second["carried_debt_in"] == pytest.approx(first["debt_carried_out"])
    # В знаменателе LLCR — и именно там, а не в числителе: принятый долг не
    # покупает никакого CAPEX, которым его можно было бы уравновесить.
    assert second["llcr_denominator"] > second["pf_draw_total"]
    assert second["llcr_denominator"] >= second["carried_debt_in"]


def test_the_transfer_does_not_eat_the_receiving_limit(healthy):
    """Лимит принимающей очереди перенос не съедает."""
    second = healthy["phases"][1]["result"]["finance"]
    assert second["pf_draw_total"] <= second["pf_limit"] + 1.0, (
        "принятый долг попал в выборку и съел лимит второй очереди")
    assert second["pf_shortfall"] == pytest.approx(0.0)


def test_the_project_does_not_count_the_same_debt_twice(healthy):
    """Свод вычитает принятый долг один раз — это не новые деньги."""
    finance = healthy["consolidated"]["finance"]
    phases = [item["result"]["finance"] for item in healthy["phases"]]
    assert finance["llcr_denominator"] == pytest.approx(
        sum(f["llcr_denominator"] for f in phases)
        - sum(f["carried_debt_in"] for f in phases))
    assert float(healthy["consolidated"]["summary"]["ending_pf"]) == pytest.approx(0.0)


def test_a_project_that_cannot_service_its_debt_gets_no_transfer():
    """Ниже порога перенос просто оттягивает дефолт — банку это не нужно."""
    bundle = _bundle(400, 9000, carry=True)
    carry = bundle.get("debt_carry") or {}
    assert carry.get("applied") is False, (
        "предохранитель: на этих вводных проект долг не обслуживает")
    assert carry["project_llcr"] < core._PHASE_DEBT_CARRY_MIN_LLCR
    assert "отодвигает дефолт" in carry["note"]
    # Дефолт остался там, где он есть, и виден.
    assert bundle["phases"][0]["result"]["finance"]["ending_pf"] > 0


def test_without_the_flag_nothing_changes():
    """Книга о переносе не знает: включённый молча, он развёл бы её с движком."""
    off = _bundle(700, 12000, carry=False)
    assert off.get("debt_carry") is None
    assert off["phases"][0]["result"]["finance"]["ending_pf"] > 0
    for phase in off["phases"]:
        assert phase["result"]["finance"]["carried_debt_in"] == pytest.approx(0.0)


# --- Перенос обязан быть ВИДЕН -----------------------------------------------
#
# Вопрос владельца (29.08.2026): «модель отчёт и пдф покажут это наглядно, что
# 1 очередь не гасится и часть долга уходит дальше?». Ответ был «нет»: перенос
# жил только в JSON ответа. Долг при этом обнулялся у передавшей очереди — то
# есть обязательство исчезало с экрана бесследно, а у принявшей падал LLCR без
# объяснения. Ровно то, что мы ловим везде: снижение без причины — это просто
# другое число.


def test_the_comparison_table_carries_the_debt_numbers(healthy):
    """Таблица сравнения очередей строится из `comparison`, и долга в ней не
    было вовсе: очередь, не рассчитавшаяся с банком, выглядела так же, как
    закрывшая долг."""
    rows = healthy["comparison"]
    assert rows[0]["ending_pf"] == pytest.approx(0.0)
    assert rows[0]["debt_carried_out"] > 500_000_000, (
        "передавшая очередь обязана назвать переданное: обнулённый остаток без "
        "этой строки читается как «рассчиталась сама»")
    assert rows[1]["carried_debt_in"] == pytest.approx(rows[0]["debt_carried_out"])
    assert rows[1]["debt_carried_out"] == pytest.approx(0.0)


def test_the_queue_report_and_the_table_say_the_same_thing(healthy):
    """У отчёта очереди свой экземпляр финансирования — не тот объект, что
    `finance`. Пока его не правили, карточка одной очереди печатала полный
    долг, а таблица сравнения по той же очереди — ноль."""
    first = healthy["phases"][0]["result"]["report"]["financing"]
    second = healthy["phases"][1]["result"]["report"]["financing"]
    assert first["ending_pf"] == pytest.approx(0.0)
    assert first["debt_carried_out"] > 500_000_000
    assert second["carried_debt_in"] == pytest.approx(first["debt_carried_out"])


def test_the_reason_reaches_the_consolidated_result(healthy):
    """PDF собирается из свода, а не из связки: без этой дороги отчёт печатал
    бы обнулённый долг первой очереди и выросший долг второй, ничего не сказав
    о переносе."""
    carry = (healthy.get("consolidated") or {}).get("debt_carry") or {}
    assert carry.get("applied") is True
    assert "генеральному соглашению" in str(carry.get("note") or "")


def test_the_refusal_also_reaches_the_consolidated_result():
    """Отказ доносится тем же путём. Читатель видит дефолтную очередь и обязан
    узнать, почему перенос, о котором сказано в методике, не сработал."""
    bundle = _bundle(430, 12000, carry=True)
    carry = (bundle.get("consolidated") or {}).get("debt_carry") or {}
    assert carry.get("applied") is False, (
        "предохранитель: на этих вводных перенос обязан быть отказан")
    assert "ниже" in str(carry.get("note") or "")


def test_the_page_shows_the_debt_rows_and_the_reason():
    page = core.PAGE
    for label in ("Непогашенный долг ПФ на конец очереди",
                  "Передано следующей очереди",
                  "Принято от предыдущей очереди",
                  "Долг передан в ПФ следующей очереди",
                  "phaseDebtCarryNote"):
        assert label in page, label
    # Признак должен быть на экране: без него перенос включить нечем, и весь
    # разбор остаётся недостижимым из интерфейса.
    assert "phaseCarryDebt" in page
    assert "Непогашенный долг очереди переходит в ПФ следующей" in page
    # Книга о переносе пока не знает — об этом обязано быть сказано рядом с
    # признаком, а не только в коммите.
    assert "Excel-книга о переносе пока не знает" in page


def test_the_pdf_prints_the_transfer_section():
    import inspect
    source = inspect.getsource(core._build_developaid_pdf)
    assert "Непогашенный долг и перенос между очередями" in source
    assert 'item.get("debt_carried_out")' in source
    assert 'result.get("debt_carry")' in source


def test_the_pdf_still_builds_with_a_carried_debt():
    """Новый раздел не имеет права ронять печать."""
    pytest.importorskip("reportlab")
    bundle = _bundle(700, 12000, carry=True)
    data = core._build_developaid_pdf({
        "result": bundle["consolidated"], "inputs": core.DEFAULT_INPUTS,
        "tep": core.TEP_DEFAULT, "rates": [], "phasing": bundle.get("phasing") or {},
        "scenario": "base", "project_name": "Проверка переноса"})
    assert data[:4] == b"%PDF"
