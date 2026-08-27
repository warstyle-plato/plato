"""Срок на сбор каталога — общий для всех источников.

Сбор был ограничен только числом страниц, то есть объёмом, а не временем. У
ГИС Торгов это сорок страниц по восемь секунд, у Росэлторга и РАД — по запросу
на каждый лот по двадцать пять; в сумме сбор мог идти минутами. Шлюз столько
не держит: он отвечает своей страницей на 504, браузер пытается разобрать её
как JSON, и человек видит «The string did not match the expected pattern»
вместо каталога (владелец, 27.08.2026: «торги перестали выдавать вообще какие
либо результаты»).

Правило то же, что у длинного ответа Платона: работу не держат соединением.
Здесь она короткая, поэтому ответ отдаётся в срок, а недособранное называется
вслух — источник, который не успели опросить, это «не знаем», а не «лотов нет».
"""

from __future__ import annotations

import time


def start(budget_seconds: float | None) -> float | None:
    """Момент, после которого сбор обязан закончиться. `None` — без срока."""
    if budget_seconds is None:
        return None
    return time.monotonic() + float(budget_seconds)


def left(deadline: float | None) -> float | None:
    """Сколько секунд осталось. `None` — срока нет, а не «ноль»."""
    if deadline is None:
        return None
    return deadline - time.monotonic()


def expired(deadline: float | None) -> bool:
    remaining = left(deadline)
    return remaining is not None and remaining <= 0


def timeout(deadline: float | None, want: float) -> float:
    """Срок одного запроса — не больше того, что осталось у всего сбора.

    Иначе один повисший запрос переваливает общий срок ровно на свои двадцать
    пять секунд, и бюджет перестаёт что-либо значить. Минимум в секунду
    оставлен намеренно: запрос с нулевым сроком не отваливается быстро, он
    отваливается СРАЗУ и выглядит как отказ источника.
    """
    remaining = left(deadline)
    if remaining is None:
        return want
    return max(1.0, min(want, remaining))
