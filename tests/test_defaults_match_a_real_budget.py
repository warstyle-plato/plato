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
])
def test_the_unit_rates_follow_the_budget(key, fact_mln, tolerance):
    assert core.DEFAULT_INPUTS[key] == pytest.approx(per_sqm(fact_mln), abs=tolerance)


LANDSCAPING_FACT_MLN = 223.2  # благоустройство и озеленение, тот же бюджет


def test_the_landscaping_rule_disagrees_with_the_measured_budget():
    """ОТКРЫТЫЙ вопрос, а не пройденная проверка.

    Благоустройство с 10.09.2026 считается по физической площади двора:
    «5 метров на человека, далее по площади комфорт 10, бизнес 25, элитный 50
    на метр» (решение владельца). База верна — благоустраивают двор, а не дом,
    — а вот два числа с бюджетом ЕГО ЖЕ проекта не сходятся.

    **Ставку берут по классу ЭТОГО проекта, а не по умолчанию движка.** Первый
    замер сравнил факт с комфортной ставкой 10 и объявил разрыв в 11,7 раза, а
    Гродненская, 18 помечена бизнесом в ОБОИХ файлах справочника
    (`housing_class: business`, `base_class: business`) — то есть ставка 25 и
    разрыв 4,7 раза. Владелец считал по 50: «по ставке 50 тысяч за метр это
    100 млн?? Разве нет» (12.09.2026) — арифметика его верна (2 000 × 50), но
    50 это элитный, и на элитной ставке норма даёт 95,25 млн. Ошибка того же
    класса, что ловится в удельных: делитель берут оттуда же, откуда числитель.

    На Гродненской, 18 статья стоила 223,2 млн ₽ при 19 341,14 м² наземной
    ГНС: 12 571,7 м² квартир, 381 житель, 1 905 м² двора. Обратным счётом
    сходится либо 23,4 м² на человека при ставке бизнеса 25, либо 117,2 тыс ₽
    за метр двора при норме 5 — и второе число от класса не зависит вовсе.
    Какое из двух неверно, решает владелец: «расхождение двух источников — не
    всегда ошибка одного из них», норма бывает полом, а проект строит больше.
    Правдоподобная третья причина названа отдельно и не подставлена в расчёт:
    двор над подземным паркингом — это эксплуатируемая кровля, а не газон, и
    метр такого двора стоит не как метр озеленения. Пока не решено,
    расхождение стоит здесь числом — молча оставленное, оно читается как
    согласие.
    """
    import math

    apartments = GNS_ABOVE_SQM * 0.65        # доля продаваемой в ГНС у жилья
    population = math.ceil(apartments / core._PARKING_2118_SQM_PER_PERSON)
    per_person = core.DEFAULT_INPUTS["landscaping_area_per_person_sqm"]
    # Класс проекта берётся из справочника, а не из умолчаний движка.
    benchmark_class = "business"
    rate = core.PROJECT_CLASS_PRESETS[benchmark_class]["landscaping_th_per_sqm"]
    by_rule_mln = population * per_person * rate / 1000.0

    assert (per_person, rate) == (5.0, 25), (
        "числа владельца изменились — перемерьте расхождение заново")
    assert (population, population * per_person) == (381, 1905), (
        "физическая цепочка сдвинулась — перемерьте")
    assert by_rule_mln == pytest.approx(47.6, abs=0.2), by_rule_mln
    ratio = LANDSCAPING_FACT_MLN / by_rule_mln
    assert ratio == pytest.approx(4.7, abs=0.1), ratio
    # Обратный счёт — те два числа, между которыми выбирать владельцу.
    assert LANDSCAPING_FACT_MLN * 1000 / (population * rate) == pytest.approx(23.4, abs=0.2)
    assert LANDSCAPING_FACT_MLN * 1000 / (population * per_person) == pytest.approx(117.2, abs=0.5)
    # И то, что класс проекта действительно бизнес, — не память, а справочник.
    assert _benchmark_housing_class() == benchmark_class


def _benchmark_housing_class() -> str:
    """Класс собственного проекта — из справочника, один ответ на оба файла."""
    import json

    root = Path(__file__).resolve().parent.parent / "reference_data" / "statistics"
    rows = json.loads((root / "normalized_benchmarks.json").read_text("utf-8"))
    named = {str(row.get("housing_class")) for row in rows
             if "родненск" in str(row.get("source", ""))}
    structure = json.loads((root / "developaid_cost_structure.json").read_text("utf-8"))
    named |= {str(one.get("housing_class")) for one in structure.get("sources", [])
              if "родненск" in str(one.get("source", ""))}
    assert len(named) == 1, f"справочник называет класс по-разному: {named}"
    return named.pop()


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


def test_the_share_before_rve_stayed_at_the_owners_value():
    """Замер даёт 71% (69% по машино-местам, 73% по кладовым), но доля осталась
    на 85% — решение владельца (10.08.2026). Она не из той группы, что удельные
    ставки: те задают расход, а доля задаёт покрытие эскроу, покрытие — ставку
    ПФ, и на 71% проект по умолчаниям перестаёт гасить долг. Тест держит
    значение от правки «за компанию» со следующей сверкой."""
    assert core.DEFAULT_INPUTS["share_before_rve_pct"] == 85


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
