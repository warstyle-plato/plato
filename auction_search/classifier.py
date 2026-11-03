from __future__ import annotations

import re

from auction_search.models import LotKind, LotOrigin


# Russian auction wording is highly inflected. Match stems, not a handful of
# nominative/genitive phrases: "о комплексном развитии территории" and
# "договора аренды" are the normal forms on ETP cards.
_KRT_RE = re.compile(r"(?:\bкрт\b|комплексн\w*\s+развити\w*\s+территор\w*)", re.I)
_LEASE_RE = re.compile(r"аренд\w*", re.I)
_PROPERTY_RE = re.compile(r"(?:имущественн\w*\s+комплекс\w*|\bзик\b|здани\w*\s+и\s+земельн\w*\s+участ\w*)", re.I)
# Доля в обществе. Правило одно на модуль — им же пользуется `equity_stake`,
# иначе один и тот же лот у списка и у разбора окажется разного вида.
_EQUITY_RE = re.compile(
    r"(?:100\s*(?:\([^)]*\)\s*)?%\s*(?:дол\w*|уставн\w*\s+капитал\w*)|"
    r"дол\w*\s+(?:в\s+размере\s+)?\d{1,3}(?:[.,]\d+)?\s*(?:\([^)]*\)\s*)?%|"
    r"дол\w*\s+(?:в\s+)?уставн\w*\s+капитал\w*|"
    r"дол\w*\s+юрлиц\w*|дол\w*\s+юридическ\w*\s+лиц\w*|"
    r"пакет\w*\s+акци\w*)",
    re.I,
)
_DEVELOPMENT_ASSET_RE = re.compile(
    r"(?:девелоп\w*|застрой\w*|жил\w*\s+комплекс\w*|проект\w*\s+(?:строительств\w*|комплекс\w*)|"
    r"гпзу|рнс|земельн\w*\s+участ\w*|недвижим\w*|здани\w*)",
    re.I,
)
_UNFINISHED_RE = re.compile(r"(?:объект\w*\s+незавершенн\w*\s+строительств\w*|незавершенн\w*)", re.I)
_LAND_RE = re.compile(r"(?:земельн\w*|участ\w*)", re.I)
# Продажа в собственность, названная самим лотом. Нужна, чтобы общая рубрика
# процедуры («Аренда и продажа земельных участков») не делала арендой лот,
# который в своём названии назван продажей.
_SALE_RE = re.compile(r"(?:продаж\w*|купл\w*|в\s+собственност\w*)", re.I)
# Аренда — когда её ПРАВО и есть предмет лота: «право (заключения договора)
# аренды…», «Аренда нежилого помещения…». Обременение предметом не является:
# «Имеется аренда», «помещение сдано в аренду», «ограничения прав (…, аренда)»
# у ЕФРСБ превращали проданное помещение в аренду земли.
_LEASE_RIGHT_RE = re.compile(
    r"прав\w*\s+(?:на\s+)?(?:заключени\w*\s+)?(?:договор\w*\s+(?:\([^)]*\)\s+)?)?аренд\w*", re.I)
_LEASE_HEAD_RE = re.compile(r"^\W*аренд\w*", re.I)
# Масштабный инвестиционный проект: участок под него город даёт в аренду без
# торгов, продажи земли здесь нет.
_MAIP_RE = re.compile(r"масштабн\w*\s+инвестиционн\w*\s+проект\w*", re.I)
# Аренда именно ЗЕМЕЛЬНОГО УЧАСТКА, а не любое слово «земельный» рядом.
_LAND_LEASE_RE = re.compile(
    r"(?:аренд\w*\s+(?:\S+\s+){0,2}?(?:земельн\w*\s+участ\w*|земл\w*)|"
    r"масштабн\w*\s+инвестиционн\w*\s+проект\w*)", re.I)
# Строение как ОТДЕЛЬНЫЙ предмет перечня: «…: Здание, …», «1) Нежилое
# помещение…». Упоминание здания внутри описания участка («для эксплуатации
# здания») предметом не является.
_BUILDING_ITEM_RE = re.compile(
    r"(?:^|[:;]|\d\))\s*-?\s*(?:(?:не)?жил\w*\s+)?(?:здани\w*|помещени\w*|сооружени\w*)", re.I)
# Лот — помещение или его часть: участок под домом арендатору или покупателю
# комнаты не переходит.
_PREMISES_HEAD_RE = re.compile(r"^\W*(?:(?:не)?жил\w*\s+)?(?:част\w*\s+)?помещени\w*", re.I)
_LAND_PARCEL_RE = re.compile(r"земельн\w*\s+участ\w*", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def names_lease(title: str, *context: str) -> bool:
    """Лот продаёт право аренды (или МаИП), а не саму вещь.

    Решает название лота: «право заключения договора аренды…» — аренда,
    «Продажа земельного участка…» — продажа, что бы ни писала рубрика
    процедуры. Только когда название молчит, решает остальной текст
    (описание, документы) — и тоже по праву аренды, а не по слову. Предикат
    один на все площадки, иначе один и тот же лот у двух площадок окажется
    разного вида.
    """
    name = _norm(title)
    if _LEASE_RIGHT_RE.search(name) or _LEASE_HEAD_RE.search(name) or _MAIP_RE.search(name):
        return True
    if _SALE_RE.search(name):
        return False
    return any(_LEASE_RIGHT_RE.search(_norm(text)) for text in context)


def lease_kind(text: str, *, land: bool = False) -> LotKind:
    """Вид лота, предмет которого — право аренды.

    Аренда земельного участка (и МаИП) — `LAND_LEASE`; та же аренда участка
    вместе с проданными зданиями или помещениями — имущественный комплекс;
    аренда помещения или имущества — `OTHER`: это не земля и не ЗИК, своего
    вида у неё нет, и подгонять её под ближайший нельзя.
    """
    name = _norm(text)
    if land or _LAND_LEASE_RE.search(name):
        return LotKind.PROPERTY_COMPLEX if _BUILDING_ITEM_RE.search(name) else LotKind.LAND_LEASE
    return LotKind.OTHER


def land_in_deal(kind: LotKind | str, title: str) -> bool:
    """Участок (или право на него) — предмет лота.

    Фильтр «участок от N га» осмыслен только для таких лотов. У аренды
    помещения и у продажи помещения площадь участка под домом — справка о
    здании, а не то, что получает победитель торгов.
    """
    value = kind.value if isinstance(kind, LotKind) else str(kind or "")
    if value in {LotKind.LAND_SALE.value, LotKind.LAND_LEASE.value, LotKind.KRT.value}:
        return True
    if value not in {LotKind.PROPERTY_COMPLEX.value, LotKind.UNFINISHED.value}:
        return False
    name = _norm(title)
    if names_lease(name) and not _LAND_LEASE_RE.search(name):
        return False
    if _PREMISES_HEAD_RE.search(name):
        return bool(_LAND_LEASE_RE.search(name) or _LAND_PARCEL_RE.search(name))
    return True


def classify_lot(title: str, procedure_text: str = "", document_titles: list[str] | None = None) -> LotKind:
    """Classify the legal/economic nature of a lot before financial modeling.

    Priority is legal structure, not the presence of the word "land". Thus a
    KRT right containing cadastral parcels remains KRT, and a lease remains a
    lease even when the title says "земельный участок".
    """
    haystack = " ".join([title or "", procedure_text or "", " ".join(document_titles or [])]).lower()
    compact = re.sub(r"\s+", " ", haystack)
    if _KRT_RE.search(compact):
        return LotKind.KRT
    if _UNFINISHED_RE.search(compact):
        return LotKind.UNFINISHED
    # Доля в обществе — свой вид, и признак развития для неё не условие.
    # Прежде «доля + слово про стройку» становилась имущественным комплексом, а
    # доля без таких слов уходила в «прочее»: отсутствие описания активов
    # читалось как их отсутствие. Что стоит за долей, отвечает `equity_stake`,
    # и «активы не описаны» там значит «не знаем» (владелец, 01.09.2026).
    if _EQUITY_RE.search(compact):
        return LotKind.EQUITY_STAKE
    if _PROPERTY_RE.search(compact):
        return LotKind.PROPERTY_COMPLEX
    if names_lease(title, procedure_text, *(document_titles or [])):
        return lease_kind(compact)
    if _LAND_RE.search(compact):
        return LotKind.LAND_SALE
    return LotKind.OTHER


# Слова, по которым банкротное происхождение опознаётся. Здесь только
# ДОКАЗАТЕЛЬНЫЕ: «конкурсное производство» — процедура банкротства, а голое
# «конкурсн» ловит «конкурсную документацию» и «конкурсную комиссию» обычных
# городских торгов. «Должник» тоже убран: имущество должника продают и приставы
# вне дела о банкротстве, а третьего значения у нас нет — лучше OTHER, чем
# уверенно неверная метка. Список объявлен ЗДЕСЬ, а не в адаптере ГИС Торгов,
# откуда он родом: правило «это банкротный лот» одно на модуль, иначе один и
# тот же лот с двух площадок попадёт в разные рынки.
BANKRUPTCY_WORDS = (
    "банкрот", "несостоятельн", "конкурсное производство",
    "агентство по страхованию вкладов",
)

# Инфлектированное ловится основой, а не перечислением падежей: на карточках
# стоит и «конкурсный управляющий», и «конкурсного управляющего».
_BANKRUPTCY_RE = re.compile(r"конкурсн\w*\s+управляющ\w*", re.I)

# Продавец города. Ищется ТОЛЬКО в продавце: организатор торгов ничего не
# доказывает — РАД проводит и городские торги, и реализацию имущества
# финансовых организаций, и это ровно та ошибка, ради которой всё написано.
CITY_SELLER_WORDS = (
    "департамент городского имущества", "департамент имуществ",
    "комитет по управлению имуществ", "министерство имуществ",
    "фонд имуществ", "агентство по управлению имуществ",
    "администрация", "мэрия", "правительство москвы", "город москва",
    "городской округ", "муниципальн",
)


# Арест и исполнительное производство. Доказательные слова, а не форма
# процедуры: судебный пристав продаёт и по аресту, и по исполнительному
# производству, и оба конвертируются почти в ноль.
SEIZED_WORDS = (
    # Основа, а не падеж: на карточках стоит и «судебных приставов», и
    # «судебным приставом-исполнителем» — та же причина, по которой
    # «конкурсный управляющий» ловится основой.
    "арестованн", "пристав", "фссп", "исполнительн",
    "росимущество", "реализация арестованного",
)


def origin_from_evidence(
    *,
    seller: str | None = None,
    organizer: str | None = None,
    procedure_type: str | None = None,
    text: str | None = None,
    known: LotOrigin | None = None,
) -> LotOrigin:
    """Кто продаёт — по тому, что известно, а не по площадке.

    Умолчания здесь нет намеренно. Прежде три наших источника ставили лоту
    `CITY` просто потому, что заводились под городские торги, — и лот РАД, где
    продавец банк, а процедура «публичное предложение», приезжал в список
    городским. Умолчание оказалось не умолчанием, а утверждением: на экране
    оно неотличимо от опознанного, и человек сравнивает городскую цену с
    банкротной, не зная об этом.

    Порядок доказательств: банкротство сильнее города (продавать имущество
    банкрота может и государственное учреждение), а неопознанное остаётся
    `OTHER` — «мы не знаем», а не «городское».

    Форма процедуры происхождения НЕ решает: публичное предложение бывает и у
    приватизации по 178-ФЗ, и у банкротства. Она входит в текст как слова, но
    сама по себе ничего не значит.
    """
    if known is not None and known is not LotOrigin.OTHER:
        return known
    everything = " ".join(
        value for value in (seller, organizer, procedure_type, text) if value
    ).lower().replace("ё", "е")
    if _BANKRUPTCY_RE.search(everything) \
            or any(word.replace("ё", "е") in everything for word in BANKRUPTCY_WORDS):
        return LotOrigin.BANKRUPTCY
    # Арест сильнее города: имущество, арестованное приставами, продаёт
    # государственный орган, и по продавцу он неотличим от городского.
    if any(word in everything for word in SEIZED_WORDS):
        return LotOrigin.SEIZED
    seller_text = (seller or "").lower().replace("ё", "е")
    if seller_text and any(word in seller_text for word in CITY_SELLER_WORDS):
        return LotOrigin.CITY
    return LotOrigin.OTHER
