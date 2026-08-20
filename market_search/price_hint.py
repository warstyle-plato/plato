"""Ориентир цены по локации и классу — одно число для поля модели.

Отдельно от отчёта нарочно. Отчёт объясняет и показывает, на чём построен;
здесь нужно другое — подставить в «Цена квартир» число, когда у оценщика ещё
нет своей цифры. Поэтому наружу уходит значение, его дата и число наблюдений,
а перечень проектов не уходит: он относится к аналитике, а не к вводным.

Порядок оснований — от узкого к широкому, и он важен. Соседи того же класса
рядом лучше округа, округ лучше города: чем шире база, тем меньше она знает про
конкретное место. Основание всегда называется в ответе, потому что «медиана
шести соседей в километре» и «медиана девяноста семи проектов Москвы» — числа
разной силы, и подписывать их одинаково нельзя.

Ничего не нашлось — возвращается `available: False` с причиной. Подставлять
в модель городскую медиану молча, как будто это оценка места, нельзя.
"""

from __future__ import annotations

import statistics
from typing import Any

from .market_reference import MoscowMarket
from .segments import segments_comparable


BASIS_PEERS = "peers"
BASIS_OKRUG = "okrug"
BASIS_CITY = "city"

BASIS_TITLES = {
    BASIS_PEERS: "по сопоставимым проектам рядом",
    BASIS_OKRUG: "по округу и классу",
    BASIS_CITY: "по классу в Москве",
}

# Меньше трёх наблюдений — это не медиана, а одно-два случайных числа.
_MIN_PEERS = 3


def _fresh_prices(rows: list[dict[str, Any]], segment: str | None, since: str) -> list[int]:
    out: list[int] = []
    for row in rows:
        price = row.get("price_per_sqm")
        observed = str(row.get("observed_at") or "")
        if not price or observed < since:
            continue
        if segment and row.get("segment") and not segments_comparable(segment, row["segment"]):
            continue
        out.append(int(price))
    return out


def price_hint(
    *,
    peers: list[dict[str, Any]],
    segment: str | None,
    okrug: str | None = None,
    city: MoscowMarket | None = None,
    fresh_since: str = "",
) -> dict[str, Any]:
    """Ориентир и то, на чём он стоит."""
    reference = city or MoscowMarket.bundled()

    prices = _fresh_prices(peers, segment, fresh_since)
    if len(prices) >= _MIN_PEERS:
        return {
            "available": True,
            "price_per_sqm": int(round(statistics.median(prices))),
            "price_th_per_sqm": round(statistics.median(prices) / 1000, 1),
            "basis": BASIS_PEERS,
            "basis_title": BASIS_TITLES[BASIS_PEERS],
            "sample": len(prices),
            "segment": segment,
            "observed_at": max(str(row.get("observed_at") or "") for row in peers) or None,
        }

    okrug_row = reference.okrug(okrug, segment) if okrug else None
    if okrug_row and okrug_row.get("price_median"):
        return {
            "available": True,
            "price_per_sqm": int(okrug_row["price_median"]),
            "price_th_per_sqm": round(okrug_row["price_median"] / 1000, 1),
            "basis": BASIS_OKRUG,
            "basis_title": BASIS_TITLES[BASIS_OKRUG],
            "sample": int(okrug_row.get("projects") or 0),
            "segment": segment,
            "observed_at": reference.observed_at,
        }

    snapshot = reference.snapshot(segment)
    if snapshot and snapshot.price_median:
        return {
            "available": True,
            "price_per_sqm": int(snapshot.price_median),
            "price_th_per_sqm": round(snapshot.price_median / 1000, 1),
            "basis": BASIS_CITY,
            "basis_title": BASIS_TITLES[BASIS_CITY],
            "sample": snapshot.projects,
            "segment": segment,
            "observed_at": reference.observed_at,
        }

    return {
        "available": False,
        "reason": (
            "Рядом нет сопоставимых проектов с действующей ценой, "
            "а класс площадки не определён — ориентир не рассчитан"
            if not segment
            else "Нет ни соседей с действующей ценой, ни свода по этому классу"
        ),
        "segment": segment,
    }
