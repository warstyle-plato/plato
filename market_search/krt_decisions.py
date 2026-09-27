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
# Номер части площадки: «территория 2», «тер. 4, 5, 6», «территория № 1»,
# «проект 2», «проект 2.1». Город пишет его то в скобках, то без них — «ул.
# Дербеневская (территория 2)» в решении и «Дербеневская ул. тер. 2» в
# каталоге, — и пока уточнение читалось ТОЛЬКО из скобок, одна сторона пары
# была пустой, а пустая с непустой не спорит. Номер поэтому читается отовсюду
# и своей величиной, как номер производственной зоны.
_PART = re.compile(
    r"(?iu)\b(?P<kind>тер(?:\.|ритори[яий])?|проект(?:а|ы)?)\.?\s*"
    r"№?\s*(?P<nums>\d+(?:\.\d+)?(?:\s*,\s*\d+)*)")
_PART_NUM = re.compile(r"\d+(?:\.\d+)?")
# Имя площадки в кавычках: «в производственной зоне № 56 «Грайвороново»».
_QUOTED = re.compile(r"[«\"]([^«»\"]{2,60})[»\"]")


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


# Номер распоряжения в заголовке карточки mos.ru. Разделитель между буквенной
# частью и числом город пишет то дефисом («ДГП-Р-54/26»), то пробелом
# («ДГП-Р 58/26»), а образец требовал цифру сразу за буквами — и второе
# написание не читалось вовсе. Та же семья, что ASCII-дефис в именах ЖК и
# номер владения, написанный диапазоном: форма записи у источника не одна.
# Буквы только ЗАГЛАВНЫЕ и без флага регистронезависимости намеренно: это
# аббревиатура ведомства, а при (?i) «№ от 03.09.2026» дало бы номер «от 03.09».
_ORDER_NUMBER = re.compile(r"(?u)№\s*((?:[А-ЯЁA-Z]+[-\s])*\d+(?:[/-]\d+)?)")


def order_action(title: str) -> str:
    """Что ДЕЛАЕТ распоряжение: назначает торги или отменяет их.

    Слово источника прочиталось наоборот: распоряжение № 56209 от 09.08.2023
    «Об ОТМЕНЕ проведения торгов… Волгоградский проспект, вл. 32» стояло в
    фильтре площадок как «Торги», а его начальная цена годилась бы модели за
    цену входа. Вид документа читается тем же способом, каким читается всё
    остальное в его заголовке.

    Неопознанное остаётся пустым: «не поняли, что это за документ» — не
    «назначены торги», и подставлять одно вместо другого нельзя.
    """
    low = _clean(title).casefold()
    if "отмен" in low:
        return "cancel"
    if "о проведении" in low or "проведени" in low:
        return "hold"
    return ""


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
        "action": order_action(title),
    }


def _walk(fetch: Callable[[str], bytes], query: str, *, max_pages: int,
          per_page: int) -> tuple[list[dict[str, Any]], int, int, int, int, bool]:
    """Обойти выдачу поиска по объявленным страницам. Один обход на два запроса.

    **Сколько у источника есть — спрашивают у источника.** Прежде каждый обход
    считал себя полным, как только страница не приносила новых записей, — верно
    на последней странице (поиск повторяет её вместо отказа) и неверно в
    середине: выдача ранжированная, порядок между запросами плывёт, и
    повторившаяся страница обрывала обход посреди списка. Обрыв объявлялся
    полным обходом, усечённый список заменял снимок, а выпавшая из него
    площадка возвращалась следующим заходом уже НОВОЙ — бот писал в чат «в
    каталоге КРТ новая площадка» об одном и том же весь день (экран владельца,
    15.09.2026).

    Замер того часа развёл источник и нас: у проектов решений mos.ru объявляет
    `totalCount` 580 и `pageCount` 58, два полных обхода подряд дали 580
    документов из 580 без единого расхождения, и все четыре «новые» площадки в
    выдаче есть; у распоряжений о торгах те же поля — 55 и 6. То есть шатался
    обход, а не город.

    Отсюда правило: конец выдачи — это ПРОЧИТАННЫЕ ВСЕ объявленные страницы, а
    бесплодная страница в середине обход не кончает. Источник не объявил своих
    чисел — остаётся прежняя примета (страница без новых записей), и она
    названа нулями: «не объявил» и «объявил ноль» — разные ответы.

    Возвращает строки выдачи, страниц прочитано, страниц объявлено, различных
    документов, объявленное число документов и дошёл ли обход до конца.
    """
    import json

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    announced = pages_announced = pages = 0
    ended = False
    for page in range(1, max_pages + 1):
        try:
            payload = json.loads(
                fetch(search_url(page, per_page, query)).decode("utf-8"))
        except Exception:
            break
        pages = page
        meta = payload.get("_meta") if isinstance(payload, dict) else None
        if isinstance(meta, dict):
            try:
                announced = max(announced, int(meta.get("totalCount") or 0))
                pages_announced = max(pages_announced,
                                      int(meta.get("pageCount") or 0))
            except (TypeError, ValueError):
                pass
        got = payload.get("results") if isinstance(payload, dict) else payload
        got = [row for row in (got or []) if isinstance(row, dict)]
        fresh = [row for row in got if str(row.get("id") or "") not in seen]
        for row in fresh:
            seen.add(str(row.get("id") or ""))
        rows.extend(fresh)
        if pages_announced:
            # Объявленные страницы читаются все. Бесплодная страница в середине
            # — это повтор выдачи, а не её конец.
            if page >= pages_announced:
                ended = True
                break
            continue
        if not got or not fresh:
            ended = True
            break
    return rows, pages, pages_announced, len(seen), announced, ended


@dataclass(frozen=True)
class Walk:
    """Один обход выдачи: что принесено и насколько это полно.

    Полнота здесь не украшение и не догадка: по ней решают, вправе ли обход
    ЗАМЕНИТЬ прежний снимок. Поэтому рядом с признаком лежат числа, которыми он
    посчитан, — сколько страниц прочитано из объявленных источником и сколько
    различных документов увидено из объявленных. «Обход недособран» без этих
    чисел неотличимо от «в источнике столько и есть».
    """

    items: list[Any]
    complete: bool
    seen: int = 0
    announced: int = 0
    pages: int = 0
    pages_announced: int = 0
    # Документы выдачи, не ставшие нашей записью: заголовок не про КРТ либо
    # идентификатора нет вовсе. Это НЕ ошибка — поиск отдаёт и чужие бумаги, —
    # но и не пустяк: пока они выбрасывались молча, снимок не мог объяснить
    # объявленное источником число документов ПО ПОСТРОЕНИЮ, а «молча
    # выброшенное читается как его отсутствие». Едут идентификаторами, а не
    # числом: снимок обязан помнить, КАКИЕ именно, иначе на следующем обходе
    # они посчитаются заново и дважды.
    unparsed: tuple[str, ...] = ()

    def shortfall(self) -> str:
        """Чего не хватило обходу. Пусто — значит дочитан."""
        if self.complete:
            return ""
        if self.pages_announced and self.pages < self.pages_announced:
            return f"прочитано страниц {self.pages} из {self.pages_announced}"
        if self.announced and self.seen < self.announced:
            return f"документов выдачи {self.seen} из {self.announced}"
        return "обход оборвался"


def _walked(rows: list[Any], pages: int, pages_announced: int, seen: int,
            announced: int, ended: bool,
            unparsed: tuple[str, ...] = ()) -> Walk:
    """Собрать ответ обхода. Полнота — все объявленные страницы и все документы.

    Считаются документы ВЫДАЧИ, а не наши: `totalCount` — это все попадания
    поиска, включая те, чей заголовок не про КРТ, и сравнивать его с числом
    наших записей значило бы не дочитать никогда.
    """
    return Walk(items=rows,
                complete=ended and (seen >= announced if announced else True),
                seen=seen, announced=announced, pages=pages,
                pages_announced=pages_announced, unparsed=unparsed)


def _kept_and_skipped(rows: list[dict[str, Any]], parse: Callable[[dict[str, Any]], Any],
                      key: Callable[[Any], str]) -> tuple[list[Any], tuple[str, ...]]:
    """Разобрать строки выдачи и НАЗВАТЬ те, что записью не стали.

    Счёт один на оба запроса: вторая копия разошлась бы с первой молча, а от
    этого числа зависит, вправе ли снимок объявить себя полным. Документ,
    выброшенный без счёта, делает объявленное источником число недостижимым —
    и снимок либо не дочитается никогда, либо объявит себя полным по union'у,
    накопленному за несколько обходов.
    """
    out: list[Any] = []
    known: set[str] = set()
    skipped: list[str] = []
    for row in rows:
        one = parse(row)
        name = key(one) if one else ""
        if one and name and name not in known:
            known.add(name)
            out.append(one)
            continue
        # Идентификатор берётся у СТРОКИ ВЫДАЧИ: у неразобранной записи нашего
        # имени нет вовсе, а документ у источника есть, и объяснить его надо.
        found = str(row.get("id") or "")
        if found and found not in known:
            skipped.append(found)
    return out, tuple(skipped)


def collect_tender_orders(fetch: Callable[[str], bytes], *, max_pages: int = 12,
                          per_page: int = 25) -> Walk:
    """Обойти распоряжения о торгах тем же обходом, что и проекты решений."""
    rows, pages, pages_announced, seen, announced, ended = _walk(
        fetch, MOS_TENDER_QUERY, max_pages=max_pages, per_page=per_page)
    out, skipped = _kept_and_skipped(rows, parse_tender_order,
                                     lambda one: str(one.get("id") or ""))
    return _walked(out, pages, pages_announced, seen, announced, ended, skipped)

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


def collect(fetch: Callable[[str], bytes], *, max_pages: int = 120,
            per_page: int = 25) -> Walk:
    """Обойти выдачу проектов решений. Возвращает принесённое и его полноту.

    Сам обход и правило «дочитано» живут в `_walk` — один ответ на два запроса:
    вторая копия приметы разошлась бы с первой молча, и половина снимков
    шаталась бы и дальше.
    """
    rows, pages, pages_announced, seen, announced, ended = _walk(
        fetch, MOS_KRT_QUERY, max_pages=max_pages, per_page=per_page)
    out, skipped = _kept_and_skipped(rows, parse_decision, lambda one: one.id)
    return _walked(out, pages, pages_announced, seen, announced, ended, skipped)

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


def part_numbers(text: str, kind: str) -> frozenset[str]:
    """Номера части площадки: `kind` — «территория» или «проект».

    Город делит одну площадку на части и различает их только этим, а пишет
    по-разному: «ул. Дербеневская (территория 2)» в решении и «Дербеневская
    ул. тер. 2» в каталоге. Пока номер читался только из скобок, у карточки
    уточнения не было вовсе — а пустая сторона с непустой не спорит, и
    решение по территории 2 либо не находило своей карточки, либо садилось на
    соседнюю: замер прода 20.09.2026 по 579 решениям и 282 карточкам нашёл
    девять таких привязок (Соколиная гора «территория 2» на карточке «тер. 1»,
    Серп и Молот «территория № 3» и «№ 4» на карточке «тер. 1») и четыре
    решения, стоявших не на своей карточке.

    Номера идут списком — «тер. 4, 5, 6», «(территории 1, 2)», — и берутся все:
    часть, выданная за целое, читается так же уверенно, как целое.
    """
    head = "территория" if str(kind).startswith("тер") else "проект"
    out: set[str] = set()
    for found in _PART.finditer(str(text or "").lower().replace("ё", "е")):
        mine = "территория" if found.group("kind").startswith("тер") else "проект"
        if mine != head:
            continue
        out |= set(_PART_NUM.findall(found.group("nums")))
    return frozenset(out)


def named(text: str) -> frozenset[str]:
    """Имя площадки в кавычках — «в производственной зоне № 56 «Грайвороново»».

    Оно и есть то, чем площадка опознаётся, когда номер части у сторон совпал,
    а общих слов всего одно: «Южное Очаково (территория 3)» и «Северное Очаково
    тер. 3» совпадают словом «очаково» и номером части, но это разные площадки,
    как «Грайвороново» и «Карачарово» в одном районе.
    """
    out: set[str] = set()
    for found in _QUOTED.finditer(str(text or "")):
        flat = found.group(1).lower().replace("ё", "е")
        out |= {w for w in _WORD.findall(flat) if w not in _STOP}
    return frozenset(out)


def _without_parts(text: str) -> str:
    return _PART.sub(" ", str(text or "").lower().replace("ё", "е"))


def qualifier(text: str) -> frozenset[str]:
    """Остаток скобок: «(юг)», «(Рязанский)», «(САО, ЦАО)».

    Номер части площадки («проект 2», «территория 3») сюда НЕ входит: его
    считает `part_numbers` и считает отовсюду, а не только из скобок. Пока он
    жил здесь, сравнение спотыкалось о то, ГДЕ город его написал: «(проект 2,
    территория 1)» в решении и «тер. 1 (проект 2)» в карточке — одна и та же
    площадка, а наборы выходили разные. И наоборот: «(территория № 4, 5, 6)
    (САО, ЦАО)» в решении против «тер. 4, 5, 6» в карточке расходилось на
    округах, которые к части площадки отношения не имеют вовсе.
    """
    out: set[str] = set()
    for found in _QUALIFIER.finditer(_without_parts(text)):
        out |= set(_NAME_TOKEN.findall(found.group("q")))
        out |= set(re.findall(r"\d+", found.group("q")))
    return frozenset(out)


def qualifier_text(text: str) -> frozenset[str]:
    """Скобки как они написаны — для проверки ТОЖДЕСТВА адреса.

    `qualifier` разбирает содержимое скобок на значащие слова и числа, и
    короткое уточнение до трёх букв в них не попадает вовсе: у «(юг)» набор
    пуст, как и у адреса без скобок. Для правила «адрес совпал целиком» этого
    мало — «Огородный проезд (юг)» и «Огородный проезд» стали бы одной
    площадкой, а это ровно то, от чего писана строгость.
    """
    return frozenset(
        _SPACE.sub(" ", found.group("q").strip(" ,;"))
        for found in _QUALIFIER.finditer(_without_parts(text))
        if found.group("q").strip(" ,;"))


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
    # Номер части площадки — такой же различающий признак, как номер зоны, и
    # читается он отовсюду, а не только из скобок.
    lt, rt = part_numbers(left, "территория"), part_numbers(right, "территория")
    if lt and rt and lt != rt:
        return False
    ln, rn = part_numbers(left, "проект"), part_numbers(right, "проект")
    if ln and rn and ln != rn:
        return False
    lw, lh = address_tokens(left)
    rw, rh = address_tokens(right)
    shared = lw & rw
    if not shared:
        return False
    # Адрес совпал ЦЕЛИКОМ — это одна площадка, сколько бы значащих слов в нём
    # ни было. Порог «двух общих слов» писан для частичных совпадений, и адрес
    # из одного значащего слова не проходил его даже при тождестве:
    # `same_place("Машкинское шоссе", "Машкинское шоссе")` отвечал «нет», и 13
    # площадок стояли в списке дважды — карточкой каталога и «площадкой без
    # карточки» (снимок прода 06.09.2026). Тождество проверяется всеми
    # различающими признаками сразу: номера владений, уточнение в скобках и
    # номер зоны обязаны совпасть тоже, иначе «ул. Десантная» забрала бы себе
    # «Десантную ул., вл. 5», а это ровно та ошибка, от которой писана
    # строгость: улица опознаёт квартал, а не площадку.
    if (lw == rw and lh == rh and lz == rz and lt == rt and ln == rn
            and qualifier_text(left) == qualifier_text(right)):
        return True
    # Одного общего слова хватает, только когда стороны совпали ещё и
    # уточнением или номером зоны: «Огородный» сам по себе — половина адреса.
    if (lq and rq) or (lz and rz):
        return True
    # Совпавший номер части — признак сильный, но сам по себе он не опознаёт
    # площадку: «Южное Очаково (территория 3)» и «Северное Очаково тер. 3»
    # совпадают им и словом «очаково», а это разные площадки, как
    # «Грайвороново» и «Карачарово» в одном районе. Поэтому рядом обязано
    # сойтись ИМЯ: различающее слово улицы у сторон одно и то же, а имя в
    # кавычках отзывается в словах другой стороны. Кавычек нет ни у кого —
    # остаётся прежняя строгость: слова одной стороны вложены в другую.
    if (lt and rt) or (ln and rn):
        if (lw & _SIDE) == (rw & _SIDE):
            lnm, rnm = named(left), named(right)
            if lnm and (lnm & rw):
                return True
            if rnm and (rnm & lw):
                return True
            if not lnm and not rnm and (lw <= rw or rw <= lw):
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
