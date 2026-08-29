"""Почему работа уехала вправо — словами, из тех же чисел, что дали сдвиг.

«В каждой статье монитора, где есть красный хвост, должно быть пояснение…
непонятно, когда нет никаких данных, почему именно они смещены» (владелец,
27 и 29.08.2026). Второе важнее первого: работа без единого акта КС всё равно
показывает сдвиг — потому что его унаследовала по сети от предшественников, — и
на экране это выглядит как сдвиг ниоткуда.

Здесь ничего не считается заново. Сдвиг уже посчитан: `own_delay_days` —
собственный, `inherited_delay_days` — пришедший от предшественников,
`current_float_days` — сколько запаса осталось, `pace_forecast_method` — чем
построен прогноз. Разбор только выбирает из этих чисел причину и называет её.
Считать здесь второй раз значило бы завести второе объяснение одного сдвига, и
разошлось бы оно молча.

Модель к этому не зовётся намеренно: причина сдвига выводится из сети
однозначно, а «по мнению ИИ» рядом с однозначным ответом — это второй ответ на
один вопрос.
"""

from __future__ import annotations

from typing import Any

# Чем построен прогноз работы. Метод приходит из `pace_finish`; человеку нужно
# не имя метода, а то, на чём прогноз держится.
PACE_WORDS = {
    "rolling_3m_acts": "по темпу актов КС за последние три месяца",
    "average_acts_since_start": "по среднему темпу актов с начала работ",
    "accepted_complete": "работа принята полностью",
    "plan_duration_shifted_by_predecessors": "от плановой длительности, сдвинутой предшественниками",
    "approved_rebaseline": "по утверждённому перепланированию",
    "mixed_lifecycle_rss": "КС по этой статье — только стоимостной индикатор, темпа из него не выводится",
    "baseline_closed": "базовый план по работе закрыт",
    "future": "работа ещё не начиналась",
    "no_pace": "темпа нет: актов КС по работе не было",
}

_MAX_NAMED = 3


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def delay_reason(node: dict[str, Any]) -> dict[str, Any] | None:
    """Причина сдвига одной работы: чем вызван, на сколько и от кого.

    Возвращает `None`, когда объяснять нечего: работа не опаздывает или сети
    нет вовсе. «Нет сети» — не причина сдвига, а отсутствие ответа, и выдавать
    одно за другое нельзя.
    """
    delta = node.get("delta_days")
    if delta is None or _int(delta) <= 0:
        return None
    dependencies = node.get("dependencies") or {}
    own = _int(dependencies.get("own_delay_days"))
    inherited = _int(dependencies.get("inherited_delay_days"))
    method = str(node.get("pace_forecast_method") or "")
    parts: list[str] = []
    kind = "unknown"

    if own and inherited:
        kind = "both"
        parts.append(f"свой сдвиг {own} дн и {inherited} дн, унаследованных по сети")
    elif inherited:
        kind = "inherited"
        parts.append(f"сдвиг унаследован целиком: {inherited} дн пришли от предшественников")
    elif own:
        kind = "own"
        parts.append(f"свой сдвиг {own} дн")

    if kind in {"own", "both"} and method:
        parts.append("прогноз построен " + PACE_WORDS.get(method, f"методом «{method}»")
                     if method not in {"no_pace", "mixed_lifecycle_rss", "future",
                                       "baseline_closed", "accepted_complete"}
                     else PACE_WORDS.get(method, method))

    late = [str(item.get("name") or item.get("id") or "")
            for item in (dependencies.get("predecessors") or [])]
    late = [name for name in late if name]
    if kind in {"inherited", "both"}:
        if late:
            named = ", ".join(late[:_MAX_NAMED])
            more = f" и ещё {len(late) - _MAX_NAMED}" if len(late) > _MAX_NAMED else ""
            parts.append(f"предшественники: {named}{more}")
        else:
            # Сдвиг унаследован, а от кого — сеть не говорит. Это находка, а не
            # мелочь: связь есть в расчёте и потеряна в показе.
            parts.append("от кого именно — в сети не указано")

    if kind == "unknown":
        # Работа опаздывает, а разложить сдвиг не на что: своего сдвига нет,
        # унаследованного нет. Так бывает, когда прогноз пришёл не из сети, а
        # от темпа строки, у которой нет узла в PM-файле.
        if method:
            kind = "pace"
            parts.append("сдвиг посчитан " + PACE_WORDS.get(method, f"методом «{method}»"))
        else:
            parts.append("сеть зависимостей не загружена — разложить сдвиг не на что")

    float_days = dependencies.get("current_float_days")
    if float_days is not None:
        remaining = _int(float_days)
        parts.append(f"свободный запас {remaining} дн" if remaining > 0
                     else "свободного запаса не осталось — сдвиг уходит дальше по сети")
    impact = _int(dependencies.get("impact_rnv_days"))
    if impact > 0:
        parts.append(f"работа лежит на критическом пути: сдвигает ввод на {impact} дн")

    return {"kind": kind, "delay_days": _int(delta), "own_days": own,
            "inherited_days": inherited, "predecessors": late[:_MAX_NAMED],
            "text": "; ".join(parts) + "."}


def annotate(view: dict[str, Any]) -> dict[str, Any]:
    """Проставить причину сдвига каждой опаздывающей работе.

    Ходит по тем же узлам, что рисует экран: причина обязана стоять рядом с
    красным хвостом, а не в отдельном ответе, который надо запрашивать.
    """
    schedule = view.get("schedule") or {}
    stack = list(schedule.get("management") or [])
    while stack:
        node = stack.pop()
        stack.extend(node.get("children") or [])
        reason = delay_reason(node)
        if reason:
            node["delay_reason"] = reason
    for row in schedule.get("rows") or []:
        reason = delay_reason(row)
        if reason:
            row["delay_reason"] = reason
    return view
