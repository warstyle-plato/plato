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


NOTE_BUILDERS = {
    "price": price_note,
    "pace": pace_note,
    "stock": stock_note,
    "lot_size": lot_note,
    "absorption": absorption_note,
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
    return {"blocks": notes, "overall": overall(blocks, notes)}
