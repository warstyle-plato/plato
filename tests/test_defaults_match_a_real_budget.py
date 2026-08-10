"""Удельные умолчания — замер по банковскому бюджету, а не круглые числа.

Умолчания в тыс ₽/м² стояли круглыми: подготовка 1, благоустройство 5,
содержание площадки 1, проектирование 2,5 + 2,5. Сверка с бюджетом
собственного проекта (Гродненская, 18: ГНС наземной 19 341,14 м², подземная
3 733,2 м², лимит банка по главам) показала, что проценты у нас верные —
генподряд 7%, коммерческие 7% от выручки, служба заказчика 10,8% против
наших 10%, — а всё удельное занижено в 1,4–2,8 раза.

Ставки классов при этом сошлись: старт квартир 644,94 против пресета 650,
машино-место 5 000 против 5 000. Класс менять было не нужно, общие умолчания —
нужно, и разница между этими двумя выводами и есть содержание сверки.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy as core  # noqa: E402

# Замер: статья бюджета (млн ₽) и база, на которую движок делит.
GNS_ABOVE_SQM = 19_341.14
UNDERGROUND_SQM = 3_733.2
REVENUE_MLN = 13_134.68


def per_sqm(mln: float) -> float:
    """Тыс ₽ на м² ГНС наземной части — база удельных полей движка."""
    return mln * 1_000.0 / GNS_ABOVE_SQM


@pytest.mark.parametrize("key,fact_mln,tolerance", [
    ("preparation_th_per_sqm", 53.4, 0.2),      # подготовительный период
    ("utilities_th_per_sqm", 198.0, 0.2),       # наружные инженерные сети
    ("landscaping_th_per_sqm", 223.2, 0.2),     # благоустройство и озеленение
])
def test_the_unit_rates_follow_the_budget(key, fact_mln, tolerance):
    assert core.DEFAULT_INPUTS[key] == pytest.approx(per_sqm(fact_mln), abs=tolerance)


def test_the_site_maintenance_excludes_the_contractor_fee():
    """В книге содержание площадки (391,4 млн) несёт внутри себя вознаграждение
    генподрядчика (300,6 млн), а у движка это отдельное поле gc_fee_pct.
    Сложить их в одну ставку значило бы посчитать генподряд дважды."""
    site_only_mln = 391.38 - 300.63
    assert core.DEFAULT_INPUTS["site_maintenance_th_per_sqm"] == pytest.approx(
        per_sqm(site_only_mln), abs=0.2)


def test_the_design_stages_add_up_to_the_measured_line():
    """Проектирование, изыскания, экспертиза и авторский надзор идут в книге
    одной строкой 291,8 млн. Разбивка П/РД внутри неё — наша, а сумма — замер,
    и проверять надо именно сумму."""
    p = core.DEFAULT_INPUTS["design_p_th_per_sqm"]
    rd = core.DEFAULT_INPUTS["design_rd_th_per_sqm"]
    supervision = core.DEFAULT_INPUTS["author_supervision_pct"] / 100.0
    assert (p + rd) * (1 + supervision) == pytest.approx(per_sqm(291.8), abs=0.3)


def test_the_commercial_split_matches_the_ledger():
    """Сумма 7% была верной, а разбивка — нет: реклама 602,7 млн против
    риэлторских 285,3, то есть маркетинг вдвое больше расходов на продажи,
    а стояло наоборот."""
    marketing = core.DEFAULT_INPUTS["marketing_pct"]
    selling = core.DEFAULT_INPUTS["selling_pct"]
    assert marketing == pytest.approx(602.7 / REVENUE_MLN * 100, abs=0.2)
    assert selling == pytest.approx(285.3 / REVENUE_MLN * 100, abs=0.4)
    assert marketing > selling


def test_the_share_before_rve_is_not_optimistic():
    """85% задавали покрытие эскроу выше фактического, а покрытие задаёт ставку
    ПФ: модель показывала более дешёвые деньги, чем проект получает."""
    assert core.DEFAULT_INPUTS["share_before_rve_pct"] == 71


@pytest.mark.parametrize("key,value", [
    ("gc_fee_pct", 7),
    ("project_management_pct", 5),
    ("technical_supervision_pct", 5),
])
def test_the_percentages_were_already_right(key, value):
    """Сверка подтвердила проценты — их менять было не нужно, и тест держит их
    от правки «заодно»."""
    assert core.DEFAULT_INPUTS[key] == value


@pytest.mark.parametrize("key,value", [
    ("apartment_price_th", 650),
    ("parking_price_th", 5000),
    ("main_above_th_per_sqm", 190),
])
def test_the_business_class_preset_survived_the_check(key, value):
    """Старт квартир по факту 644,94 при пресете 650, машино-место 5 000 при
    5 000. Класс — не то, что показала сверка неверным."""
    assert core.PROJECT_CLASS_PRESETS["business"][key] == value
