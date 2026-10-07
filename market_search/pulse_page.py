"""Страница проекта «Пульса»: стадия, сроки и остатки — по корпусам.

Карта и таблица проекта, которые читает основной маршрут, поля стадии не
несут: функция стадии соседей на проде отвечала «стадия не указана» почти
для всех. Человек же в ЛК видит на странице проекта (`/complex/<id>/`)
распределение по корпусам «по состоянию на …»:

    Стадия строительства  ввз (сдан/гк) — 18 корпусов
                          верхние этажи (последние 25% …) — 2 корпуса
    Тип договора          ДКПН — 18 корпусов; ДДУ — 2 корпуса
    Статус реализации     полностью продан — 16; в продаже — 4
    Количество жилья      11 321 шт, остаток 10.48 %

и во всплывающей карточке на карте — «Начало продаж Ноябрь 2015», «Срок
сдачи 18/IV-27/IV», «Остатки жилья 55 926 м², 9 %», «Темп продаж за 3 мес
3 786 м²/месяц».

Модуль разбирает видимый текст по подписям. Разметку ЛК без входа мы не
видели, поэтому разбор держится за подписи, а не за классы вёрстки, и
возвращает список найденных подписей: на проде это видно маршрутом
`/market/pulse/project-page`, и непонятое не превращается в «нет данных».

Правила, объявленные здесь одним местом:

* **Стадия для цены** — самая ранняя НЕзавершённая стадия корпусов. Страница
  не привязывает стадию к статусу продаж корпуса, а в продаже обычно те, что
  ещё строятся; сданные корпуса проданы. Все корпуса сданы — «сдан».
  Распределение отдаётся целиком, рядом — самая поздняя стадия.
* **Плановый ввод** — последний корпус по сроку сдачи («27/IV» → IV кв. 2027,
  месяц — последний в квартале, как у остального разбора дат). Первый ввод
  отдаётся рядом.
* **Остаток** — каждое число со своей единицей и базой (шт. жилья, м²) и
  датой состояния; общая «доля» — из источника с более поздней датой.
"""

from __future__ import annotations

import datetime
import html
import re
from typing import Any

from . import stage as stage_module

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
_MONTH_RE = re.compile(
    r"\b(январ[ьяе]|феврал[ьяе]|март[ае]?|апрел[ьяе]|ма[йяе]|июн[ьяе]|июл[ьяе]|"
    r"август[ае]?|сентябр[ьяе]|октябр[ьяе]|ноябр[ьяе]|декабр[ьяе])\s+(20\d{2})",
    re.IGNORECASE,
)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
_SPAN_PART = r"(\d{2})\s*/\s*(IV|I{1,3}|[1-4])"
_SPAN_RE = re.compile(_SPAN_PART + r"(?:\s*[-–—]\s*" + _SPAN_PART + r")?", re.IGNORECASE)
_NUM = r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"

# Подписи страницы и карточки. Порядок не важен: границы поля — следующая
# найденная подпись. Ключ — имя поля в ответе.
LABELS: dict[str, str] = {
    "stage": r"стадия\s+строительства",
    "contract": r"тип\s+договора(?:\s+продажи\s+жилья)?|договор(?=\s*[:—|-]?\s*(?:ддкп|дкп|дду|пдкп|жск))",
    "status": r"статус\s+реализации",
    "escrow": r"применение\s+эскроу",
    "living": r"количество\s+жилья",
    # Слова, которые встречаются и внутри значений («16 корпусов | в продаже»),
    # подписью считаются, только когда за ними идёт число, а перед — нет.
    "flats": r"(?<!\d)(?<!\d )квартир(?=\s*[:|]?\s*\d)",
    "commercial": r"(?<!\d)(?<!\d )коммерци[яи](?=\s*[:|]?\s*\d)",
    "parking": r"(?<!\d)(?<!\d )машино-?мест\w*(?=\s*[:|]?\s*\d)",
    "storage": r"(?<!\d)(?<!\d )кладов\w*(?=\s*[:|]?\s*\d)",
    "buildings": r"(?<!\d)(?<!\d )корпусов(?=\s*[:|]?\s*\d)",
    "land": r"площадь\s+з\.?\s?у\.?",
    "cadastre": r"кадастровые\s+номера(?:\s+участков)?",
    "floors": r"этажность",
    "ceiling": r"(?:высота\s+)?потолк\w*",
    "technology": r"технология(?:\s+строительства)?",
    "finishing": r"отделка",
    "sales_start": r"(?:начало|старт)\s+продаж",
    "delivery": r"(?:планов\w+\s+)?(?:срок|дата)\s+(?:сдачи|ввода(?:\s+в\s+эксплуатацию)?)",
    "remaining": r"остатки\s+жилья",
    "pace": r"темп\s+продаж(?:\s+за\s+\d+\s+мес\.?)?",
    "price": r"цена\s+в\s+экспонировании",
    "as_of": r"по\s+состоянию\s+на|данные\s+на",
}
_LABEL_RE = re.compile("|".join(f"(?P<{key}>{pattern})" for key, pattern in LABELS.items()), re.IGNORECASE)
_BUILDING_ITEM = re.compile(
    r"\s*[;,|·]?\s*(?P<value>.+?)\s*[—–:-]?\s*(?P<count>\d+)\s*корп(?:ус(?:а|ов)?|\.)?(?![а-я])",
    re.IGNORECASE | re.S,
)
_BARE_ITEM = re.compile(
    r"\s*[;,|·]?\s*(?P<value>[^;|\d]+?)\s*[—–:-]\s*(?P<count>\d+)(?=\s*(?:[;,|]|$))",
    re.IGNORECASE | re.S,
)


def number(text: Any) -> float | None:
    if text in (None, ""):
        return None
    clean = re.sub(r"[   ]", "", str(text)).replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return None


def _int(text: Any) -> int | None:
    value = number(text)
    return int(round(value)) if value is not None else None


def month_date(text: Any) -> str | None:
    """«Ноябрь 2015», «1 октября 2026» → ISO-дата. Месяц словом — и только он.

    Прежний разбор дат месяцев словами не знал вовсе: «Начало продаж
    Ноябрь 2015» с карточки проходило мимо, и в отчёт попадала дата из
    другого источника.
    """
    found = re.search(r"\b(\d{1,2})\s+" + _MONTH_RE.pattern[2:], str(text or ""), re.IGNORECASE)
    day = 1
    if found:
        day = int(found.group(1))
        word, year = found.group(2), found.group(3)
    else:
        found = _MONTH_RE.search(str(text or ""))
        if not found:
            return None
        word, year = found.group(1), found.group(2)
    low = word.lower()
    month = next((value for stem, value in MONTHS.items() if low.startswith(stem) and len(stem) > 2), None)
    if month is None and low.startswith("ма"):
        month = 5
    try:
        return datetime.date(int(year), int(month or 0), day).isoformat()
    except ValueError:
        return None


def delivery_span(text: Any) -> dict[str, Any] | None:
    """«18/IV-27/IV» → первый и последний ввод корпусов.

    Формат карточки — «год/квартал»: `18/IV` — IV квартал 2018. Месяц — последний
    в квартале, как у остального разбора сроков ввода.
    """
    found = _SPAN_RE.search(str(text or ""))
    if not found:
        return None

    def to_date(year: str | None, quarter: str | None) -> str | None:
        if not year or not quarter:
            return None
        raw = quarter.lower()
        q = _ROMAN.get(raw) or (int(raw) if raw.isdigit() else None)
        if not q:
            return None
        return datetime.date(2000 + int(year), q * 3, 1).isoformat()

    first = to_date(found.group(1), found.group(2))
    last = to_date(found.group(3), found.group(4)) or first
    if not first:
        return None
    return {"raw": found.group(0).strip(), "first": min(first, last), "last": max(first, last)}


def _plain(page: str) -> str:
    text = html.unescape(page or "")
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(?:p|div|li|tr|td|th|dd|dt|span)>", " | ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace(" ", " ")
    return " ".join(text.split())


def _segments(plain: str) -> dict[str, str]:
    """Текст после каждой подписи до следующей. Повтор подписи — первый."""
    marks = [(m.start(), m.end(), m.lastgroup) for m in _LABEL_RE.finditer(plain)]
    out: dict[str, str] = {}
    for index, (_start, end, key) in enumerate(marks):
        stop = marks[index + 1][0] if index + 1 < len(marks) else min(len(plain), end + 400)
        if key and key not in out:
            out[key] = plain[end:stop].strip(" :—–-|")
    return out


def by_buildings(segment: str | None) -> list[dict[str, Any]]:
    """«ввз (сдан/гк) — 18 корпусов; верхние этажи … — 2 корпуса» → список."""
    out: list[dict[str, Any]] = []
    text = segment or ""
    # Слово «корпус» есть — только пары с ним; нет — «значение — число».
    pattern = _BUILDING_ITEM if re.search(r"корп", text, re.IGNORECASE) else _BARE_ITEM
    for found in pattern.finditer(text):
        value = " ".join(found.group("value").strip(" ;,|·—–-:").split())
        if value:
            out.append({"value": value, "buildings": int(found.group("count"))})
    return out


def stage_summary(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Распределение стадий по корпусам и стадия для цены по объявленному правилу."""
    if not items:
        return None
    order = {code: index for index, (code, _title) in enumerate(stage_module.CONSTRUCTION_STAGES)}
    rows = []
    for item in items:
        code = stage_module.stage_from_text(item["value"])
        rows.append({
            "raw": item["value"],
            "code": code,
            "label": stage_module.STAGE_TITLES.get(code) if code else None,
            "buildings": item["buildings"],
        })
    known = [row for row in rows if row["code"]]
    unfinished = [row for row in known if row["code"] != "done"]
    if unfinished:
        price_row = min(unfinished, key=lambda row: order[row["code"]])
        rule = "самая ранняя незавершённая стадия корпусов: в продаже — строящиеся корпуса"
    elif known:
        price_row = known[0]
        rule = "все корпуса сданы"
    else:
        price_row = None
        rule = "стадия корпусов словарём не распознана"
    latest = max(known, key=lambda row: order[row["code"]]) if known else None
    return {
        "distribution": rows,
        "buildings": (
            sum(row["buildings"] for row in rows)
            if all(row["buildings"] is not None for row in rows) else None
        ),
        "price_stage": price_row,
        "latest_stage": latest,
        "rule": rule,
    }


def _quantity(segment: str | None) -> dict[str, Any]:
    """«11 321 шт (631 246 м²), остаток 10.48 %» → числа с единицами."""
    text = segment or ""
    out: dict[str, Any] = {}
    found = re.search(rf"({_NUM})\s*шт", text)
    if found:
        out["units"] = _int(found.group(1))
    found = re.search(rf"({_NUM})\s*м(?:²|2|\s*кв)", text)
    if found:
        out["area_sqm"] = number(found.group(1))
    found = re.search(rf"остат\w*\s*({_NUM})\s*%", text, re.IGNORECASE)
    if found:
        out["remaining_pct"] = number(found.group(1))
    found = re.search(rf"коэф\w*\.?\s*({_NUM})", text, re.IGNORECASE)
    if found:
        out["ratio"] = number(found.group(1))
    if "units" not in out:
        found = re.match(rf"\s*({_NUM})(?![\d.,])(?![ \u00a0\u202f]\d)(?!\s*(?:м|%|га))", text)
        if found:
            out["units"] = _int(found.group(1))
    return out


def _range(segment: str | None) -> dict[str, float] | None:
    found = re.search(rf"({_NUM})\s*[-–—]\s*({_NUM})", segment or "")
    if found:
        return {"min": number(found.group(1)), "max": number(found.group(2))}
    found = re.search(rf"({_NUM})", segment or "")
    if found:
        value = number(found.group(1))
        return {"min": value, "max": value}
    return None


def parse_project_page(page: str) -> dict[str, Any]:
    """Всё, что страница проекта (или карточка) говорит словами, — с единицами.

    Пустые поля не выдумываются: нет подписи — нет поля. `labels` — какие
    подписи найдены: по ним видно, что разбор узнал на живой странице.
    """
    plain = _plain(page)
    parts = _segments(plain)
    out: dict[str, Any] = {"labels": sorted(parts)}
    as_of = month_date(parts.get("as_of"))
    if as_of:
        out["as_of"] = as_of

    stage_items = by_buildings(parts.get("stage"))
    summary = stage_summary(stage_items)
    if summary:
        out["stage"] = summary
    elif parts.get("stage"):
        # Без разбивки по корпусам — сырой текст (карточка: «верхние этажи …,
        # ВВЭ (сдан/ГК)»): каждое значение — корпус неизвестного числа.
        raw_items = [
            {"value": " ".join(value.split()), "buildings": None}
            for value in re.split(r",\s*(?![^()]*\))", parts["stage"][:300])
            if value.strip()
        ]
        summary = stage_summary(raw_items)
        if summary:
            out["stage"] = summary

    for key in ("contract", "status", "escrow", "finishing"):
        items = by_buildings(parts.get(key))
        if items:
            out[key] = items
        elif parts.get(key) and key == "contract":
            values = [v.strip() for v in re.split(r"[,;]", parts[key][:80]) if v.strip()]
            values = [v for v in values if re.fullmatch(r"[A-ZА-ЯЁ]{2,6}", v)]
            if values:
                out[key] = [{"value": value, "buildings": None} for value in values]

    for key in ("living", "flats", "commercial", "parking", "storage"):
        found = _quantity(parts.get(key))
        if found:
            out[key] = found
    buildings = _int((re.match(rf"\s*({_NUM})", parts.get("buildings") or "") or [None, None])[1])
    if buildings:
        out["buildings"] = buildings
    found = re.search(rf"({_NUM})\s*га", parts.get("land") or "")
    if found:
        out["land_ha"] = number(found.group(1))
    if parts.get("cadastre"):
        numbers = re.findall(r"\b\d{2}:\d{2}:\d{6,7}:\d+\b", parts["cadastre"])
        if numbers:
            out["cadastre"] = numbers
    for key in ("floors", "ceiling"):
        found_range = _range(parts.get(key))
        if found_range:
            out[key] = found_range
    if parts.get("technology"):
        out["technology"] = parts["technology"].split("|")[0].strip()[:60] or None

    from .pulse import _pulse_date  # noqa: PLC0415 — общий разбор чисел-дат

    head = (parts.get("sales_start") or "")[:40]
    sales_start = month_date(head) or _pulse_date(head)
    if sales_start:
        out["sales_start"] = sales_start
    head = (parts.get("delivery") or "")[:40]
    span = delivery_span(head)
    if not span:
        single = month_date(head) or _pulse_date(head)
        if single:
            span = {"raw": head.split("|")[0].strip(), "first": single, "last": single}
    if span:
        out["delivery"] = span
    if parts.get("remaining"):
        remaining = _quantity(parts["remaining"])
        found = re.search(rf"({_NUM})\s*%", parts["remaining"])
        if found:
            remaining["remaining_pct"] = number(found.group(1))
        if remaining:
            out["remaining"] = remaining
    found = re.search(rf"({_NUM})\s*м(?:²|2)\s*/\s*мес", parts.get("pace") or "")
    if found:
        months = re.search(r"темп\s+продаж\s+за\s+(\d+)\s+мес", plain, re.IGNORECASE)
        out["pace"] = {
            "sqm_per_month": number(found.group(1)),
            "window_months": int(months.group(1)) if months else None,
        }
    found = re.search(rf"({_NUM})", parts.get("price") or "")
    if found:
        out["exposure_price_per_sqm"] = _int(found.group(1))
    return out


def remaining_figures(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Все остатки страницы — каждый со своей единицей, базой и датой."""
    as_of = parsed.get("as_of")
    out: list[dict[str, Any]] = []
    for key, basis in (("living", "жильё, шт."), ("flats", "квартиры, шт.")):
        block = parsed.get(key) or {}
        if block.get("remaining_pct") is not None:
            out.append({"value": block["remaining_pct"], "unit": "%", "basis": basis, "as_of": as_of})
    block = parsed.get("remaining") or {}
    if block.get("area_sqm") is not None:
        out.append({"value": block["area_sqm"], "unit": "м²", "basis": "жильё, м²", "as_of": as_of})
    if block.get("remaining_pct") is not None:
        out.append({"value": block["remaining_pct"], "unit": "%", "basis": "остатки жилья", "as_of": as_of})
    return out
