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

import re

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


def readiness_from_dates(start: str | None, finish: str | None,
                         today: str | None = None) -> float | None:
    """Готовность дома по двум датам — той же кривой, что разносит СМР.

    Стадия в процентах ниоткуда не приходит; приходят даты — начала стройки и
    ввода. «Сколько построено к этому месяцу» между ними говорит кривая
    освоения движка (`build_curve`), и другой у проекта быть не должно: две
    кривые об одном процессе — это два мнения, которые не с чем сверить.

    Нет любой из дат — `None`. Нулевая готовность и неизвестная выглядят
    одинаково числом, а значат противоположное: одна говорит «котлован»,
    другая — «мы не знаем».
    """
    import build_curve

    first, last, now = _months(start), _months(finish), _months(today)
    if first is None or last is None:
        return None
    if now is None:
        return None
    total = last - first
    if total <= 0:
        # Ввод не позже начала — это не готовый дом, это негодные даты.
        return None
    return build_curve.readiness_between(now - first, total)


def _months(value: str | None) -> int | None:
    """Дата в месяцах от нуля — считать разницу в месяцах проще, чем в днях."""
    parts = [part for part in re.split(r"[-./\s]", str(value or "")) if part.isdigit()]
    if len(parts) < 2:
        return None
    year = next((part for part in parts if len(part) == 4), None)
    if year is None:
        return None
    rest = [part for part in parts if part is not year]
    month = next((part for part in rest if 1 <= int(part) <= 12), None)
    if month is None:
        return None
    return int(year) * 12 + int(month)



def calendar_progress(
    start: str | None, finish: str | None, today: str | None = None
) -> float | None:
    """Положение даты внутри календарного окна 0…1.

    Это НЕ физическая готовность стройки. Для рынка сейчас надёжно известны
    старт продаж и плановый ввод, поэтому эта величина годится только как
    прозрачный прокси стадии реализации: 0 — старт окна, 1 — плановый ввод.
    Когда появится подтверждённая строительная готовность, её нужно передавать
    в factor напрямую, не смешивая два понятия.
    """
    first, last, now = _months(start), _months(finish), _months(today)
    if first is None or last is None or now is None or last <= first:
        return None
    return _clamp((now - first) / (last - first))


def calendar_stage_label(progress: float | None) -> str | None:
    """Человеческая подпись календарной стадии без притворства о % стройки."""
    if progress is None:
        return None
    value = _clamp(float(progress))
    if value <= 0.10:
        return "старт продаж"
    if value < 0.40:
        return "ранняя стадия"
    if value < 0.70:
        return "середина цикла"
    if value < 0.90:
        return "поздняя стадия"
    if value < 1.0:
        return "около ввода"
    return "плановый срок ввода наступил"


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


# --- стадия строительства аналога ------------------------------------------
#
# Пульс на своём сайте даёт отобрать проекты по стадии строительства руками.
# Здесь — словарь этих стадий, один на сервер и на страницы: подпись стадии,
# её код и то, как сырой текст источника к ней приводится, объявлены один раз.
#
# У стадии аналога всегда названо происхождение:
#   * «pulse»    — стадия пришла полем Пульса;
#   * «calendar» — поля нет, стадия оценена по срокам «старт продаж → плановый
#                  ввод» (календарный прокси, не измеренная готовность);
#   * None       — нет ни поля, ни дат: «стадия не указана». Это не «любая
#                  стадия», и при отборе по стадии такой аналог не проходит.

CONSTRUCTION_STAGES: tuple[tuple[str, str], ...] = (
    ("pit", "котлован"),
    ("frame", "каркас"),
    ("finish", "отделка"),
    ("done", "сдан"),
)
STAGE_TITLES: dict[str, str] = dict(CONSTRUCTION_STAGES)
STAGE_UNKNOWN_LABEL = "стадия не указана"

STAGE_ORIGIN_PULSE = "pulse"
STAGE_ORIGIN_CALENDAR = "calendar"
STAGE_ORIGIN_TITLES = {
    STAGE_ORIGIN_PULSE: "Пульс",
    STAGE_ORIGIN_CALENDAR: "оценка по срокам",
}

# Слова, по которым сырой текст источника приводится к стадии. Порядок важен:
# «сдан»/«ввод» проверяются раньше «отделки», а «отделка» раньше «каркаса» —
# строка «каркас возведён, идёт отделка» говорит о более поздней стадии.
_STAGE_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("done", ("сдан", "введен", "ввод в эксплуатац", "в эксплуатац", "получено рнв",
              "разрешение на ввод", "completed", "commissioned", "finished")),
    ("finish", ("отделк", "фасад", "кровл", "остеклен", "инженерн", "благоустр",
                "finishing", "facade")),
    ("frame", ("каркас", "монолит", "возведен", "надземн", "коробк", "этаж",
               "frame", "superstructure")),
    ("pit", ("котлован", "нулев", "землян", "фундамент", "подготовит",
             "свай", "excavation", "foundation")),
)

# Календарный прокси → стадия. Допущение, объявленное одним местом: доля
# окна «старт продаж → плановый ввод». Наступивший плановый срок — «сдан» по
# плану, а не подтверждённый ввод; происхождение это и говорит.
CALENDAR_STAGE_BOUNDS: tuple[tuple[float, str], ...] = (
    (0.25, "pit"),
    (0.65, "frame"),
    (1.0, "finish"),
)


def stage_from_text(value: object) -> str | None:
    """Код стадии по тексту источника; нераспознанный текст — `None`."""
    text = " ".join(str(value or "").lower().replace("ё", "е").split())
    if not text:
        return None
    for code, title in CONSTRUCTION_STAGES:
        if text == title:
            return code
    for code, words in _STAGE_WORDS:
        if any(word in text for word in words):
            return code
    return None


def stage_from_calendar(progress: float | None) -> str | None:
    """Стадия по календарному положению проекта; нет положения — `None`."""
    if progress is None:
        return None
    value = _clamp(float(progress))
    for bound, code in CALENDAR_STAGE_BOUNDS:
        if value < bound:
            return code
    return "done"


def analog_stage(raw: object, progress: float | None) -> dict:
    """Стадия аналога с происхождением: поле Пульса → сроки → «не указана»."""
    raw_text = " ".join(str(raw or "").split()) or None
    code = stage_from_text(raw_text)
    if code:
        origin = STAGE_ORIGIN_PULSE
    else:
        code = stage_from_calendar(progress)
        origin = STAGE_ORIGIN_CALENDAR if code else None
    return {
        "code": code,
        "label": STAGE_TITLES[code] if code else STAGE_UNKNOWN_LABEL,
        "origin": origin,
        "origin_title": STAGE_ORIGIN_TITLES.get(origin) if origin else None,
        # Сырой текст источника — даже нераспознанный: человек должен видеть,
        # что поле пришло, а словарь его не узнал.
        "raw": raw_text,
    }


def normalize_stage_codes(values: object) -> list[str]:
    """Выбранные стадии в порядке словаря; неизвестный код — ошибка, а не тишина."""
    if values in (None, ""):
        return []
    if isinstance(values, str):
        values = [part for part in re.split(r"[,\s]+", values) if part]
    picked = []
    for value in values:  # type: ignore[union-attr]
        code = str(value).strip()
        if code not in STAGE_TITLES:
            raise ValueError(f"неизвестная стадия строительства: {code!r}")
        picked.append(code)
    return [code for code, _ in CONSTRUCTION_STAGES if code in picked]


def suggest_project_stage(sales_start: str | None = None,
                          commissioning: str | None = None,
                          today: str | None = None) -> dict:
    """Подсказка стадии НАШЕГО проекта для отбора аналогов.

    Это подсказка, а не решение: страница её предлагает, но не включает сама.
    Сроки проекта известны — стадия по тем же календарным границам, что у
    аналогов. Неизвестны — котлован: новый проект выходит в продажу на старте
    стройки, и сравнивать его стартовую цену честнее с теми, кто тоже на старте.
    """
    progress = calendar_progress(sales_start, commissioning, today)
    code = stage_from_calendar(progress)
    if code:
        return {
            "code": code,
            "label": STAGE_TITLES[code],
            "reason": (f"по срокам проекта: {round(progress * 100)}% окна "
                       "«старт продаж → плановый ввод»"),
        }
    return {
        "code": "pit",
        "label": STAGE_TITLES["pit"],
        "reason": "новый проект выходит в продажу на старте стройки — котловане",
    }
