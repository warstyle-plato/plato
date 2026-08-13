"""Часть первоначального финансирования может идти не из банка.

До открытия ПФ модель считала весь разрыв банковским: любой рубль, потраченный
раньше эскроу, становился БРИДЖем и нёс ключевую плюс спред. Проект, в котором
вход и проектирование закрыты своими деньгами, заёмом учредителя или
перехваченным чужим долгом, выглядел дороже, чем он есть, — и разговор с банком
шёл от завышенной потребности.

Собственные средства тратятся раньше БРИДЖа, процентов не несут и не
возвращаются: это вклад, а не кредит. В расшифровке пика они стоят отдельной
строкой со знаком минус — уменьшают долг, а не расходы.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _tep():
    return {key: dict(value) for key, value in core.TEP_DEFAULT.items()}


def _run(own_mln: float = 0.0, **extra):
    inputs = {**core.DEFAULT_INPUTS, "purchase_price_mln": 4000.0,
              "pre_pf_own_funds_mln": own_mln, **extra}
    return core.calculate(core.CalcRequest(inputs=inputs, tep=_tep(), rates=[]))


def _phased(own_mln: float, count: int = 3):
    inputs = {**core.DEFAULT_INPUTS, "purchase_price_mln": 4000.0,
              "pre_pf_own_funds_mln": own_mln}
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=_tep(), rates=[],
        phasing={"enabled": True, "phase_count": count, "phase_gap_months": 12}))


# --- свои деньги тратятся раньше банковских ----------------------------------

def test_own_funds_lower_the_bridge_by_their_own_size():
    without = _run(0.0)["report"]["financing"]["actual_bridge"]
    with_own = _run(3000.0)["report"]["financing"]["actual_bridge"]
    assert without - with_own == pytest.approx(3000.0 * 1e6, rel=1e-6)


def test_own_funds_carry_no_interest():
    """Иначе это не свои деньги, а тот же кредит под другим названием."""
    without = _run(0.0)["summary"]["financing_cost"]
    with_own = _run(3000.0)["summary"]["financing_cost"]
    assert with_own < without


def test_enough_own_funds_remove_the_bridge_entirely():
    """«Собственный капитал вместо БРИДЖа» — это та же настройка, доведённая до
    конца, а не отдельный режим."""
    result = _run(100_000.0)
    assert result["report"]["financing"]["actual_bridge"] == 0.0
    assert result["finance"]["own_funds_used"] > 0


def test_unused_money_is_not_counted_as_spent():
    """Вложено ровно столько, сколько понадобилось до открытия ПФ."""
    result = _run(100_000.0)
    finance = result["finance"]
    assert finance["own_funds_used"] < finance["own_funds_available"]


def test_nothing_changes_when_there_are_no_own_funds():
    """Умолчание обязано оставить прежний расчёт неизменным."""
    base = _run(0.0)["summary"]
    assert base["llcr"] == pytest.approx(
        core.calculate(core.CalcRequest(
            inputs={**core.DEFAULT_INPUTS, "purchase_price_mln": 4000.0},
            tep=_tep(), rates=[]))["summary"]["llcr"])


def test_own_money_is_spent_before_the_bank_not_after():
    """Порядок важен: потраченные позже, они не сняли бы процентную нагрузку
    первых месяцев, ради которой их и вкладывают."""
    rows = _run(1000.0)["finance"]["rows"]
    first_own = next(i for i, row in enumerate(rows) if row.get("own_funds_draw", 0) > 0)
    first_bridge = next(i for i, row in enumerate(rows) if row.get("bridge_draw", 0) > 0)
    assert first_own <= first_bridge


# --- очереди ------------------------------------------------------------------

def test_the_pot_is_one_for_the_whole_project():
    """Без деления каждая очередь получила бы всю сумму, и проект
    «финансировал» бы себя вчетверо."""
    bundle = _phased(3000.0)
    assert bundle["consolidated"]["finance"]["own_funds_available"] == pytest.approx(
        3000.0 * 1e6, rel=1e-6)


def test_the_entry_money_goes_to_the_first_queue_by_default():
    bundle = _phased(3000.0)
    used = [phase["result"]["finance"]["own_funds_used"] for phase in bundle["phases"]]
    assert used[0] > 0
    assert sum(used[1:]) == 0


def test_the_consolidated_bridge_drops_too():
    without = _phased(0.0)["consolidated"]["report"]["financing"]["actual_bridge"]
    with_own = _phased(3000.0)["consolidated"]["report"]["financing"]["actual_bridge"]
    assert with_own < without


# --- расшифровка остаётся честной --------------------------------------------

def test_the_structure_still_adds_up_to_the_peak():
    financing = _run(3000.0)["report"]["financing"]
    rows = financing["actual_bridge_structure"]
    assert sum(row["value"] for row in rows) == pytest.approx(
        financing["actual_bridge"], rel=1e-6)


def test_own_funds_stand_as_a_line_of_their_own():
    """Они уменьшают долг, а не расходы: спрятать их внутри статей значило бы
    занизить стоимость стройки."""
    rows = _run(3000.0)["report"]["financing"]["actual_bridge_structure"]
    own = [row for row in rows if "собственными" in row["label"]]
    assert own and own[0]["value"] == pytest.approx(-3000.0 * 1e6, rel=1e-6)


def test_the_line_is_absent_without_own_funds():
    rows = _run(0.0)["report"]["financing"]["actual_bridge_structure"]
    assert not any("собственными" in row["label"] for row in rows)


# --- поверхности --------------------------------------------------------------

def test_the_field_is_on_the_form():
    assert any(field[0] == "pre_pf_own_funds_mln"
               for group in core.FIELD_GROUPS for field in group[1])
    assert core.DEFAULT_INPUTS["pre_pf_own_funds_mln"] == 0.0
    assert '"pre_pf_own_funds_mln": 0' in core.PAGE, "умолчание страницы отстало от движка"


def test_the_page_and_the_print_show_the_amount():
    assert "Собственные средства до ПФ" in core.PAGE
    import inspect
    assert "Собственные средства до ПФ" in inspect.getsource(core._build_developaid_pdf)


# --- поле доезжает до страницы, а не только до движка -------------------------

def test_the_page_renders_the_field_from_the_engine_list():
    """Список полей жил на странице отдельной копией, и поле, добавленное в
    движок, там не появлялось: движок его считал, а нарисовать было некому.
    Проверяем не наличие строки, а совпадение самих списков."""
    import json
    import re

    page = core.PAGE
    groups = json.loads(re.search(r"^const FIELD_GROUPS=(\[.*\]);$", page, re.M).group(1))
    assert groups == json.loads(json.dumps(core.FIELD_GROUPS, ensure_ascii=False)), \
        "список полей страницы разошёлся с движком"
    assert any(field[0] == "pre_pf_own_funds_mln" for group in groups for field in group[1])


def test_the_page_defaults_are_the_engine_defaults():
    """Вторая такая же копия: умолчания. Разойдясь, они дают поле, которое
    выглядит пустым, хотя движок считает его заполненным."""
    import json
    import re

    page = core.PAGE
    defaults = json.loads(re.search(r"^const INPUT_DEFAULT=(\{.*\});$", page, re.M).group(1))
    assert defaults == json.loads(json.dumps(core.DEFAULT_INPUTS, ensure_ascii=False))


def test_no_placeholder_survives_into_the_page():
    """Незамещённый плейсхолдер — это синтаксическая ошибка в браузере, то есть
    белый экран вместо приложения."""
    assert "__DEVELOPAID_" not in core.PAGE
