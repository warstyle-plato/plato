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
                  "Осталось непогашенным на очереди",
                  "Передано следующей очереди",
                  "Принято от предыдущей очереди",
                  "Долг передан в ПФ следующей очереди",
                  "phaseDebtCarryNote"):
        assert label in page, label


def test_the_remainder_comes_after_what_went_in_and_out():
    """Порядок строк — это и есть рассказ: пришло, ушло, осталось.

    Прежде «непогашенный долг 0» стоял МЕЖДУ «принято 11,73» и «передано
    11,73» и читался как противоречие: «как это долга нет, но он передан в
    другую очередь тут же в другой строке» (владелец, 30.08.2026).
    Противоречия не было, но объяснять его читателю не должно приходиться.
    """
    page = core.PAGE
    taken = page.index("'Принято от предыдущей очереди'")
    passed = page.index("'Передано следующей очереди'")
    left = page.index("'Осталось непогашенным на очереди'")
    assert taken < passed < left, (
        "остаток обязан стоять последним: он вывод, а не одно из трёх чисел")


def test_the_remainder_is_not_called_unpaid_when_the_debt_moved():
    """11,73 млрд ПФ не погашены — они сменили должника.

    Название «Непогашенный долг на конец очереди» обещало ровно то, что
    стояло строкой выше с тем же числом. При переносе строка называется
    иначе, при его отсутствии — как раньше.
    """
    page = core.PAGE
    marker = "anyDebt('debt_carried_out')\n                 ?'Осталось непогашенным на очереди'"
    assert marker.replace("\n", "\n") in page or (
        "?'Осталось непогашенным на очереди'" in page
        and "'Непогашенный долг ПФ на конец очереди'" in page), (
        "название строки обязано зависеть от того, был ли перенос")
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


# --- Момент и сумма переноса --------------------------------------------------
#
# Владелец (29.08.2026): «долг переходит в тот момент, когда средства с эскроу
# после РнВ предыдущей очереди раскрылись и их не хватило на погашение. При
# этом деньги от последующих продаж остаются у застройщика».
#
# И его же довод, почему прежняя версия неверна: «а как он может там висеть
# если по договору НКЛ должна быть закрыта — юридически он или дефолтный или в
# воздухе». Третьего состояния нет, а модель изображала именно третье: остаток
# год жил на закрытой линии, начисляя полную базовую ставку (покрытие после
# раскрытия нулевое), и гасился остаточными продажами.


def test_the_debt_moves_at_the_escrow_release_not_at_the_next_permit():
    """Дата переноса — РВЭ передавшей очереди, а не открытие ПФ принимающей.

    Прежде бралось открытие ПФ следующей очереди: на контрольном проекте это
    январь 2029, а О1 не рассчитывается только к январю 2031. О2 два года
    платила проценты за обязательство, которого ещё нет.
    """
    bundle = _bundle(700, 12000, carry=True)
    carry = bundle["debt_carry"]
    transfer = carry["transfers"][0]
    rve = bundle["phases"][0]["result"]["dates"]["rve"]
    permit_of_receiver = bundle["phases"][1]["result"]["dates"]["permit"]
    assert transfer["at"] == rve
    assert transfer["at"] != permit_of_receiver, (
        "предохранитель: на этих вводных две даты обязаны различаться, иначе "
        "тест проходит и на старой методике")
    # Долг ложится на баланс принимающей очереди именно в этот месяц.
    rows = bundle["phases"][1]["result"]["finance"]["rows"]
    jump = next(r for r in rows if str(r["month"])[:10] == rve)
    before = rows[rows.index(jump) - 1]
    assert jump["pf_balance"] - before["pf_balance"] > 7_000_000_000


def test_the_amount_is_what_the_released_escrow_did_not_cover():
    """Переносится нехватка на дату раскрытия, а не остаток на конец горизонта.

    Разница на контрольном проекте — 7 816 против 4 229 млн: прежняя версия
    брала остаток ПОСЛЕ того, как остаточные продажи год гасили долг на уже
    закрытой линии."""
    plain = _bundle(700, 12000, carry=False)
    source = plain["phases"][0]["result"]["finance"]
    unpaid = source["rve_unpaid"]
    assert unpaid > 1_000_000_000, (
        "предохранитель: на этих вводных раскрытого эскроу обязано не хватить")
    carried = _bundle(700, 12000, carry=True)
    assert carried["debt_carry"]["transfers"][0]["amount"] == pytest.approx(
        unpaid, rel=1e-6)


def test_after_the_transfer_the_closed_line_neither_lends_nor_collects():
    """НКЛ закрыт: ни выборки, ни погашения, ни процентов после РВЭ.

    Остаточные продажи остаются застройщику. Прежде они уходили банку — 3 587
    млн, — а на непогашенном остатке год начислялись проценты по полной
    базовой ставке 13,5%: 691,3 млн ₽ на линии, которой по договору уже нет.
    """
    bundle = _bundle(700, 12000, carry=True)
    source = bundle["phases"][0]["result"]["finance"]
    rve = bundle["phases"][0]["result"]["dates"]["rve"]
    after = [r for r in source["rows"] if str(r["month"])[:10] > rve]
    assert after, "предохранитель: у очереди обязаны быть месяцы после РВЭ"
    assert sum(r["pf_draw"] for r in after) == pytest.approx(0.0)
    assert sum(r["pf_repayment"] for r in after) == pytest.approx(0.0)
    assert sum(r.get("pf_interest") or 0.0 for r in after) == pytest.approx(0.0)
    # А продажи в эти месяцы есть — значит деньги действительно остались.
    assert sum(r["sales"] for r in after) > 3_000_000_000
    assert source["ending_pf"] == pytest.approx(0.0)


def test_without_the_transfer_the_default_is_named_but_the_model_goes_on():
    """Без переноса дефолт НАЗЫВАЕТСЯ датой и суммой, но модель не обрывается.

    Владелец, 30.08.2026: «не закрывай! лучше просто показывай, что по факту
    модель — дефолт на такой-то очереди и надо будет согласие банка на перенос
    долга на следующую или реструктуризация». Вариантов у банка много, чаще
    всего долг просто переоформляют; а если эскроу не наполнился из-за продаж,
    это форс-мажор, которого в НКЛ и не могло быть заложено.

    Условий реструктуризации модель не знает, поэтому считает прежним
    допущением — остаток обслуживается продажами следующих периодов, — и
    называет его вслух на экране.
    """
    plain = _bundle(700, 12000, carry=False)
    source = plain["phases"][0]["result"]["finance"]
    rve = plain["phases"][0]["result"]["dates"]["rve"]
    assert source["default_date"] == rve, "дефолт фиксируется в дату раскрытия"
    assert source["rve_unpaid"] > 1_000_000_000, (
        "предохранитель: раскрытого эскроу обязано не хватить")
    after = [r for r in source["rows"] if str(r["month"])[:10] > rve]
    assert sum(r["pf_repayment"] for r in after) > 1_000_000_000, (
        "модель не обрывается на дефолте: остаток гасится продажами следующих "
        "периодов — допущение о реструктуризации, названное на экране")
    assert source["ending_pf"] < source["rve_unpaid"], (
        "остаток на конец меньше нехватки в РВЭ — продажи его обслуживали")


def test_the_transferred_debt_does_close_the_line():
    """А вот переоформленный долг линию закрывает: он ушёл к другому должнику."""
    carried = _bundle(700, 12000, carry=True)
    source = carried["phases"][0]["result"]["finance"]
    rve = carried["phases"][0]["result"]["dates"]["rve"]
    after = [r for r in source["rows"] if str(r["month"])[:10] > rve]
    assert after, "предохранитель: у очереди обязаны быть месяцы после РВЭ"
    assert sum(r["sales"] for r in after) > 1_000_000_000, (
        "предохранитель: остаточные продажи обязаны быть")
    assert sum(r["pf_repayment"] for r in after) == pytest.approx(0.0)
    assert sum(r["pf_draw"] for r in after) == pytest.approx(0.0)
    assert sum(r.get("pf_interest") or 0.0 for r in after) == pytest.approx(0.0)
    assert source["default_date"] is None, "перенос — не дефолт"


def test_the_debt_cannot_land_before_the_receiving_line_exists():
    """Пол по дате: раньше своего РнС очередь принять долг в ПФ не может —
    линии ещё нет. Проверяется на самом движке, а не на связке."""
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(project_start="2027-01-01", ird_months=12,
                  _phase_carried_debt_mln=1000.0,
                  _phase_carried_debt_month="2027-03-01")
    result = core.calculate(core.CalcRequest(
        inputs=inputs, tep={k: dict(v) for k, v in core.TEP_DEFAULT.items()}, rates=[]))
    permit = result["dates"]["permit"]
    rows = result["finance"]["rows"]
    landed = next(r for r in rows if (r.get("pf_balance") or 0) > 0)
    assert str(landed["month"])[:10] >= permit

