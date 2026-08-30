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

BLOCK_TITLES = {
    BLOCK_PRICE: "Цена метра",
    BLOCK_PACE: "Темп продаж",
    BLOCK_STOCK: "Остаток и экспозиция",
    BLOCK_LOT: "Размер лота",
    BLOCK_ABSORPTION: "Поглощение в метрах",
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
        if snapshot.discount_median_pct:
            block.notes.append(
                f"Медианная скидка к прайсу по классу «{snapshot.segment}» в Москве — "
                f"{snapshot.discount_median_pct} %; у проекта она может быть иной"
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


BUILDERS: dict[str, Callable[..., MetricBlock]] = {
    BLOCK_PRICE: price_block,
    BLOCK_PACE: pace_block,
    BLOCK_STOCK: stock_block,
    BLOCK_LOT: lot_size_block,
    BLOCK_ABSORPTION: absorption_block,
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
