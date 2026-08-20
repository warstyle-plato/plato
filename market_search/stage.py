"""Поправка на стадию строительства: цена готового метра и S-кривая.

Медиана по выборке собрана из проектов разной готовности — от котлована до
сдачи. Стартующему проекту она не ориентир: метр в готовом доме дороже того же
метра на старте, потому что покупатель платит за снятый риск.

Отбраковывать соседей по стадии нельзя (замечание владельца, 20.08.2026): если
все вокруг на половине цикла, они и есть рынок. В оценке поправку **вносят**, а
не выбрасывают сопоставимые — иначе от восьми соседей остаётся один, и это
хуже, чем восемь приведённых.

Модель — его же: цена условно готовой квартиры, умноженная на коэффициент
готовности, и коэффициент идёт S-кривой.

    P(g) = P_готовой × f(g),    f(0) = START_FACTOR,  f(1) = 1

Кривая — сглаженный шаг `3g² − 2g³`: ноль в нуле, единица в единице, обе
производные на концах нулевые, самый быстрый рост в середине. Свободных
коэффициентов у неё нет вовсе, кроме одного — цены старта в долях готовой; всё
остальное задано формой. Это нарочно: чем меньше подкручиваемых чисел, тем
меньше мест, где можно подогнать результат под желаемый.

Приведение работает в обе стороны. Цена соседа делится на его коэффициент —
получается его цена «как если бы дом был готов»; медиана таких цен умножается
на коэффициент нашей стадии — получается ориентир для неё. Никто не выброшен.

Чего здесь нет и не будет придумано: самой готовности соседей. Источник её не
отдаёт, и подставить сюда правдоподобное число значит назначить цену по
догадке. Пока готовность не пришла, поправка не считается, а не считается
наугад.
"""

from __future__ import annotations

# Цена старта в долях от цены готового метра. Это допущение, а не измерение:
# разброс «котлован → сдача» по рынку называют в двадцать-тридцать процентов, и
# 0,8 — середина этого разговора. Число объявлено здесь один раз, печатается в
# отчёте рядом с результатом и меняется одним местом. Пока оно не подтверждено
# выборкой, отчёт обязан называть его допущением вслух.
START_FACTOR = 0.8


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def factor(readiness: float, *, start_factor: float = START_FACTOR) -> float:
    """Коэффициент цены при готовности `readiness` (0…1).

    Сглаженный шаг: медленно у котлована, быстро в середине стройки, снова
    медленно у сдачи. Линейная поправка здесь была бы неверна не формой, а
    смыслом — покупатель платит не за потраченные месяцы, а за снятый риск, и
    снимается он неравномерно.
    """
    done = _clamp(readiness)
    smooth = done * done * (3.0 - 2.0 * done)
    return start_factor + (1.0 - start_factor) * smooth


def to_ready(price: float, readiness: float, *, start_factor: float = START_FACTOR) -> float:
    """Цена соседа, приведённая к готовому дому."""
    return price / factor(readiness, start_factor=start_factor)


def at_readiness(ready_price: float, readiness: float,
                 *, start_factor: float = START_FACTOR) -> float:
    """Цена готового метра, приведённая к нужной стадии."""
    return ready_price * factor(readiness, start_factor=start_factor)


def median(values: list[float]) -> float | None:
    ordered = sorted(value for value in values if value)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def adjust(peers: list[dict], *, target_readiness: float,
           start_factor: float = START_FACTOR) -> dict | None:
    """Ориентир, приведённый к стадии `target_readiness`.

    Сосед без готовности в поправку не идёт, но и не пропадает молча: сколько
    их, сказано в ответе. Поправки нет вовсе, если готовность неизвестна у
    всех, — «привели к стадии» на пустом множестве было бы ложью в самом
    ответственном числе отчёта.
    """
    known: list[tuple[float, float]] = []
    unknown = 0
    for row in peers or []:
        price = row.get("price_per_sqm")
        done = row.get("readiness")
        if not price:
            continue
        if done is None:
            unknown += 1
            continue
        known.append((float(price), _clamp(float(done))))
    if not known:
        return None
    ready = [to_ready(price, done, start_factor=start_factor) for price, done in known]
    ready_median = median(ready)
    if not ready_median:
        return None
    target = _clamp(target_readiness)
    return {
        "price_per_sqm": int(round(at_readiness(ready_median, target,
                                                start_factor=start_factor))),
        "ready_price_per_sqm": int(round(ready_median)),
        "target_readiness_pct": round(target * 100, 1),
        "peers_used": len(known),
        "peers_without_readiness": unknown,
        "peers_readiness_median_pct": round((median([done for _, done in known]) or 0) * 100, 1),
        "start_factor": start_factor,
        # Своя цена без поправки — рядом, чтобы видно было, что именно сделала
        # поправка и в какую сторону.
        "plain_median": int(round(median([price for price, _ in known]) or 0)),
    }
