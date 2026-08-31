"""ГИС Торги (torgi.gov.ru) — банкротные лоты и прочее имущество должников.

Наши три источника продают ГОРОДСКОЕ имущество. Реестры, которые смотрит
девелопер, наполовину состоят из другого: имущественные комплексы, нежилые
здания и незавершёнка от арбитражных управляющих, залоговых кредиторов и
госкорпораций. Ни один из них через РАД, Росэлторг и «Торги Москвы» не виден —
разница не в фильтре, а в источнике (владелец, 24.08.2026).

Почему ГИС Торги, а не площадки банкротства напрямую: их десятки — Сбербанк-АСТ,
Фабрикант, Ютендер, Центр реализации, — один и тот же лот лежит на нескольких
сразу, и склеивать дубли пришлось бы нам. ГИС Торги — официальный агрегатор с
машинным ответом, и извещение там одно на лот.

## Чего этот файл НЕ знает

Из локальной среды torgi.gov.ru нестабилен, поэтому окончательная проба
идёт с ядра. Форма ответа и поля карточки сверены живыми ответами.
Внутренний `dynSubjRF=78` для Москвы и категории `catCode=2/7` берутся из
публичных примеров запросов ГИС Торги; чужой регион всё равно не пройдёт
независимую проверку `subjectRFCode=77`. Адаптер выключается переменной
`TORGI_GOV_DISCOVERY=0`.

Проверять это надо с ядра — тем же способом, что и слои НСПД: `probe()` печатает
сырой ответ и разобранный лот рядом, чтобы расхождение было видно глазами, а не
вылезло числом в отчёте.

## Что сверено живым ответом, а что нет

24.08.2026 пришёл настоящий ответ поиска — три карточки одной страницы. Он
подтвердил оболочку (`content`, `totalElements`, нумерация страниц с нуля) и
опроверг почти весь наш разбор:

- **Ценовое поле ОДНО** — `priceMin` (плюс оно же строкой, `priceMinExact`).
  `estimatedPrice` и `priceFin` не приходят вовсе, и какой у числа правовой
  смысл — начальная цена, текущая или отсечка — из ответа не следует. Значит
  батарейка хода по этому источнику не рисуется: ей нужны обе границы.
- **Форма торгов живёт в `biddForm`**, отдельно от вида (`biddType`): «PP» —
  публичное предложение, «SMP» — по минимально допустимой цене, «PK» — конкурс.
  Именно здесь ответ на «ползёт ли цена», а не в законе: у приватизации по
  178-ФЗ бывают обе формы. Графика снижения в ответе поиска нет.
- **Кадастр, площадь, этажность и год — строки `characteristics`** с кодами
  `cadastralNumberRealty`, `totalAreaRealty`, `numberFloors`,
  `yearCommissioning`, а не поля карточки. Площадь там — метры ЗДАНИЯ; метры
  участка стоят только в тексте описания.
- **Адреса отдельным полем нет.** `estateAddress`, `estateArea`, `seller`,
  `permittedUse`, `documents`, координаты — ничего этого в ответе не было.
- **Дата публикации** называется `noticeFirstVersionPublicationDate`.
- **`dynSubjRF` — не код субъекта.** Старый запрос ошибочно посылал
  `dynSubjRF=77` и получал Ярославскую область. Это внутренний id справочника;
  для Москвы используется 78. После серверного фильтра каждая карточка
  всё равно проверяется по официальному `subjectRFCode=77`.
- **Кода банкротства в выборке не было.** Подтвердился только `178FZ` —
  приватизация, то есть городской рынок; наш `127FZ` остаётся догадкой.

Три карточки — не весь сервис, и это важнее списка выше: **поле, которого нет
в трёх карточках, не доказано отсутствующим.** Поэтому проба считает ключи по
всей странице, а разбор пропускает ненайденное, а не подставляет умолчание.

Отсюда же правило, стоившее двух заходов: **чужая уверенность — не проба.**
Сверка по памяти модели не подтвердила ни одного имени поля и была права, что
не подтвердила; наши «уверенные» имена оказались выдумкой почти полностью.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable

from auction_search import deadline as clock
from auction_search.adapters.base import AuctionPlatformAdapter
from auction_search.classifier import (
    BANKRUPTCY_WORDS as _BANKRUPTCY_WORDS,
    origin_from_evidence,
)
from auction_search.models import (
    AuctionDocument, AuctionLot, AuctionSource, LotKind, LotOrigin, SourceKind,
)


FLAG = "TORGI_GOV_DISCOVERY"
HOST = "torgi.gov.ru"
SEARCH_PATH = "/new/api/public/lotcards/search"
LOT_URL = "https://torgi.gov.ru/new/public/lots/lot/{id}"
# Адрес одиночной карточки. Живым ответом НЕ сверен: из песочницы
# torgi.gov.ru не спросить. Это соседний путь того же ресурса, что и
# сверенный поиск (`/lotcards/search`), — догадка названа вслух, а разбор
# ответа ничего не пропускает молча: не та форма — ошибка с адресом и
# верхними ключами ответа, а не пустой лот.
LOT_CARD_PATH = "/new/api/public/lotcards/{id}"
USER_AGENT = "DevelopAid-AuctionCollector/0.1 (+https://developaid.ru)"
TIMEOUT_SECONDS = 8
# Размер страницы мы ПРОСИМ, а не назначаем. На прод приехал сбор из ОДНОЙ
# страницы: сервис прислал десять карточек на запрос с `size=50`, и сработала
# остановка «пришло меньше запрошенного — значит последняя». Она верна только
# там, где размер страницы соблюдают. Конец выборки объявляет сама оболочка
# (`totalPages`, `last`), пустая страница — последний рубеж, а страница без
# единого нового лота ловит сервис, игнорирующий и номер страницы тоже.
PAGE_SIZE = 50
# Четыре целевых выборки по десять страниц сохраняют прежний общий
# потолок в сорок запросов, но не тратят его на поток квартир.
MAX_PAGES_PER_FILTER = 10

# Страница называется «Торги Москвы», поэтому субъект здесь только Москва.
# Код 50 в `subjectRFCode` означает Московскую область. Это не то же самое,
# что исторический кадастровый префикс 50 у отдельных участков Новой Москвы:
# кадастровый номер может начинаться с 50, но субъект такой карточки остаётся 77.
SUBJECT_CODES = ("77",)

# `dynSubjRF` is not the legal `subjectRFCode`: it is the portal's internal
# dictionary id.  Live public examples use 63 for Rostov (subject 61), 80 for
# Sevastopol (subject 92), and 78 for Moscow.  We still verify every returned
# card by the authoritative `subjectRFCode=77` below.
MOSCOW_DYN_SUBJECT_IDS = ("78",)
ACTIVE_LOT_STATUSES = ("PUBLISHED", "APPLICATIONS_SUBMISSION")

# One broad newest-first stream brought 300 mostly residential cards before a
# development lot.  These public API filters target the asset classes the user
# actually asked for while keeping the same forty-page ceiling overall.
DISCOVERY_FILTERS = (
    ("земельные участки", "2", ""),
    ("здания", "7", "здание"),
    ("незавершённые объекты", "7", "незаверш"),
    ("имущественные комплексы", "7", "имущественный комплекс"),
)

# `dynSubjRF` — внутренний id справочника портала. Его нельзя заменять
# официальным кодом субъекта: `dynSubjRF=77` отдавал карточки с
# `subjectRFCode=76`. Для Москвы в запросе идёт id 78, а на выходе остаётся
# жёсткая проверка каждой карточки по `subjectRFCode=77`.
REGION_PARAM = "dynSubjRF"
REGION_PARAM_CANDIDATES = (
    "dynSubjRF", "subjectRFCode", "subjectRF", "dynSubjRFCode", "subjectRFList",
)

# Виды торгов. Сами КОДЫ не сверены ответом сервиса — см. оговорку в шапке;
# сверено другое, и это не про API, а про право: 178-ФЗ — приватизация
# государственного и муниципального имущества, то есть ровно городской рынок,
# а не банкротный. Продавец там город, и в наш список он попадает как CITY.
# Банкротство — 127-ФЗ «О несостоятельности (банкротстве)».
PRIVATIZATION_CODES = ("178FZ",)
BANKRUPTCY_CODES = ("127FZ", "BANKRUPTCY")

# Слова, по которым происхождение опознаётся, когда код не опознан, живут в
# `classifier`: правило «это банкротный лот» одно на модуль. Разойдись копии —
# один и тот же лот с ГИС Торгов и с РАД попал бы в разные рынки, и оба списка
# выглядели бы верными. Имя здесь оставлено: по нему ходят проба и тесты.
BANKRUPTCY_WORDS = _BANKRUPTCY_WORDS

# Формы торгов — отдельное поле `biddForm`, не то же самое, что вид торгов.
# Подтверждено живым ответом 24.08.2026: «PP» — публичное предложение (цена
# снижается по графику), «SMP» — продажа по минимально допустимой цене, «PK» —
# конкурс. Именно здесь, а не в `biddType`, лежит ответ на вопрос «ползёт ли
# цена»: у приватизации по 178-ФЗ бывают обе формы.
FORM_PUBLIC_OFFER = "PP"
FORM_MIN_PRICE = "SMP"
FORM_CONTEST = "PK"

# Коды характеристик. Кадастровый номер, площадь, этажность и год стоят не
# полями карточки, а строками списка `characteristics`.
CHAR_CADASTRE = "cadastralNumberRealty"
CHAR_TOTAL_AREA = "totalAreaRealty"
CHAR_FLOORS = "numberFloors"
CHAR_YEAR = "yearCommissioning"

# Начала кодов атрибутов. Целиком код несёт в себе форму торгов и закон
# (`DA_limitations_PP(178)`, `DA_limitations_minpriced(178)`), да ещё и с
# опечатками самого сервиса — поэтому сверяем начало.
ATTR_LIMITATIONS = "DA_limitations"
ATTR_PERMITTED_USE = "DA_permittedUse"
ATTR_APPRAISAL = "DA_appraisalReport"

# Что считаем интересным для девелопмента. Слова из названия и назначения лота:
# у ГИС Торгов своей рубрики «под редевелопмент» нет и быть не может.
LAND_WORDS = ("земельн", "участок", "зу ")
BUILDING_WORDS = ("здани", "помещен", "комплекс", "незавершен", "незавершён", "сооружен")


# Дополнительные корневые сертификаты. Живой ответ с ядра 24.08.2026:
# соединение с torgi.gov.ru УСТАНАВЛИВАЕТСЯ, но цепочка не проверяется —
# «unable to get local issuer certificate». Российские госсайты выпускают
# сертификаты у национального удостоверяющего центра, и его корня в обычном
# хранилище нет: иностранные центры им больше не выдают.
#
# Лечится это добавлением корня в доверенные, а НЕ отключением проверки.
# Выключенная проверка молча принимает любой сертификат — и тогда «мы читаем
# ГИС Торги» перестаёт что-либо значить, потому что читать могли и не их.
# Такого переключателя здесь нет намеренно.
# Поддержка добавочных корней объявлена один раз и общая с модулем рынка:
# каталог КРТ ходил наружу мимо неё и падал на проверке сертификата всегда.
# Имена оставлены на месте — их зовут и отсюда, и проверки.
from trusted_roots import (  # noqa: E402
    EXTRA_CA_DIR,
    extra_ca_files,
    load_extra_roots,
    trust_context,
)


def trust_report(directory: str = "") -> dict[str, list[str]]:
    """Что из каталога корней сервис принял, а что отверг."""
    accepted, rejected = load_extra_roots(ssl.create_default_context(), directory)
    return {"accepted": accepted, "rejected": rejected}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _moment(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def classify(card: dict[str, Any]) -> tuple[LotKind, LotOrigin]:
    """Вид и происхождение лота по тому, что написано в извещении.

    Ни то ни другое не выдумывается: не опознали — `OTHER`, и лот виден в
    списке как «другое», а не подогнан под ближайшую рубрику.
    """
    blob = " ".join(_text(card.get(key)).lower() for key in (
        "lotName", "lotDescription")) + " " + _text(
        (card.get("category") or {}).get("name")
        if isinstance(card.get("category"), dict) else card.get("category")).lower()
    bidd = card.get("biddType") or {}
    code = _text(bidd.get("code") if isinstance(bidd, dict) else bidd).upper()
    name = _text(bidd.get("name") if isinstance(bidd, dict) else "").lower()
    # Порядок здесь не косметический. Слова процедуры — знание о праве и верны
    # сами по себе; коды — наша догадка о справочнике сервиса. Живой ответ
    # 24.08.2026 подтвердил только «178FZ»; кода банкротства в нём не было,
    # и наш «127FZ» остаётся догадкой. Поэтому догадка не отменяет
    # доказательства: карточка, прямо называющая конкурсное производство,
    # банкротная при любом коде.
    origin = origin_from_evidence(procedure_type=name, text=blob)
    if origin is LotOrigin.OTHER:
        if code in BANKRUPTCY_CODES:
            origin = LotOrigin.BANKRUPTCY
        elif code in PRIVATIZATION_CODES:
            origin = LotOrigin.CITY
    # Вид: сперва рубрика самого сервиса, и только потом слова из прозы.
    # У ГИС Торгов есть `category` («Здания» в живом ответе) — это его
    # собственная классификация, а гонка слов в описании выигрывается кем
    # попало: «Здание дома кордона С ЗЕМЕЛЬНЫМ УЧАСТКОМ» уходило в продажу
    # земли только потому, что «земельн» стоит в нашем списке выше «здание».
    category = _text((card.get("category") or {}).get("name")
                     if isinstance(card.get("category"), dict)
                     else card.get("category")).lower()
    kind = LotKind.OTHER
    if any(word in blob for word in ("незавершен", "незавершён")):
        kind = LotKind.UNFINISHED
    elif "комплекс" in blob:
        kind = LotKind.PROPERTY_COMPLEX
    elif category:
        if any(word in category for word in LAND_WORDS):
            kind = LotKind.LAND_SALE
        elif any(word in category for word in BUILDING_WORDS):
            kind = LotKind.PROPERTY_COMPLEX
    if kind is LotKind.OTHER:
        if any(word in blob for word in LAND_WORDS):
            kind = LotKind.LAND_SALE
        elif any(word in blob for word in BUILDING_WORDS):
            kind = LotKind.PROPERTY_COMPLEX
    return kind, origin


def characteristic(card: dict[str, Any], code: str) -> str | None:
    """Значение характеристики по коду.

    Кадастровый номер, площадь, этажность и год у ГИС Торгов лежат не полями
    карточки, а строками списка `characteristics` — ищутся по `code`, а не по
    человеческому названию: название приходит текстом и меняется вместе с
    редакцией справочника.
    """
    for item in card.get("characteristics") or []:
        if isinstance(item, dict) and _text(item.get("code")) == code:
            value = _text(item.get("characteristicValue"))
            return value or None
    return None


def attribute(card: dict[str, Any], prefix: str) -> str | None:
    """Значение атрибута по НАЧАЛУ кода, а не по точному совпадению.

    Код атрибута несёт в себе форму торгов и закон: обременения приезжают то
    как `DA_limitations_PP(178)`, то как `DA_limitations_minpriced(178)`. Хуже
    того, в живом ответе встречаются опечатки самого сервиса — `minpiced` без
    «r» и лишняя скобка в `minpriced((178)`. Сверять такое целиком значит
    терять поле на каждой новой форме торгов и на каждой чужой описке.
    """
    for source_key in ("attributes", "noticeAttributes"):
        for item in card.get(source_key) or []:
            if isinstance(item, dict) and _text(item.get("code")).startswith(prefix):
                value = _text(item.get("value"))
                if value:
                    return value
    return None


_CADASTRE_PATTERN = re.compile(r"\b\d{2}:\d{2}:\d{6,7}:\d+\b")


def cadastral_numbers(card: dict[str, Any]) -> list[str]:
    """Кадастровые номера: сперва структурированный, затем найденные в тексте.

    В живом ответе структурирован ровно один номер — здания. Номер участка, на
    котором это здание стоит, приходит только внутри описания. Брать из прозы
    страшно (в модуле рынка так уехал адрес объекта оценки), но здесь форма
    номера жёсткая и ни с чем не совпадает, а потерять участок — значит
    потерять то, ради чего лот вообще смотрят.
    """
    found: list[str] = []
    structured = characteristic(card, CHAR_CADASTRE)
    if structured:
        found.extend(_CADASTRE_PATTERN.findall(structured) or [structured])
    for key in ("lotName", "lotDescription"):
        found.extend(_CADASTRE_PATTERN.findall(_text(card.get(key))))
    seen: list[str] = []
    for item in found:
        if item not in seen:
            seen.append(item)
    return seen


_LOT_ID_CHARS = re.compile(r"^[0-9a-zA-Z_-]{6,}$")
# Слова самого маршрута. Они проходят проверку формы, но лотом не являются.
_NOT_A_LOT_ID = {"public", "lots", "lotcards", "notice", "search", "new"}


def lot_id_from_url(lot_url: str) -> str:
    """Номер лота из адреса карточки — ПОСЛЕДНИЙ сегмент пути, и только он.

    Перебирать сегменты вверх нельзя: у `/new/public/lots/` последним годным
    оказывается «public», и мы спросили бы чужой адрес с уверенным видом. Не
    разобрали — пусто, и вызвавший скажет это вслух.
    """
    parts = [part for part in urllib.parse.urlparse(lot_url).path.split("/") if part]
    if not parts:
        return ""
    last = parts[-1]
    return last if _LOT_ID_CHARS.match(last) and last.lower() not in _NOT_A_LOT_ID else ""


_CARD_KEYS = ("lotName", "lotDescription")
_CARD_WRAPPERS = ("lot", "lotCard", "content", "data", "result")


def _looks_like_card(value: Any) -> bool:
    return (isinstance(value, dict) and _text(value.get("id") or value.get("lotId"))
            and any(_text(value.get(key)) for key in _CARD_KEYS))


def lot_card(payload: Any) -> dict[str, Any] | None:
    """Карточка внутри ответа: сама по себе, в обёртке или первой в списке.

    Форму одиночного ответа мы не видели, поэтому она ищется по признакам, а не
    назначается. Не нашлась — `None`, и вызвавший скажет, что именно пришло:
    неверная догадка об оболочке иначе читалась бы как «лота нет».
    """
    if _looks_like_card(payload):
        return payload
    if not isinstance(payload, dict):
        return None
    for key in _CARD_WRAPPERS:
        value = payload.get(key)
        if _looks_like_card(value):
            return value
        if isinstance(value, list):
            for item in value:
                if _looks_like_card(item):
                    return item
    return None


_DOC_URL_KEYS = ("url", "fileUrl", "link", "href", "downloadUrl")
_DOC_NAME_KEYS = ("name", "fileName", "title", "documentName")
_DOC_LIST_KEYS = ("documents", "attachments", "lotAttachments", "files", "noticeDocuments")


def lot_documents(card: dict[str, Any]) -> list[AuctionDocument]:
    """Приложения карточки — только те, у которых есть адрес и имя.

    Состав этого списка живым ответом не сверен. Поэтому берётся не «что-нибудь
    похожее», а строго запись с адресом: документ без ссылки в списке выглядел
    бы полученным, хотя открыть его нечем.
    """
    found: list[AuctionDocument] = []
    seen: set[str] = set()
    for key in _DOC_LIST_KEYS:
        items = card.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            url = next((_text(item.get(name)) for name in _DOC_URL_KEYS
                        if _text(item.get(name))), "")
            if not url or url in seen:
                continue
            seen.add(url)
            title = next((_text(item.get(name)) for name in _DOC_NAME_KEYS
                          if _text(item.get(name))), "") or "документ лота"
            found.append(AuctionDocument(title=title, url=url, access_status="public"))
    return found


def in_target_region(
    card: dict[str, Any], subject_codes: tuple[str, ...] = SUBJECT_CODES
) -> bool:
    """Наш ли это регион — по полю карточки, а не по вере в параметр запроса.

    Серверная выборка сокращает поток, но не заменяет проверку. Внутренний
    id региона может измениться или быть передан ошибочно; в московский список
    попадают только карточки с официальным `subjectRFCode=77`.
    """
    code = _text(card.get("subjectRFCode"))
    if not code:
        # Запасного пути по словам здесь нет намеренно. «Москва» и
        # «московская» встречаются в названии улицы: улица Московская есть в
        # половине городов страны, и ярославский лот на ней прошёл бы за наш.
        # Это ровно та ошибка, на которой в модуле рынка кандидат забрал себе
        # адрес объекта оценки. Нет кода региона — не знаем, а не «наш»;
        # сколько таких, сбор считает отдельно и говорит вслух.
        return False
    return code.lstrip("0") in {item.lstrip("0") for item in subject_codes}


def to_lot(card: dict[str, Any], fetched_at: str) -> AuctionLot | None:
    """Карточка ГИС Торгов в наш лот. Без обязательного — пропуск."""
    lot_id = _text(card.get("id") or card.get("lotId"))
    title = _text(card.get("lotName") or card.get("lotDescription"))
    if not lot_id or not title:
        return None
    kind, origin = classify(card)
    form = card.get("biddForm") or {}
    form_code = _text(form.get("code") if isinstance(form, dict) else form).upper()
    form_name = _text(form.get("name") if isinstance(form, dict) else "")
    bidd = card.get("biddType") or {}
    bidd_name = _text(bidd.get("name") if isinstance(bidd, dict) else bidd)

    # Цена. В живом ответе ценовое поле ОДНО — `priceMin` (и его же строкой,
    # `priceMinExact`), а `estimatedPrice` и `priceFin`, на которые мы
    # рассчитывали, не приходят вовсе. Какой у этого числа правовой смысл —
    # начальная цена, текущая или отсечка — по ответу не определить, и
    # разложить его по трём нашим полям значит выдумать два из них. Кладём в
    # «цену сейчас»: это то, что в карточке названо ценой сегодня. Начальная и
    # минимальная остаются пустыми, поэтому батарейка хода не рисуется — ей
    # нужны обе границы, а у нас их нет.
    price = _number(card.get("priceMin"))
    if price is None:
        price = _number(card.get("priceMinExact"))
    flags: list[str] = []
    if price is not None:
        flags.append(
            "ГИС Торги отдают одно ценовое поле (priceMin); начальная это цена, "
            "текущая или отсечка — из ответа сервиса не следует")
    if form_code == FORM_PUBLIC_OFFER:
        flags.append(
            "публичное предложение: цена снижается по графику, но графика в "
            "ответе поиска нет — шаг и сроки надо смотреть в извещении")

    source = AuctionSource(
        platform=SourceKind.TORGI_GOV,
        lot_url=LOT_URL.format(id=urllib.parse.quote(lot_id)),
        external_lot_id=lot_id,
        fetched_at=fetched_at,
        source_name="ГИС Торги (torgi.gov.ru)",
    )
    return AuctionLot(
        source=source,
        lot_kind=kind,
        title=title,
        origin=origin,
        # Отдельного поля адреса в ответе нет: он живёт внутри названия и
        # описания. Выдирать его оттуда не берёмся — в модуле рынка ровно так
        # кандидат забрал себе адрес объекта оценки и встал в ноль километров.
        address=None,
        cadastral_numbers=cadastral_numbers(card),
        building_area_sqm=_number(characteristic(card, CHAR_TOTAL_AREA)),
        permitted_use=attribute(card, ATTR_PERMITTED_USE),
        procedure_type=" · ".join(part for part in (bidd_name, form_name) if part) or None,
        current_price_rub=price,
        application_deadline=_moment(card.get("biddEndTime")),
        status=_text(card.get("lotStatus")) or None,
        relevance_flags=flags,
    )


class TorgiGovAdapter(AuctionPlatformAdapter):
    """Банкротные и прочие лоты имущества должников из ГИС Торгов."""

    # Хост объявлен здесь, чтобы маршрут `/auctions/ingest` спрашивал адаптер,
    # а не хранил вторую копию имени. Копию негде обновлять — её нет.
    HOST = HOST
    # Пусто — «разбор одного лота есть». Строка — причина, по которой его нет;
    # её показывают в списке ДО клика.
    deep_parse_unavailable = ""

    def __init__(
        self,
        *,
        subject_codes: tuple[str, ...] = SUBJECT_CODES,
        dyn_subject_ids: tuple[str, ...] = MOSCOW_DYN_SUBJECT_IDS,
        discovery_filters: tuple[tuple[str, str, str], ...] = DISCOVERY_FILTERS,
    ) -> None:
        self.subject_codes = subject_codes
        self.dyn_subject_ids = dyn_subject_ids
        self.discovery_filters = discovery_filters
        self.last_report: dict[str, Any] = {"pages": 0, "cards": 0, "kept": 0, "reason": ""}

    @property
    def platform_name(self) -> str:
        return "ГИС Торги (torgi.gov.ru)"

    @staticmethod
    def enabled() -> bool:
        """Включён. Выключается `TORGI_GOV_DISCOVERY=0`.

        Форма ответа и поля карточки сверены живым ответом. Рабочий запрос
        передаёт внутренний id Москвы `dynSubjRF=78`, только активные статусы
        и целевые категории земли/недвижимости. На выходе каждая карточка
        дополнительно проверяется по `subjectRFCode=77`.
        """
        return str(os.getenv(FLAG, "1")).strip().lower() not in ("0", "false", "no", "off")

    def _fetch_page(
        self,
        page: int,
        *,
        filter_spec: tuple[str, str, str] | None = None,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        """Разобранная страница. Адрес собирается там же, где для пробы.

        Второй сборки адреса не заводим: проба и рабочий сбор обязаны ходить
        по одному и тому же URL, иначе сверенное пробой относится не к тому
        запросу, который потом пойдёт в дело.
        """
        _label, cat_code, text = filter_spec or self.discovery_filters[0]
        _status, _ctype, body = self._fetch_raw(
            self._search_url(page, cat_code=cat_code, text=text),
            deadline=deadline,
        )
        return json.loads(body)

    def discover_moscow(self, *, deadline: float | None = None) -> Iterable[AuctionLot]:
        if not self.enabled():
            self.last_report = {"pages": 0, "cards": 0, "kept": 0,
                                "region_filter": "",
                                "reason": f"источник выключен: {FLAG}=0"}
            return []
        fetched_at = datetime.now(timezone.utc).isoformat()
        lots: list[AuctionLot] = []
        cards = pages = unknown_region = 0
        seen: set[str] = set()
        widest_page = 0
        reasons: list[str] = []
        filter_reports: list[dict[str, Any]] = []
        for filter_spec in self.discovery_filters:
            label, _cat_code, _search_text = filter_spec
            previous_keys: list[str] = []
            filter_pages = filter_cards = 0
            filter_total: int | None = None
            filter_reason = ""
            for page in range(MAX_PAGES_PER_FILTER):
                if clock.expired(deadline):
                    filter_reason = "остановлено по времени"
                    break
                try:
                    payload = self._fetch_page(
                        page, filter_spec=filter_spec, deadline=deadline)
                except Exception as exc:  # noqa: BLE001
                    filter_reason = f"страница {page}: {exc}"
                    break
                content = payload.get("content") or []
                page_keys = [_text(card.get("id")) for card in content]
                if content and page_keys == previous_keys:
                    filter_reason = (
                        f"нумерация страниц не двигается: страница {page} "
                        "повторила предыдущую"
                    )
                    break
                previous_keys = page_keys
                pages += 1
                filter_pages += 1
                filter_cards += len(content)
                cards += len(content)
                widest_page = max(widest_page, len(content))
                if filter_total is None and isinstance(payload.get("totalElements"), int):
                    filter_total = payload["totalElements"]
                for card in content:
                    if not _text(card.get("subjectRFCode")):
                        unknown_region += 1
                        continue
                    if not in_target_region(card, self.subject_codes):
                        continue
                    lot = to_lot(card, fetched_at)
                    if lot is None:
                        continue
                    key = str(lot.source.external_lot_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    lots.append(lot)
                if not content:
                    break
                total_pages = payload.get("totalPages")
                if isinstance(total_pages, int) and page + 1 >= total_pages:
                    break
                if payload.get("last") is True:
                    break
            filter_reports.append({
                "filter": label,
                "pages": filter_pages,
                "cards": filter_cards,
                "total_elements": filter_total,
                "reason": filter_reason,
            })
            if filter_reason:
                reasons.append(f"{label}: {filter_reason}")
            if clock.expired(deadline):
                break
        reason = "; ".join(reasons)
        totals = [item["total_elements"] for item in filter_reports
                  if isinstance(item.get("total_elements"), int)]
        if unknown_region:
            # Пропущенное молча читается как отсутствующее. Карточка без кода
            # региона — «не знаем», и сказать это обязаны мы, а не читатель.
            note = f"пропущено без кода региона: {unknown_region}"
            reason = f"{reason}; {note}" if reason else note
        if cards and not lots:
            # Пустой список после полной страницы читался бы как «лотов нет».
            note = (f"из {cards} карточек ни одна не прошла проверку Москвы "
                    "по subjectRFCode=77")
            reason = f"{reason}; {note}" if reason else note
        self.last_report = {"pages": pages, "cards": cards, "kept": len(lots),
                            # Просили 50, приходит 10 — по этому числу видно,
                            # соблюдают ли наш размер, не заглядывая в лог.
                            # Берётся САМАЯ полная страница, а не среднее:
                            # пустая последняя утянула бы среднее вниз, и
                            # соблюдённый размер стал бы неотличим от нет.
                            "cards_per_page": widest_page,
                            # Сохраняем общий счётчик для диагностики и
                            # старых клиентов. Деталь по каждой выборке — в `filters`.
                            "total_elements": sum(totals) if totals else None,
                            "filters": filter_reports,
                            "region_filter": "dynSubjRF=78 (Москва) + проверка "
                                             "официального subjectRFCode=77",
                            # Что источник СОДЕРЖИТ — часть ответа. Живой ответ
                            # подтвердил один код вида торгов, `178FZ`: это
                            # приватизация государственного и муниципального
                            # имущества. Банкротных лотов — 44% рынка владельца
                            # — здесь не найдено, и молчать об этом значит
                            # выдавать один рынок за оба.
                            "market": "приватизация государственного и "
                                      "муниципального имущества (178-ФЗ); "
                                      "банкротные лоты в выдаче не найдены",
                            "reason": reason}
        return lots

    def fetch_lot(self, lot_url: str) -> AuctionLot:
        """Одна карточка ГИС Торгов по её адресу.

        Карточка разбирается тем же `to_lot`, что и выдача поиска: второй
        разбор одного и того же ответа однажды разошёлся бы с первым, и список
        с карточкой показали бы про один лот разное.

        Чего этот метод НЕ знает: адрес одиночной карточки
        (`/new/api/public/lotcards/{id}`) живым ответом не сверен — из
        песочницы torgi.gov.ru не спросить. Поэтому здесь нет ни одного
        молчаливого пропуска: не тот адрес, не тот вид ответа, не та форма
        оболочки — каждая называет, что именно спросили и что пришло. Неверная
        догадка так видна сразу, а не выглядит как «лот пустой».
        """
        lot_id = lot_id_from_url(lot_url)
        if not lot_id:
            raise ValueError(
                f"В адресе «{lot_url}» не видно номера лота ГИС Торгов")
        url = f"https://{HOST}" + LOT_CARD_PATH.format(id=urllib.parse.quote(lot_id))
        status, ctype, body = self._fetch_raw(url)
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise ValueError(
                f"ГИС Торги ответили на {url} не JSON (HTTP {status}, {ctype}): "
                f"{body[:200]}") from exc
        card = lot_card(payload)
        if card is None:
            top = (", ".join(sorted(payload)[:12]) if isinstance(payload, dict)
                   else type(payload).__name__)
            raise ValueError(
                f"В ответе {url} карточки лота нет; верхние ключи: {top}")
        lot = to_lot(card, datetime.now(timezone.utc).isoformat())
        if lot is None:
            raise ValueError(
                f"Карточка {lot_id} пришла без номера или названия — разбирать нечего")
        lot.documents = lot_documents(card)
        lot.raw = dict(card)
        return lot

    def probe(self, page: int = 0) -> dict[str, Any]:
        """Сырой ответ и разобранный лот рядом — для сверки с ядра.

        Проба существует, чтобы ПОКАЗАТЬ ответ, поэтому она ничего не
        обрезает по ключам: поле, которого мы не ждём, — как раз то, ради
        чего сюда идут, и урезанный список выглядел бы полным. Обрезаются
        только длинные значения, имена ключей остаются целиком.

        И она не верит собственным догадкам. Адрес, код ответа и тип
        содержимого печатаются; не-JSON показывается началом тела, а не
        падает невнятной ошибкой разбора; массив лотов ищется по нашему
        предполагаемому ключу, а не нашёлся — берётся первый список словарей,
        и это говорится вслух. Иначе неверная догадка об оболочке читалась бы
        как «лотов нет».
        """
        url = self._search_url(page)
        try:
            status, ctype, body = self._fetch_raw(url)
        except Exception as exc:  # noqa: BLE001
            report = {"ok": False, "url": url, "reason": str(exc),
                      "extra_ca": trust_report()}
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                # Причина без выхода читается как тупик, а выход здесь есть.
                broken = report["extra_ca"]["rejected"]
                report["hint"] = (
                    (f"файл «{broken[0]}» сертификатом не является — его "
                     "содержимое не разобралось; проверьте, что скачался "
                     "сертификат, а не страница. " if broken else "") +
                    "цепочка сертификата не проверяется: нужного корня нет в "
                    f"хранилище. Положите корневой сертификат в «{EXTRA_CA_DIR}» "
                    "рядом с приложением — он будет добавлен к системным. "
                    "Чей это корень, скажет: openssl s_client -connect "
                    "torgi.gov.ru:443 -servername torgi.gov.ru | openssl x509 "
                    "-noout -issuer. Проверку сертификата не отключаем: тогда "
                    "«мы читаем ГИС Торги» перестанет что-либо значить.")
            return report
        try:
            payload = json.loads(body)
        except ValueError as exc:
            return {"ok": False, "url": url, "http_status": status,
                    "content_type": ctype,
                    "reason": f"ответ не JSON: {exc}",
                    "body_head": body[:600]}
        if not isinstance(payload, dict):
            return {"ok": False, "url": url, "http_status": status,
                    "reason": f"ответ не объект, а {type(payload).__name__}",
                    "body_head": body[:600]}

        cards, array_key, envelope_note = _find_cards(payload)
        first = cards[0] if cards else {}
        lot = to_lot(first, datetime.now(timezone.utc).isoformat()) if first else None
        return {
            "ok": True,
            "url": url,
            "http_status": status,
            "content_type": ctype,
            "extra_ca": trust_report(),
            "envelope_keys": sorted(payload),
            "array_key": array_key,
            "envelope_note": envelope_note,
            "on_page": len(cards),
            # Даже при серверном `dynSubjRF` проба показывает фактические
            # `subjectRFCode`: ошибка внутреннего id не должна выглядеть успехом.
            "in_target_region": sum(1 for card in cards if in_target_region(card)),
            "subject_codes_seen": sorted({
                _text(card.get("subjectRFCode")) for card in cards
                if _text(card.get("subjectRFCode"))}),
            "field_counts": _field_counts(cards),
            # Справочники сервиса — списком встреченных значений. Код
            # банкротства мы до сих пор не видели ни разу: три карточки первой
            # выборки были приватизацией. Гадать его больше не надо — он
            # появится здесь сам, как только попадётся в выдаче.
            "codes_seen": _codes_seen(cards),
            "raw_first": {key: _short(value) for key, value in sorted(first.items())},
            "parsed_first": lot.to_dict() if lot is not None else None,
            "parsed_note": None if lot is not None else
                "лот не собрался: обязательного поля нет или оно названо иначе",
        }

    def probe_regions(self, page: int = 0) -> dict[str, Any]:
        """Какое имя параметра действительно фильтрует регион.

        `dynSubjRF` имеет собственные id, не совпадающие с `subjectRFCode`.
        Проба показывает фактические коды в ответе и сравнивает их с контрольным
        запросом без параметра.
        """
        trials: list[dict[str, Any]] = []
        for name in (None,) + REGION_PARAM_CANDIDATES:
            url = self._search_url(page, region_param=name)
            try:
                _status, _ctype, body = self._fetch_raw(url)
                payload = json.loads(body)
            except Exception as exc:  # noqa: BLE001
                trials.append({"param": name or "(без параметра)", "url": url,
                               "reason": str(exc)})
                continue
            cards, _key, _note = _find_cards(payload if isinstance(payload, dict) else {})
            ours = sum(1 for card in cards if in_target_region(card))
            trials.append({
                "param": name or "(без параметра)",
                "on_page": len(cards),
                "in_target_region": ours,
                "subject_codes_seen": sorted({
                    _text(card.get("subjectRFCode")) for card in cards
                    if _text(card.get("subjectRFCode"))}),
                # Фильтр либо отбирает всё, либо не фильтр. «Больше половины» —
                # это совпадение, а не работающий параметр.
                "filters": bool(cards) and ours == len(cards),
            })
        working = [one["param"] for one in trials if one.get("filters")]
        return {
            "ok": True,
            "trials": trials,
            "working": working,
            "note": ("рабочее имя параметра: " + ", ".join(working)) if working else
                    "ни один кандидат не отфильтровал регион — отбираем сами по "
                    "subjectRFCode, как сейчас",
        }

    def _search_url(
        self,
        page: int,
        region_param: str | None = "",
        *,
        cat_code: str = "2",
        text: str = "",
    ) -> str:
        fields: list[tuple[str, Any]] = [
            *(("lotStatus", status) for status in ACTIVE_LOT_STATUSES),
            ("page", page),
            ("size", PAGE_SIZE),
            ("sort", "firstVersionPublicationDate,desc"),
            ("catCode", cat_code),
        ]
        if text:
            fields.append(("text", text))
        # Пустая строка — «как в рабочем сборе», None — «без параметра вовсе».
        name = REGION_PARAM if region_param == "" else region_param
        if name:
            values = self.dyn_subject_ids if name == "dynSubjRF" else self.subject_codes
            fields.extend((name, value) for value in values)
        query = urllib.parse.urlencode(fields)
        return f"https://{HOST}{SEARCH_PATH}?{query}"

    def _fetch_raw(self, url: str, *, deadline: float | None = None) -> tuple[int, str, str]:
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(
                request, timeout=clock.timeout(deadline, TIMEOUT_SECONDS),
                context=trust_context()) as response:
            body = response.read().decode("utf-8", "replace")
            ctype = response.headers.get("Content-Type", "")
            return int(getattr(response, "status", 0) or 0), ctype, body


def _short(value: Any, limit: int = 300) -> Any:
    """Длинное значение — обрезком, но с пометкой. Ключ не трогаем никогда."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"… (ещё {len(value) - limit} симв.)"
    if isinstance(value, list) and len(value) > 5:
        return value[:5] + [f"… (ещё {len(value) - 5} элем.)"]
    return value


def _find_cards(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Массив лотов в ответе: по нашему ключу, а не нашёлся — по форме.

    Возвращает и то, каким путём он найден. Догадка, сработавшая случайно,
    и догадка, подтверждённая ответом, для читателя пробы — разные вещи.
    """
    guess = payload.get("content")
    if isinstance(guess, list) and (not guess or isinstance(guess[0], dict)):
        return [item for item in guess if isinstance(item, dict)], "content", None
    for key, value in payload.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return ([item for item in value if isinstance(item, dict)], key,
                    f"ключа «content» в ответе нет — массив взят из «{key}»")
    return [], None, "массива словарей в ответе не нашлось: оболочка другая"


def _codes_seen(cards: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Встреченные значения справочников с числом карточек у каждого.

    Одно значение — не справочник: пока в выдаче одна приватизация, кажется,
    что других видов торгов не бывает. Счётчик показывает и редкие.
    """
    seen: dict[str, dict[str, int]] = {}
    for card in cards:
        for field in ("biddType", "biddForm", "category", "lotVat"):
            value = card.get(field)
            code = _text(value.get("code") if isinstance(value, dict) else value)
            if not code:
                continue
            bucket = seen.setdefault(field, {})
            bucket[code] = bucket.get(code, 0) + 1
    for field in ("lotStatus", "etpCode", "typeTransaction", "npaHintCode"):
        for card in cards:
            code = _text(card.get(field))
            if not code:
                continue
            bucket = seen.setdefault(field, {})
            bucket[code] = bucket.get(code, 0) + 1
    return {field: dict(sorted(values.items())) for field, values in sorted(seen.items())}


def _field_counts(cards: list[dict[str, Any]]) -> dict[str, int]:
    """Сколько карточек на странице несут каждый ключ.

    По одной карточке необязательное поле неотличимо от отсутствующего:
    ключ, стоящий у трёх лотов из пятидесяти, надо увидеть до того, как
    разбор начнёт считать его обязательным.
    """
    counts: dict[str, int] = {}
    for card in cards:
        for key in card:
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
