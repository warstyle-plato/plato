"""Объём Программы реновации берётся из ОБОРОТА, а не из наибольшего числа рядом.

Владелец открыл каталог и сказал: «Опять реновации. А там же надо выделить 10%
на нужды реновации» (04.09.2026, снимок площадки «Задонский проезд, влд. 1А,
Ясеневая ул., влд. 48»). Он прав дважды: доля там действительно десятая часть,
и на экране её не было — стояло «в документе сказано о городских нуждах, объём
не назван, −10%».

Живой ответ прода по этой площадке показал, что причин три, и каждая своя.

1. Разбор брал НАИБОЛЬШЕЕ число предложения. В решении их три — 173 200 м²
   предельной СПП, 150 940 м² жилья и 15 100 м² реновации, — и бралось первое.
   Дальше скрининг обрезал его по жилью (`min`), и десятая часть превращалась в
   уверенные 100%: площадка выходила без рыночного продукта вовсе. Соседнее
   решение (5-й Верхний Михайловский) ловилось так же — 87 690 м² итога зоны
   вместо 85 580 м² её реновации.
2. Блок реновации, посчитанный скринингом, не доезжал до строки рейтинга: на
   268 площадках прода поле пустое у ВСЕХ.
3. Поэтому экран падал в запасной путь «объём не назван» — утверждение о
   ДОКУМЕНТЕ, сделанное из нашего пробела чтения. Тот же случай, что пустой
   ответ НСПД, показанный как отсутствие ограничений.

Предложения ниже — дословно из двух живых решений (прод, 04.09.2026), вместе с
пробелами внутри слов, которые оставляет разбор PDF: «объекты жило го
назначения», «объектов кап итального строительства». Совпадение по целым словам
на них не работает, и это часть проверки.

Запуск: python3 -m pytest tests/test_the_renovation_volume_is_read_from_its_clause.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402

from auction_search.krt_ranking import score_row  # noqa: E402
from auction_search.krt_screening import build_krt_model_screening  # noqa: E402
from market_search.krt_requirements import renovation_volume  # noqa: E402

# Задонский проезд, влд. 1А / Ясеневая ул., влд. 48 — одна зона, десятая часть.
ZADONSKY = [
    "Предельная (максимальная) суммарная поэтажная площадь объектов капитального "
    "строительства в габаритах наружных стен – 173 200 кв.м, в том числе: - объекты "
    "жилого назначения – 150 940 кв.м, в том числе для реализации Программы реновации "
    "жилищного фонда в городе Москве – 15 100 кв.м; - объекты общественно-делового и "
    "иного назначения – 22 260 кв.м.",
    "Объектов капитального строительства жилого назн ачения площадью не менее 15 100 "
    "кв.м в целях реализации Программы реновации жилищного фонда в городе Москве.",
]

# 5-й Верхний Михайловский пр-д — две зоны, и вместе это ВСЁ жильё площадки.
MIHAILOVSKY = [
    "Предельная (максимальная) суммарная поэтажная площадь объектов кап итального "
    "строительства в габаритах наружных стен – 28 610 кв. м, в том числе: - объекты "
    "жило го назначения – 9 600 кв. м, в том числе для реализации Программы реновации "
    "жилищного фонда в городе Москве – 9 600 кв. м; - объекты общественно-делового и "
    "иного назначения – 19 010 кв. м.",
    "Предельная (максимальная) суммарная поэтажная площадь объектов капитального "
    "строительства в габаритах наружных стен – 87 690 кв. м, в том числе: - объекты "
    "жилого назначения – 85 580 кв. м, в том числе для реализации Программы реновации "
    "жилищного фонда в городе Москве – 85 580 кв. м; - объекты коммунального, "
    "производственного и иного назначения – 2 110 кв. м.",
    "Объектов капитального строительства жилого назначения площадью не менее 9 600 "
    "кв. м в целях реализации Программы реновации жилищного фонда в городе Москве. 4.1.2.",
    "Объектов капитального строительства жилого назначения общей площадью не менее "
    "85 580 кв.м. в целях реализации Программы реновации жилищного фонда в городе "
    "Москве. 4.3.2.",
]


def test_the_volume_is_the_one_named_by_the_clause() -> None:
    """Ровно та поломка: бралась предельная СПП площадки вместо объёма реновации."""
    got = renovation_volume(ZADONSKY)
    assert got["area_sqm"] == 15_100, "объём взят не из оборота, называющего программу"
    assert got["area_sqm"] != 173_200, "взята предельная СПП всей площадки"
    assert got["housing_sqm"] == 150_940, "парная площадь жилья не прочитана"
    assert got["basis"] == "zone_programme_clause"
    assert round(100 * got["area_sqm"] / 150_940) == 10, "десятая часть, а не всё жильё"


def test_zones_are_parts_and_they_sum() -> None:
    """Две зоны отдают 9 600 и 85 580 — вместе ровно жильё каталога, 95 180 м²."""
    got = renovation_volume(MIHAILOVSKY)
    assert got["zones"] == 2, "перечень зон прочитан не весь"
    assert got["area_sqm"] == 95_180, "части зон не сложились"
    # Самопроверка полноты: сумма парных площадей жилья сходится с каталогом.
    assert got["housing_sqm"] == 95_180


def test_a_duty_clause_repeats_the_volume_and_is_not_added_to_it() -> None:
    """Обязательство повторяет число ТЭП другими словами — сложить их значит удвоить."""
    got = renovation_volume(MIHAILOVSKY)
    assert got["area_sqm"] == 95_180, "обязательственные обороты сложены с ТЭП"
    only_duty = renovation_volume(ZADONSKY[1:])
    assert only_duty["area_sqm"] == 15_100, "без оборота ТЭП объём не прочитан вовсе"
    assert only_duty["basis"] == "duty_clause", "основание чтения не названо"


def test_a_mention_without_a_volume_stays_unknown() -> None:
    """«Доля неизвестна» — это не «доли нет» и не «забирают всё»."""
    got = renovation_volume([
        "Квартал строится в рамках Программы реновации жилищного фонда в городе Москве."])
    assert got["mentioned"] is True
    assert got["area_sqm"] is None
    assert got["basis"] == "mentioned_without_volume"


def _market(price: int = 680_000) -> dict:
    return {
        "analysis": {"site": {"segment": "бизнес", "price_per_sqm": price,
                              "sold_lot_avg": 50.0, "units_per_month": 21.5}},
        "price_hint": {"entry_per_sqm": price, "price_per_sqm": price},
    }


PROJECT = {
    "slug": "yasenevaya-ul-vl-48",
    "name": "Задонский проезд, влд. 1А, Ясеневая ул., влд. 48",
    "housing_gfa_sqm": 150_940,
    "business_gfa_sqm": 22_260,
    "total_gfa_sqm": 173_200,
}


def _screen(renovation: dict) -> dict:
    return build_krt_model_screening(
        PROJECT, _market(), core,
        requirements={"available": True, "decision_available": True,
                      "source_level": "official_project_decision",
                      "renovation": renovation})


def test_the_named_share_leaves_the_rest_to_the_market() -> None:
    """Десятая часть уходит городу, девять десятых продаются — это и просил владелец."""
    result = _screen(renovation_volume(ZADONSKY))
    reno = result["renovation"]
    assert reno["spp_sqm"] == 15_100
    assert 0.09 < reno["share"] < 0.11, f"доля {reno['share']} вместо десятой части"
    assert reno["whole_site"] is False, "десятая часть прочитана как весь объём жилья"
    assert not reno["not_counted_reason"]
    row = next(r for r in result["programme"]["tep"] if r["kind"] == "apartments") \
        if isinstance(result.get("programme", {}).get("tep"), list) else None
    if row is not None:
        assert row["transfer"] > 0, "переданные метры не помечены"


def test_a_volume_bigger_than_the_housing_is_not_clamped_into_the_whole_site() -> None:
    """Обрезка `min` превращала непонятое число в уверенные 100% — и молча.

    Это ровно то, что делал прежний разбор: 173 200 м² предельной СПП обрезались
    по жилью и давали «всё жильё площадки — реновация». Обрезка, прячущая
    противоречие, — не проверка, а её отсутствие.
    """
    result = _screen({"mentioned": True, "area_sqm": 173_200, "housing_sqm": None,
                      "zones": 1, "basis": "zone_programme_clause", "quote": ""})
    reno = result["renovation"]
    assert reno["whole_site"] is False, "непонятое число выдано за 100% реновации"
    assert reno["spp_sqm"] == 0, "по непонятому числу нельзя вычитать выручку"
    assert reno["not_counted_reason"], "причина отказа не названа"
    assert any("реновации" in item and "больше" in item
               for item in result["assumptions"]), "пробел не назван в предпосылках"


def test_an_incomplete_zone_list_refuses_instead_of_undercounting() -> None:
    """Сумма парных площадей жилья не сошлась — перечень зон прочитан не весь."""
    result = _screen({"mentioned": True, "area_sqm": 9_600, "housing_sqm": 9_600,
                      "zones": 1, "basis": "zone_programme_clause", "quote": ""})
    assert result["renovation"]["not_counted_reason"], (
        "неполный перечень зон принят за полный")


def test_the_row_carries_the_volume_it_computed() -> None:
    """Посчитанное на сервере, но не доехавшее до строки, неотличимо от непосчитанного."""
    result = _screen(renovation_volume(ZADONSKY))
    row = score_row(PROJECT, result)
    assert row["renovation"]["spp_sqm"] == 15_100, "объём не доехал до строки рейтинга"
    assert 0.09 < row["renovation"]["share"] < 0.11


# --- то же на экране: снижение обязано быть утверждением о документе ---------

from test_krt_score_is_lowered_not_replaced import score  # noqa: E402

SITE = {"slug": "site", "name": "КРТ", "status": "Планируемый",
        "housing_gfa_sqm": 150_940, "total_gfa_sqm": 173_200}
CITY_NEEDS = {"intent": {"decision_read": True,
                         "city_needs": ["в целях реализации Программы реновации"]}}


def _labels(got: dict) -> str:
    return " | ".join(cut["label"] for cut in got["cuts"])


def test_an_unread_decision_is_our_gap_and_not_the_documents_silence() -> None:
    """Строка рейтинга без объёма — это «не читали», а не «в решении не сказано».

    Ровно так выглядел экран владельца: у площадки, решение которой называет
    15 100 м², стояло «объём не назван, −10%».
    """
    got = score(None, rank={}, site=SITE, requirements=CITY_NEEDS)
    assert "объём не назван" not in _labels(got), (
        "наш пробел чтения выдан за молчание документа")
    assert any("ещё не прочитано" in gap for gap in got["gaps"]), (
        "пробел скрыт: молча снятое снижение читается как «всё в порядке»")


def test_a_named_volume_is_never_called_unnamed() -> None:
    """Объём прочитан — снижения «не назван» быть не может ни при каких условиях."""
    rank = {"renovation": {"spp_sqm": 15_100, "share": 0.1, "mentioned": True,
                           "basis": "zone_programme_clause", "zones": 1,
                           "not_counted_reason": "", "whole_site": False}}
    got = score(None, rank=rank, site=SITE, requirements=CITY_NEEDS)
    assert "объём не назван" not in _labels(got)


def test_an_unreliable_volume_does_not_lower_the_score_but_is_said_out_loud() -> None:
    """Прочитали и не поняли — наш пробел: балл он не снижает, молчать нельзя."""
    rank = {"renovation": {"spp_sqm": 0, "share": 0.0, "mentioned": True,
                           "basis": "zone_programme_clause", "zones": 1,
                           "not_counted_reason": "объём реновации по решению больше "
                                                 "всего жилья площадки",
                           "whole_site": False}}
    got = score(None, rank=rank, site=SITE, requirements=CITY_NEEDS)
    assert "объём не назван" not in _labels(got)
    assert any("ненадёжно" in gap for gap in got["gaps"]), "пробел не назван"
    assert any("выручка площадки завышена" in gap for gap in got["gaps"])


def test_a_document_that_really_says_nothing_still_lowers_the_score() -> None:
    """Прочитали и в решении объёма нет — это ответ документа, и он снижает балл."""
    rank = {"renovation": {"spp_sqm": 0, "share": 0.0, "mentioned": True,
                           "basis": "mentioned_without_volume", "zones": 0,
                           "not_counted_reason": "", "whole_site": False}}
    got = score(None, rank=rank, site=SITE, requirements=CITY_NEEDS)
    assert "объём не назван" in _labels(got), (
        "молчание документа перестало быть ответом документа")
