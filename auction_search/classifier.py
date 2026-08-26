from __future__ import annotations

import re

from auction_search.models import LotKind, LotOrigin


# Russian auction wording is highly inflected. Match stems, not a handful of
# nominative/genitive phrases: "о комплексном развитии территории" and
# "договора аренды" are the normal forms on ETP cards.
_KRT_RE = re.compile(r"(?:\bкрт\b|комплексн\w*\s+развити\w*\s+территор\w*)", re.I)
_LEASE_RE = re.compile(r"аренд\w*", re.I)
_PROPERTY_RE = re.compile(r"(?:имущественн\w*\s+комплекс\w*|\bзик\b|здани\w*\s+и\s+земельн\w*\s+участ\w*)", re.I)
_EQUITY_RE = re.compile(
    r"(?:100\s*(?:\([^)]*\)\s*)?%\s*(?:дол\w*|уставн\w*\s+капитал\w*)|"
    r"дол\w*\s+(?:в\s+размере\s+)?100\s*(?:\([^)]*\)\s*)?%|"
    r"дол\w*\s+(?:в\s+)?уставн\w*\s+капитал\w*)",
    re.I,
)
_DEVELOPMENT_ASSET_RE = re.compile(
    r"(?:девелоп\w*|застрой\w*|жил\w*\s+комплекс\w*|проект\w*\s+(?:строительств\w*|комплекс\w*)|"
    r"гпзу|рнс|земельн\w*\s+участ\w*|недвижим\w*|здани\w*)",
    re.I,
)
_UNFINISHED_RE = re.compile(r"(?:объект\w*\s+незавершенн\w*\s+строительств\w*|незавершенн\w*)", re.I)
_LAND_RE = re.compile(r"(?:земельн\w*|участ\w*)", re.I)


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
    if _PROPERTY_RE.search(compact) or (_EQUITY_RE.search(compact) and _DEVELOPMENT_ASSET_RE.search(compact)):
        return LotKind.PROPERTY_COMPLEX
    if _LEASE_RE.search(compact):
        return LotKind.LAND_LEASE
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
