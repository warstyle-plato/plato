"""«Цена окружения» — измеренная цена ЭТОЙ площадки, а не среднее по городу.

Находка ревизии 27.09.2026 (`docs/unlanded_branches_audit_2026-09-27.md`, п.1).
`price_hint` честно отдаёт три разных ответа: медиану свежих сопоставимых
проектов рядом (`peers`), медиану округа по классу (`okrug`) и медиану класса по
Москве (`city`). Обещание «минимум три свежих сопоставимых прайса» относится
только к первому — а `_market_inputs` брал `price_per_sqm` при ЛЮБОМ основании.

Цена оттуда шла в три места сразу: в колонку «Цена окружения», в фильтр
каталога «от 600 000 ₽/м²» и в ценовую составляющую рейтинга #485. То есть
среднее по округу выдавалось за наблюдение площадки — и площадка попадала в
выборку «дорогое окружение» по чужому числу.

Правило: цена окружения ненулевая ТОЛЬКО при основании `peers`. Медиана округа
и медиана города остаются ценой модели — она лучше пресета класса, — но идут с
названным основанием и в наблюдения площадки не записываются.

Запуск: python3 -m pytest tests/test_krt_surrounding_price_needs_three_live_peers.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from auction_search import krt_ranking, krt_screening  # noqa: E402
from market_search import price_hint  # noqa: E402

SITE = {"slug": "krt:peers", "name": "Площадка", "okrug": "ЮАО",
        "area_ha": 5.0, "housing_gfa_sqm": 120_000.0}


def _report(price: int, basis: str) -> dict:
    """Отчёт рынка с ориентиром на названном основании."""
    return {
        "analysis": {"site": {"segment": "бизнес", "price_per_sqm": price,
                              "sold_lot_avg": 45.0, "units_per_month": 12.0}},
        "price_hint": {"available": True, "price_per_sqm": price,
                       "basis": basis,
                       "basis_title": price_hint.BASIS_TITLES[basis],
                       "sample": 3 if basis == price_hint.BASIS_PEERS else 41,
                       "segment": "бизнес"},
    }


def test_the_surrounding_price_is_only_the_price_of_the_peers() -> None:
    """Соседей меньше трёх — цены окружения нет, и это не ноль «от бедности».

    Падает на прежнем коде: там медиана округа приезжала ценой окружения.
    """
    seg, model, surrounding, basis = krt_screening._market_inputs(
        _report(512_000, price_hint.BASIS_OKRUG))

    assert seg == "бизнес"
    assert surrounding == 0.0, "медиана округа снова выдана за цену окружения"
    # Считать по ней можно — она лучше пресета класса, — но основание названо.
    assert model == 512_000
    assert "по округу и классу" in basis and "не измерена" in basis, basis

    # То же и у медианы города: это тем более не наблюдение площадки.
    _seg, model_city, surrounding_city, basis_city = krt_screening._market_inputs(
        _report(480_000, price_hint.BASIS_CITY))
    assert surrounding_city == 0.0 and model_city == 480_000
    assert "по классу в Москве" in basis_city


def test_three_live_peers_do_give_a_surrounding_price() -> None:
    """Предохранитель: при основании `peers` цена окружения на месте.

    Без него проверку выше проходил бы код, у которого цены окружения нет
    никогда.
    """
    seg, model, surrounding, basis = krt_screening._market_inputs(
        _report(640_000, price_hint.BASIS_PEERS))

    assert seg == "бизнес"
    assert model == 640_000 and surrounding == 640_000
    assert "сопоставимых проектов" in basis


def test_the_catalogue_row_carries_no_surrounding_price_from_the_okrug() -> None:
    """Строка каталога — то, что видит экран и по чему работает фильтр."""
    okrug = krt_screening.build_krt_model_screening(
        dict(SITE), _report(512_000, price_hint.BASIS_OKRUG), core)
    assert okrug["available"] is True, okrug.get("reason")
    row = krt_ranking.score_row(dict(SITE), okrug)
    assert row.get("surrounding_price_rub_sqm") in (None, 0), row
    # Модель при этом посчитана — отказа по цене нет.
    assert okrug["market"]["start_price_rub_sqm"] == 512_000
    assert okrug["market"]["market_price_rub_sqm"] is None

    peers = krt_screening.build_krt_model_screening(
        dict(SITE), _report(640_000, price_hint.BASIS_PEERS), core)
    assert krt_ranking.score_row(dict(SITE), peers)["surrounding_price_rub_sqm"] == 640_000


def test_the_basis_reaches_the_assumptions() -> None:
    """Чем считали, видно на экране: основание едет в предпосылки."""
    got = krt_screening.build_krt_model_screening(
        dict(SITE), _report(512_000, price_hint.BASIS_OKRUG), core)
    said = " ".join(got["assumptions"])
    assert "по округу и классу" in said, said
    assert "цена окружения не измерена" in said, said


def test_the_rules_version_grew_so_stored_rows_are_read_again() -> None:
    """Правило сменилось — строки, посчитанные прежним, обязаны перечитаться."""
    assert krt_screening.SCREENING_RULES_VERSION >= 6
