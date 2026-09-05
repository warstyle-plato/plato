"""Проекты решений о КРТ на mos.ru — вход со стороны документа, а не карточки.

Каталог krt.mos.ru отвечает на вопрос «какие площадки город показывает». Он не
отвечает на вопрос «о каких площадках город принял решение»: решение
публикуется отдельно, Департаментом градостроительной политики (раньше —
городского имущества), и площадка может иметь опубликованное решение, не имея
карточки в каталоге вовсе.

До сих пор мы ходили только в одну сторону: брали площадку из каталога и по ней
искали решение. Ручная таблица владельца (27 площадок, 31.08.2026) показала
цену такого хода — шесть площадок с опубликованными решениями 2023–2025 годов у
нас не появлялись ни при каком фильтре. У его таблицы колонка так и называется:
«Проект решения о КРТ», с датой; источник у неё документ, а не каталог.

Здесь обратный ход. Разбор написан по живому ответу поиска mos.ru (575
документов на 31.08.2026), а не по догадке о полях: заголовок несёт и вид КРТ, и
адрес, и округ в скобках.

Сопоставление с каталогом намеренно строгое. Ложная привязка прячет настоящий
пробел — площадка выглядит найденной, хотя карточки у неё нет, — поэтому
совпадение требует и общего имени улицы, и общего номера владения. Не
сопоставилось — так и говорим: «решение есть, карточки нет», а не «новая
площадка».
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

from .krt_requirements import MOS_SEARCH_URL, krt_kind

MOS_KRT_QUERY = "проект решения о комплексном развитии территории"
# Распоряжение, которым город объявляет торги по КРТ. Адреса в нём нет: ни в
# заголовке, ни в карточке документа, а PDF — скан, из которого извлекается
# только регистрационный штамп (проверено на живом документе, 31.08.2026).
# Поэтому такие распоряжения показываются фактом со ссылкой и датой, а к
# площадке не привязываются — привязка по номеру была бы выдумкой.
MOS_TENDER_QUERY = "аукцион на право заключения договора о комплексном развитии территории"

_SPACE = re.compile(r"\s+")
_OKRUG = re.compile(r"\((ЦАО|САО|СВАО|ВАО|ЮВАО|ЮАО|ЮЗАО|ЗАО|СЗАО|ЗелАО|НАО|ТАО|ТиНАО)\)")
# «…расположенной по адресу: г. Москва, ул. Рогова, вл. 22-24 (ЗАО)» — адрес
# начинается после двоеточия. У части решений адреса нет вовсе: там названа
# производственная зона, и это тоже ответ, а не пропуск.
# Разделитель после «по адресу» город пишет как придётся: двоеточием,
# точкой с запятой и никак, а «по» иногда теряет вовсе («расположенной
# адресу»). Пять заголовков из 298 на снимке прода 04.09.2026 оставались
# без адреса ровно на этой пунктуации — то есть площадку нельзя было ни
# найти в публикациях, ни назвать по имени.
_AT_ADDRESS = re.compile(r"(?iu)расположенн\w*\s+(?:по\s+)?адрес\w*\s*[:;]?\s*(.+)$")
_AT_ZONE = re.compile(r"(?iu)расположенн\w*\s+(в\s+производственн\w+\s+зоне.+)$")
_CITY = re.compile(r"(?iu)^\s*(?:г\.?\s*)?москва\s*,?\s*")
_STOP = {
    "ул", "улица", "вл", "влд", "владение", "стр", "строение", "к", "корп", "д",
    "дом", "пер", "переулок", "пр", "проезд", "пркт", "проспект", "ш", "шоссе",
    "наб", "набережная", "тер", "территория", "зона", "зоне", "москва", "город",
    "производственной", "производственная", "проект", "участок", "участка", "и",
    # Канцелярия решения и лота. Она стоит в КАЖДОМ имени с обеих сторон, и на
    # запасном пути «два общих значащих слова» ею совпадает что угодно с чем
    # угодно: 03.09.2026 лот по «Прожектору» привязался к «Новохорошевскому
    # пр-ду», а МКАД 41 км — к чужой площадке, обе с уверенным видом. Признак,
    # совпадающий почти со стопроцентной частотой, — не признак.
    "комплексном", "комплексного", "комплексное", "комплексном развитии",
    "развитии", "развития", "развитие", "территории", "территорий",
    "нежилой", "жилой", "застройки", "застройка", "города", "москвы",
    "решения", "решение", "решении", "проекта", "проектов",
    "расположенной", "расположенных", "расположенного", "адресу", "адресам",
    "аукцион", "аукциона", "право", "права", "заключения", "договора",
    "площадью", "площади", "имущественные", "торги", "лот",
    "объектов", "объекта", "капитального", "строительства", "кроме",
}
_WORD = re.compile(r"[А-Яа-яЁёA-Za-z]{3,}")
_HOUSE = re.compile(r"\d+[А-Яа-яA-Za-z]?")
# «…ул. 7-я Парковая, влд. 33»: имя улицы — то, что стоит перед указателем
# владения, вместе с порядковым номером; номер владения — то, что после.
_HOUSE_MARK = re.compile(
    r"(?iu)\b(?:влд|вл|владение|д|дом|уч|участок|з/у|зу)\b\.?\s*№?\s*(?P<house>\d+[а-яё]?)")
_ORDINAL = re.compile(r"(?iu)\d+-[а-яё]")
# Различающее слово улицы. Без него Верхняя и Нижняя Первомайская — одна улица.
_SIDE = {"верхняя", "нижняя", "большая", "малая", "старая", "новая", "средняя",
         "верхний", "нижний", "большой", "малый", "старый", "новый", "северное",
         "южное", "восточное", "западное", "северная", "южная"}
_NAME_TOKEN = re.compile(r"(?iu)\d+-[а-яё]|[а-яё]{3,}")
_ZONE_NO = re.compile(r"(?iu)зоне?\s*№\s*(\d+)")
_QUALIFIER = re.compile(r"(?iu)\((?P<q>[^)]{1,40})\)")


@dataclass
class KrtDecision:
    """Одно опубликованное решение. Ничего не считает — только то, что сказано."""

    id: str
    title: str
    url: str
    address: str = ""
    okrug: str = ""
    kind: str = ""
    published_at: int = 0
    department: str = ""
    matched_slug: str = ""
    matched_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "url": self.url,
            "address": self.address, "okrug": self.okrug, "kind": self.kind,
            "published_at": self.published_at, "department": self.department,
            "matched_slug": self.matched_slug, "matched_name": self.matched_name,
        }


def search_url(page: int = 1, per_page: int = 25, query: str = MOS_KRT_QUERY) -> str:
    return MOS_SEARCH_URL + "?" + urlencode(
        {"q": query, "page": max(1, int(page)), "per_page": int(per_page)})


_ORDER_NUMBER = re.compile(r"(?iu)№\s*([А-ЯЁA-Z-]*\d+[/-]?\d*)")


def parse_tender_order(row: dict[str, Any]) -> dict[str, Any] | None:
    """Распоряжение о торгах: номер, дата, ссылка. Адреса в нём нет."""
    title = _clean(row.get("title"))
    low = title.casefold()
    if "аукцион" not in low or "комплексн" not in low:
        return None
    number = _ORDER_NUMBER.search(title)
    kind, _ = krt_kind(title)
    return {
        "id": str(row.get("id") or "").strip(),
        "number": number.group(1) if number else "",
        "title": title,
        "url": _clean(row.get("url")),
        "published_at": int(row.get("date") or 0),
        "kind": kind,
    }


def collect_tender_orders(fetch: Callable[[str], bytes], *, max_pages: int = 12,
                          per_page: int = 25) -> tuple[list[dict[str, Any]], bool]:
    """Обойти распоряжения о торгах тем же путём, что и проекты решений."""
    import json

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        try:
            payload = json.loads(
                fetch(search_url(page, per_page, MOS_TENDER_QUERY)).decode("utf-8"))
        except Exception:
            return out, False
        rows = (payload or {}).get("results") or []
        fresh = []
        for row in rows:
            one = parse_tender_order(row) if isinstance(row, dict) else None
            if one and one["id"] and one["id"] not in seen:
                seen.add(one["id"])
                fresh.append(one)
        out.extend(fresh)
        if not fresh:
            return out, True
    return out, False


def _clean(text: str) -> str:
    return _SPACE.sub(" ", str(text or "").replace("­", "")).strip()


def parse_decision(row: dict[str, Any]) -> KrtDecision | None:
    """Одна запись выдачи. Не про КРТ — не наша запись, а не пустая."""
    title = _clean(row.get("title"))
    if "комплексном развити" not in title.casefold():
        return None
    okrug = ""
    found = _OKRUG.search(title)
    if found:
        okrug = found.group(1)
    body = _OKRUG.sub("", title).strip().rstrip(".").strip()
    address = ""
    at = _AT_ADDRESS.search(body) or _AT_ZONE.search(body)
    if at:
        address = _CITY.sub("", _clean(at.group(1))).strip(" ,")
    kind, _ = krt_kind(title)
    return KrtDecision(
        id=str(row.get("id") or "").strip(),
        title=title,
        url=_clean(row.get("url")),
        address=address,
        okrug=okrug,
        kind=kind,
        published_at=int(row.get("date") or 0),
        department=_clean(row.get("category")),
    )


def parse_decisions(payload: Any) -> list[KrtDecision]:
    rows = (payload or {}).get("results") if isinstance(payload, dict) else payload
    out: list[KrtDecision] = []
    for row in rows or []:
        if isinstance(row, dict):
            one = parse_decision(row)
            if one and one.id:
                out.append(one)
    return out


def collect(fetch: Callable[[str], bytes], *, max_pages: int = 60,
            per_page: int = 25) -> tuple[list[KrtDecision], bool]:
    """Обойти выдачу постранично. Возвращает решения и признак «дошли до конца».

    Оборвались на середине — так и сказано: недособранный список, выданный за
    полный, читается как «таких решений больше нет».
    """
    import json

    seen: set[str] = set()
    out: list[KrtDecision] = []
    complete = False
    for page in range(1, max_pages + 1):
        try:
            payload = json.loads(fetch(search_url(page, per_page)).decode("utf-8"))
        except Exception:
            return out, False
        got = parse_decisions(payload)
        fresh = [one for one in got if one.id not in seen]
        for one in fresh:
            seen.add(one.id)
        out.extend(fresh)
        # Пустая страница и страница без новых записей — обе значат конец:
        # поиск повторяет последнюю страницу вместо отказа.
        if not fresh:
            complete = True
            break
    else:
        complete = False
    return out, complete


def address_tokens(text: str) -> tuple[frozenset[str], frozenset[str]]:
    """Значащие слова адреса и номера владений — раздельно. Запасной путь."""
    flat = str(text or "").lower().replace("ё", "е")
    words = frozenset(w for w in _WORD.findall(flat) if w not in _STOP)
    houses = frozenset(_HOUSE.findall(flat))
    return words, houses


def places(text: str) -> frozenset[tuple[str, str]]:
    """Пары «улица — владение». Мешок слов против мешка чисел здесь не годится.

    «ул. 7-я Парковая, влд. 33» и «ул. 9-я Парковая, влд. 33» отличаются одним
    порядковым номером, а по словам и числам совпадают целиком; «Игарский пр-д,
    влд. 2» и «Игарский пр-д, вл. 6» — две разные площадки на одной улице.
    Поэтому номер владения держится за своей улицей.

    Имя улицы — последнее значащее слово перед номером, вместе с порядковым
    («7-я») или различающим («Верхняя», «Малая») словом перед ним: без них
    Верхняя и Нижняя Первомайская — одна улица.
    """
    flat = _SPACE.sub(" ", str(text or "").lower().replace("ё", "е"))
    out: set[tuple[str, str]] = set()
    for found in _HOUSE_MARK.finditer(flat):
        head = flat[max(0, found.start() - 70):found.start()]
        words = [w for w in _NAME_TOKEN.findall(head) if w not in _STOP]
        if not words:
            continue
        name = words[-1]
        if len(words) > 1 and (_ORDINAL.fullmatch(words[-2]) or words[-2] in _SIDE):
            name = words[-2] + " " + name
        out.add((name, found.group("house")))
    return frozenset(out)


def zone_number(text: str) -> str:
    """Номер производственной зоны: «№ 50 „Алтуфьевское шоссе“»."""
    found = _ZONE_NO.search(str(text or ""))
    return found.group(1) if found else ""


def qualifier(text: str) -> frozenset[str]:
    """Уточнение в скобках: «(проект 2)», «(территория 3)», «(юг)».

    Город делит одну площадку на части и различает их только этим. «Огородный
    проезд (юг)» и «Огородный проезд (проект 2)» — разные площадки, и по словам
    они совпадают целиком.
    """
    out: set[str] = set()
    for found in _QUALIFIER.finditer(str(text or "").lower().replace("ё", "е")):
        # Служебные слова здесь НЕ отбрасываются: «проект» и «территория» —
        # ровно то, чем город различает части одной площадки, и без них
        # «(проект 2)» и «(территория 2)» становятся одним и тем же.
        out |= set(_NAME_TOKEN.findall(found.group("q")))
        out |= set(re.findall(r"\d+", found.group("q")))
    return frozenset(out)


def same_place(left: str, right: str) -> bool:
    """Строго: ложная привязка прячет настоящий пробел.

    Совпали пары «улица — владение» — это одна площадка. Пар нет (решение
    названо производственной зоной) — сверяем номер зоны, уточнение в скобках и
    значащие слова.
    """
    lp, rp = places(left), places(right)
    if lp and rp:
        return bool(lp & rp)
    lq, rq = qualifier(left), qualifier(right)
    if lq and rq and lq != rq:
        return False
    lz, rz = zone_number(left), zone_number(right)
    if lz and rz and lz != rz:
        return False
    lw, _ = address_tokens(left)
    rw, _ = address_tokens(right)
    shared = lw & rw
    if not shared:
        return False
    # Одного общего слова хватает, только когда стороны совпали ещё и
    # уточнением или номером зоны: «Огородный» сам по себе — половина адреса.
    if (lq and rq) or (lz and rz):
        return True
    return len(shared) >= 2


def match_catalogue(decisions: Iterable[KrtDecision],
                    catalogue: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Разложить решения на «карточка есть» и «карточки нет»."""
    sites = [
        {"slug": str(site.get("slug") or ""), "name": _clean(site.get("name")),
         "okrug": _clean(site.get("okrug"))}
        for site in catalogue or []
    ]
    matched: list[KrtDecision] = []
    unmatched: list[KrtDecision] = []
    for one in decisions:
        probe = one.address or one.title
        hit = None
        for site in sites:
            if one.okrug and site["okrug"] and one.okrug != site["okrug"]:
                continue
            if same_place(probe, site["name"]):
                hit = site
                break
        if hit:
            one.matched_slug, one.matched_name = hit["slug"], hit["name"]
            matched.append(one)
        else:
            unmatched.append(one)
    unmatched.sort(key=lambda d: d.published_at, reverse=True)
    return {"matched": matched, "unmatched": unmatched,
            "total": len(matched) + len(unmatched)}
