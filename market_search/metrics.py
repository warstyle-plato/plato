"""Метрики отчёта: блоками, а не сплошным текстом.

Конструктор отчёта — это выбор блоков, а не свободная генерация. Каждый блок
знает, что он считает, из чего и чего не знает; Платон Сергеевич получает
готовые числа и пишет по ним словами. Обратный порядок — когда модель считает
сама — однажды даёт правдоподобную и неверную медиану, которую нечем проверить.

Блок отвечает на один вопрос сразу в трёх основаниях:

* **сам проект** — что у него;
* **соседи** — те, кто рядом и сопоставим;
* **город** — Москва того же класса, из свода `market_reference`.

Пустая база — не ошибка: блок возвращает то, что смог посчитать, и говорит,
чего не хватило. Молчаливый ноль в отчёте об оценке опаснее пропуска.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable

from .market_reference import MoscowMarket
from .segments import normalize_segment


BLOCK_PRICE = "price"
BLOCK_PACE = "pace"
BLOCK_STOCK = "stock"
BLOCK_LOT = "lot_size"
BLOCK_ABSORPTION = "absorption"
BLOCK_ROOMS = "rooms"
BLOCK_PAYMENT = "payment"
BLOCK_CHANNEL = "channel"

BLOCK_TITLES = {
    BLOCK_PRICE: "Цена метра",
    BLOCK_PACE: "Темп продаж",
    BLOCK_STOCK: "Остаток и экспозиция",
    BLOCK_LOT: "Размер лота",
    BLOCK_ABSORPTION: "Поглощение в метрах",
    BLOCK_ROOMS: "Комнатность и вымывание",
    BLOCK_PAYMENT: "Способы оплаты",
    BLOCK_CHANNEL: "Кто покупает",
}


@dataclass
class MetricBlock:
    code: str
    title: str
    subject: dict[str, Any] = field(default_factory=dict)
    peers: dict[str, Any] = field(default_factory=dict)
    city: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return bool(self.subject)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "subject": self.subject,
            "peers": self.peers,
            "city": self.city,
            "notes": self.notes,
        }


def _median(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None]
    return statistics.median(clean) if clean else None


def _round(value: float | None, digits: int = 0) -> float | int | None:
    if value is None:
        return None
    return int(round(value)) if digits == 0 else round(value, digits)


def _ratio(value: float | None, base: float | None) -> float | None:
    if not value or not base:
        return None
    return round((value / base - 1) * 100, 1)


def _peer_stats(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [row.get(key) for row in rows if row.get(key) is not None]
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "median": round(statistics.median(values), 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
        "names": [row.get("name") for row in rows if row.get(key) is not None][:12],
    }


def _class_key(row: dict[str, Any]) -> str | None:
    """Ключ «своего класса»: метка источника, если он различает тоньше нашей лестницы.

    Решение владельца 30.08.2026: «считаем как считает источник». У bnMAP класс
    дробный — «Бизнес+», «Бизнес», «Бизнес−», — и наша лестница из пяти ступеней
    сводит их в один «бизнес». Тогда медиана своего класса совпадает с общей, и
    тонкость источника пропадает МОЛЧА: на Кутузов Сити это разница между
    504 904 ₽/м² по смешанной выборке и 783 431 у единственного соседа того же
    класса, что назвал источник.

    Строка, пришедшая с меткой источника (`segment_exact`), группируется по ней.
    Остальные — по ступени лестницы, как раньше: у «Пульса» дробных меток нет, и
    его путь этой правкой не двигается.
    """
    exact = row.get("segment_exact")
    if exact:
        return " ".join(str(exact).split()).casefold()
    return normalize_segment(row.get("segment"))


def _add_same_class(
    block: MetricBlock,
    subject: dict[str, Any],
    peers: list[dict[str, Any]],
    price: float,
) -> None:
    """Медиана по своему классу — рядом с общей, когда выборка смешанная.

    Соседний класс берётся в выборку по решению владельца от 10.08.2026, и на
    элитном конце это верно: элитный и премиум конкурируют за одного покупателя.
    Но у бизнес-класса соседи — комфорт и премиум, и в Можайском районе это
    разброс от 268 до 1254 тыс ₽/м²: медиана такой выборки — не уровень рынка,
    а середина между тремя разными товарами. Отдельная медиана своего класса
    показывает, из чего сложилась общая, вместо того чтобы прятать это в одно
    число.
    """
    own = _class_key(subject)
    if not own:
        return
    same = [row for row in peers if _class_key(row) == own]
    if not same or len(same) == len(peers):
        return
    exact = _peer_stats(same, "price_per_sqm")
    if not exact["count"]:
        return
    block.peers["same_class"] = {**exact, "vs_median_pct": _ratio(price, exact["median"])}
    label = subject.get("segment_exact") or own
    # Разделитель тысяч заменяется в САМОМ ЧИСЛЕ, а не во всей строке: прежде
    # `.replace(",", " ")` стояла на конце f-строки и вместе с разделителем
    # съедала запятую предложения — «1 из 4  их медиана».
    median = f"{exact['median']:,.0f}".replace(",", " ")
    block.notes.append(
        f"В выборку входят соседние классы; только своего класса «{label}» — "
        f"{exact['count']} из {len(peers)}, их медиана {median} ₽/м²"
    )


def price_block(subject: dict[str, Any], peers: list[dict[str, Any]], city: MoscowMarket) -> MetricBlock:
    block = MetricBlock(BLOCK_PRICE, BLOCK_TITLES[BLOCK_PRICE])
    price = subject.get("price_per_sqm")
    if not price:
        block.notes.append("У проекта нет действующего прайса, сравнивать нечего")
        return block
    block.subject = {
        "price_per_sqm": price,
        "price_min": subject.get("price_per_sqm_min"),
        "price_max": subject.get("price_per_sqm_max"),
        "observed_at": subject.get("observed_at"),
        "basis": "прайс-лист, не сделка",
    }
    stats = _peer_stats(peers, "price_per_sqm")
    if stats["count"]:
        block.peers = {**stats, "vs_median_pct": _ratio(price, stats["median"])}
        _add_same_class(block, subject, peers, price)
    else:
        block.notes.append("Ни у одного сопоставимого соседа нет действующего прайса")

    snapshot = city.snapshot(subject.get("segment"))
    if snapshot:
        block.city = {
            "segment": snapshot.segment,
            "projects": snapshot.projects,
            "observed_at": city.observed_at,
            **(snapshot.position(price) or {}),
        }
        if snapshot.discount_projects:
            # Медиана по всем объявившим выходит нулём — скидку даёт примерно
            # каждый второй. Одно это число читается как «скидок на рынке нет»,
            # поэтому рядом стоит, сколько проектов её дают и какая она у них.
            offering = snapshot.discount_offering or 0
            if offering:
                block.notes.append(
                    # «53 проектов» — падеж числительного. Оборот «53 из 85
                    # проектов» верен при любом числе, и склонять нечего.
                    f"Скидку к прайсу в классе «{snapshot.segment}» объявляют {offering} "
                    f"из {snapshot.discount_projects} проектов; у них она "
                    f"{snapshot.discount_median_offered_pct} % по медиане, у остальных "
                    f"нулевая. Прайс и сделка — разные числа, и у проекта скидка своя"
                )
            else:
                block.notes.append(
                    f"Ни один проект класса «{snapshot.segment}» скидки к прайсу в этом "
                    f"месяце не объявил"
                )
    elif subject.get("segment"):
        block.notes.append("В своде рынка нет класса этого проекта")
    else:
        block.notes.append("Класс проекта не определён — сравнение с городом невозможно")
    return block


def pace_block(subject: dict[str, Any], peers: list[dict[str, Any]], city: MoscowMarket) -> MetricBlock:
    block = MetricBlock(BLOCK_PACE, BLOCK_TITLES[BLOCK_PACE])
    pace = subject.get("units_per_month")
    if pace is None:
        block.notes.append("Темп продаж по проекту неизвестен")
        return block
    block.subject = {
        "units_per_month": pace,
        "units_per_month_3m": subject.get("units_per_month_3m"),
        "sales_end_forecast": subject.get("sales_end_forecast"),
        "known_sales_for": subject.get("known_sales_for"),
    }
    stats = _peer_stats(peers, "units_per_month")
    if stats["count"]:
        slower = None
        if pace and stats["median"]:
            slower = round(stats["median"] / pace, 1) if pace else None
        block.peers = {**stats, "vs_median_pct": _ratio(pace, stats["median"]),
                       "peer_median_over_subject": slower}
    snapshot = city.snapshot(subject.get("segment"))
    if snapshot and snapshot.sold_median is not None:
        block.city = {
            "segment": snapshot.segment,
            "sold_median": snapshot.sold_median,
            "sold_total": snapshot.sold_total,
            "projects": snapshot.projects,
            "observed_at": city.observed_at,
            "vs_median_pct": _ratio(pace, snapshot.sold_median),
        }
    block.notes.append(
        "Темп считается по зарегистрированным ДДУ и отстаёт от брони на срок регистрации"
    )
    return block


def stock_block(subject: dict[str, Any], peers: list[dict[str, Any]], city: MoscowMarket) -> MetricBlock:
    block = MetricBlock(BLOCK_STOCK, BLOCK_TITLES[BLOCK_STOCK])
    remaining = subject.get("remaining_units")
    exposure = subject.get("lot_count")
    if remaining is None and exposure is None:
        block.notes.append("Ни остаток, ни экспозиция по проекту неизвестны")
        return block
    total = subject.get("living_units")
    block.subject = {
        "remaining_units": remaining,
        "remaining_area": subject.get("remaining_area"),
        "living_units": total,
        "exposure_lots": exposure,
        "exposure_share_pct": round(exposure / total * 100, 1) if exposure and total else None,
    }
    pace = subject.get("units_per_month")
    if remaining and pace:
        block.subject["months_to_sell"] = round(remaining / pace, 1)
    peer_exposure = [row.get("lot_count") for row in peers if row.get("lot_count")]
    if peer_exposure:
        block.peers = {
            "count": len(peer_exposure),
            "exposure_total": int(sum(peer_exposure)),
            "exposure_median": round(statistics.median(peer_exposure), 1),
            "subject_share_pct": round(
                (exposure or 0) / (sum(peer_exposure) + (exposure or 0)) * 100, 1
            ) if exposure else None,
        }
    snapshot = city.snapshot(subject.get("segment"))
    if snapshot and snapshot.remainder_total:
        block.city = {
            "segment": snapshot.segment,
            "remainder_total": snapshot.remainder_total,
            "observed_at": city.observed_at,
        }
    return block


def lot_size_block(subject: dict[str, Any], peers: list[dict[str, Any]], city: MoscowMarket) -> MetricBlock:
    block = MetricBlock(BLOCK_LOT, BLOCK_TITLES[BLOCK_LOT])
    # Средний проданный лот приходит либо готовым от источника, либо считается
    # из проданных метров и штук: делить их можно, потому что оба числа
    # посчитаны по одному периоду.
    sold_units = subject.get("sold_units")
    sold_area = subject.get("sold_area")
    average = subject.get("sold_lot_avg")
    if average is None and sold_units and sold_area:
        average = round(sold_area / sold_units, 1)
    project_average = subject.get("lot_area_avg")
    if average is None and project_average is None:
        block.notes.append("Размер лота по проекту неизвестен")
        return block
    block.subject = {
        "sold_lot_avg": average,
        "project_lot_avg": project_average,
        "gap_pct": _ratio(average, project_average),
    }
    if average and project_average and average < project_average * 0.95:
        block.notes.append(
            "Средний проданный лот меньше среднего лота в проекте: уходят квартиры "
            "меньше средней, крупные форматы стоят"
        )
    stats = _peer_stats(peers, "sold_lot_avg")
    if stats["count"]:
        block.peers = {**stats, "vs_median_pct": _ratio(average, stats["median"])}
    return block


def absorption_block(subject: dict[str, Any], peers: list[dict[str, Any]], city: MoscowMarket) -> MetricBlock:
    """Метры в месяц — поглощение, свободное от квартирографии.

    Штуки зависят от того, что за квартиры в проекте: сто студий и сто
    трёхкомнатных продаются по-разному. Метры от этого свободны.
    """
    block = MetricBlock(BLOCK_ABSORPTION, BLOCK_TITLES[BLOCK_ABSORPTION])
    area = subject.get("area_per_month")
    if area is None:
        block.notes.append("Поглощение в метрах по проекту неизвестно")
        return block
    block.subject = {"area_per_month": area}
    stats = _peer_stats(peers, "area_per_month")
    if stats["count"]:
        block.peers = {**stats, "vs_median_pct": _ratio(area, stats["median"])}
    return block






ROOM_TITLES = {
    "studio": "студии",
    "r1": "1-комнатные",
    "r2": "2-комнатные",
    "r3": "3-комнатные",
    "r4": "4-комнатные",
    "r5": "5-комнатные и больше",
}


# За сколько месяцев считается «что берут». Один месяц у одного ЖК — это
# десяток сделок, то есть шум: доля пляшет от месяца к месяцу, а в тихий месяц
# её нет вовсе. Год — срок, за который проект успевает показать спрос на каждую
# комнатность, и он же граница памяти справочника.
ROOM_WINDOW_MONTHS = 12


def _room_window(row: dict[str, Any], span: int = ROOM_WINDOW_MONTHS) -> dict[str, Any] | None:
    """Продано по комнатности за окно — и само окно, названное месяцами.

    Ряда нет — возвращается `None`, и это «справочник собран прежним импортом»,
    а не «продаж не было»: два разных ответа, и подменять первый вторым нельзя.
    """
    line = row.get("rooms_sold") or {}
    months = row.get("rooms_months") or []
    if not line or not months:
        return None
    span = min(span, len(months))
    start = len(months) - span
    sold: dict[str, float] = {}
    for name, values in line.items():
        total = sum(float(value) for value in values[start:] if value)
        if total:
            sold[name] = total
    if not sold:
        return None
    return {"sold": sold, "from": months[start], "to": months[-1], "months": span}


# Помесячная доля рисует шум как сигнал. Замер по августовской книге (365
# проектов с рядом): активных месяцев из двенадцати медианно семь, в 40 %
# активных месяцев меньше десяти сделок — там одна сделка двигает долю на
# десяток процентов, — а месячный скачок ведущей доли медианно 21,7 п.п. при
# девяностом процентиле в 60. Квартал даёт 36 сделок в точке медианно и скачок
# 17,7 п.п.: разброс падает вдвое, и остаток от него — не шум выборки, а
# настоящая смена того, что вывели в продажу.
# Ниже этого точку рисуем, но называем малой: доля на пяти сделках выглядит на
# картинке ровно так же, как доля на пятидесяти.
ROOM_TREND_MIN_DEALS = 10


def _room_trend(
    row: dict[str, Any],
    span: int = ROOM_WINDOW_MONTHS,
) -> list[dict[str, Any]]:
    """Как менялся состав спроса — по КАЛЕНДАРНЫМ кварталам окна.

    Квартал, а не месяц: помесячно у одного ЖК десяток сделок, и доля пляшет
    сильнее, чем меняется спрос (замер выше). Календарный, а не «три месяца от
    конца окна»: «1 кв. 2025» читается однозначно, а «09.25–11.25» и как три
    месяца, и как два (вычитанием краёв) — и второе прочтение оспорить нечем
    (владелец, 07.09.2026). Нарезка от конца окна кварталом НЕ является, и
    подписать её кварталом значило бы соврать: менять надо саму нарезку.

    Цена честного имени — неполные края: окно в двенадцать месяцев кончается
    месяцем отчёта, поэтому первый и последний кварталы бывают короче. Сколько
    месяцев в точке, она говорит сама, а не выдаёт часть за целое.

    Пустой квартал выбрасывается, а не рисуется нулями: пропуск в ряду — не
    ноль, и колонка нулевой высоты показала бы состав спроса там, где спроса не
    было вовсе. Сколько сделок в точке — тоже часть ответа: доля на пяти
    сделках и доля на пятидесяти на картинке неразличимы.
    """
    line = row.get("rooms_sold") or {}
    months = row.get("rooms_months") or []
    if not line or not months:
        return []
    span = min(span, len(months))
    start = len(months) - span

    buckets: dict[tuple[int, int], list[int]] = {}
    for index in range(start, len(months)):
        year, month = (int(part) for part in str(months[index]).split("-")[:2])
        buckets.setdefault((year, (month - 1) // 3 + 1), []).append(index)

    out: list[dict[str, Any]] = []
    for (year, quarter), indexes in sorted(buckets.items()):
        point: dict[str, float] = {}
        for name, values in line.items():
            total = sum(
                float(values[index])
                for index in indexes
                if index < len(values) and values[index]
            )
            if total:
                point[name] = total
        deals = sum(point.values())
        if not deals:
            continue
        out.append({
            "year": year,
            "quarter": quarter,
            "from": months[indexes[0]],
            "to": months[indexes[-1]],
            # Длина точки — ответ сервера, а не экрана: неполный край окна
            # обязан назвать себя, а не выглядеть целым кварталом.
            "months": len(indexes),
            "deals": round(deals, 1),
            "shares": {
                name: round(value / deals * 100, 1)
                for name, value in sorted(point.items())
            },
        })
    return out


def _room_shift(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Что сдвинулось между первой и последней точкой — если сдвиг читается.

    Читается он не «на глаз»: доля, снятая с горстки сделок, гуляет сама по
    себе, и порог берётся из числа сделок обеих точек — удвоенная ошибка
    разности двух долей. Сдвиг ниже порога не называется вовсе: названный, он
    выглядел бы измеренным ровно так же, как настоящий.
    """
    if len(points) < 2:
        return None
    first, last = points[0], points[-1]
    n_first, n_last = float(first["deals"]), float(last["deals"])
    if n_first <= 0 or n_last <= 0:
        return None
    # Порядок обхода задан: у двух комнатностей сдвиги равны по величине и
    # противоположны по знаку, и множество отдавало победителя по-разному от
    # запуска к запуску — один проект получал две разные фразы, и обе выглядели
    # бы верными. При равенстве называется выросшая: «берут больше того-то»
    # отвечает на вопрос раздела, «берут меньше того-то» — его зеркало.
    best: dict[str, Any] | None = None
    for name in sorted(set(first["shares"]) | set(last["shares"])):
        was = float(first["shares"].get(name) or 0)
        now = float(last["shares"].get(name) or 0)
        delta = now - was
        error = math.sqrt(
            was / 100 * (1 - was / 100) / n_first + now / 100 * (1 - now / 100) / n_last
        ) * 100
        if abs(delta) <= 2 * error:
            continue
        better = best is None or (abs(delta), delta) > (abs(best["delta_pp"]), best["delta_pp"])
        if better:
            best = {
                "name": name,
                "was_pct": round(was, 1),
                "now_pct": round(now, 1),
                "delta_pp": round(delta, 1),
                "deals_was": round(n_first, 1),
                "deals_now": round(n_last, 1),
                "from": first["from"],
                "to": last["to"],
            }
    return best


def _room_mix_from_series(row: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Состав по комнатности из ряда, когда снимка последнего месяца нет.

    Снимок «Пульс» кладёт только в тот месяц, где по проекту были сделки: на
    августовской книге он есть у 202 проектов из 368, а годовой ряд — у 365.
    Пересечение 197, и 75 проектов имеют ЦЕЛЫЙ ГОД продаж по комнатности, о
    которых блок молчал — требовал снимок и без него не строил ничего. Это тот
    же случай, что пустой ответ НСПД, выданный за отсутствие ограничений:
    источник ответил, а мы показываем пустоту.

    Проданное придёт окном, поэтому здесь только остаток — из ПОСЛЕДНЕГО
    месяца, где он назван. Вместе с ним возвращается его месяц: остаток такого
    проекта не сегодняшний, и подписать его «сегодняшним» значит соврать о
    дате. Цен здесь нет вовсе — их помесячно не храним, и разложение разрыва
    цены таким проектам не считается.
    """
    line = row.get("rooms_rem") or {}
    months = row.get("rooms_months") or []
    if not line or not months:
        return {}, None
    for index in range(min(len(months), max((len(v) for v in line.values()), default=0)) - 1, -1, -1):
        at = {
            name: values[index]
            for name, values in line.items()
            if index < len(values) and values[index] is not None
        }
        if at:
            return {name: {"rem": value} for name, value in sorted(at.items())}, months[index]
    return {}, None


def _room_shares(
    rooms: dict[str, Any] | None, window: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Доли в проданном и в остатке по комнатности.

    Считаются от суммы известных строк, а не от «всего по ПД»: комнатность
    части лотов источник не знает, и деление на общий объём молча занизило бы
    каждую долю.

    Проданное берётся за окно, когда оно есть: месяц отвечает «что взяли в
    августе», а вопрос у раздела другой — «что берут». Остаток остаётся
    сегодняшним: он и есть сегодняшний.
    """
    if not rooms:
        return {}
    sold_by_room = (window or {}).get("sold") if window else None
    if sold_by_room is not None:
        rooms = {
            name: {**item, "sold": sold_by_room.get(name, 0)}
            for name, item in rooms.items()
        }
        for name, value in sold_by_room.items():
            if name not in rooms:
                rooms[name] = {"sold": value}
    sold_total = sum(float(item.get("sold") or 0) for item in rooms.values())
    rem_total = sum(float(item.get("rem") or 0) for item in rooms.values())
    out: dict[str, Any] = {}
    for name, item in rooms.items():
        row: dict[str, Any] = {"title": ROOM_TITLES.get(name, name)}
        if item.get("total") is not None:
            row["total"] = item["total"]
        if item.get("rem") is not None:
            row["rem"] = item["rem"]
            row["rem_share_pct"] = round(item["rem"] / rem_total * 100, 1) if rem_total else None
        if item.get("sold") is not None:
            row["sold"] = item["sold"]
            row["sold_share_pct"] = (
                round(item["sold"] / sold_total * 100, 1) if sold_total else None
            )
        if item.get("price"):
            row["price_per_sqm"] = item["price"]
        if item.get("lot_avg"):
            row["lot_avg"] = round(float(item["lot_avg"]), 1)
        out[name] = row
    return out


def _weighted_price(prices: dict[str, float], weights: dict[str, float]) -> tuple[float | None, float]:
    """Цена метра при заданном наборе квартир.

    Возвращает саму цену и долю набора, на которую цена известна: комнатность,
    у которой цены нет, из веса выбрасывается — иначе она молча считалась бы по
    средней, а средняя тут и есть предмет спора. Доля покрытия печатается
    рядом с числом: «580 тыс при наборе соседей» на трети набора — не ответ.
    """
    known = {name: weights.get(name, 0.0) for name in prices if weights.get(name)}
    total_weight = sum(weights.values())
    covered = sum(known.values())
    if not covered:
        return None, 0.0
    price = sum(prices[name] * weight for name, weight in known.items()) / covered
    return round(price), round(covered / total_weight * 100, 1) if total_weight else 0.0


def _mix_effect(
    own_prices: dict[str, float],
    own_weights: dict[str, float],
    peer_prices: dict[str, float],
    peer_weights: dict[str, float],
) -> dict[str, Any]:
    """Сколько разрыва в цене метра объясняется набором квартир, а не уровнем цен.

    Вопрос владельца (05.09.2026): «соседи продают крупные лоты больше, и
    поэтому цена у них ниже?» Внутри одного проекта метр тем дороже, чем мельче
    квартира — на живом примере студии 644 тыс против 379 у трёшек, — поэтому
    проект с крупным набором показывает цену ниже при тех же ценах на каждый
    товар. Но ПО РЫНКУ связь обратная: у 174 проектов августа корреляция
    «средний проданный лот ↔ медианная цена метра» +0,64, потому что крупные
    форматы строят в дорогих классах. Значит на догадку отвечать нельзя — надо
    считать на своём проекте.
    
    Считается стандартизацией: наша цена при НАШЕМ наборе и наша же цена при
    наборе соседей. Разница между ними — вклад структуры; остаток общего
    разрыва — уровень цен. Обе половины считаются на ЦЕНАХ ПРАЙСА по
    комнатности из одного источника: смешивать их со средней ценой экспозиции
    из кабинета нельзя, это разные величины.
    """
    own_at_own, own_cover = _weighted_price(own_prices, own_weights)
    own_at_peer, cross_cover = _weighted_price(own_prices, peer_weights)
    peer_at_peer, peer_cover = _weighted_price(peer_prices, peer_weights)
    if own_at_own is None or own_at_peer is None or peer_at_peer is None:
        return {}
    out: dict[str, Any] = {
        "own_at_own_mix": own_at_own,
        "own_at_peers_mix": own_at_peer,
        "peers_at_peers_mix": peer_at_peer,
        "own_coverage_pct": own_cover,
        "peers_coverage_pct": peer_cover,
        "cross_coverage_pct": cross_cover,
        "gap_pct": round((own_at_own / peer_at_peer - 1) * 100, 1),
        "mix_pct": round((own_at_peer / own_at_own - 1) * 100, 1),
        "level_pct": round((own_at_peer / peer_at_peer - 1) * 100, 1),
    }
    return out


def rooms_block(
    subject: dict[str, Any], peers: list[dict[str, Any]], city: MoscowMarket
) -> MetricBlock:
    """Что берут и что остаётся — по комнатности и по полосам площади.

    Комнатность отвечает на «какой продукт», полосы — на «какой метраж»: двушка
    бывает и 44 м², и 84, и в вымывании это разные товары. Обе линейки стоят
    рядом, потому что источник даёт первую отчётом, а вторую — выписками.
    """
    block = MetricBlock(BLOCK_ROOMS, BLOCK_TITLES[BLOCK_ROOMS])
    window = _room_window(subject)
    mix, rem_at = subject.get("room_mix"), None
    if not mix and window:
        mix, rem_at = _room_mix_from_series(subject)
    own = _room_shares(mix, window)
    bands = subject.get("bands") or {}
    if not own and not bands:
        block.notes.append(
            "Комнатность проекта в отчёте не раскрыта — сравнивать продукт не с чем"
        )
        return block
    if own:
        block.subject["rooms"] = own
        if window:
            # Окно называется вслух: «доля в проданном» за месяц и за год —
            # разные величины, и без подписи первую читают как вторую.
            block.subject["rooms_window"] = {
                "from": window["from"],
                "to": window["to"],
                "months": window["months"],
                "deals": round(sum(window["sold"].values()), 1),
            }
            if rem_at:
                block.subject["rooms_rem_at"] = rem_at
            trend = _room_trend(subject)
            if len(trend) > 1:
                block.subject["rooms_trend"] = trend
                shift = _room_shift(trend)
                if shift:
                    block.subject["rooms_shift"] = shift
                thin = [point for point in trend if point["deals"] < ROOM_TREND_MIN_DEALS]
                if thin:
                    block.subject["rooms_trend_thin"] = len(thin)
            else:
                block.subject["rooms_trend_gap"] = (
                    "Продажи по комнатности уложились в один квартал — "
                    "сравнивать состав спроса не с чем"
                )
        else:
            block.subject["rooms_trend_gap"] = (
                "Помесячной комнатности в справочнике нет: он собран прежним "
                "импортом. Перезалейте книгу «Пульса» — тогда появится и "
                "динамика доли, и её счёт за год"
            )
        if not sum(float(item.get("sold") or 0) for item in own.values()):
            # Ноль в доле проданного и «в этом месяце не продавали» на экране
            # выглядят одинаково, а это разные ответы. Причина стоит У САМОГО
            # ГРАФИКА, а не строкой выше: легенда обещает две полосы, и когда
            # рисуется одна, читается это как поломка, а не как молчание
            # источника. Комнатность отчёт даёт помесячно, и продаж в последнем
            # месяце у каждого восьмого проекта нет (25 из 202 на выпуске
            # 2026-08) — то есть это обычный случай, а не редкость.
            block.subject["rooms_sold_gap"] = (
                (
                    f"Продаж по комнатности за {window['months']} мес. "
                    f"({window['from']} — {window['to']}) нет"
                    if window
                    else "Продаж по комнатности в последнем месяце отчёта нет"
                )
                + " — полосу проданного строить не из чего, показан только остаток"
            )
    if bands:
        total = sum(bands.values())
        block.subject["bands"] = {
            band: {"deals": count, "share_pct": round(count / total * 100, 1)}
            for band, count in sorted(bands.items())
        }
        block.subject["bands_deals"] = total
    # У соседей складывается ОБЪЁМ, а не среднее долей: проект на тысячу лотов
    # и проект на сорок иначе весят одинаково.
    pooled_sold: dict[str, float] = {}
    pooled_rem: dict[str, float] = {}
    pooled_bands: dict[str, float] = {}
    counted = 0
    # Проданное у соседей берётся тем же окном, что и у нас, — но только у тех,
    # у кого ряд есть. Сложить год одного соседа с последним месяцем другого
    # значит выдумать третью величину: она не за год и не за месяц. Остаток
    # складывается по всем — он сегодняшний у любого.
    windows = {id(row): _room_window(row) for row in peers}
    windowed = sum(1 for row in peers if windows[id(row)])
    by_window = bool(window and windowed)
    sold_from = 0
    for row in peers:
        their = windows[id(row)]
        rooms = row.get("room_mix") or {}
        if not rooms and their:
            rooms = _room_mix_from_series(row)[0]
        if rooms:
            counted += 1
        if by_window:
            if their:
                sold_from += 1
                for name, value in their["sold"].items():
                    pooled_sold[name] = pooled_sold.get(name, 0) + float(value)
        else:
            if rooms:
                sold_from += 1
            for name, item in rooms.items():
                pooled_sold[name] = pooled_sold.get(name, 0) + float(item.get("sold") or 0)
        for name, item in rooms.items():
            pooled_rem[name] = pooled_rem.get(name, 0) + float(item.get("rem") or 0)
        for band, count in (row.get("bands") or {}).items():
            pooled_bands[band] = pooled_bands.get(band, 0) + float(count)
    if counted:
        sold_total = sum(pooled_sold.values())
        rem_total = sum(pooled_rem.values())
        block.peers["projects"] = counted
        block.peers["sold_projects"] = sold_from
        if by_window:
            block.peers["rooms_window"] = {
                "from": window["from"], "to": window["to"], "months": window["months"],
            }
            if sold_from < counted:
                block.notes.append(
                    f"Помесячной комнатности нет у {counted - sold_from} из {counted} "
                    "соседей — их проданное в полосу не вошло"
                )
        block.peers["rooms"] = {
            name: {
                "title": ROOM_TITLES.get(name, name),
                "sold": _round(pooled_sold.get(name)),
                "sold_share_pct": (
                    round(pooled_sold.get(name, 0) / sold_total * 100, 1) if sold_total else None
                ),
                "rem": _round(pooled_rem.get(name)),
                "rem_share_pct": (
                    round(pooled_rem.get(name, 0) / rem_total * 100, 1) if rem_total else None
                ),
            }
            for name in sorted(set(pooled_sold) | set(pooled_rem))
        }
        if not sold_total:
            block.notes.append(
                ("У соседей за то же окно продаж нет" if by_window
                 else "У соседей в последнем месяце продаж нет")
                + " — доли считаны по остатку"
            )
    if pooled_bands:
        total = sum(pooled_bands.values())
        block.peers["bands"] = {
            band: {"deals": _round(count), "share_pct": round(count / total * 100, 1)}
            for band, count in sorted(pooled_bands.items())
        }
    # Цена метра по комнатности — то, чем проверяется догадка «у соседей дешевле,
    # потому что лоты крупнее». Веса берутся по ОСТАТКУ: цены здесь прайсовые,
    # то есть про экспозицию, и взвешивать их проданным значило бы считать цену
    # витрины по набору сделок.
    own_prices = {
        name: float(item["price"])
        for name, item in (subject.get("room_mix") or {}).items()
        if item.get("price")
    }
    peer_prices: dict[str, list[float]] = {}
    for row in peers:
        for name, item in (row.get("room_mix") or {}).items():
            if item.get("price"):
                peer_prices.setdefault(name, []).append(float(item["price"]))
    peer_median = {name: _median(values) for name, values in peer_prices.items()}
    if own_prices and peer_median:
        for name, price in sorted(peer_median.items()):
            row = block.peers.setdefault("rooms", {}).setdefault(
                name, {"title": ROOM_TITLES.get(name, name)}
            )
            row["price_per_sqm"] = _round(price)
            row["projects"] = len(peer_prices[name])
            own = own_prices.get(name)
            row["vs_own_pct"] = _ratio(own, price) if own else None
        own_rem = {
            name: float(item.get("rem") or 0)
            for name, item in (subject.get("room_mix") or {}).items()
        }
        effect = _mix_effect(own_prices, own_rem, peer_median, pooled_rem)
        if effect:
            block.subject["mix"] = effect
    elif own_prices:
        block.notes.append("Цен по комнатности у соседей нет — набор с уровнем не развести")
    if not block.peers:
        block.notes.append("Комнатности соседей в отчёте нет — сравнивать не с чем")
    return block


def payment_block(
    subject: dict[str, Any], peers: list[dict[str, Any]], city: MoscowMarket
) -> MetricBlock:
    """Ипотека: чем платят у нас, чем рядом и чем по классу в городе.

    Доля считается источником от числа сделок месяца, поэтому у проекта без
    продаж её нет вовсе — и это «не знаем», а не ноль.
    """
    block = MetricBlock(BLOCK_PAYMENT, BLOCK_TITLES[BLOCK_PAYMENT])
    share = subject.get("mortgage")
    banks = subject.get("banks") or {}
    if share is None and not banks:
        block.notes.append("Доли ипотеки у проекта нет: в последних месяцах продаж не было")
    if share is not None:
        block.subject["mortgage_pct"] = share
        block.subject["observed_at"] = subject.get("mortgage_at")
    if banks:
        total = sum(banks.values())
        block.subject["banks"] = {
            name: {"deals": count, "share_pct": round(count / total * 100, 1)}
            for name, count in sorted(banks.items(), key=lambda pair: -pair[1])
        }
        block.subject["banks_deals"] = total
    stats = _peer_stats(peers, "mortgage")
    if stats["count"]:
        block.peers = {**stats, "vs_median_pct": _ratio(share, stats["median"])}
    else:
        block.notes.append("Ни у одного соседа доля ипотеки в отчёте не раскрыта")
    snapshot = city.snapshot(subject.get("segment"))
    if snapshot is not None and getattr(snapshot, "mortgage_median_pct", None) is not None:
        block.city = {
            "segment": snapshot.segment,
            "mortgage_median_pct": snapshot.mortgage_median_pct,
            "observed_at": city.observed_at,
        }
    return block


def channel_block(
    subject: dict[str, Any], peers: list[dict[str, Any]], city: MoscowMarket
) -> MetricBlock:
    """Кто покупает: физлица, юрлица и переуступки.

    Юрлица в жилом проекте — это не обязательно инвестор: так же покупают
    кладовые и машино-места, поэтому доля считается по жилым сделкам, а
    переуступка стоит отдельной строкой — она про вторичный оборот, а не про
    покупателя.
    """
    block = MetricBlock(BLOCK_CHANNEL, BLOCK_TITLES[BLOCK_CHANNEL])
    legal = subject.get("legal")
    resale = subject.get("resale")
    if legal is None and resale is None:
        block.notes.append("Состава покупателей у проекта в отчёте нет: продаж не было")
        return block
    if legal is not None:
        block.subject["company_pct"] = legal
        block.subject["person_pct"] = round(100 - legal, 1)
        block.subject["observed_at"] = subject.get("legal_at")
    if resale is not None:
        block.subject["resale_deals"] = resale
    stats = _peer_stats(peers, "legal")
    if stats["count"]:
        block.peers = {**stats, "vs_median_pct": _ratio(legal, stats["median"])}
    else:
        block.notes.append("У соседей состав покупателей в отчёте не раскрыт")
    return block


BUILDERS: dict[str, Callable[..., MetricBlock]] = {
    BLOCK_PRICE: price_block,
    BLOCK_PACE: pace_block,
    BLOCK_STOCK: stock_block,
    BLOCK_LOT: lot_size_block,
    BLOCK_ABSORPTION: absorption_block,
    BLOCK_ROOMS: rooms_block,
    BLOCK_PAYMENT: payment_block,
    BLOCK_CHANNEL: channel_block,
}


def build_blocks(
    subject: dict[str, Any],
    peers: list[dict[str, Any]],
    city: MoscowMarket | None = None,
    codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Собрать выбранные блоки. Неизвестный код — не молчание, а отказ.

    Конструктор передаёт список кодов из интерфейса, и опечатка в нём не должна
    выглядеть как «этот раздел ничего не показал».
    """
    reference = city or MoscowMarket.bundled()
    wanted = codes or list(BUILDERS)
    unknown = [code for code in wanted if code not in BUILDERS]
    if unknown:
        raise ValueError(f"Неизвестные разделы отчёта: {', '.join(unknown)}")
    return [BUILDERS[code](subject, peers, reference).to_dict() for code in wanted]
