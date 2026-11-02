"""Стоящий ли лот городской приватизации — одно правило на все площадки.

## Откуда взялось

В августе 2026 приватизацию по 178-ФЗ из ГИС Торгов назвали «не тем рынком»:
гаражи по 0,2 млн ₽, машино-места, помещения по 12–195 м². Владелец прислал
лот Росэлторга 178fz30102600019 — продажу 100% доли ООО «Фонвизина 8» за
596 млн ₽, — которого в выборке не было, и решил (02.11.2026): «добавить с
фильтром», то есть собирать приватизацию, но только стоящие лоты.

Пороги — ответы владельца на живой выдаче (02.11.2026), а не наша догадка:

- регион — Москва или Московская область;
- земля — от 0,5 га; правило распространено и на продажу городской земли по
  Земельному кодексу (на Росэлторге она лежит в том же разделе «Имущественные
  торги (178-ФЗ)»);
- здание — от 1 000 м² (или здание на участке от 0,5 га);
- начальная цена земли и здания — от 10 млн ₽;
- машино-места, гаражи, кладовые, квартиры и отдельные помещения — нет;
- доля в обществе меряется не метрами: её цену решает действующее правило
  владельца для долей (`equity_stake`, 500 млн ₽ за 100%), здесь она только
  допускается к нему.

## Живой лот — по сроку и статусу

«Лот существует» и «идёт приём заявок» — разные состояния. Лот со статусом
«Работа комиссии» или с прошедшим сроком подачи в выборку не входит, и причина
говорит, что приём заявок закончился.

## Что возвращает

`verdict` — пустая строка, если лот стоящий, иначе причина простыми словами.
Причина без чисел одного лота — это ключ счётчика отсева: «участок меньше
0,5 га — 26» читается, а двадцать шесть разных строк — нет. Подробность для
одного лота отдаёт `detail`.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from auction_search.export_areas import export_areas
from auction_search.models import AuctionLot, LotKind, LotOrigin
from auction_search.parsing import deadline_is_current, mentions_moscow

LAND_MIN_SQM = 5_000.0
BUILDING_MIN_SQM = 1_000.0
MIN_PRICE_RUB = 10_000_000.0

REGIONS = {"77": "Москва", "50": "Московская область"}

# Организатор, который продаёт только имущество города Москвы. Явная карта по
# ИНН, а не догадка по слову «Московский» в имени продавца: у долей в карточке
# нет ни адреса, ни кода региона, и Москву называет только организатор.
MOSCOW_ORGANIZERS = {
    "7704515009": "Департамент города Москвы по конкурентной политике",
}

_MOSCOW_OBLAST = re.compile(r"(?iu)московск\w*\s+обл")
# Рубрика площадки, а не голое «178-ФЗ»: оно стоит в меню Росэлторга на любой
# странице («торги в соответствии с 178-ФЗ»), и по нему приватизацией
# оказался бы каждый лот площадки.
_SECTION_178 = re.compile(r"(?iu)имущественн\w*\s+торги\s*\(\s*178\s*-?\s*фз\s*\)")

# Что продаётся — по ПЕРВОМУ предмету в названии лота. «Нежилое помещение
# здания мастерских» — помещение, «Нежилое здание с помещениями» — здание:
# решает то, что названо первым, а не то, что встретилось где-то в описании.
_SUBJECTS = (
    ("parking", re.compile(r"(?iu)машино-?\s*мест|машиномест|парковочн\w*\s+мест")),
    ("garage", re.compile(r"(?iu)гараж|\bбокс")),
    ("storage", re.compile(r"(?iu)кладов")),
    ("flat", re.compile(r"(?iu)квартир|\bкомнат")),
    ("premises", re.compile(r"(?iu)помещени")),
    ("equity", re.compile(r"(?iu)\bдол[яиейю]\b|\bдоли\b|уставн\w*\s+капитал|акци[йия]")),
    ("land", re.compile(r"(?iu)земельн\w*\s+участ|\bз/у\b|\bзу\b")),
    ("building", re.compile(r"(?iu)здани|сооружени|строени|имущественн\w*\s+комплекс|незаверш")),
)
_SMALL_LABELS = {
    "parking": "машино-место",
    "garage": "гараж",
    "storage": "кладовая",
    "flat": "квартира или комната",
    "premises": "отдельное помещение",
}

REASON_REGION = "не Москва и не Московская область"
REASON_REGION_UNKNOWN = "регион в карточке не указан"
REASON_CLOSED = "приём заявок закончен"
REASON_NO_DEADLINE = "срок приёма заявок не указан"
REASON_LAND_SMALL = "участок меньше 0,5 га"
REASON_LAND_NO_AREA = "площадь участка не указана"
REASON_BUILDING_SMALL = "здание меньше 1 000 м²"
REASON_BUILDING_NO_AREA = "площадь здания не указана"
REASON_CHEAP = "начальная цена ниже 10 млн ₽"
REASON_NO_PRICE = "начальная цена не указана"
REASON_NOT_ASSET = "не земля, не здание и не доля в обществе"

_CLOSED_STATUS = ("отмен", "заверш", "работа комиссии", "заключение договора",
                  "архив", "приостанов", "состоял", "определение победител",
                  "подведение итог")


def is_privatization(lot: AuctionLot) -> bool:
    """Лот из раздела городской приватизации.

    Росэлторг — раздел «Имущественные торги (178-ФЗ)» или номер процедуры
    `178fz…`; ГИС Торги — код вида торгов `178FZ`. КРТ сюда не входит: у права
    на договор о КРТ свой путь и свои ворота (`catalogue_quality`).
    """
    if lot.lot_kind is LotKind.KRT:
        return False
    raw = lot.raw or {}
    if str(raw.get("bidd_type_code") or "").upper() == "178FZ":
        return True
    external = str(lot.source.external_lot_id or "").lower()
    if external.startswith("178fz"):
        return True
    return any(_SECTION_178.search(str(value or ""))
               for value in (lot.title, raw.get("trading_section_clean")))


def is_city_land_sale(lot: AuctionLot) -> bool:
    """Продажа городской земли по Земельному кодексу — правило то же.

    Владелец распространил порог земли на неё (02.11.2026). Аренда земли и
    договоры о масштабных инвестпроектах (цена 1 ₽) сюда не входят: это не
    продажа участка, и мерить их ценой нельзя. Имущество должников — тоже нет:
    у него свой рынок.
    """
    return (lot.lot_kind is LotKind.LAND_SALE
            and lot.origin not in (LotOrigin.BANKRUPTCY, LotOrigin.SEIZED))


def applies(lot: AuctionLot) -> bool:
    """Отвечает ли это правило за лот."""
    return is_privatization(lot) or is_city_land_sale(lot)


def subject_of(title: str, kind: LotKind | None = None) -> str:
    """Что продаётся: первый предмет в названии, затем вид лота."""
    # Рубрика площадки в начале названия — не предмет.
    text = _SECTION_178.sub(" ", str(title or ""))
    found: list[tuple[int, str]] = []
    for name, pattern in _SUBJECTS:
        match = pattern.search(text)
        if match:
            found.append((match.start(), name))
    if found:
        return min(found)[1]
    if kind is LotKind.EQUITY_STAKE:
        return "equity"
    if kind in (LotKind.LAND_SALE, LotKind.LAND_LEASE):
        return "land"
    if kind in (LotKind.PROPERTY_COMPLEX, LotKind.UNFINISHED):
        return "building"
    return ""


def subject(lot: AuctionLot) -> str:
    return subject_of(lot.title or "", lot.lot_kind)


def listing_problem(title: str, area_sqm: float | None) -> str:
    """Отсев по строке списка — до чтения карточки.

    Карточка — отдельный запрос в общий срок каталога (сорок секунд на все
    источники). Гараж или участок на 600 м², названные таковыми прямо в
    списке, читать незачем; всё, о чём строка молчит, решает карточка.
    """
    kind = subject_of(title)
    if kind in _SMALL_LABELS:
        return f"{_SMALL_LABELS[kind]} — не земля и не здание"
    if kind == "land" and area_sqm is not None and area_sqm < LAND_MIN_SQM:
        return REASON_LAND_SMALL
    return ""


def region(lot: AuctionLot) -> tuple[str, str]:
    """Код региона лота и чем он подтверждён; не подтверждён — пусто."""
    raw = lot.raw or {}
    code = str(raw.get("lot_region_code") or "").strip()
    if code:
        return code, "код региона в карточке"
    place = " ".join(str(value or "") for value in (raw.get("location"), lot.address))
    if _MOSCOW_OBLAST.search(place):
        return "50", "расположение в карточке"
    if mentions_moscow(place):
        return "77", "расположение в карточке"
    organizer = str(lot.organizer or "")
    for inn, name in MOSCOW_ORGANIZERS.items():
        if inn in organizer:
            return "77", f"организатор — {name}"
    return "", ""


def areas(lot: AuctionLot) -> tuple[float | None, float | None]:
    """Площадь участка и здания — тем же правилом, что у таблицы и книги.

    Площадь, названная только в названии лота («…и земельный участок площадью
    396 кв. м»), достраивается `export_areas`; второй разбор здесь разошёлся бы
    с таблицей: лот прошёл бы порог, которого в выгрузке не видно.
    """
    found = export_areas({
        "land_area_sqm": lot.land_area_sqm,
        "building_area_sqm": lot.building_area_sqm,
        "name": lot.title or "",
        "url": lot.source.lot_url,
    })
    return found.land_area_sqm, found.building_area_sqm


def _price(lot: AuctionLot) -> float | None:
    for value in (lot.start_price_rub, lot.current_price_rub):
        if value is not None:
            return float(value)
    return None


def _live_problem(lot: AuctionLot, now: datetime | None) -> str:
    status = str(lot.status or "").lower()
    if any(marker in status for marker in _CLOSED_STATUS):
        return REASON_CLOSED
    if not str(lot.application_deadline or "").strip():
        return REASON_NO_DEADLINE
    if not deadline_is_current(lot.application_deadline, now=now):
        return REASON_CLOSED
    return ""


def verdict(lot: AuctionLot, *, now: datetime | None = None) -> str:
    """Пусто — лот стоящий; иначе причина отсева (ключ счётчика)."""
    code, _evidence = region(lot)
    if not code:
        return REASON_REGION_UNKNOWN
    if code not in REGIONS:
        return REASON_REGION
    problem = _live_problem(lot, now)
    if problem:
        return problem
    kind = subject(lot)
    if kind in _SMALL_LABELS:
        return f"{_SMALL_LABELS[kind]} — не земля и не здание"
    if kind == "equity":
        # Цену доли решает правило владельца для долей — одно на модуль.
        return ""
    land, building = areas(lot)
    if kind == "land":
        area = land
        if area is None:
            return REASON_LAND_NO_AREA
        if area < LAND_MIN_SQM:
            return REASON_LAND_SMALL
    elif kind == "building":
        big_building = building is not None and building >= BUILDING_MIN_SQM
        big_site = land is not None and land >= LAND_MIN_SQM
        if not (big_building or big_site):
            if building is None and land is None:
                return REASON_BUILDING_NO_AREA
            return REASON_BUILDING_SMALL
    else:
        return REASON_NOT_ASSET
    price = _price(lot)
    if price is None:
        return REASON_NO_PRICE
    if price < MIN_PRICE_RUB:
        return REASON_CHEAP
    return ""


def detail(lot: AuctionLot, reason: str) -> str:
    """Причина для одного лота — с его числами."""
    land, building = areas(lot)
    if reason == REASON_LAND_SMALL and land is not None:
        return f"участок {land:,.0f} м² — меньше 0,5 га".replace(",", " ")
    if reason == REASON_BUILDING_SMALL:
        area = building or land
        if area is not None:
            return f"здание {area:,.0f} м² — меньше 1 000 м²".replace(",", " ")
    if reason == REASON_CHEAP:
        price = _price(lot)
        if price is not None:
            return f"начальная цена {price / 1e6:.1f} млн ₽ — ниже 10 млн ₽".replace(".", ",")
    if reason == REASON_CLOSED:
        when = str(lot.application_deadline or "").strip()
        status = str(lot.status or "").strip()
        bits = [f"статус «{status}»" if status else "", f"срок подачи {when}" if when else ""]
        return "приём заявок закончен: " + ", ".join(bit for bit in bits if bit)
    return reason


class Tally:
    """Счётчик отсева правила для строки охвата источника."""

    def __init__(self) -> None:
        self.seen = 0
        self.kept = 0
        self.dropped: dict[str, int] = {}

    def keep(self, lot: AuctionLot, *, now: datetime | None = None) -> bool:
        """Пропустить ли лот; отсеянный посчитан со своей причиной."""
        self.seen += 1
        reason = verdict(lot, now=now)
        if reason:
            self.dropped[reason] = self.dropped.get(reason, 0) + 1
            lot.raw["privatization_reason"] = detail(lot, reason)
            return False
        self.kept += 1
        code, evidence = region(lot)
        lot.raw.setdefault("lot_region_code", code)
        lot.raw["privatization_region"] = f"{REGIONS.get(code, code)} ({evidence})"
        return True

    def report(self) -> dict[str, Any]:
        """Поля для `last_report` источника."""
        return {
            "privatization_seen": self.seen,
            "privatization_kept": self.kept,
            "privatization_dropped": dict(
                sorted(self.dropped.items(), key=lambda pair: -pair[1])),
            "privatization_rule": (
                "Москва и Московская область; земля от 0,5 га, здание от 1 000 м², "
                "цена от 10 млн ₽; доля в обществе — по правилу для долей; "
                "только пока идёт приём заявок"),
        }
