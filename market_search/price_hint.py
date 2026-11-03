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
from .segments import (
    OWN_CLASS_ENOUGH,
    SCOPE_ADJACENT,
    SCOPE_SAME,
    class_scope,
    class_step,
    in_class_scope,
)


BASIS_PEERS = "peers"
BASIS_PEERS_ADJACENT = "peers_adjacent"
BASIS_OKRUG = "okrug"
BASIS_CITY = "city"

BASIS_TITLES = {
    BASIS_PEERS: "по сопоставимым проектам рядом",
    BASIS_PEERS_ADJACENT: "по проектам рядом соседних классов",
    BASIS_OKRUG: "по округу и классу",
    BASIS_CITY: "по классу в Москве",
}

# Меньше трёх наблюдений — это не медиана, а одно-два случайных числа.
_MIN_PEERS = OWN_CLASS_ENOUGH


def _fresh_prices(
    rows: list[dict[str, Any]], segment: str | None, since: str, scope: str = SCOPE_SAME
) -> list[int]:
    """Действующие цены соседей класса `segment` при охвате `scope`.

    Сосед без класса входит в любую выборку (решение владельца): «класс не
    назван» — не повод его терять.
    """
    out: list[int] = []
    for row in rows:
        price = row.get("price_per_sqm")
        observed = str(row.get("observed_at") or "")
        if not price or observed < since:
            continue
        if segment and row.get("segment") and not in_class_scope(segment, row["segment"], scope):
            continue
        out.append(int(price))
    return out


def _own_class(rows: list[dict[str, Any]], segment: str, since: str) -> int:
    """Соседи с действующей ценой и тем же классом — для порога нехватки."""
    return sum(
        1 for row in rows
        if row.get("price_per_sqm") and str(row.get("observed_at") or "") >= since
        and class_step(segment, row.get("segment")) == 0
    )


def _few_own(segment: str, own: int, taken: str) -> str:
    """Подпись основания, когда своих соседей не хватило: что взято вместо них."""
    return f"соседних ЖК класса «{segment}» мало ({own}) — взят {taken}"


def price_hint(
    *,
    peers: list[dict[str, Any]],
    segment: str | None,
    okrug: str | None = None,
    city: MoscowMarket | None = None,
    fresh_since: str = "",
) -> dict[str, Any]:
    """Ориентир и то, на чём он стоит.

    Порядок при известном классе: соседи только своего класса; их меньше
    трёх — свод класса (муниципалитет или округ, затем регион или город);
    свода нет — соседи с соседними классами. Каждая замена называется в
    `basis_title` и в `class_fallback`.
    """
    reference = city or MoscowMarket.bundled()

    prices = _fresh_prices(peers, segment, fresh_since)
    observed_at = max((str(row.get("observed_at") or "") for row in peers), default="") or None
    # «Своих» считает только известный класс: сосед без класса входит в
    # выборку, но нехватку своего класса не закрывает.
    own = _own_class(peers, segment, fresh_since) if segment else len(prices)
    if class_scope(own) == SCOPE_SAME and len(prices) >= _MIN_PEERS:
        return {
            "available": True,
            "price_per_sqm": int(round(statistics.median(prices))),
            "price_th_per_sqm": round(statistics.median(prices) / 1000, 1),
            "basis": BASIS_PEERS,
            "basis_title": BASIS_TITLES[BASIS_PEERS],
            "sample": len(prices),
            "segment": segment,
            "class_scope": SCOPE_SAME if segment else None,
            "observed_at": observed_at,
        }
    fallback = {"own_peers": own, "needed": _MIN_PEERS} if segment else None

    okrug_row = reference.okrug(okrug, segment) if okrug else None
    if okrug_row and okrug_row.get("price_median"):
        return {
            "available": True,
            "price_per_sqm": int(okrug_row["price_median"]),
            "price_th_per_sqm": round(okrug_row["price_median"] / 1000, 1),
            "basis": BASIS_OKRUG,
            # Подпись даёт свод: у региона средняя ступень — муниципалитет.
            "basis_title": _titled(
                getattr(reference, "okrug_basis_title", None) or BASIS_TITLES[BASIS_OKRUG],
                segment, own,
            ),
            "sample": int(okrug_row.get("projects") or 0),
            "segment": segment,
            "class_fallback": fallback and {**fallback, "taken": BASIS_OKRUG},
            "observed_at": reference.observed_at,
        }

    snapshot = reference.snapshot(segment)
    if snapshot and snapshot.price_median:
        return {
            "available": True,
            "price_per_sqm": int(snapshot.price_median),
            "price_th_per_sqm": round(snapshot.price_median / 1000, 1),
            "basis": BASIS_CITY,
            "basis_title": _titled(
                getattr(reference, "city_basis_title", None) or BASIS_TITLES[BASIS_CITY],
                segment, own,
            ),
            "sample": snapshot.projects,
            "segment": segment,
            "class_fallback": fallback and {**fallback, "taken": BASIS_CITY},
            "observed_at": reference.observed_at,
        }

    if segment:
        wider = _fresh_prices(peers, segment, fresh_since, SCOPE_ADJACENT)
        if len(wider) >= _MIN_PEERS:
            return {
                "available": True,
                "price_per_sqm": int(round(statistics.median(wider))),
                "price_th_per_sqm": round(statistics.median(wider) / 1000, 1),
                "basis": BASIS_PEERS_ADJACENT,
                "basis_title": _few_own(segment, own, "соседний класс: " + BASIS_TITLES[BASIS_PEERS_ADJACENT]),
                "sample": len(wider),
                "segment": segment,
                "class_scope": SCOPE_ADJACENT,
                "class_fallback": {**fallback, "taken": BASIS_PEERS_ADJACENT},
                "observed_at": observed_at,
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


def _titled(title: str, segment: str | None, own: int) -> str:
    """Подпись свода; при известном классе — с причиной: своих соседей мало."""
    return _few_own(segment, own, "свод: " + title) if segment else title

