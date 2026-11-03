from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional


_CAD_RE = re.compile(r"\b\d{2}:\d{2}:\d{6,7}:\d+\b")
_MONEY_RE = re.compile(r"([\d\s\u00a0]+(?:[.,]\d+)?)\s*(?:₽|руб(?:\.|лей)?)", re.I)
_AREA_RE = re.compile(r"([\d\s\u00a0]+(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м2|м²)", re.I)
# Гектары в извещениях города — обычная мера: «площадью 14,62 га». Пока их не
# читали, у площадки метров не было вовсе, а «метров нет» и «метров мало» —
# разные ответы: допуск подборки требует площадь, и лот выпадал молча.
_HECTARE_RE = re.compile(r"(?<![\d.,])(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*(?:га\b|гектар\w*)", re.I)

# Москва склоняется, и наш отбор об этом не знал. «города Москвы» в заголовке
# аукциона КРТ не проходило ни одну из проверок: `\bмосква\b` требует
# именительного падежа, а `город\s*москва` — пробела там, где стоит «города».
# Живой лот владельца (01.09.2026) — «...нежилой застройки города Москвы,
# площадью 14,62 га» — по этой причине выбрасывался как немосковский.
#
# Область вычитается ДО поиска города: «Московская область» содержит корень,
# но городом не является. Слово ищется целиком (`\b`), иначе Новомосковск
# станет Москвой.
_MOSCOW_OBLAST_RE = re.compile(r"московск\w*\s+обл\w*", re.I)
_MOSCOW_RE = re.compile(r"\bмоскв(?:а|ы|е|у|ой|ою)\b", re.I)


def normalize_space(value: str | None) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def parse_decimal(value: str | None) -> Optional[float]:
    if not value:
        return None
    cleaned = normalize_space(value).replace(" ", "").replace(",", ".")
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def parse_money(value: str | None) -> Optional[float]:
    if not value:
        return None
    match = _MONEY_RE.search(value)
    return parse_decimal(match.group(1)) if match else parse_decimal(value)


def parse_area_sqm(value: str | None) -> Optional[float]:
    if not value:
        return None
    match = _AREA_RE.search(value)
    return parse_decimal(match.group(1)) if match else parse_decimal(value)


def parse_hectares_sqm(value: str | None) -> Optional[float]:
    """Площадь, названная в гектарах, — в квадратных метрах. Нет гектаров — None."""
    if not value:
        return None
    match = _HECTARE_RE.search(value)
    if not match:
        return None
    hectares = parse_decimal(match.group(1))
    return None if hectares is None else hectares * 10_000


def mentions_moscow(*values: str | None) -> bool:
    """Сказано ли здесь про Москву — в любом падеже и не про область.

    Объявлено один раз: тремя копиями в читателях площадок это правило
    расходилось молча, и две из трёх искали подстроку «москва», то есть
    «Москвы» и «Москве» не узнавали тоже.

    Какие поля сюда подать, решает читатель: на странице площадки в подвале
    стоит её собственный московский адрес, и вся страница целиком ответила бы
    «Москва» про любой лот.
    """
    text = " ".join(str(value or "") for value in values).lower()
    return bool(_MOSCOW_RE.search(_MOSCOW_OBLAST_RE.sub(" ", text)))


def cadastral_numbers(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted(set(_CAD_RE.findall(value)))


def value_after_label(text: str, label: str, *, stop_labels: tuple[str, ...] = ()) -> Optional[str]:
    """Extract text following a visible platform label from normalized page text."""
    normalized = normalize_space(text)
    low = normalized.lower()
    marker = label.lower()
    idx = low.find(marker)
    if idx < 0:
        return None
    start = idx + len(marker)
    end = len(normalized)
    tail_low = low[start:]
    for stop in stop_labels:
        stop_idx = tail_low.find(stop.lower())
        if stop_idx >= 0:
            end = min(end, start + stop_idx)
    return normalized[start:end].strip(" :-") or None


# Срок подачи заявки разбирается ОДИН раз и здесь.
#
# 08.09.2026 владелец прислал два экрана: на Росэлторге по лоту «Рубцовская
# наб., влд. 3» стоит «Окончание приёма заявок 09.10.26 15:00», а у нас —
# «10.09.26, 15:00» и снятие балла «до конца приёма заявок 2 дн.». На айфоне
# при этом дата была верная. Сервер тут ни при чём: он хранит ровно строку
# площадки, `'09.10.26 15:00'`. Считал её БРАУЗЕР — `new Date('09.10.26 15:00')`
# в V8 читает первое число месяцем и даёт 10 сентября; Safari на ту же строку
# отвечает Invalid Date, и страница печатала её как есть — то есть верным
# оказывался запасной путь, а не основной.
#
# Цена была не в подписи. `02.10.26 15:00` тот же разбор уводит в 10 февраля —
# в ПРОШЛОЕ: балл снимается на 60% «срок подачи заявки истёк», а `krtLiveLot`
# перестаёт считать лот живым, и с площадки исчезает плашка «идут торги».
# Дни с 13-го по 31-е при этом не читаются вовсе и потому показываются верно:
# ошибка выборочна ровно настолько, чтобы не выглядеть ошибкой.
#
# Поэтому порядок дня и месяца больше нигде не угадывается: момент считает
# сервер и отдаёт его отдельным полем в ISO, а строку площадки поверхности
# печатают как написано. Американский порядок здесь не принимается никогда —
# у «09.10» два прочтения, различающиеся на месяц, и одно из них неверно.
_MOSCOW_TZ = ZoneInfo("Europe/Moscow")
_DEADLINE_WITH_TIME = (
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
    "%d.%m.%y %H:%M:%S", "%d.%m.%y %H:%M",
)
_DEADLINE_DAY_ONLY = ("%d.%m.%Y", "%d.%m.%y")


def deadline_moment(raw: str | None) -> Optional[datetime]:
    """Момент окончания приёма заявок из того, что записала площадка.

    Понимает и ISO (так пишут РАД и ГИС Торги), и русскую запись дня
    (Росэлторг, ИнвестМосква). Час назван не всегда: «заявки до 21.09.26» —
    это «до конца того дня», а не «в полночь того дня», иначе живой лот
    выбрасывается как просроченный.
    """
    if not raw:
        return None
    text = normalize_space(str(raw))
    try:
        moment = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        moment = None
    if moment is not None and ":" not in text:
        # День без часа кончается вместе с днём — хоть «21.09.26», хоть
        # «2026-09-21»: запись разная, ответ один, иначе живой лот с утра
        # объявлен просроченным.
        moment = moment.replace(hour=23, minute=59, second=59)
    if moment is None:
        for fmt in _DEADLINE_WITH_TIME:
            try:
                moment = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if moment is None:
        for fmt in _DEADLINE_DAY_ONLY:
            try:
                moment = datetime.strptime(text, fmt).replace(
                    hour=23, minute=59, second=59)
                break
            except ValueError:
                continue
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_MOSCOW_TZ)
    return moment


def deadline_iso(raw: str | None) -> Optional[str]:
    """Тот же момент строкой ISO — её браузеру разбирать нечем ошибиться."""
    moment = deadline_moment(raw)
    return moment.isoformat() if moment is not None else None


def deadline_is_current(raw: str | None, *, now: datetime | None = None) -> bool:
    """Срок ещё не прошёл. Неразобранный срок — это «не знаем», а не «прошёл»."""
    moment = deadline_moment(raw)
    if moment is None:
        return False
    return moment >= (now or datetime.now(_MOSCOW_TZ))


def stamp_day(raw: object) -> str:
    """День городской отметки времени — по Москве и числами.

    Отметка приезжает секундами эпохи, и печаталась она как есть: в сообщении
    бота стояло «решение от 1688749200» (экран владельца, 09.09.2026). Число
    вместо даты — половина беды; вторая в том, что по одному адресу у города
    бывает несколько решений разных лет, и в списке «2-й Тушинский пр-д, вл. 12»
    стоял трижды подряд. Различала эти три строки ровно отметка, которую
    прочитать было нельзя.

    Зона — часть величины: отметку ставит город, и день у неё московский. Без
    пришпиленной зоны решение, опубликованное поздним вечером, у читателя
    западнее съезжает на сутки назад. Это про отметку ГОРОДА; наши собственные
    мгновения (возраст снимка, «спрошено») остаются в зоне зрителя.

    Числами, а не словами: в списке из двенадцати строк «07.07.2023» короче
    «7 июля 2023» и не заводит третьего списка названий месяцев. Год полный —
    у двузначного прочтений два.
    """
    text = normalize_space(str(raw) if raw is not None else "")
    if not text:
        return ""
    try:
        seconds = int(float(text))
    except (TypeError, ValueError):
        seconds = 0
    if seconds > 0:
        try:
            return datetime.fromtimestamp(seconds, _MOSCOW_TZ).strftime("%d.%m.%Y")
        except (OverflowError, OSError, ValueError):
            return ""
    # Записью ISO эта отметка не приходит ни от одного нынешнего источника
    # (`KrtDecision.published_at` — секунды), но читается и она: молча
    # выброшенная дата неотличима от даты, которой у документа нет.
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone(_MOSCOW_TZ)
    return moment.strftime("%d.%m.%Y")


def deadline_label(raw: str | None) -> str:
    """Срок заявки строкой — тем же разбором, каким считается сам срок.

    Резать сырую строку по длине нельзя: «09.10.26 15:00»[:10] даёт
    «09.10.26 1» — обрубок часа, читаемый как часть даты. Разбор у срока один
    (`deadline_moment`), поверхность его только печатает; неразобранное
    печатается как написано — придумывать за площадку нечего.

    Час печатается, только когда его назвала сама площадка: у дня без часа
    момент поставлен на конец дня, и «23:59 МСК» выдавало бы наше допущение за
    объявленное время.
    """
    moment = deadline_moment(raw)
    if moment is None:
        return normalize_space(raw if isinstance(raw, str) else "")
    moment = moment.astimezone(_MOSCOW_TZ)
    if ":" not in normalize_space(str(raw)):
        return moment.strftime("%d.%m.%Y")
    return moment.strftime("%d.%m.%Y, %H:%M") + " МСК"
