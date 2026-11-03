"""Точка площадки КРТ — дом, а не улица длиной в пятнадцать километров.

«Варшавское шоссе, вл. 37, Нагатинская ул., влд. 3А/6» показывалась в Южном
Бутове (владелец, 02.09.2026, снимок экрана). Живая проба геокодера в тот же
день объяснила почему:

    «Москва, Варшавское шоссе, вл. 37» → addresstype `road`, 55,553 / 37,587
    «Москва, Варшавское шоссе, 37»     → 55,689 / 37,623, Нагатино-Садовники
    «Москва, Нагатинская улица, 3А»    → addresstype `building`, 55,681 / 37,632

Владение геокодеру не понятно, а улица понятна — и она отвечает охотно. Ответ
про улицу выглядит на карте так же уверенно, как адрес, и стоит в четырнадцати
километрах от площадки. Отсюда два правила: номер дома приводится к форме,
которую геокодер понимает, и тип ответа читается — это продолжение правила
«точность геокодера — часть ответа», записанного для рыночного модуля и не
дошедшего до лестницы КРТ.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_search.geocoder import GeoPoint  # noqa: E402
from market_search.subject import (  # noqa: E402
    _krt_geocode_candidates, geocode_rank, resolve_subject,
)

SITE = {
    "name": "Варшавское шоссе, вл. 37, Нагатинская ул., влд. 3А/6",
    "district": "Нагатино-Садовники",
    "geocode_query": "Москва, Нагатино-Садовники, Варшавское шоссе, вл. 37",
    "query": "krt:varshavskoe-shosse-vl-37-nagatinskaya-ul-vld-3a-6",
}


def test_the_holding_prefix_is_dropped_for_the_geocoder():
    asked = [query for query, _ in _krt_geocode_candidates(SITE, "krt:x")]
    assert "Москва, Варшавское шоссе, 37" in asked
    assert not any("вл." in query or "влд." in query for query in asked), asked
    # Составной номер спрашивается и целиком, и до дроби: «3А/6» город пишет
    # владением, а дом в базе стоит как «3А».
    assert "Москва, Нагатинская ул., 3А/6" in asked
    assert "Москва, Нагатинская ул., 3А" in asked
    # Район остаётся последним: он хуже любого адреса, но лучше пустоты.
    assert asked[-1] == "Москва, район Нагатино-Садовники"


def test_a_street_answer_is_not_an_address_answer():
    road = GeoPoint(55.553, 37.587, "Варшавское шоссе, район Южное Бутово",
                    "nominatim", "road")
    house = GeoPoint(55.681, 37.632, "3А, Нагатинская улица", "nominatim", "building")
    district = GeoPoint(55.67, 37.63, "район Нагатино-Садовники", "nominatim", "suburb")
    assert geocode_rank(road, "Москва, Варшавское шоссе, 37") == 1
    assert geocode_rank(house, "Москва, Нагатинская ул., 3А") == 3
    assert geocode_rank(district, "Москва, район Нагатино-Садовники") == 0


def test_a_silent_provider_is_judged_by_its_own_answer():
    """Провайдер типа не назвал — спрашиваем, есть ли в ответе номер дома."""
    named = GeoPoint(55.689, 37.623, "Москва 115127, 37, Варшавское шоссе", "dadata", None)
    vague = GeoPoint(55.7, 37.6, "Москва", "dadata", None)
    assert geocode_rank(named, "Москва, Варшавское шоссе, 37") == 3
    assert geocode_rank(vague, "Москва, Варшавское шоссе, 37") == 2


def test_the_best_answer_wins_not_the_first():
    """Улица отвечает первой — точка всё равно ставится по дому."""
    answers = {
        "Москва, Варшавское шоссе, 37": GeoPoint(
            55.553, 37.587, "Варшавское шоссе, Южное Бутово", "nominatim", "road"),
        "Москва, Нагатинская ул., 3А/6": GeoPoint(
            55.681, 37.632, "3А, Нагатинская улица", "nominatim", "building"),
    }
    asked: list[str] = []

    def geocode(query: str) -> GeoPoint:
        asked.append(query)
        if query in answers:
            return answers[query]
        raise RuntimeError("место не найдено")

    subject = resolve_subject(
        "krt:test", geocode=geocode, find_krt=lambda text: dict(SITE))
    assert (round(subject.latitude, 3), round(subject.longitude, 3)) == (55.681, 37.632)
    # Дом найден — район не спрашивается вовсе: лишний запрос к геокодеру.
    assert "Москва, район Нагатино-Садовники" not in asked


def test_a_street_only_point_says_so():
    def geocode(query: str) -> GeoPoint:
        if "район" in query:
            raise RuntimeError("место не найдено")
        return GeoPoint(55.553, 37.587, "Варшавское шоссе", "nominatim", "road")

    subject = resolve_subject(
        "krt:test", geocode=geocode, find_krt=lambda text: dict(SITE))
    assert any("только улицу, а не дом" in note for note in subject.notes), subject.notes
