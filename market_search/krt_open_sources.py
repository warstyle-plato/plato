"""Что об этой площадке КРТ сказано в открытых источниках.

Проверка на восьми живых проектах решений mos.ru (31.08.2026) показала: в самом
решении об этом не сказано почти ничего. «Реновация» встретилась один раз из
восьми, «оператор», «застройщик», «государственных нужд», «изъятие» и
«победитель» — ноль раз из восьми. Признаки, собранные по решению и карточке,
поэтому и не срабатывали: искать было негде («твой фильтр КРТ не отлавливает ни
операторы, ни городские нужды», владелец, 31.08.2026).

Живут эти факты там, откуда их берёт ручная таблица владельца, — в публикациях
mos.ru и деловой прессы. Разбор написан по НАСТОЯЩИМ фразам оттуда:

    «Оператором выступает компания «КРТ «Магистральные улицы» — группа ЕСН.»
    «В течение семи лет на Молдавской улице назначенный городом оператор
     проведет редевелопмент неэффективно используемой площадки…»
    «Право на редевелопмент участка в центре столицы выставят на торги…»
    «В марте 2026 были объявлены торги на поиск генерального подрядчика.»

Отсюда три разных ответа про оператора, а не один флажок: назван по имени;
назначен, но имя не названо; ещё не выбран — право выставят на торги. Свести их
в «занята / свободна» значит потерять ровно ту разницу, ради которой смотрят.

Ни один признак не ставится без цитаты и ссылки. Сниппет поиска содержит слова
запроса — это уже стоило нам адреса объекта оценки, приписанного каждому
кандидату, — поэтому находка засчитывается, только когда в том же предложении
стоит и признак, и что-то от самой площадки.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

_SPACE = re.compile(r"\s+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[А-Яа-яЁёA-Za-z]{4,}")

# Оператор назван по имени. Ищется в два шага: сперва само слово «оператор»,
# потом имя в его хвосте — одним образцом это не берётся, потому что между
# ними стоит что угодно: «Оператором выступает компания «КРТ …» — группа ЕСН».
_OPERATOR_WORD = re.compile(r"(?iu)\b(?:оператор\w*|застройщик\w*|инвестор\w*)\b")
# Имя — в кавычках или с формой собственности. Без них «оператор проведёт»
# даёт «Проведёт» в качестве имени.
_NAME = re.compile(
    r"(?iu)(?P<name>«[^»]{2,80}»(?:\s*[—-]\s*(?:группа|ГК)\s+[А-ЯЁA-Z][^.,;]{0,40})?"
    r"|(?:ООО|АО|ПАО|ЗАО|ГК|Группа компаний|группа)\s+«?[А-ЯЁA-Z][^.,;]{1,60}?»?)"
    r"(?=[.,;]|$)")

# Оператор есть, но имя не названо: «назначенный городом оператор проведёт…»
_APPOINTED = ("назначенный городом оператор", "определенный городом оператор",
              "определённый городом оператор", "оператор комплексного развития",
              "с оператором заключен", "с оператором заключён")

# Оператора ещё нет: право на реализацию только выставляют.
_TO_BE_CHOSEN = ("выставят на торги", "выставили на торги", "объявлены торги на право",
                 "торги на право реализации", "будет определен по результатам торгов",
                 "будет определён по результатам торгов", "объявлен аукцион на право")

# Городские нужды — то же, что искали в решении, плюс обороты прессы.
# Реновация — это тоже городские нужды (владелец, 31.08.2026): отдельной
# строкой её заводить нельзя, иначе на экране выйдут два ответа на один вопрос.
_CITY_NEEDS = ("реноваци", "фонд реновации", "для нужд города", "государственных нужд",
               "муниципальных нужд", "переселени", "расселение жител",
               "жилой застройки")

# Стадия проекта: не признак, а факт с датой — им объясняется, почему площадка
# ещё «Планируемая», а работа по ней уже идёт.
_STAGE = ("представлена концепция", "утвержден проект планировки",
          "утверждён проект планировки", "заключен договор о комплексном",
          "заключён договор о комплексном", "объявлены торги",
          "получено разрешение на строительство", "начались работы")

_TRUSTED = ("mos.ru", "stroi.mos.ru", "krt.mos.ru", "investmoscow.ru", "torgi.gov.ru")


def queries(name: str, okrug: str = "", district: str = "") -> list[str]:
    """Запросы к поиску. Имя площадки — это её адрес, и он же якорь находки."""
    base = _SPACE.sub(" ", str(name or "")).strip()
    if not base:
        return []
    where = " ".join(part for part in (district, okrug) if part)
    out = [f'КРТ "{base}" оператор', f'"{base}" комплексное развитие территории Москва']
    if where:
        out.append(f'"{base}" {where} КРТ застройщик')
    return out[:3]


def _anchor_words(name: str) -> set[str]:
    """Основы слов площадки: «Молдавская» и «на Молдавской улице» — одно место.

    Сравнивать словоформы целиком нельзя: русский падеж рассыпает совпадение, и
    якорь не срабатывает ровно там, где публикация написана живым языком.
    """
    flat = str(name or "").lower().replace("ё", "е")
    stop = {"улица", "улице", "улиц", "проезд", "проезде", "переулок", "владение",
            "москва", "территория", "территории", "проект", "участок", "участка",
            "город", "тер", "влд"}
    return {word[:6] for word in _WORD.findall(flat) if word not in stop}


def _mentions(sentence: str, anchors: set[str]) -> bool:
    if not anchors:
        return True
    words = _WORD.findall(sentence.lower().replace("ё", "е"))
    return any(word.startswith(stem) for word in words for stem in anchors)


# Имя проекта рынком известно раньше адреса: «Строгино 360» знают все, а
# «Маршала Воробьева ул., вл. 12» — никто. Статья про бренд к площадке не
# привязывалась вовсе: якорем служит адрес, и это дыра, а не осторожность
# (владелец, 01.09.2026: «по улице Маршала Воробьева 12 не показывает, что оно
# обещано кому-то, а там же Строгино 360 и это ПИК»).
#
# Бренд берётся только доказанный: он обязан стоять в ОДНОМ предложении с
# адресом площадки. Иначе повторится ошибка модуля рынка, где сниппет,
# повторяющий запрос, отдавал каждому кандидату адрес объекта оценки.
_BRAND = re.compile(
    r"(?:ЖК|жилой комплекс|жилого комплекса|проект|проекта|квартал)\s+"
    r"[«\"]([^«»\"]{3,40})[»\"]"
    r"|[«\"]([А-ЯЁA-Z][^«»\"]{2,39})[»\"]")
# Слова, которые в кавычках стоят, но именем проекта не являются.
_NOT_BRAND = {"крт", "комплексное развитие территории", "реновация", "москва",
              "планируемый", "в реализации", "проект решения"}


def brand_names(docs: Iterable[Any], name: str) -> list[str]:
    """Как площадка называется на рынке — по соседству с её адресом.

    Пусто — значит пусто: имя, взятое из предложения без адреса, привязало бы
    к площадке чужой проект.
    """
    anchors = _anchor_words(name)
    found: list[str] = []
    for doc in docs or []:
        text = f"{getattr(doc, 'title', '')}. {getattr(doc, 'snippet', '')}"
        for sentence in _sentences(text):
            if not _mentions(sentence, anchors):
                continue
            for match in _BRAND.finditer(sentence):
                brand = (match.group(1) or match.group(2) or "").strip()
                low = brand.lower().replace("ё", "е")
                if not brand or low in _NOT_BRAND:
                    continue
                # Имя, состоящее из слов самого адреса, вторым якорем не
                # является: оно ничего не добавляет.
                if _mentions(brand, anchors):
                    continue
                if brand not in found:
                    found.append(brand)
    return found[:3]


# Сокращения, после которых точка — не конец фразы. Адрес площадки сам состоит
# из них: «Маршала Воробьева ул., вл. 12» разваливалось пополам, адрес уезжал в
# одно предложение, признак — в другое, и правило «в одном предложении» молча
# теряло настоящую находку на КАЖДОМ адресе с «вл.» (владелец, 01.09.2026).
_ABBR = {"вл", "влд", "д", "дом", "стр", "корп", "к", "тер", "кв", "ул", "просп",
         "пр", "пер", "наб", "ш", "г", "гг", "руб", "тыс", "млн", "млрд", "им",
         "обл", "мкр", "п", "с", "им", "т", "ок", "прим", "рис", "см"}
_TAIL_WORD = re.compile(r"([А-Яа-яЁёA-Za-z]+)\.$")


def _sentences(text: str) -> list[str]:
    flat = _SPACE.sub(" ", str(text or "")).strip()
    parts = [part.strip() for part in _SENTENCE.split(flat) if part.strip()]
    out: list[str] = []
    for part in parts:
        if out:
            tail = _TAIL_WORD.search(out[-1])
            short = tail and tail.group(1).lower().replace("ё", "е") in _ABBR
            # Точка после сокращения или перед числом фразу не кончает:
            # «вл. 12», «д. 5 стр. 2», «тыс. кв. м».
            if short or part[:1].isdigit():
                out[-1] = out[-1] + " " + part
                continue
        out.append(part)
    return out


def _operator_name(sentence: str) -> str:
    """Имя оператора в хвосте слова «оператор». Нет имени — пустая строка."""
    word = _OPERATOR_WORD.search(sentence)
    if not word:
        return ""
    tail = sentence[word.end():word.end() + 140]
    found = _NAME.search(tail)
    if not found:
        return ""
    return _SPACE.sub(" ", found.group("name")).strip(" «»")


def _found(sentence: str, doc: Any) -> dict[str, Any]:
    return {
        "quote": sentence[:400],
        "url": getattr(doc, "url", "") or "",
        "domain": getattr(doc, "domain", "") or "",
        "official": any(host in (getattr(doc, "domain", "") or "") for host in _TRUSTED),
    }


def read_findings(docs: Iterable[Any], name: str) -> dict[str, Any]:
    """Разобрать выдачу по одной площадке. Без цитаты признак не ставится."""
    anchors = set(_anchor_words(name))
    # Бренд площадки, если он доказан соседством с адресом, работает якорем
    # наравне с адресом: статья, где сказано только «Строгино 360», иначе
    # проходит мимо.
    docs = list(docs or [])
    brands = brand_names(docs, name)
    for brand in brands:
        anchors |= _anchor_words(brand)
    operator_named: list[dict[str, Any]] = []
    operator_appointed: list[dict[str, Any]] = []
    operator_pending: list[dict[str, Any]] = []
    city_needs: list[dict[str, Any]] = []
    stage: list[dict[str, Any]] = []
    seen: set[str] = set()
    checked = 0
    for doc in docs or []:
        checked += 1
        text = f"{getattr(doc, 'title', '')}. {getattr(doc, 'snippet', '')}"
        for sentence in _sentences(text):
            low = sentence.lower().replace("ё", "е")
            # Якорь площадки в ТОМ ЖЕ предложении: сниппет повторяет запрос, и
            # без якоря сюда попадает любой соседний проект.
            if not _mentions(sentence, anchors):
                continue
            key = low[:120]
            if key in seen:
                continue
            seen.add(key)
            named = _operator_name(sentence)
            if named:
                item = _found(sentence, doc)
                item["name"] = named
                operator_named.append(item)
            elif any(mark in low for mark in _APPOINTED):
                operator_appointed.append(_found(sentence, doc))
            elif any(mark in low for mark in _TO_BE_CHOSEN):
                operator_pending.append(_found(sentence, doc))
            if any(mark in low for mark in _CITY_NEEDS):
                city_needs.append(_found(sentence, doc))
            if any(mark in low for mark in _STAGE):
                stage.append(_found(sentence, doc))
    # «Оператор назван» и «оператор назначен» — разные ответы, и второй не
    # отменяется первым: имя может быть в одной публикации, а факт назначения в
    # другой. Пустой список значит «не нашли», а не «нет».
    return {
        "checked": checked,
        "operator_named": operator_named[:3],
        "operator_appointed": operator_appointed[:3],
        "operator_pending": operator_pending[:3],
        "city_needs": city_needs[:3],
        "stage": stage[:4],
        # Как площадка известна рынку: имя проекта, доказанное соседством с
        # адресом. По нему идёт второй круг поиска — статья про бренд адреса
        # чаще всего не называет.
        "brands": brands,
        "taken": bool(operator_named or operator_appointed),
        "free": bool(operator_pending) and not (operator_named or operator_appointed),
    }
