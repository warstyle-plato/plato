"""Справочник РНГП Московской области отвечает за своё происхождение.

Мы возили московские нормативы под видом областных и не могли этого увидеть:
числа выглядят одинаково достоверно независимо от того, из какого документа
они взяты и в какой редакции. Здесь заведено правило: норма живёт в справочнике
только вместе с прямой цитатой, документом, редакцией и ссылкой на официальную
публикацию. Всё, что этого не имеет, лежит отдельно, в списке дыр, и в расчёт
не идёт.

Главная проверка — официальный пример из приложения 7 к 713/30 (в редакции
774-ПП). Он даёт четыре строки с готовыми ответами, и наша формула обязана
воспроизвести их до десятой доли. Это единственная сверка методики, которая у
нас есть без доступа к архитектору: норматив проверяет сам себя.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mo_rngp_reference as ref  # noqa: E402


# --- норма без происхождения не норма ---------------------------------------------

@pytest.mark.parametrize("rule", ref.ALL_RULES, ids=lambda r: r["key"])
def test_every_rule_carries_its_source(rule):
    """Цитата, документ, пункт, редакция и официальная публикация — обязательны."""
    for field in ("key", "unit", "rule_type", "conditions", "document", "point",
                  "effective_revision", "official_publication", "quote", "status"):
        assert field in rule, f"{rule.get('key')}: нет поля {field}"
    assert rule["quote"].strip(), rule["key"]
    assert rule["official_publication"].startswith("http"), rule["key"]
    assert rule["status"] in ("CONFIRMED_PRIMARY", "CONFIRMED_EXAMPLE"), rule["key"]


def test_the_holes_are_not_pretending_to_be_rules():
    """Дыры лежат отдельно и не имеют значений: иначе их подхватят как нормы."""
    for key, hole in ref.UNRESOLVED.items():
        assert "question" in hole and hole["question"].strip(), key
        assert "source_seen" in hole, key
        assert "value" not in hole, f"{key}: у дыры не должно быть значения"


def test_the_moscow_methodology_is_marked_as_superseded():
    """Московские формулы паркинга в область не переносятся — это записано."""
    superseded = " ".join(ref.SUPERSEDED_MOSCOW_RULES.values())
    assert "356" in superseded
    assert "30" in superseded


# --- официальный пример воспроизводится -------------------------------------------

def test_the_official_example_reproduces():
    """S_min = К_уд × расчётное население — до десятой доли, все четыре строки."""
    example = ref.LAND_SMIN_OFFICIAL_EXAMPLE
    for row in example["rows"]:
        assert row["population"] * example["kud"] == pytest.approx(
            row["s_min_sqm"], abs=0.05), row["name"]


def test_the_population_divisor_matches_the_example():
    """Расчётное население восстановлено из площади квартир: одно отношение на
    все строки. Разойдись оно — значит, делитель не один и правило другое."""
    ratios = [row["flat_area_sqm"] / row["population"]
              for row in ref.LAND_SMIN_OFFICIAL_EXAMPLE["rows"]]
    assert max(ratios) - min(ratios) < 0.05, ratios
    assert ref.LAND_POPULATION_PER_FLAT_AREA["value"] == pytest.approx(
        sum(ratios) / len(ratios), abs=0.02)


def test_the_balance_line_is_the_plot_minus_the_minimum():
    """«Профицит (дефицит)» норматива — это участок минус S_min, а не наоборот.

    Допуск в полметра — не наша вольность: в самом примере МКД 1 показан как
    +885 при точном 884,5, остальные три строки сходятся до десятой. Округляет
    документ, и подгонять свою формулу под это округление нельзя."""
    for row in ref.LAND_SMIN_OFFICIAL_EXAMPLE["rows"]:
        assert row["plot_sqm"] - row["s_min_sqm"] == pytest.approx(
            row["balance_sqm"], abs=0.5), row["name"]


def test_the_kud_is_the_sum_of_its_rows():
    """К_уд = 19,50 складывается из шести строк таблицы № 13, а не задан числом."""
    rule = ref.LAND_KUD_EXAMPLE_URBAN_15_50K
    assert sum(rule["value"].values()) == pytest.approx(rule["total"], abs=1e-9)
    assert rule["total"] == pytest.approx(ref.LAND_SMIN_OFFICIAL_EXAMPLE["kud"])


# --- парковки по действующей редакции ----------------------------------------------

def test_the_permanent_rate_is_the_area_one():
    """90% от 356 на тысячу — п. 5.12 в редакции 774-ПП."""
    assert ref.PARKING_PERMANENT_RATE["value"] == pytest.approx(320.4)


def test_the_temporary_rate_is_a_minimum_not_a_share():
    """Ключевая замена: в области временное хранение задано числом на тысячу
    жителей, а не долей от постоянного, как считает московская методика."""
    rule = ref.PARKING_TEMPORARY_RATE
    assert rule["value"] == 30.0
    assert rule["rule_type"] == "MANDATORY_MINIMUM"
    assert rule["unit"] == ref.UNIT_CARS_PER_1000


def test_not_all_spaces_belong_to_the_plot():
    """Норматив прямо разрешает 60% мест вне квартала — значит «на участке не
    хватает земли под все места» отказом быть не может."""
    assert ref.PARKING_SHARE_IN_QUARTER["value"] == 0.40
    assert ref.PARKING_SHARE_IN_DISTRICT["value"] == 0.60


def test_the_reductions_do_not_claim_to_be_cumulative():
    """Складывать послабления текст не разрешает — и справочник этого не решает
    за него: пока не выяснено, стоит UNKNOWN."""
    for rule in (ref.PARKING_REDUCTION_STATION_WALK,
                 ref.PARKING_REDUCTION_TRANSIT_TO_STATION,
                 ref.PARKING_REDUCTION_COOPERATIVE):
        assert rule["cumulative_with_others"] == "UNKNOWN", rule["key"]


def test_the_flat_norm_declares_its_narrow_scope():
    """22,5 в первичном тексте видно только для кластеров ИЖС и МЖС. Пока общая
    норма не подтверждена, справочник обязан об этом предупреждать."""
    rule = ref.PARKING_FLAT_AREA_PER_SPACE_CLUSTER
    assert rule["value"] == 22.5
    assert "ИЖС" in rule["scope_warning"]
    assert "G3a" in ref.UNRESOLVED


# --- актуальность видно снаружи ----------------------------------------------------

def test_the_status_names_the_revision_and_the_check_date():
    state = ref.reference_status()
    assert state["effective_revision"] == "02.07.2026"
    assert state["in_force_since"] == "2026-07-03"
    assert state["official_publication"].startswith("http")
    date.fromisoformat(state["verified_at"])
    assert state["rules_unresolved"] == len(ref.UNRESOLVED)


def test_the_reference_registers_in_the_freshness_list():
    """Справочник, о сроке годности которого не напоминают, устареет молча."""
    import main_legacy as core

    rows = {item["key"]: item for item in core.reference_freshness()}
    assert "mo_rngp" in rows
    entry = rows["mo_rngp"]
    assert "02.07.2026" in entry["current"]
    assert entry["source"].startswith("Постановление Правительства Московской области")


def test_a_year_without_a_check_turns_the_reminder_on():
    """Через год после сверки строка обязана загореться."""
    import main_legacy as core

    verified = date.fromisoformat(ref.reference_status()["verified_at"])
    late = verified.replace(year=verified.year + 1, day=max(1, verified.day - 1))
    rows = {item["key"]: item for item in core.reference_freshness(late)}
    assert rows["mo_rngp"]["stale"] is False
    much_later = verified.replace(year=verified.year + 2)
    rows = {item["key"]: item for item in core.reference_freshness(much_later)}
    assert rows["mo_rngp"]["stale"] is True
