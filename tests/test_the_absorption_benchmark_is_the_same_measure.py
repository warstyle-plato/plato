"""Знаменатель поглощения мерится тем же, чем числитель — средним темпом.

Решение владельца 27.09.2026. Числитель рейтинга КРТ — СРЕДНИЙ месячный темп
аналогов Пульса за период; знаменателем же стояла медиана Москвы за ОДИН
последний месяц (`series[index]`). Это две разные величины под одним именем, и
отношение из них — не отношение.

Замер владельца на 2026-08, медиана «1 месяц» → медиана «среднее 12 мес.»:

    Бизнес        708 (n  79) → 884 (n 102)
    Комфорт       670 (n  50) → 1016 (n 66)
    Премиум       304 (n  43) → 550 (n 52)
    Элит/De Luxe  236 (n   4) → 292 (n 16)

Перекос около 1,45× в одну сторону — то есть одномесячный эталон СИСТЕМАТИЧЕСКИ
занижал знаменатель и завышал балл поглощения. И выборка при этом росла: месяц
без сделок выбрасывал из неё работающий проект целиком.

Запуск: python3 -m pytest tests/test_the_absorption_benchmark_is_the_same_measure.py -q
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import market_reference  # noqa: E402
from market_search.market_reference import MoscowMarket  # noqa: E402

DATA = ROOT / "market_search" / "registry_data"
# Числа замера владельца: класс → (одномесячная медиана, медиана средних).
OWNER_MEASURED = {
    "Бизнес": (708.2, 883.8),
    "Комфорт": (669.7, 1016.0),
    "Премиум": (304.4, 549.7),
    "Элит/De Luxe": (235.8, 292.2),
}


def _dynamics() -> dict:
    newest = None
    for path in sorted(DATA.glob("moscow-dynamics-*.json")):
        newest = json.loads(path.read_text(encoding="utf-8"))
    assert newest, "нет городской динамики — проверять нечем"
    return newest


def _one_month_median() -> dict[str, tuple[float, int]]:
    """ПРЕЖНЯЯ мера — срез последнего месяца. Считается здесь, чтобы разница
    была измерена на тех же данных, а не взята литералом."""
    got = _dynamics()
    months = list(got.get("months") or [])
    wanted = str(got.get("last_month") or "")
    index = months.index(wanted) if wanted in months else len(months) - 1
    by: dict[str, list[float]] = {}
    for project in (got.get("projects") or {}).values():
        segment = str(project.get("segment") or "").strip()
        series = project.get("area") or []
        if not segment or index >= len(series) or series[index] is None:
            continue
        value = float(series[index])
        if value > 0:
            by.setdefault(segment, []).append(value)
    return {segment: (round(statistics.median(values), 1), len(values))
            for segment, values in by.items() if values}


def test_the_benchmark_is_the_average_pace_not_one_month() -> None:
    """Эталон равен медиане СРЕДНИХ темпов, а не срезу месяца.

    Падает на прежней мере: у всех четырёх классов числа расходятся в разы
    сотых, а не в округлении.
    """
    city = MoscowMarket.bundled()
    was = _one_month_median()

    for segment, (one_month, average) in OWNER_MEASURED.items():
        assert city.area_median(segment) == pytest.approx(average, abs=0.05), segment
        # Прежняя мера на тех же данных даёт другое число — значит проверка
        # выше не могла бы пройти на одномесячном эталоне.
        assert was[segment][0] == pytest.approx(one_month, abs=0.05), segment
        assert city.area_median(segment) != pytest.approx(was[segment][0], abs=0.05)

    # Направление перекоса — одно у всех классов: одномесячный срез занижал
    # эталон, то есть завышал балл поглощения у всего каталога.
    assert all(city.area_median(segment) > was[segment][0]
               for segment in OWNER_MEASURED), "перекос перестал быть односторонним"


def test_the_window_lets_more_projects_speak() -> None:
    """Выборка класса растёт: месяц без сделок больше не выбрасывает проект."""
    city = MoscowMarket.bundled()
    was = _one_month_median()
    now = city.payload["_area_median_projects"]

    for segment, (_, average) in OWNER_MEASURED.items():
        assert now[segment] > was[segment][1], segment
    assert now["Бизнес"] == 102 and now["Комфорт"] == 66, now


def test_the_window_and_the_threshold_are_declared_once() -> None:
    """Окно и порог — объявленные константы, а не числа внутри цикла."""
    assert market_reference.ABSORPTION_WINDOW_MONTHS == 12
    assert market_reference.ABSORPTION_MIN_MONTHS == 3
    city = MoscowMarket.bundled()
    assert city.payload["_area_median_window_months"] == 12
    assert city.payload["_area_median_min_months"] == 3
    source = Path(market_reference.__file__).read_text(encoding="utf-8")
    body = source[source.index("area_by_segment: dict[str, list[float]] = {}"):
                  source.index('payload["_area_median_by_segment"]')]
    assert "ABSORPTION_WINDOW_MONTHS" in body and "ABSORPTION_MIN_MONTHS" in body
    assert "series[index]" not in body, (
        "эталон снова считается срезом одного месяца")


def test_one_benchmark_for_every_reader() -> None:
    """Эталон один: читатели зовут `area_median`, второй меры рядом нет."""
    import re

    for module in ("auction_search/api.py", "auction_search/krt_screening.py",
                   "market_search/metrics.py"):
        source = (ROOT / module).read_text(encoding="utf-8")
        assert "_area_median_by_segment" not in source, (
            f"{module} читает свод эталона мимо area_median")
        assert not re.search(r"\bseries\[index\]", source), module


# --- неполная пара: локальная медиана есть, эталона нет ---------------------
#
# Пробел №2, найденный при сверке с #528 и оставленный им нетронутым. Поглощение
# считается ПАРОЙ «локальная медиана / эталон класса». Случай «локальная есть,
# эталона нет» не разбирала ни одна ветвь: составляющая молча уходила в missing,
# без подстановки и без названной причины. Замер прода 27.09.2026 подстановкой
# живых строк: две площадки из 365 теряли балл именно так.

SLUG = "alpha"
PROJECT = {"slug": SLUG, "name": "Альфа", "status": "Планируемый", "area_ha": 5.0,
           "housing_gfa_sqm": 100_000.0}


class _CityWithoutBenchmark:
    """Город без медианы поглощения по классу: снимок цены есть, эталона нет."""

    def area_median(self, segment):
        return None

    def snapshot(self, segment):
        import types as _types

        return _types.SimpleNamespace(price_median=500_000.0)

    def segments(self):
        return ["Комфорт"]


class _Registry:
    def find(self, query):
        slug = str(query).split(":", 1)[-1]
        return dict(PROJECT) if slug == SLUG else None

    def catalogue(self, refresh=False):
        return [dict(PROJECT)]

    def decisions(self, refresh=False):
        return []


@pytest.fixture()
def app_without_benchmark(tmp_path, monkeypatch):
    """Приложение с настоящими маршрутом и фоновой сборкой — как у #528."""
    import time
    import types

    from fastapi import FastAPI

    from auction_search import api
    from auction_search.krt_ranking import KrtRanking

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AUCTIONS_VIEW_KEY", raising=False)
    monkeypatch.delitem(sys.modules, "developaid_core", raising=False)
    application = FastAPI()
    application.state.market_discovery_service = types.SimpleNamespace(
        krt=_Registry(), city=_CityWithoutBenchmark())
    api.install(application)
    ranking = KrtRanking(tmp_path / "market")
    now = int(time.time())
    ranking._persist({SLUG: {
        "slug": SLUG, "name": "Альфа", "available": True, "computed_at": now,
        "project_llcr_x": 1.25, "surrounding_price_rub_sqm": 650_000,
        "segment": "Комфорт",
    }})
    ranking.save_report(SLUG, {
        "project": PROJECT,
        "market": {"peers": [{"area_per_month": 900.0}, {"area_per_month": 700.0}],
                   "comparison": {"segment": "Комфорт"}},
        "screening": {"available": True, "metrics": {"project_llcr_x": 1.25}},
    })
    return application, ranking


def _neighbours_with_absorption(ranking, count: int) -> None:
    """Строки каталога с известным поглощением — выборка медианы эталона."""
    import time

    now = int(time.time())
    for index in range(count):
        slug = f"pace-{index}"
        ranking._persist({slug: {
            "slug": slug, "name": slug, "available": True, "computed_at": now,
            "project_llcr_x": 1.2,
            "local_absorption_sqm_month": 800.0 + index,
        }})


def test_an_absorption_pair_without_a_benchmark_takes_the_catalogue_median(
        app_without_benchmark) -> None:
    """Эталона Москвы нет — эталоном служит медиана каталога, и это названо."""
    application, ranking = app_without_benchmark
    _neighbours_with_absorption(ranking, market_reference.ABSORPTION_MIN_MONTHS + 5)

    rating = application.state.krt_background_rating_fields(
        dict(PROJECT))["investment_rating"]
    absorption = rating["components"]["absorption"]

    assert absorption["benchmark"], "эталон снова остался пустым при известной локальной"
    assert absorption["score"] is not None
    assert absorption["estimated"] is True
    said = str(absorption.get("estimate_source") or "")
    assert "эталона Москвы по классу нет" in said, said
    assert rating["display_score"] is not None, "неполная пара снова обнулила балл"


def test_without_a_catalogue_median_the_pair_says_why_it_is_missing(
        app_without_benchmark) -> None:
    """Подставить нечем — составляющая откладывается с причиной, а не молчит."""
    application, _ranking = app_without_benchmark

    rating = application.state.krt_background_rating_fields(
        dict(PROJECT))["investment_rating"]
    deferred = {item["component"]: item["reason"] for item in rating["deferred"]}

    assert "absorption" in deferred, (
        "неполная пара поглощения снова ушла в прочерк молча")
    assert "поглощения" in deferred["absorption"], deferred
    assert rating["components"]["absorption"]["deferred"] is True
