"""Выводы по разделам и общий вердикт: «так» или «не так».

Числа считает движок, словами их излагает Платон Сергеевич. Но сам вывод —
«цена высокая, и продажи это подтверждают» против «цена высокая, и продажи
встали» — вычисляется здесь, а не сочиняется моделью. Причина та же, по которой
модель не считает медиану: правдоподобный и неверный вывод нечем проверить, а
проверить его надо, потому что по нему принимают решение о цене.

Главное правило — читать цену вместе с темпом. Цена сама по себе не бывает
высокой или низкой: она бывает подтверждённой продажами или нет.

    цена выше рынка + темп в рынке   → премия работает, товар её несёт
    цена выше рынка + темп ниже      → перегрев: рынок цену не подтверждает
    цена ниже рынка + темп выше      → недобор: продаётся быстрее, чем стоит
    цена ниже рынка + темп ниже      → дело не в цене, а в товаре или спросе

Пороги названы здесь один раз и вслух. «В рынке» — это ±15 % по цене и разница
меньше полутора раз по темпу: за этими границами шум перестаёт объяснять
разницу. Числа взяты не из теории, а из разброса контрольных выборок; менять
их можно, но только здесь и с оговоркой в отчёте.
"""

from __future__ import annotations

from typing import Any

from .segments import BUSINESS, COMFORT, ECONOMY, ELITE, PREMIUM, normalize_segment


PRICE_BAND_PCT = 15.0
PACE_BAND_RATIO = 1.5

TONE_GOOD = "good"
TONE_WATCH = "watch"
TONE_BAD = "bad"
TONE_FLAT = "flat"


def _pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{'+' if value > 0 else ''}{value:.{digits}f} %".replace(".", ",")


def _num(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text


def _trend(series: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Куда шла цена за период: с какого значения, на какое, на сколько."""
    points = [p for p in (series or []) if p.get("value")]
    if len(points) < 2:
        return None
    first, last = points[0], points[-1]
    change = (last["value"] / first["value"] - 1) * 100 if first["value"] else None
    peak = max(points, key=lambda p: p["value"])
    return {
        "from_month": first["month"],
        "to_month": last["month"],
        "from_value": first["value"],
        "to_value": last["value"],
        "change_pct": round(change, 1) if change is not None else None,
        "peak_month": peak["month"],
        "peak_value": peak["value"],
        "months": len(points),
    }


def price_note(block: dict[str, Any], series: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    subject, peers, city = block.get("subject") or {}, block.get("peers") or {}, block.get("city") or {}
    price = subject.get("price_per_sqm")
    if not price:
        return {"tone": TONE_FLAT, "text": "Прайса у проекта нет — сравнивать нечего."}

    lines: list[str] = []
    same = peers.get("same_class") or {}
    # Медиана своего класса вернее общей: в общую входит соседний уровень, и на
    # бизнесе он растягивает выборку от комфорта до премиума.
    base = same if same.get("median") else peers
    gap = base.get("vs_median_pct")
    label = "своего класса" if same.get("median") else "соседей"
    if gap is not None:
        lines.append(
            f"Прайс {_num(price)} ₽/м² — это {_pct(gap)} к медиане {label} "
            f"({_num(base.get('median'))} ₽/м², {base.get('count')} проектов)."
        )
        if same.get("median") and peers.get("median") and same["median"] != peers["median"]:
            lines.append(
                f"Общая медиана выборки {_num(peers['median'])} ₽/м² — она включает соседний "
                f"класс и потому шире."
            )

    band = city.get("band")
    if band:
        where = {
            "above_p75": "выше верхнего квартиля",
            "interquartile": "внутри квартилей",
            "below_p25": "ниже нижнего квартиля",
        }.get(band, band)
        lines.append(
            f"По Москве того же класса проект {where} "
            f"({_pct(city.get('vs_median_pct'))} к медиане {_num(city.get('median'))} ₽/м²)."
        )

    trend = _trend(series)
    if trend:
        lines.append(
            f"За {trend['months']} мес. цена прошла путь {_num(trend['from_value'])} → "
            f"{_num(trend['to_value'])} ₽/м² ({_pct(trend['change_pct'])})"
            + (
                f"; пик был в {trend['peak_month']} — {_num(trend['peak_value'])} ₽/м²."
                if trend["peak_month"] != trend["to_month"]
                else "."
            )
        )
        if trend["peak_month"] != trend["to_month"] and trend["peak_value"] > trend["to_value"] * 1.02:
            lines.append("Цена уже снижалась с пика — прайс отыгрывает назад сам.")

    tone = TONE_FLAT
    if gap is not None:
        tone = TONE_WATCH if abs(gap) > PRICE_BAND_PCT else TONE_GOOD
    return {"tone": tone, "text": " ".join(lines), "gap_pct": gap, "trend": trend}


def pace_note(block: dict[str, Any]) -> dict[str, Any]:
    subject, peers, city = block.get("subject") or {}, block.get("peers") or {}, block.get("city") or {}
    pace = subject.get("units_per_month")
    if pace is None:
        return {"tone": TONE_FLAT, "text": "Темп продаж неизвестен."}
    lines = [f"Проект продаёт {_num(pace, 1)} ДДУ в месяц."]
    ratio = peers.get("peer_median_over_subject")
    if peers.get("median") is not None:
        if ratio and ratio >= PACE_BAND_RATIO:
            lines.append(
                f"Соседи — {_num(peers['median'], 1)} в месяц, то есть в {_num(ratio, 1)} раза быстрее."
            )
        elif ratio and ratio > 0:
            lines.append(f"Медиана соседей {_num(peers['median'], 1)} — проект идёт вровень с рынком.")
    recent = subject.get("units_per_month_3m")
    if recent is not None and pace:
        delta = (recent / pace - 1) * 100 if pace else None
        if delta is not None and abs(delta) >= 10:
            lines.append(
                f"Последние три месяца — {_num(recent, 1)} в месяц, "
                + ("темп ускоряется." if delta > 0 else "темп замедляется.")
            )
    if city.get("sold_median") is not None:
        lines.append(f"По Москве того же класса медиана {_num(city['sold_median'], 1)} ДДУ в месяц.")
    if subject.get("sales_end_forecast"):
        lines.append(f"Источник прогнозирует окончание продаж к {subject['sales_end_forecast']}.")

    tone = TONE_FLAT
    if ratio:
        tone = TONE_BAD if ratio >= 2 else (TONE_WATCH if ratio >= PACE_BAND_RATIO else TONE_GOOD)
    return {"tone": tone, "text": " ".join(lines), "ratio": ratio}


def stock_note(block: dict[str, Any]) -> dict[str, Any]:
    subject = block.get("subject") or {}
    if not subject:
        return {"tone": TONE_FLAT, "text": "Остаток и экспозиция неизвестны."}
    lines = []
    months = subject.get("months_to_sell")
    remaining, total = subject.get("remaining_units"), subject.get("living_units")
    if remaining and total:
        lines.append(
            f"Не продано {_num(remaining)} из {_num(total)} лотов "
            f"({_num(remaining / total * 100, 1)} % объёма)."
        )
    if months:
        lines.append(f"По текущему темпу распродажа займёт {_num(months, 1)} мес.")
        if months > 60:
            lines.append("Это больше пяти лет — срок, за который меняется и рынок, и себестоимость.")
    if subject.get("exposure_lots") and subject.get("remaining_units"):
        share = subject["exposure_lots"] / subject["remaining_units"] * 100
        lines.append(
            f"В экспозиции {_num(subject['exposure_lots'])} лотов — "
            f"{_num(share, 0)} % остатка; остальное придержано."
        )
    tone = TONE_FLAT
    if months:
        tone = TONE_BAD if months > 60 else (TONE_WATCH if months > 36 else TONE_GOOD)
    return {"tone": tone, "text": " ".join(lines), "months_to_sell": months}


def lot_note(block: dict[str, Any]) -> dict[str, Any]:
    subject, peers = block.get("subject") or {}, block.get("peers") or {}
    sold, project = subject.get("sold_lot_avg"), subject.get("project_lot_avg")
    if sold is None and project is None:
        return {"tone": TONE_FLAT, "text": "Размер лота неизвестен."}
    lines = []
    if sold and project:
        lines.append(
            f"Средний проданный лот {_num(sold, 1)} м² против {_num(project, 1)} м² в проекте "
            f"({_pct(subject.get('gap_pct'))})."
        )
        if subject.get("gap_pct") is not None and subject["gap_pct"] < -5:
            lines.append(
                "Уходит то, что меньше среднего: крупные форматы стоят, и в остатке их доля растёт."
            )
    if peers.get("median"):
        lines.append(f"У соседей продаётся {_num(peers['median'], 1)} м² в среднем.")
    gap = subject.get("gap_pct")
    tone = TONE_WATCH if gap is not None and gap < -10 else TONE_FLAT
    return {"tone": tone, "text": " ".join(lines)}


def absorption_note(block: dict[str, Any]) -> dict[str, Any]:
    subject, peers = block.get("subject") or {}, block.get("peers") or {}
    area = subject.get("area_per_month")
    if area is None:
        return {"tone": TONE_FLAT, "text": "Поглощение в метрах неизвестно."}
    lines = [f"Проект поглощает {_num(area)} м² в месяц."]
    if peers.get("median"):
        lines.append(
            f"Медиана соседей {_num(peers['median'])} м² ({_pct(peers.get('vs_median_pct'))})."
        )
        lines.append(
            "Метры честнее штук: они не зависят от того, из каких квартир собран проект."
        )
    gap = peers.get("vs_median_pct")
    tone = TONE_FLAT
    if gap is not None:
        tone = TONE_BAD if gap < -50 else (TONE_WATCH if gap < -20 else TONE_GOOD)
    return {"tone": tone, "text": " ".join(lines)}


def rooms_note(block: dict[str, Any]) -> dict[str, Any]:
    """Вымывание и ответ на «а не в наборе ли квартир дело».

    Разрыв в цене метра раскладывается на две части: набор квартир и сами
    цены. Внутри проекта метр тем дороже, чем мельче квартира, поэтому проект
    с крупным набором показывает цену ниже при тех же ценах на каждый товар;
    но по рынку связь обратная — крупные форматы строят в дорогих классах.
    Значит на догадку отвечают числом своего проекта, а не правилом.

    Говорится это тремя короткими фразами подряд: что видно (наш метр дороже
    или дешевле), что проверили (наш же прайс на наборе соседей) и что из
    этого следует. Прежний текст называл величины их служебными именами —
    «из этого набором квартир объясняется −12,4 %», — и читателю приходилось
    складывать в уме проценты с разными знаками.
    """
    subject, peers = block.get("subject") or {}, block.get("peers") or {}
    rooms = subject.get("rooms") or {}
    if not rooms and not subject.get("bands"):
        return {"tone": TONE_FLAT, "text": "Комнатность проекта не раскрыта."}
    lines: list[str] = []
    # Вымывание: что уходит быстрее, чем лежит в остатке.
    drains = [
        (name, item)
        for name, item in rooms.items()
        if item.get("sold_share_pct") is not None and item.get("rem_share_pct") is not None
    ]
    if drains:
        best = max(drains, key=lambda pair: (pair[1]["sold_share_pct"] - pair[1]["rem_share_pct"]))
        worst = min(drains, key=lambda pair: (pair[1]["sold_share_pct"] - pair[1]["rem_share_pct"]))
        if best[1]["sold_share_pct"] - best[1]["rem_share_pct"] > 5:
            # Имена комнатности — существительные во множественном числе
            # («студии», «1-комнатные»), и у неодушевлённых винительный
            # совпадает с именительным: «разбирают студии», «уходят 3-комнатные».
            lines.append(
                f"Быстрее всего разбирают {best[1]['title']}: "
                f"{_num(best[1]['sold_share_pct'], 1)} % продаж при "
                f"{_num(best[1]['rem_share_pct'], 1)} % остатка."
            )
        if worst[1]["rem_share_pct"] - worst[1]["sold_share_pct"] > 5:
            lines.append(
                f"Хуже всего уходят {worst[1]['title']}: "
                f"{_num(worst[1]['rem_share_pct'], 1)} % остатка при "
                f"{_num(worst[1]['sold_share_pct'], 1)} % продаж."
            )
    mix = subject.get("mix") or {}
    tone = TONE_FLAT
    if mix:
        lines.extend(_mix_lines(mix))
        tone = TONE_WATCH if abs(mix.get("gap_pct") or 0) > PRICE_BAND_PCT else TONE_FLAT
        if min(mix.get("cross_coverage_pct", 0), mix.get("peers_coverage_pct", 0)) < 70:
            lines.append(
                "Цены известны не по всей комнатности — доля покрытия стоит в таблице, "
                "и на ней это оценка, а не измерение."
            )
    elif rooms:
        lines.append("Цен по комнатности у соседей нет — набор с ценами не развести.")
    if not lines:
        lines.append("Комнатность есть, но сравнивать её не с чем.")
    return {"tone": tone, "text": " ".join(lines)}


def _mix_lines(mix: dict[str, Any]) -> list[str]:
    """Разложение разрыва цены обычными словами.

    Три величины: наш метр на нашем наборе, наш же метр на наборе соседей и
    метр соседей. Первая пара отвечает, сколько даёт набор, вторая — сколько
    дают сами цены. Порог в 2 % — ниже него разница не заслуживает
    объяснения и читается как шум.
    """
    own = mix.get("own_at_own_mix")
    cross = mix.get("own_at_peers_mix")
    peers = mix.get("peers_at_peers_mix")
    gap, part, level = mix.get("gap_pct"), mix.get("mix_pct"), mix.get("level_pct")
    if own is None or cross is None or peers is None or gap is None:
        return []
    if abs(gap) < 1:
        lines = [f"Наш метр стоит примерно как у соседей: {_num(own)} против {_num(peers)} ₽."]
    else:
        lines = [
            f"Наш метр {'дороже' if gap > 0 else 'дешевле'} соседского на "
            f"{_num(abs(gap), 1)} %: {_num(own)} против {_num(peers)} ₽."
        ]
    same_mix = (
        f"продавай мы такой же набор, как у соседей, тот же наш прайс дал бы "
        f"{_num(cross)} ₽ за метр"
    )
    big_part = part is not None and abs(part) >= 2
    big_level = level is not None and abs(level) >= 2
    if big_part and big_level:
        lines.append(
            f"Часть разницы делает набор: {same_mix} — на {_num(abs(part), 1)} % "
            f"{'дешевле' if part < 0 else 'дороже'} нынешней цены."
        )
        lines.append(
            f"Остальное — цены: на одинаковом наборе мы просим на {_num(abs(level), 1)} % "
            f"{'больше' if level > 0 else 'меньше'} соседей."
        )
    elif big_part:
        lines.append(f"Дело в наборе: {same_mix} — ровно как у них.")
        lines.append(
            "Цены на каждую комнатность у нас такие же, разницу делает только состав продаж."
        )
    elif big_level:
        lines.append(f"Набор тут ни при чём: {same_mix} — почти столько же.")
        lines.append(
            f"Мы просто просим за метр на {_num(abs(level), 1)} % "
            f"{'больше' if level > 0 else 'меньше'} соседей."
        )
    else:
        lines.append("Мы вровень с соседями и по набору квартир, и по ценам на каждую комнатность.")
    return lines


def payment_note(block: dict[str, Any]) -> dict[str, Any]:
    subject, peers, city = (
        block.get("subject") or {},
        block.get("peers") or {},
        block.get("city") or {},
    )
    share = subject.get("mortgage_pct")
    if share is None:
        return {"tone": TONE_FLAT, "text": "Доли ипотеки у проекта нет: продаж не было."}
    lines = [f"Ипотекой платят {_num(share, 1)} % сделок проекта."]
    reference = peers.get("median")
    if reference is None:
        reference = city.get("mortgage_median_pct")
        if reference is not None:
            lines.append(f"У класса в Москве медиана {_num(reference, 1)} %.")
    else:
        lines.append(f"У соседей медиана {_num(reference, 1)} %.")
    tone = TONE_FLAT
    if reference:
        # Зависимость от ипотеки — это чувствительность к ставке, а не оценка
        # «хорошо/плохо»: она названа, а не приговорена.
        if share > reference + 15:
            lines.append("Проект опирается на ипотеку сильнее рынка — он чувствительнее к ставке.")
            tone = TONE_WATCH
        elif share < reference - 15:
            lines.append("Ипотеки меньше, чем у рынка: платят своими деньгами.")
    return {"tone": tone, "text": " ".join(lines)}


def channel_note(block: dict[str, Any]) -> dict[str, Any]:
    subject, peers = block.get("subject") or {}, block.get("peers") or {}
    company = subject.get("company_pct")
    if company is None:
        return {"tone": TONE_FLAT, "text": "Состава покупателей у проекта нет: продаж не было."}
    lines = [
        f"Физлица берут {_num(subject.get('person_pct'), 1)} %, юрлица {_num(company, 1)} %."
    ]
    if peers.get("median") is not None:
        lines.append(f"У соседей юрлиц {_num(peers['median'], 1)} % по медиане.")
    tone = TONE_FLAT
    if peers.get("median") is not None and company > peers["median"] + 15:
        lines.append("Юрлиц заметно больше рынка: часть объёма уходит оптом, а не в розницу.")
        tone = TONE_WATCH
    resale = subject.get("resale_deals")
    if resale:
        lines.append(f"Переуступок за месяц {_num(resale)} — это вторичный оборот, не продажи застройщика.")
    return {"tone": tone, "text": " ".join(lines)}


NOTE_BUILDERS = {
    "price": price_note,
    "pace": pace_note,
    "stock": stock_note,
    "lot_size": lot_note,
    "absorption": absorption_note,
    "rooms": rooms_note,
    "payment": payment_note,
    "channel": channel_note,
}


def overall(blocks: list[dict[str, Any]], notes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Общий вывод: подтверждает ли рынок цену проекта.

    Собирается из двух чисел — отрыва цены от своего класса и отношения темпа
    к темпу соседей. Остальные разделы уточняют формулировку, но не меняют её:
    решение о цене принимают по этим двум.
    """
    price_gap = (notes.get("price") or {}).get("gap_pct")
    ratio = (notes.get("pace") or {}).get("ratio")
    months = (notes.get("stock") or {}).get("months_to_sell")

    if price_gap is None or ratio is None:
        return {
            "tone": TONE_FLAT,
            "headline": "Вывод не сложился",
            "text": (
                "Для вывода нужны обе величины — отрыв цены от своего класса и темп "
                "против соседей. Чего-то из них нет, и додумывать это нельзя: "
                "решение о цене принимают именно по ним."
            ),
        }

    expensive = price_gap > PRICE_BAND_PCT
    cheap = price_gap < -PRICE_BAND_PCT
    slow = ratio >= PACE_BAND_RATIO

    if expensive and slow:
        verdict = {
            "tone": TONE_BAD,
            "headline": "Цена рынком не подтверждается",
            "text": (
                f"Проект стоит {_pct(price_gap)} к своему классу и продаётся в "
                f"{_num(ratio, 1)} раза медленнее соседей. Это не премия за продукт, а "
                "разрыв: покупатель выбирает соседей."
            ),
        }
    elif expensive and not slow:
        verdict = {
            "tone": TONE_GOOD,
            "headline": "Премия работает",
            "text": (
                f"Цена выше своего класса на {_pct(price_gap)}, при этом темп держится "
                "вровень с соседями. Рынок премию оплачивает — снижать прайс нет причин."
            ),
        }
    elif cheap and not slow:
        verdict = {
            "tone": TONE_WATCH,
            "headline": "Продаётся быстрее, чем стоит",
            "text": (
                f"Цена ниже своего класса на {_pct(abs(price_gap))}, а темп не отстаёт. "
                "Это запас: рынок берёт товар по цене ниже уровня."
            ),
        }
    elif cheap and slow:
        verdict = {
            "tone": TONE_BAD,
            "headline": "Дело не в цене",
            "text": (
                f"Цена уже ниже своего класса на {_pct(abs(price_gap))}, но темп всё равно "
                f"в {_num(ratio, 1)} раза хуже соседей. Дальнейшая скидка спрос не купит — "
                "причина в товаре, стадии или локации."
            ),
        }
    elif slow:
        # Цена внутри коридора, а темп отстаёт. Эта пара проваливалась в ветку
        # «проект в рынке» и печаталась как «темп вровень с соседями» при
        # отставании в восемь раз: ветвление спрашивало о темпе только там,
        # где цена вышла из коридора. Между тем это самый частый разговор с
        # девелопером — прайс как у всех, а продаж нет, — и молчание о нём
        # читается как «всё в порядке».
        verdict = {
            "tone": TONE_BAD,
            "headline": "Цена как у всех, а продаж нет",
            "text": (
                f"Отрыв цены {_pct(price_gap)} — внутри обычного разброса, но темп в "
                f"{_num(ratio, 1)} раза хуже соседей. Причина не в прайсе: при цене "
                "на уровне класса так отстают из-за продукта, стадии или того, "
                "как проект показан покупателю."
            ),
        }
    else:
        verdict = {
            "tone": TONE_GOOD,
            "headline": "Проект в рынке",
            "text": (
                f"Отрыв цены {_pct(price_gap)} и темп вровень с соседями — "
                "и цена, и продажи внутри обычного разброса."
            ),
        }

    if months and months > 60:
        verdict["text"] += (
            f" Отдельно: при нынешнем темпе остаток уходит {_num(months, 1)} мес., "
            "и это самостоятельный риск независимо от цены."
        )
    return verdict


def _median(values: list[float]) -> float | None:
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    middle = len(clean) // 2
    return clean[middle] if len(clean) % 2 else (clean[middle - 1] + clean[middle]) / 2


def premium_series(subject_series, peers) -> list[dict[str, Any]]:
    """Премия к медиане соседей по месяцам.

    Отдельный ряд, а не одно число: разрыв бывает нажит собственным ростом
    цены, а бывает — падением соседей, и по одной сегодняшней цифре эти два
    случая неразличимы. Ряд отвечает на вопрос «мы дорожали или они дешевели».
    """
    own = {row["month"]: row["value"] for row in subject_series or [] if row.get("value")}
    if not own:
        return []
    months = sorted(own)
    out = []
    for month in months:
        values = []
        for peer in peers or []:
            for point in peer.get("price_series") or []:
                if point.get("month") == month and point.get("value"):
                    values.append(point["value"])
        median = _median(values)
        if not median:
            continue
        out.append({
            "month": month,
            "own": own[month],
            "median": int(round(median)),
            "premium_pct": round((own[month] / median - 1) * 100, 1),
            "peers": len(values),
        })
    return out


def price_of_premium(subject: dict[str, Any], peers: list[dict[str, Any]]) -> dict[str, Any]:
    """Во что премия обходится: в деньгах остатка и в сроке распродажи.

    Считается прямо: остаток метров, умноженный на разницу цен, — это выручка,
    которую премия приносит, если её платят. Срок — что будет, если продавать
    темпом соседей. Оба числа условные и названы условными: они показывают
    масштаб выбора, а не прогноз.
    """
    price = subject.get("price_per_sqm")
    area = subject.get("remaining_area")
    pace = subject.get("units_per_month")
    remaining = subject.get("remaining_units")
    peer_price = _median([p.get("price_per_sqm") for p in peers or []])
    peer_pace = _median([p.get("units_per_month") for p in peers or []])
    out: dict[str, Any] = {}
    if price and peer_price and area:
        out["premium_per_sqm"] = int(round(price - peer_price))
        out["premium_on_remainder"] = round((price - peer_price) * area / 1e6, 1)
        out["remaining_area"] = area
    if remaining and pace:
        out["months_own_pace"] = round(remaining / pace, 1)
    if remaining and peer_pace:
        out["months_peer_pace"] = round(remaining / peer_pace, 1)
    if out.get("months_own_pace") and out.get("months_peer_pace"):
        out["months_lost"] = round(out["months_own_pace"] - out["months_peer_pace"], 1)

    # Вопрос владельца: а по цене соседей? Прежде здесь стояли две половины
    # выбора порознь — деньги премии и потерянный срок, — а сам выбор человек
    # складывал в уме. Между тем он один: отказаться от премии значит отдать
    # её деньги и выиграть её же срок. Обе стороны названы вместе.
    #
    # Что здесь допущение и названо им: цена соседей не покупает темп соседей
    # автоматически. Продукт, стадия и корпусность у всех разные, и снижение
    # прайса — не гарантия ускорения, а условие сравнения.
    if out.get("premium_on_remainder") and out.get("months_lost"):
        out["price_of_month"] = round(
            out["premium_on_remainder"] / out["months_lost"], 1
        ) if out["months_lost"] else None
        out["trade"] = (
            f"Отказ от премии — это минус {_num(out['premium_on_remainder'], 1)} млн ₽ "
            f"на остатке и минус {_num(out['months_lost'], 1)} месяца срока: "
            f"{_num(out['price_of_month'], 1)} млн ₽ за каждый выигранный месяц. "
            "Цена соседей не покупает их темп сама по себе — это условие сравнения, "
            "а не обещание."
        )
    return out


def shelf(price: float | None, city) -> dict[str, Any] | None:
    """В диапазоне какого класса лежит цена проекта.

    Метка класса и цена — разные вещи. Покупатель ищет фильтром: ставит
    «бизнес» и видит список, где наш проект крайний по цене, а рядом — те же
    метры дешевле. Что цена при этом попадает в премиальный диапазон, он не
    знает: в премиальную витрину проект не показывается.
    """
    if not price or not getattr(city, "available", False):
        return None
    inside, nearest, gap, bands = [], None, None, []
    for name in city.segments():
        snapshot = city.snapshot(name)
        if not snapshot or not snapshot.price_median:
            continue
        low, high = snapshot.price_p25, snapshot.price_p75
        bands.append({"segment": name, "p25": low, "p75": high, "median": snapshot.price_median})
        if low and high and low <= price <= high:
            inside.append({"segment": name, "p25": low, "p75": high, "median": snapshot.price_median})
        distance = abs(price - snapshot.price_median)
        if gap is None or distance < gap:
            gap, nearest = distance, {"segment": name, "median": snapshot.price_median}
    # Между полками: дороже верхнего квартиля одного класса и дешевле нижнего
    # квартиля следующего. Это не мелочь, а самое неудобное место на рынке —
    # в своей витрине проект крайний, в соседнюю он не попадает.
    between = None
    ordered = sorted((b for b in bands if b["p25"] and b["p75"]), key=lambda b: b["median"])
    for lower, upper in zip(ordered, ordered[1:]):
        if lower["p75"] < price < upper["p25"]:
            between = {"below": lower, "above": upper}
            break
    return {"inside": inside, "nearest": nearest, "between": between}


def positioning(subject: dict[str, Any], peers: list[dict[str, Any]], city) -> dict[str, Any] | None:
    """Главный вывод: попадает ли проект в свою полку.

    Считается по двум вещам, которые видит покупатель: место в ряду цен своего
    класса и объём предложения дешевле. Всё остальное — подробности.
    """
    price = subject.get("price_per_sqm")
    label = subject.get("segment")
    if not price:
        return None
    priced = [p for p in peers or [] if p.get("price_per_sqm")]
    same = [p for p in priced if p.get("segment") == label]
    # Витрина и те, кто в ней дешевле, — одно и то же множество. Прежде
    # дешёвых искали сперва среди своего класса, а при неудаче среди всей
    # выборки, витрину же считали своим классом: у проекта, где в своём
    # классе дешевле нет никого, а в выборке трое, выходило «в витрине из
    # 2 проектов наш -1-й по цене — дешевле него 3». Место в ряду считается
    # внутри того ряда, о котором говорят.
    pool = same or priced
    cheaper = [p for p in pool if p["price_per_sqm"] < price]
    lots_cheaper = int(sum(p.get("lot_count") or 0 for p in cheaper))

    where = shelf(price, city)
    lines: list[str] = []
    tone = TONE_FLAT

    if pool:
        total = len(pool) + 1  # соседи плюс мы: витрина, которую видит покупатель
        rank = total - len(cheaper)
        lines.append(
            f"В своей витрине из {total} проектов наш "
            + ("самый дорогой" if rank == 1 else f"{rank}-й по цене")
            + f" — дешевле него {len(cheaper)}."
        )
    if where and where.get("between"):
        low, high = where["between"]["below"], where["between"]["above"]
        lines.append(
            f"Цена {_num(price)} ₽/м² попала между полками: выше верхнего квартиля класса "
            f"«{low['segment']}» ({_num(low['p75'])} ₽/м²) и ниже нижнего квартиля класса "
            f"«{high['segment']}» ({_num(high['p25'])} ₽/м²)."
        )
        lines.append(
            f"Это самое неудобное место на рынке. Покупатель ищет фильтром: в витрине "
            f"«{low['segment']}» наш проект крайний по цене, и рядом те же метры дешевле; "
            f"в витрину «{high['segment']}», где такая цена обычна, он не показывается — "
            "по метке он туда не проходит."
        )
        tone = TONE_BAD
    elif where and where["inside"]:
        names = [row["segment"] for row in where["inside"]]
        if label and label not in names:
            band = where["inside"][0]
            lines.append(
                f"Метка класса — «{label}», но цена {_num(price)} ₽/м² лежит в диапазоне "
                f"«{band['segment']}» по Москве ({_num(band['p25'])}–{_num(band['p75'])} ₽/м²)."
            )
            lines.append(
                f"Покупатель ищет фильтром: ставит «{label}» и видит наш проект крайним по цене, "
                f"а рядом те же метры дешевле. В витрину «{band['segment']}», где эта цена обычна, "
                "проект не показывается."
            )
            tone = TONE_BAD
    elif where and where["nearest"] and label and where["nearest"]["segment"] != label:
        lines.append(
            f"Метка класса — «{label}», а по цене проект ближе всего к медиане класса "
            f"«{where['nearest']['segment']}» ({_num(where['nearest']['median'])} ₽/м²)."
        )
        tone = TONE_WATCH
    if lots_cheaper:
        lines.append(
            f"Выбор у покупателя не из трёх домов: только у соседей дешевле нас "
            f"{_num(lots_cheaper)} лотов в экспозиции."
        )
    if not lines:
        return None
    return {
        "tone": tone,
        "text": " ".join(lines),
        "cheaper_projects": len(cheaper),
        "pool": len(pool),
        "lots_cheaper": lots_cheaper,
        "shelf": where,
    }


def site_mix(peers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Раскладка соседей по классам: что здесь вообще продаётся.

    Вывод называет один класс — здешний продукт, — но решение принимают,
    видя всю линейку: сколько чего рядом, по какой цене, каким темпом и каким
    лотом. Без этого «строить элитный» — утверждение без основания на экране.

    Проекты без действующего прайса из цены выпадают, а из счёта и темпа —
    нет: продукт и скорость они показывают честно, и для площадки это важнее
    цены. Сколько их, сказано отдельной колонкой, чтобы медиана по двум
    прайсам не читалась как медиана по десяти проектам.
    """
    by_class: dict[str, list[dict[str, Any]]] = {}
    for row in peers:
        level = normalize_segment(row.get("segment"))
        if level:
            by_class.setdefault(level, []).append(row)

    order = [ELITE, PREMIUM, BUSINESS, COMFORT, ECONOMY]
    out: list[dict[str, Any]] = []
    for level in order:
        rows = by_class.get(level)
        if not rows:
            continue
        prices = [float(r["price_per_sqm"]) for r in rows if r.get("price_per_sqm")]
        pace = [float(r["units_per_month"]) for r in rows if r.get("units_per_month")]
        lots = [float(r["sold_lot_avg"]) for r in rows if r.get("sold_lot_avg")]
        exposure = [float(r["lot_count"]) for r in rows if r.get("lot_count")]
        out.append(
            {
                "segment": level,
                "projects": len(rows),
                "priced": len(prices),
                "price_median": int(_median(prices)) if prices else None,
                "units_per_month": round(_median(pace), 1) if pace else None,
                "sold_lot_avg": round(_median(lots), 1) if lots else None,
                "exposure": int(sum(exposure)) if exposure else None,
            }
        )
    return out


def site_verdict(peers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Что здесь строить и почём — вывод для площадки без своего проекта.

    У голого участка нет ни прайса, ни темпа, и обычный вывод («цена рынком
    не подтверждается») не складывается: сравнивать нечего. Раньше на этом
    месте так и стояло «вывод не сложился» — то есть отчёт молчал ровно там,
    где решение и принимают. Между тем соседи отвечают на оба вопроса
    покупки: какой продукт здесь берут и по какой цене.

    Класс выбирается по числу проектов, а не по деньгам: один дорогой сосед
    не делает место дорогим. При равенстве берётся верхний уровень — ошибиться
    в сторону более дорогого продукта дешевле, чем построить дешёвый там, где
    покупают дорогое: цену вниз двигать можно, продукт — нет.

    Цена — медиана действующих прайсов этого класса. Соседи с мёртвым прайсом
    в неё не идут, но в счёт проектов и в темп идут: продукт и скорость они
    показывают честно.
    """
    if not peers:
        return None

    by_class: dict[str, list[dict[str, Any]]] = {}
    for row in peers:
        level = normalize_segment(row.get("segment"))
        if level:
            by_class.setdefault(level, []).append(row)
    if not by_class:
        return None

    order = [ELITE, PREMIUM, BUSINESS, COMFORT, ECONOMY]
    level = max(by_class, key=lambda key: (len(by_class[key]), -order.index(key)))
    rows = by_class[level]

    prices = [row["price_per_sqm"] for row in rows if row.get("price_per_sqm")]
    pace = [row["units_per_month"] for row in rows if row.get("units_per_month")]
    lots = [row["sold_lot_avg"] for row in rows if row.get("sold_lot_avg")]
    price = _median([float(v) for v in prices])
    speed = _median([float(v) for v in pace])
    lot = _median([float(v) for v in lots])

    said = [
        f"Вокруг участка {len(rows)} из {len(peers)} сопоставимых проектов — «{level}»; "
        f"это и есть здешний продукт."
    ]
    if price:
        said.append(
            f"Действующие прайсы этого класса дают медиану {_num(price)} ₽/м² "
            f"({len(prices)} из {len(rows)} с живой ценой) — от неё и считать."
        )
    else:
        said.append(
            f"Действующих прайсов у соседей этого класса нет ни одного, "
            f"поэтому цену отсюда взять нельзя — только продукт."
        )
    if speed:
        said.append(f"Темп у них — медиана {_num(speed, 1)} ДДУ в месяц.")
    if lot:
        said.append(f"Берут лот около {_num(lot, 1)} м² — на него и считать квартирографию.")

    return {
        "tone": TONE_FLAT,
        "headline": f"Здесь строят «{level}»" + (f" по {_num(price)} ₽/м²" if price else ""),
        "text": " ".join(said),
        "segment": level,
        "price_per_sqm": int(price) if price else None,
        "units_per_month": round(speed, 1) if speed else None,
        "sold_lot_avg": round(lot, 1) if lot else None,
        "projects": len(rows),
        "priced": len(prices),
    }


CAVEATS = [
    "Цена — прайс-лист, а не сделка: реальные договоры проходят со скидкой, "
    "и её размер у каждого свой.",
    "Темп считается по зарегистрированным ДДУ и отстаёт от брони на срок регистрации.",
    "Класс ставит источник. Он маркетинговый, а не нормативный: соседний уровень "
    "у одного проекта и у другого может значить разное.",
    "Сравнение идёт по действующим прайсам. Проект, распроданный год назад, "
    "в выборку не входит, и рынок из-за этого выглядит дороже, чем был.",
    "Радиус — геометрия, а не рынок: река, железная дорога и шоссе делят районы "
    "сильнее, чем километры.",
]


def build_notes(blocks: list[dict[str, Any]], series: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Разбор по каждому разделу плюс общий вывод."""
    notes: dict[str, dict[str, Any]] = {}
    for block in blocks:
        code = block.get("code")
        builder = NOTE_BUILDERS.get(str(code))
        if not builder:
            continue
        notes[str(code)] = (
            builder(block, series) if code == "price" else builder(block)  # type: ignore[call-arg]
        )
    return {"blocks": notes, "overall": overall(blocks, notes), "caveats": list(CAVEATS)}
