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

@pytest.mark.parametrize("rule", ref.ALL_RULES, ids=lambda r: r["rule_id"])
def test_every_rule_carries_its_source(rule):
    """Цитата, документ, пункт, редакция и официальная публикация — обязательны."""
    for field in ("rule_id", "territory", "unit", "rule_type", "conditions", "document", "point_table",
                  "effective_from", "official_source", "quote", "status"):
        assert field in rule, f"{rule.get('rule_id')}: нет поля {field}"
    assert rule["quote"].strip(), rule["rule_id"]
    assert rule["official_source"].startswith("http"), rule["rule_id"]
    assert rule["status"] in ("CONFIRMED_PRIMARY", "CONFIRMED_EXAMPLE",
                              "CONFIRMED_SECONDARY"), rule["rule_id"]


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
        sum(ratios) / len(ratios), abs=0.05)


def test_the_balance_line_is_the_plot_minus_the_minimum():
    """«Профицит (дефицит)» норматива — это участок минус S_min, а не наоборот.

    Допуск в полметра — не наша вольность: в самом примере МКД 1 показан как
    +885 при точном 884,5, остальные три строки сходятся до десятой. Округляет
    документ, и подгонять свою формулу под это округление нельзя."""
    for row in ref.LAND_SMIN_OFFICIAL_EXAMPLE["rows"]:
        assert row["plot_sqm"] - row["s_min_sqm"] == pytest.approx(
            row["balance_sqm"], abs=0.5), row["name"]


def test_the_kud_is_the_sum_of_its_rows():
    """К_уд складывается из шести строк таблицы № 13, а не задан числом."""
    assert ref.kud_for_quarter("6-7") == pytest.approx(
        ref.LAND_SMIN_OFFICIAL_EXAMPLE["kud"])


def test_the_kud_depends_on_the_storeys():
    """19,50 — это столбец 6–7 этажей. На малой этажности земли нужно в полтора
    раза больше, и подставлять 19,50 всем — та же ошибка, что московские нормы
    под видом областных."""
    assert ref.kud_for_quarter("≤3") == pytest.approx(28.67)
    assert ref.kud_for_quarter("4-5") == pytest.approx(22.31)
    assert ref.kud_for_quarter("6-7") == pytest.approx(19.50)


def test_the_parking_land_is_already_inside_the_kud():
    """Строка 1 таблицы входит в К_уд: прибавлять площадь паркинга к S_min
    отдельно значит считать землю дважды. Проверка — согласованностью самой
    таблицы: строка 1, делённая на потребность своей доли мест, даёт величину
    из приложения № 9."""
    table = ref.LAND_TABLE_13["value"]["1. Хранение индивидуального автотранспорта"]
    per_person = ref.PARKING_PERMANENT_RATE["value"] / 1000
    quarter = per_person * ref.PARKING_SHARE_IN_QUARTER["value"]
    district = per_person * ref.PARKING_SHARE_IN_DISTRICT["value"]
    # квартал 4–5 этажей ≈ надземный двухэтажный гараж (20 м² на место)
    assert table[1] / quarter == pytest.approx(20.0, abs=0.5)
    # квартал и жилой район 6–7 этажей ≈ открытая в уширении проезда (18 м²)
    assert table[2] / quarter == pytest.approx(18.0, abs=0.5)
    assert table[5] / district == pytest.approx(18.0, abs=0.5)
    assert "дважды" in ref.LAND_TABLE_13["double_count_warning"]


def test_the_appendix_nine_is_land_and_keeps_its_floors():
    """Две поправки, стоившие разбора: приложение № 9 — про землю, а не про ГНС,
    и этажность в его значениях уже учтена."""
    rule = ref.PARKING_AREA_BY_GARAGE_TYPE
    assert rule["rule_type"] == "RECOMMENDED"
    assert rule["hard_fail_allowed"] is False
    assert rule["floors_already_included"] is True
    assert rule["use_for_underground_gfa"] is False
    assert rule["value"]["надземный 5 и более этажей"][0] == 10.0
    assert rule["value"]["подземный 1 ярус под двором"] == (35.0, ref.BASIS_LAND_PLOT)
    assert rule["value"]["подземный 2 яруса под домом"] == (
        25.0, ref.BASIS_BUILDING_FOOTPRINT)


def test_the_open_parking_norm_may_be_used_hard():
    """22,5 стоит в самом п. 5.11 и рекомендательным не назван — в отличие от
    таблицы приложения № 9."""
    assert ref.PARKING_OPEN_AREA_PER_SPACE["hard_fail_allowed"] is True
    assert ref.PARKING_AREA_BY_GARAGE_TYPE["hard_fail_allowed"] is False


def test_the_population_divisor_is_the_flat_area_one():
    """Делится площадь квартир, а не ГНС и не СПП: перепутать — промах в разы."""
    rule = ref.LAND_POPULATION_PER_FLAT_AREA
    assert rule["value"] == 28.0
    assert "КВАРТИР" in rule["conditions"]


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
        assert rule["cumulative_with_others"] == "UNKNOWN", rule["rule_id"]


def test_the_flat_norm_declares_its_narrow_scope():
    """22,5 в 774-ПП стоит в абзаце про кластеры ИЖС и МЖС; общая норма живёт
    в п. 5.11 отдельной строкой. Обе записаны, и каждая знает свою область."""
    rule = ref.PARKING_FLAT_AREA_PER_SPACE_CLUSTER
    assert rule["value"] == 22.5
    assert "ИЖС" in rule["scope_warning"]
    assert ref.PARKING_OPEN_AREA_PER_SPACE["value"] == 22.5
    assert "G3a" in ref.CLOSED_BY_SOURCE_PACK


# --- актуальность видно снаружи ----------------------------------------------------

def test_the_status_names_the_revision_and_the_check_date():
    state = ref.reference_status()
    assert state["effective_from"] == "02.07.2026"
    assert state["in_force_since"] == "2026-07-03"
    assert state["official_source"].startswith("http")
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


# --- две записи одного источника не должны разойтись -------------------------------

def test_the_machine_rules_agree_with_the_written_source_pack():
    """Source pack лежит в двух видах: человеческий `data/normatives/mo/*.md`
    и машинный `mo_rngp_reference`. Это не копия ради копии — читают их разные
    (человек и движок), — но числа в них одни, и разойтись они могут молча.

    Заведено после того, как две сессии независимо собрали один и тот же пакет
    по 774-ПП. Тогда сошлось; сторож нужен на следующий раз."""
    pack = (ROOT / "data" / "normatives" / "mo" / "pp_774_2026-07-02.md")
    if not pack.exists():
        pytest.skip("source pack не найден")
    text = pack.read_text(encoding="utf-8")
    assert ref.PP_774["official_source"].split("/")[-1] in text
    assert ref.PP_774["in_force_since"].replace("2026-07-03", "03.07.2026") in text
    # Ключевые числа действующей редакции п. 5.12.
    assert "356" in text
    assert "30 автомобилей" in text
    assert "40%" in text and "60%" in text
    assert "800" in text and "1200" in text
    assert str(int(ref.PARKING_SHARE_IN_QUARTER["value"] * 100)) + "%" in text
    assert str(ref.PARKING_TEMPORARY_RATE["value"]).rstrip("0").rstrip(".") in text
