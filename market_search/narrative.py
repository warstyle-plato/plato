"""«Что из этого следует» — связные выводы, а не подписи к графикам.

Разделы отчёта отвечают каждый на свой вопрос: почём, как быстро, каким лотом,
сколько осталось. Человек, читающий отчёт, задаёт другой — «и что?». Пока
ответа на него не было, его складывал сам читатель, глядя на пять карточек,
и складывал по-разному от раза к разу.

Здесь он складывается один раз и одинаково. Каждый вывод — это связка двух
чисел, которые порознь ничего не значат: цена и коридор класса, темп и медиана
темпа, сегодняшний разрыв и то, кем он нажит. Связки названы вслух и
перечислены в коде, поэтому спорить можно с правилом, а не с формулировкой.

Числа сюда приходят посчитанными. Модуль их складывает в предложения и не
считает сам ничего, кроме отношений между уже посчитанным: правило то же, по
которому Платон не считает медиану — правдоподобный и неверный вывод нечем
проверить, а по нему принимают решение о цене.

Вывод, для которого нет данных, не пишется вовсе. Пустой абзац «данных нет»
читается как проделанная работа, а её не было.
"""

from __future__ import annotations

import re
from typing import Any

from .segments import _LADDER, normalize_segment
from .verdict import _num, _pct

MONTHS = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле",
          "августе", "сентябре", "октябре", "ноябре", "декабре"]

# Во сколько раз темп должен отличаться, чтобы об этом стоило писать отдельным
# выводом. Порог тот же, что у вердикта: за полутора разами шум перестаёт
# объяснять разницу.
PACE_GAP_RATIO = 1.5
# Насколько премия должна сдвинуться за наблюдаемый период, чтобы это было
# движением, а не колебанием прайса.
PREMIUM_SHIFT_PP = 5.0


GENITIVE = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
            "августа", "сентября", "октября", "ноября", "декабря"]
# «С январе по июле» — так выходит, если на все случаи держать одну форму.
# Предлоги требуют разных падежей: «в январе», но «с января по июль».
NOMINATIVE = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
              "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def _month_from(month: str) -> str:
    """Месяц после «с»: родительный."""
    return _month_form(month, GENITIVE)


def _month_to(month: str) -> str:
    """Месяц после «по»: винительный, совпадающий с именительным."""
    return _month_form(month, NOMINATIVE)


def _month_form(month: str, forms: list[str]) -> str:
    parts = str(month or "").split("-")
    if len(parts) < 2:
        return str(month or "")
    try:
        return forms[int(parts[1]) - 1]
    except (ValueError, IndexError):
        return str(month or "")


def _day(iso: str | None) -> str:
    """Дата в прозе словами: «старше 2026-06-01» — это выгрузка, а не фраза."""
    parts = str(iso or "").split("-")
    if len(parts) != 3:
        return str(iso or "—")
    try:
        return f"{int(parts[2])} {GENITIVE[int(parts[1]) - 1]} {parts[0]}"
    except (ValueError, IndexError):
        return str(iso)


def _month_year(value: str | None) -> str:
    """«2031-02-01» в прозе — строка выгрузки, а не строка отчёта.

    Источник отдаёт прогноз то полной датой, то «02.2031»; год узнаётся по
    четырём цифрам, а не по месту в строке.
    """
    parts = [part for part in re.split(r"[-./]", str(value or "")) if part]
    if len(parts) < 2:
        return str(value or "")
    year = next((part for part in parts if len(part) == 4), parts[0])
    rest = next((part for part in parts if part != year), "")
    try:
        return f"{NOMINATIVE[int(rest) - 1]} {year}"
    except (ValueError, IndexError):
        return str(value or "")


def _plural(count: float, one: str, few: str, many: str) -> str:
    """Форма слова при числе. Без неё выходит «1 092 лотов» и «3,0 года».

    Дробное число в русском всегда требует родительного единственного —
    «4,6 квартиры», «35,9 месяца», — и это не исключение, а отдельное правило.
    """
    if count != int(count):
        return few
    number = abs(int(count)) % 100
    if 11 <= number <= 14:
        return many
    last = number % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def _amount(value: float, one: str, few: str, many: str, digits: int = 0) -> str:
    """Число со словом в правильной форме."""
    return f"{_num(value, digits)} {_plural(value, one, few, many)}"


def _drop(value: float | None) -> str:
    """Изменение словами, а не знаком.

    «медиана — -8,9 %» читается как опечатка: минус после тире. Направление
    называется словом, величина остаётся числом.
    """
    if value is None:
        return "не изменилась"
    if value < 0:
        return f"упала на {_num(abs(value), 1)} %"
    if value > 0:
        return f"выросла на {_num(value, 1)} %"
    return "не изменилась"


def _title(segment: str | None) -> str:
    """Метка класса с прописной: в предложении «класса «бизнес»» она имя."""
    text = str(segment or "").strip()
    return text[:1].upper() + text[1:] if text else "—"


def _month_name(month: str) -> str:
    parts = str(month or "").split("-")
    if len(parts) < 2:
        return str(month or "")
    try:
        return MONTHS[int(parts[1]) - 1]
    except (ValueError, IndexError):
        return str(month or "")


def _priced(peers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in peers or [] if row.get("price_per_sqm")]


def _same_class(peers: list[dict[str, Any]], segment: str | None) -> list[dict[str, Any]]:
    level = normalize_segment(segment)
    if not level:
        return []
    return [row for row in _priced(peers) if normalize_segment(row.get("segment")) == level]


def _change_pct(series: list[dict[str, Any]], key: str) -> float | None:
    points = [row for row in series or [] if row.get(key)]
    if len(points) < 2:
        return None
    first, last = points[0][key], points[-1][key]
    if not first:
        return None
    return round((last / first - 1) * 100, 1)


def _price_finding(subject, peers, segment) -> dict[str, Any] | None:
    """Цена против коридора своего класса — и против соседнего, если она там."""
    price = subject.get("price_per_sqm")
    same = _same_class(peers, segment)
    if not price or not same:
        return None
    values = sorted(row["price_per_sqm"] for row in same)
    low, high = values[0], values[-1]
    level = normalize_segment(segment) or segment
    label = _title(level)
    nearest = min(
        (row for row in same if row["price_per_sqm"] != price),
        key=lambda row: abs(row["price_per_sqm"] - price),
        default=None,
    )
    # Сосед классом выше, который стоит дороже нас: он показывает, что цена
    # попала не «в никуда», а в промежуток между двумя классами.
    # Лестница объявлена по убыванию престижа (элит → эконом), поэтому «класс
    # выше» — это индекс меньше. Своей копии порядка здесь нет: она разошлась
    # бы с той, по которой отбираются сопоставимые.
    above = None
    if level in _LADDER and _LADDER.index(level) > 0:
        higher = _LADDER[_LADDER.index(level) - 1]
        candidates = [
            row for row in _priced(peers)
            if normalize_segment(row.get("segment")) == higher and row["price_per_sqm"] > price
        ]
        above = min(candidates, key=lambda row: row.get("distance_km") or 99, default=None)

    if price > high:
        headline = "Проект дороже всего своего класса"
        text = (
            f"{_num(price)} ₽/м² — выше любого из {_amount(len(same), 'соседа', 'соседей', 'соседей')} "
            f"класса «{label}» "
            f"с действующим прайсом."
        )
        if nearest:
            text += f" Ближайший по цене, {nearest['name']}, просит {_num(nearest['price_per_sqm'])}."
        if above:
            text += (
                f" Это не приговор: {above['name']} классом выше "
                f"в {_num(above.get('distance_km'), 2)} км стоит {_num(above['price_per_sqm'])}, "
                f"то есть цена попадает в зазор между классами, а не выше рынка вообще."
            )
        tone = "watch"
    elif price < low:
        headline = "Проект дешевле всего своего класса"
        text = (
            f"{_num(price)} ₽/м² — ниже любого из {len(same)} соседей класса «{label}». "
            f"Ближайший, {nearest['name'] if nearest else '—'}, просит "
            f"{_num(nearest['price_per_sqm']) if nearest else '—'}. Цена ниже коридора — это либо "
            f"недобор выручки, либо продукт, который в этот класс не попадает."
        )
        tone = "watch"
    else:
        headline = "Цена в коридоре своего класса"
        text = (
            f"{_amount(len(same), 'сосед', 'соседа', 'соседей')} класса «{label}» "
            f"с действующим прайсом укладываются "
            f"в коридор от {_num(low)} до {_num(high)} ₽/м². {_num(price)} — внутри него."
        )
        tone = "good"
    return {"code": "price", "headline": headline, "text": text, "tone": tone}


def _pace_finding(subject, peers) -> dict[str, Any] | None:
    """Темп против медианы — и кто именно продаёт быстрее и почём."""
    pace = subject.get("units_per_month")
    values = sorted(
        (row for row in peers or [] if row.get("units_per_month")),
        key=lambda row: row["units_per_month"], reverse=True,
    )
    if not pace or len(values) < 3:
        return None
    ordered = sorted(row["units_per_month"] for row in values)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    if not median:
        return None
    ratio = round(median / pace, 1) if pace else None
    three = subject.get("units_per_month_3m")
    if ratio and ratio >= PACE_GAP_RATIO:
        headline = f"Темп отстаёт от класса в {_num(ratio, 1)} раза"
        text = (f"{_amount(pace, 'квартира', 'квартиры', 'квартир', 1)} в месяц "
                f"против медианы {_num(median, 1)} по выборке.")
        if three:
            steady = abs(three - pace) / pace < 0.3 if pace else False
            text += (
                f" За последние три месяца — {_num(three, 1)}, то есть "
                + ("это устойчивый уровень, а не провал одного месяца."
                   if steady else "месяц на месяц не приходится.")
            )
        fast = [row for row in values[:2] if row.get("price_per_sqm")]
        if fast and subject.get("price_per_sqm"):
            parts = [
                f"{row['name']} — {_num(row['units_per_month'], 1)} при "
                f"{_num(row['price_per_sqm'])} ₽/м²" for row in fast
            ]
            cheaper = [
                round((1 - row["price_per_sqm"] / subject["price_per_sqm"]) * 100)
                for row in fast
            ]
            text += " Быстрее всех продают " + ", ".join(parts) + "."
            if all(value > 0 for value in cheaper):
                text += (
                    f" Оба дешевле нас на {min(cheaper)}–{max(cheaper)} %"
                    if len(cheaper) > 1 and min(cheaper) != max(cheaper)
                    else f" Это дешевле нас на {cheaper[0]} %"
                ) + "."
        tone = "bad"
    elif ratio and ratio <= 1 / PACE_GAP_RATIO:
        headline = f"Темп выше медианы класса в {_num(round(1 / ratio, 1), 1)} раза"
        text = (
            f"{_amount(pace, 'квартира', 'квартиры', 'квартир', 1)} в месяц против медианы "
            f"{_num(median, 1)}. Продажи идут быстрее рынка — вопрос, не дёшево ли."
        )
        tone = "good"
    else:
        headline = "Темп в рынке"
        text = (
            f"{_amount(pace, 'квартира', 'квартиры', 'квартир', 1)} в месяц против медианы "
            f"{_num(median, 1)} по выборке — разница меньше полутора раз, в пределах разброса."
        )
        tone = "flat"
    return {"code": "pace", "headline": headline, "text": text, "tone": tone}


def _premium_finding(premium: list[dict[str, Any]], peers) -> dict[str, Any] | None:
    """Разрыв нажит нашим ростом или их падением — по одной цифре не видно."""
    points = [row for row in premium or [] if row.get("premium_pct") is not None]
    if len(points) < 3:
        return None
    first, last = points[0], points[-1]
    shift = round(last["premium_pct"] - first["premium_pct"], 1)
    if abs(shift) < PREMIUM_SHIFT_PP:
        return None
    own_change = _change_pct(points, "own")
    median_change = _change_pct(points, "median")
    grew = shift > 0
    headline = "Разрыв вырос сам, без нашего участия" if grew else "Разрыв сокращается"
    text = (
        f"Премия к медиане соседей {'поднялась' if grew else 'опустилась'} "
        f"с {_num(first['premium_pct'], 1)} % в {_month_name(first['month'])} "
        f"до {_num(last['premium_pct'], 1)} % в {_month_name(last['month'])}."
    )
    if own_change is not None and median_change is not None:
        text += (
            f" Прайс проекта за это время изменился на {_pct(own_change)}, "
            f"а медиана выборки {_drop(median_change)}."
        )
        if grew and abs(own_change) < 3 and median_change < -3:
            headline = "Разрыв вырос сам, без нашего участия"
            text += " Мы не дорожали — подешевели остальные."
        elif grew and own_change > 3:
            headline = "Разрыв вырос, потому что выросли мы"
    # Кто именно двигал медиану — иначе «рынок упал» остаётся безымянным.
    movers = []
    for row in peers or []:
        change = _change_pct(row.get("price_series") or [], "value")
        if change is not None and change <= -5:
            movers.append((change, row.get("name") or "—"))
    movers.sort()
    if movers:
        # Род имени проекта неизвестен и неизвлекаем: «Верейская 41 срезал» —
        # брак, а угадывать по окончанию нельзя. Глагол называется один раз, до
        # перечисления, и дальше идут только числа.
        named = ", ".join(
            f"{name} на {_num(abs(change), 1)} %" for change, name in movers[:3]
        )
        text += f" Снижались не все одинаково: {named}."
    return {"code": "premium", "headline": headline, "text": text,
            "tone": "watch" if grew else "good"}


def _volume_finding(subject, peers) -> dict[str, Any] | None:
    """Конкуренция считается лотами, а не числом домов."""
    stock = [row for row in peers or [] if row.get("lot_count")]
    own = subject.get("lot_count")
    if len(stock) < 3:
        return None
    total = sum(int(row["lot_count"]) for row in stock)
    biggest = sorted(stock, key=lambda row: row["lot_count"], reverse=True)[:2]
    text = "В экспозиции у соседей: " + ", ".join(
        f"{row['name']} — {_amount(row['lot_count'], 'лот', 'лота', 'лотов')}"
        for row in biggest
    ) + "."
    if own:
        times = round(total / own, 1) if own else None
        text += (
            f" Всего у соседей выборки {_amount(total, 'лот', 'лота', 'лотов')} —"
            f" в {_num(times, 1)} раза больше, чем наши {_num(own)}."
        )
    text += (
        f" Покупатель в этом радиусе выбирает не из"
        f" {_amount(len(stock), 'дома', 'домов', 'домов')},"
        f" а из {_amount(total, 'квартиры', 'квартир', 'квартир')}."
    )
    return {"code": "volume", "headline": "Конкуренция объёмная, а не точечная",
            "text": text, "tone": "watch"}


def _alive_finding(comparison: dict[str, Any], peers, segment) -> dict[str, Any] | None:
    """Сколько проектов в радиусе живы, а сколько просто стоят в списке."""
    found = comparison.get("found") or 0
    no_price = comparison.get("no_price") or 0
    stale = comparison.get("stale_price") or 0
    if found < 5 or not (no_price or stale):
        return None
    alive = max(found - no_price - stale, 0)
    same = len(_same_class(peers, segment))
    text = (
        f"Из {_amount(found, 'проекта', 'проектов', 'проектов')} в радиусе "
        f"у {_num(no_price)} нет действующего прайса вовсе, ещё у {_num(stale)} он старше "
        f"{_day(comparison.get('fresh_since'))}."
        f" Это не пробел в данных: так выглядят сданные и распроданные дома."
    )
    if same:
        text += (
            f" Живая конкуренция здесь — не {_amount(found, 'проект', 'проекта', 'проектов')},"
            f" а около {_num(alive)}, и {_num(same)} из них сопоставимы по классу."
        )
    return {"code": "alive", "headline": "Живых конкурентов меньше, чем проектов в радиусе",
            "text": text, "tone": "flat"}


def _horizon_finding(subject) -> dict[str, Any] | None:
    """Когда кончится остаток при нынешнем темпе."""
    forecast = subject.get("sales_end_forecast")
    remaining = subject.get("remaining_units")
    pace = subject.get("units_per_month")
    if not forecast or not (remaining and pace):
        return None
    months = round(remaining / pace)
    years = round(months / 12, 1)
    years_text = _num(int(years), 0) if years == int(years) else _num(years, 1)
    return {
        "code": "horizon",
        "headline": "Остаток уходит дольше, чем строится дом",
        "text": (
            f"Непроданных {_amount(remaining, 'квартира', 'квартиры', 'квартир')} "
            f"при темпе {_num(pace, 1)} в месяц — это "
            f"{_amount(months, 'месяц', 'месяца', 'месяцев')}, то есть "
            f"{years_text} {_plural(years, 'год', 'года', 'лет')}; прогноз окончания продаж — "
            f"{_month_year(forecast)}. Остаток в готовом доме означает либо пересмотр цены, либо расходы "
            f"на содержание непроданного."
        ),
        "tone": "watch",
    }


def findings(
    subject: dict[str, Any],
    peers: list[dict[str, Any]],
    comparison: dict[str, Any],
    *,
    segment: str | None,
    premium: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Связные выводы по отчёту, в порядке чтения.

    Порядок не случаен и не совпадает с порядком разделов: сначала где стоит
    цена, потом подтверждают ли её продажи, потом кем нажит сегодняшний разрыв,
    и только затем масштаб и сроки. Это ход рассуждения, а не оглавление.
    """
    built = [
        _price_finding(subject, peers, segment),
        _pace_finding(subject, peers),
        _premium_finding(premium or [], peers),
        _volume_finding(subject, peers),
        _alive_finding(comparison or {}, peers, segment),
        _horizon_finding(subject),
    ]
    return [row for row in built if row]


def _ceiling(peers: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """Цена, выше которой в этом радиусе темпа уже нет.

    Не теория, а наблюдение по выборке: самый дорогой из тех, кто продаёт
    быстрее медианы. Выше этой отметки быстрых нет ни одного — значит, там
    проходит граница, за которой покупатель здешнего радиуса не идёт.
    """
    rows = [row for row in peers or []
            if row.get("price_per_sqm") and row.get("units_per_month")]
    if len(rows) < 4:
        return None, None
    paces = sorted(row["units_per_month"] for row in rows)
    middle = len(paces) // 2
    median = paces[middle] if len(paces) % 2 else (paces[middle - 1] + paces[middle]) / 2
    quick = [row for row in rows if row["units_per_month"] >= median]
    if not quick:
        return None, median
    return max(row["price_per_sqm"] for row in quick), median


def _essay_project(subject, peers, segment, premium, cost) -> list[dict[str, Any]]:
    """Разбор действующего проекта: цена, темп, разрыв, цена премии."""
    out: list[dict[str, Any]] = []
    price = subject.get("price_per_sqm")
    same = _same_class(peers, segment)
    label = _title(normalize_segment(segment) or segment)
    if price and same:
        values = sorted(row["price_per_sqm"] for row in same)
        low, high = values[0], values[-1]
        middle = len(values) // 2
        median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
        above_top = round((price / high - 1) * 100, 1) if high else None
        above_mid = round((price / median - 1) * 100, 1) if median else None
        higher = [row for row in _priced(peers)
                  if normalize_segment(row.get("segment")) != normalize_segment(segment)
                  and row["price_per_sqm"] > price]
        higher.sort(key=lambda row: row.get("distance_km") or 99)
        first = [
            f"{_amount(len(same), 'сосед', 'соседа', 'соседей')} класса «{label}» "
            f"с действующим прайсом укладываются в коридор от {_num(low)} до {_num(high)} ₽/м², "
            f"медиана {_num(median)}. Проект просит {_num(price)}"
            + (f" — на {_num(above_top, 1)} % выше верхней границы коридора" if above_top and above_top > 0 else "")
            + (f" и на {_num(above_mid, 1)} % выше медианы." if above_mid and above_mid > 0
               else ".")
        ]
        if higher:
            near = ", ".join(
                f"{row['name']} в {_num(row.get('distance_km'), 2)} км — {_num(row['price_per_sqm'])}"
                for row in higher[:2]
            )
            first.append(
                f"Ближайшее по цене окружение у проекта уже не «{label}»: {near}. "
                f"По прайсу он стоит между двумя классами, не принадлежа целиком ни одному."
            )
        first.append(
            "Само по себе это не ошибка позиционирования: премию к массовому уровню класса "
            "берут сознательно, и продукт её может нести. Вопрос не в том, обоснована ли "
            "премия, а в том, платит ли её рынок. На это отвечает темп."
        )
        headline = (
            f"Формально «{label}», по цене — выше своего класса"
            if above_top and above_top > 0 else f"Цена внутри коридора класса «{label}»"
        )
        out.append({"code": "position", "headline": headline, "paragraphs": first})

    pace = subject.get("units_per_month")
    ceiling, median_pace = _ceiling(peers)
    if pace and median_pace:
        ratio = round(median_pace / pace, 1) if pace else None
        slow = ratio and ratio >= PACE_GAP_RATIO
        second = [
            f"{_amount(pace, 'квартира', 'квартиры', 'квартир', 1)} в месяц против медианы "
            f"{_num(median_pace, 1)} по выборке"
            + (f" — медленнее в {_num(ratio, 1)} раза." if slow else ".")
        ]
        three = subject.get("units_per_month_3m")
        if three:
            second[0] += (
                f" За последние три месяца — {_num(three, 1)}: "
                + ("уровень устойчивый, а не провал одного месяца."
                   if abs(three - pace) / pace < 0.3 else "месяц на месяц не приходится.")
            )
        if ceiling and price and ceiling < price:
            second.append(
                f"Внутри выборки видна закономерность: быстрее медианы не продаёт никто "
                f"дороже {_num(ceiling)} ₽/м². Граница, за которой темп в этом радиусе "
                f"заметно падает, проходит примерно там; проект стоит на "
                f"{_num(round((price / ceiling - 1) * 100, 1), 1)} % выше неё."
            )
        second.append(
            "Оговорка, без которой сравнение было бы нечестным: проекты выборки находятся на "
            "разных стадиях, и у только что стартовавших темп ниже по естественным причинам. "
            "Сравнивать корректно тех, кто продаёт не первый месяц."
        )
        out.append({
            "code": "pace",
            "headline": "Темп продаж премию не подтверждает" if slow
                        else "Темп продаж премию выдерживает",
            "paragraphs": second,
        })

    points = [row for row in premium or [] if row.get("premium_pct") is not None]
    if len(points) >= 3:
        first_point, last_point = points[0], points[-1]
        own_change = _change_pct(points, "own")
        median_change = _change_pct(points, "median")
        third = [
            f"С {_month_from(first_point['month'])} по {_month_to(last_point['month'])} прайс "
            f"проекта изменился на {_pct(own_change)} — с {_num(first_point['own'])} "
            f"до {_num(last_point['own'])}. За те же месяцы медиана выборки "
            f"{_drop(median_change)}: с {_num(first_point['median'])} "
            f"до {_num(last_point['median'])}. Премия к классу прошла путь "
            f"с {_num(first_point['premium_pct'], 1)} % до {_num(last_point['premium_pct'], 1)} %."
        ]
        if own_change is not None and median_change is not None and abs(own_change) < 3 \
                and median_change < -3:
            third[0] += " Разрыв создал не наш прайс, а движение рынка вниз."
        movers = []
        for row in peers or []:
            change = _change_pct(row.get("price_series") or [], "value")
            if change is not None:
                movers.append((change, row.get("name") or "—"))
        movers.sort()
        if movers:
            down = [item for item in movers if item[0] <= -5][:3]
            up = [item for item in movers if item[0] >= 5][-2:]
            said = []
            if down:
                said.append("снижались " + ", ".join(
                    f"{name} на {_num(abs(change), 1)} %" for change, name in down))
            if up:
                said.append("дорожали " + ", ".join(
                    f"{name} на {_num(change, 1)} %" for change, name in up))
            if said:
                third.append(
                    "Двигались не все одинаково: " + "; ".join(said) + ". "
                    "Спрос в районе есть — вопрос, в каком продукте он его находит."
                )
        out.append({
            "code": "drift",
            "headline": "Разрыв растёт, и не потому, что мы дорожаем"
                        if (own_change or 0) < 3 and (median_change or 0) < 0
                        else "Как двигались мы и как двигался рынок",
            "paragraphs": third,
        })

    if (cost or {}).get("trade"):
        out.append({
            "code": "cost",
            "headline": "Во что обходится премия",
            "paragraphs": [cost["trade"]],
        })
    return out


def _essay_site(subject, peers, comparison, site, hint) -> list[dict[str, Any]]:
    """Разбор площадки: что здесь строят, почём, как быстро уходит и чего ждать.

    У голого участка нет ни прайса, ни темпа, и разбор действующего проекта не
    складывается: сравнивать нечего. Но решение принимают именно здесь — что
    строить и почём, — и соседи отвечают на оба вопроса.
    """
    out: list[dict[str, Any]] = []
    level = (site or {}).get("segment")
    if not level:
        return out
    label = _title(level)
    rows = [row for row in peers or []
            if normalize_segment(row.get("segment")) == normalize_segment(level)]
    lots = [row["sold_lot_avg"] for row in rows if row.get("sold_lot_avg")]
    first = [
        f"Вокруг участка {_amount(len(rows), 'проект', 'проекта', 'проектов')} класса «{label}» "
        f"из {_num(len(peers or []))} в выборке — это и есть здешний продукт. "
        f"Класс выбран по числу проектов, а не по деньгам: один дорогой сосед не делает "
        f"место дорогим."
    ]
    if lots:
        lots.sort()
        middle = len(lots) // 2
        lot = lots[middle] if len(lots) % 2 else (lots[middle - 1] + lots[middle]) / 2
        first.append(
            f"Уходит лот около {_num(lot, 1)} м² — на него и считать квартирографию. "
            f"Продукт, заметно крупнее или мельче здешнего, продаётся другому покупателю, "
            f"и темп соседей к нему уже не относится."
        )
    out.append({"code": "product", "headline": f"Здесь покупают «{label}»",
                "paragraphs": first})

    price = (site or {}).get("price_per_sqm")
    if price:
        values = sorted(row["price_per_sqm"] for row in rows if row.get("price_per_sqm"))
        second = [
            f"Действующие прайсы этого класса дают медиану {_num(price)} ₽/м²"
            + (f" при коридоре от {_num(values[0])} до {_num(values[-1])} ₽/м²."
               if values else ".")
        ]
        entry = (hint or {}).get("entry_per_sqm")
        if entry:
            second.append(
                f"Внутри проекта средняя и цена входа — разные числа. Медиана самых дешёвых "
                f"лотов соседей — {_num(entry)} ₽/м², на "
                f"{_num(abs(round((1 - entry / price) * 100, 1)), 1)} % ниже медианы: с такой "
                f"цены заводят покупателя, а средняя набирается по ходу продаж за счёт "
                f"квартирографии и очередей."
            )
        # Стадия — поправка того же порядка, что класс, и её мы не считаем.
        # Умолчать об этом значит выдать уровень рынка за цену старта: медиана
        # собрана по проектам всех стадий, от котлована до сдачи, а стартующий
        # выходит ниже неё. Насколько — здесь не сказано, потому что дат ввода
        # и старта продаж у соседей источник нам не отдаёт.
        second.append(
            "Обе цифры — уровень рынка, а не цена старта. Соседи в выборке стоят на разных "
            "стадиях, от котлована до сдачи, и метр в готовом доме стоит дороже того же метра "
            "на старте: покупатель платит за снятый риск. Стартующий проект выходит ниже "
            "медианы, и насколько — по этим данным не установить: стадии соседей источник "
            "не отдаёт. Поправку на неё делает решение владельца, а не эта таблица."
        )
        out.append({"code": "price", "headline": "Почём здесь продают",
                    "paragraphs": second})

    speed = (site or {}).get("units_per_month")
    stock = [row for row in peers or [] if row.get("lot_count")]
    third = []
    if speed:
        third.append(
            f"Медиана темпа у соседей этого класса — "
            f"{_amount(speed, 'квартира', 'квартиры', 'квартир', 1)} в месяц. "
            f"Сто квартир при таком темпе уходят за "
            f"{_amount(round(100 / speed), 'месяц', 'месяца', 'месяцев')} — "
            f"это и есть срок экспозиции, который надо закладывать в модель, а не желаемый."
        )
    if stock:
        total = sum(int(row["lot_count"]) for row in stock)
        third.append(
            f"В экспозиции у соседей {_amount(total, 'лот', 'лота', 'лотов')}. "
            f"Выходить придётся не на пустое место: покупатель этого радиуса выбирает "
            f"из уже выставленного, и новый корпус встаёт в этот же ряд."
        )
    if third:
        out.append({"code": "speed", "headline": "С какой скоростью это уходит",
                    "paragraphs": third})

    found = (comparison or {}).get("found") or 0
    no_price = (comparison or {}).get("no_price") or 0
    stale = (comparison or {}).get("stale_price") or 0
    if found and (no_price or stale):
        alive = max(found - no_price - stale, 0)
        out.append({
            "code": "risk",
            "headline": "Чего эти числа не обещают",
            "paragraphs": [
                f"Из {_amount(found, 'проекта', 'проектов', 'проектов')} в радиусе живых — "
                f"около {_num(alive)}: у остальных прайс мёртвый или его нет вовсе, и это не "
                f"пробел в данных, а сданные и распроданные дома. Цены здесь — прайс-листы, "
                f"а не сделки, и договоры проходят со скидкой, размер которой у каждого свой.",
                "Соседи показывают, что рынок берёт сегодня, и не показывают, что он возьмёт "
                "к вводу нового дома. Между решением о покупке участка и первой продажей "
                "проходят годы, и этот разрыв ни одна выборка сегодняшних прайсов не "
                "закрывает — его закрывает решение владельца.",
            ],
        })
    return out


def analysis(
    subject: dict[str, Any],
    peers: list[dict[str, Any]],
    comparison: dict[str, Any],
    *,
    segment: str | None,
    premium: list[dict[str, Any]] | None = None,
    cost: dict[str, Any] | None = None,
    site: dict[str, Any] | None = None,
    hint: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """«Разбор» — те же числа, но связанные между собой.

    Это не рекомендация к действию: решение о цене принимает владелец проекта,
    а здесь описано, из чего оно складывается. Два случая — действующий проект
    и площадка — разбираются по-разному, потому что и вопрос у них разный:
    у первого «платит ли рынок нашу цену», у второго «что здесь строить».
    """
    if subject.get("price_per_sqm"):
        return _essay_project(subject, peers, segment, premium, cost)
    return _essay_site(subject, peers, comparison, site, hint)
