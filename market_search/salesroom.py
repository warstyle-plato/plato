"""Чат отдела продаж: встречи, брони и то, что говорят покупатели.

Владелец, 01.09.2026: «в отчёт продаж надо визуализацию и разбор аналитики от
Платона; какие новые выводы по тому, что реально говорили и говорят покупатели,
возможно в динамике, и какая воронка от встреч».

Источник — экспорт Telegram-чата, где менеджеры каждый день пишут отчёт:
эскроу, сделки на регистрации, текущие брони, встречи в офисе, целевые звонки
и описание визита. До сих пор свод продаж начинался с подписанного договора и
дотягивался вверх до обращения из CRM; выше обращения не было ничего, а именно
там слышно, чего человек хотел и почему не купил.

Три правила, из которых собран разбор.

**Меряется отчёт менеджера, а не разговор.** Это пересказ, и отсутствие
площади в нём значит «не записали», а не «не спрашивали». Так же мы уже читаем
комментарии CRM, и оговорка стоит рядом с числами.

**Одна бронь, повторённая в тридцати ежедневных сводках, — одна бронь.**
Отчёты повторяют состояние: лот 34 м² по 920 000 ₽/м² стоит в каждом дне,
пока держится. Счёт по упоминаниям дал бы тридцатикратный объём, и выглядел
бы он правдоподобно.

**Наполнение эскроу отсюда не берём** (решение владельца, 01.09.2026): деньги
считаются по проводкам 1С и книге, а ряд из чата был бы четвёртым источником
одной величины. Он читается только затем, чтобы не спутать его с ценой лота.
"""

from __future__ import annotations

import html
import re
import statistics
from collections import Counter
from typing import Any

# Экспорт Telegram: сообщение — блок `message default`, внутри имя, дата и текст.
_MESSAGE = re.compile(r'<div class="message default[^"]*"[^>]*>(.*?)(?=<div class="message |\Z)', re.S)
_AUTHOR = re.compile(r'<div class="from_name">\s*(.*?)\s*<', re.S)
_WHEN = re.compile(r'<div class="pull_right date details" title="([^"]+)"')
_TEXT = re.compile(r'<div class="text">(.*?)</div>', re.S)
_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")

# Строки ежедневного отчёта. Числа берутся по подписи, а не по порядку: формат
# отчёта у менеджеров плавает, а подписи держатся.
_COUNTS = {
    "meetings": r"встреч[а-яё]*\s*в\s*офисе\s*[-–—:]?\s*(\d+)",
    "calls": r"целевых\s*звонк[а-яё]*\s*[-–—:]?\s*(\d+)",
    "bookings": r"текущих\s*брон[а-яё]*[^\d]{0,20}(\d+)",
    "registering": r"сделк[аи]\s*на\s*регистрации\s*[-–—:]?\s*(\d+)",
}

# Цена лота в брони: «площадь 34 кв.м., 920 000 руб.за кв.м.» и «694 000 за
# кв.м. за 3К (37 метров)» — формулировка у каждого своя, число одно.
_PER_SQM = re.compile(r"(?<![\d.,])(\d{3}[\s ]?\d{3})\s*(?:руб\.?\s*)?за\s*кв\.?\s*м", re.I)
_AREA = re.compile(r"(?<![\d.,])(\d{2,3}(?:[.,]\d)?)\s*(?:кв\.?\s*м|м2|м²|метр)", re.I)

# О чём говорят. Слова — из самого чата, а не из головы: каждая строка
# проверена на живом экспорте 01.09.2026.
TOPICS: tuple[tuple[str, str], ...] = (
    ("рассрочка", r"рассрочк|беспроцентн|первоначальн|\bпв\b|транш"),
    ("ипотека", r"ипотек|семейн[ао][йя]|it-ипотек|господдержк|одобрен[ио]"),
    ("площадь и планировка", r"планировк|метраж|площад|кв\.?\s?м|евродв|евротр|кухня-гостин"),
    ("студии и однушки", r"студи|однушк|\b1-?к\b"),
    ("двушки и больше", r"двушк|\b2-?к\b|тр[её]шк|\b3-?к\b|четыр[её]х"),
    ("паркинг и кладовые", r"паркинг|машиномест|м/м\b|кладов"),
    ("отделка", r"отделк|чистов|white\s?box|вайтбокс"),
    ("срок ввода", r"срок сдач|ввод|ключ[иа]|\bрвэ\b"),
    ("скидка и торг", r"скидк|дисконт|торг\b|индивидуальн[ыо][ех] услови"),
    ("сравнение с соседями", r"сравнива|конкурент|у соседей"),
)

# Соседние проекты, с которыми сравнивают. Список короткий и явный: ловить
# имена «по заглавной букве» значило бы записать в конкуренты Ипотеку и Москву.
RIVALS: tuple[tuple[str, str], ...] = (
    ("Родина Парк", r"родин[аы]\b"),
    ("Веер", r"\bвеер\b"),
    ("Сет", r"\bсет\b|\bset\b"),
    ("Верейская 41", r"верейск"),
    ("Кутузовский квартал", r"кутузовск(ий|ая) кварт"),
    ("Level", r"\blevel\b|левел"),
    ("Индиво", r"индиво"),
)


def _plain(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def read_salesroom(data: bytes) -> dict[str, Any]:
    """Разобрать экспорт чата. Не тот файл — исключение, а не пустой свод.

    Пустой ответ читался бы как «в чате ничего нет», а это другое утверждение.
    """
    text = data.decode("utf-8", errors="replace")
    if "page_body chat_page" not in text and 'class="message default' not in text:
        raise ValueError("это не экспорт переписки Telegram")
    title = re.search(r'<div class="text bold">\s*(.*?)\s*</div>', text, re.S)
    messages: list[dict[str, Any]] = []
    author = ""
    for block in _MESSAGE.findall(text):
        got = _AUTHOR.search(block)
        author = _plain(got.group(1)) if got else author
        when = _WHEN.search(block)
        body = _TEXT.search(block)
        day = ""
        if when:
            stamp = _DATE.search(when.group(1))
            if stamp:
                day = f"{stamp.group(3)}-{stamp.group(2)}-{stamp.group(1)}"
        messages.append({
            "day": day, "author": author,
            "text": _plain(re.sub(r"<br\s*/?>", " ", body.group(1))) if body else "",
        })
    if not messages:
        raise ValueError("в экспорте нет сообщений")
    return {"messages": messages, "chat": _plain(title.group(1)) if title else "",
            "missing": []}


def _lots(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Лоты из броней: площадь и цена метра, каждый лот один раз.

    Ежедневный отчёт повторяет действующую бронь, пока она держится. Ключ —
    сама пара «площадь и цена»: номера лота в отчёте может не быть вовсе.
    """
    seen: dict[tuple[float, int], dict[str, Any]] = {}
    for message in messages:
        text = message["text"]
        for found in _PER_SQM.finditer(text):
            price = float(found.group(1).replace(" ", "").replace(" ", ""))
            if not 300_000 <= price <= 2_000_000:
                continue
            window = text[max(0, found.start() - 120):found.end() + 120]
            areas = [float(a.replace(",", ".")) for a in _AREA.findall(window)]
            areas = [a for a in areas if 15 <= a <= 200]
            if not areas:
                continue
            key = (round(areas[0], 1), int(price))
            seen.setdefault(key, {"day": message["day"], "area": key[0],
                                  "price_per_sqm": float(key[1])})
    return sorted(seen.values(), key=lambda row: row["day"])



def _slice_share(_rows: list[dict[str, Any]], seen: Counter,
                 said: Counter, months: list[str]) -> float | None:
    """Доля темы в куске месяцев. Меньше трёх месяцев — не тренд, а один месяц."""
    if len(months) < 3:
        return None
    total = sum(said[month] for month in months)
    return (sum(seen.get(month, 0) for month in months) / total) if total else None


def summarise(read: dict[str, Any], bands: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Свод по чату: воронка от встреч, темы разговоров и цены броней."""
    messages = [m for m in (read.get("messages") or []) if m.get("day")]
    if not messages:
        return {"days": [], "months": [], "topics": [], "rivals": [], "lots": [],
                "notes": ["в экспорте нет ни одного сообщения с датой"]}

    days: dict[str, dict[str, Any]] = {}
    for message in messages:
        text = message["text"]
        day = days.setdefault(message["day"], {"day": message["day"]})
        for key, pattern in _COUNTS.items():
            found = re.search(pattern, text, re.I)
            if found:
                # В дне бывает несколько отчётов — берём последний по времени.
                day[key] = float(found.group(1))

    months: dict[str, dict[str, Any]] = {}
    for day in days.values():
        month = months.setdefault(day["day"][:7], {"month": day["day"][:7], "days": 0.0})
        month["days"] += 1
        for key in _COUNTS:
            if key in day:
                month[key] = month.get(key, 0.0) + day[key]
                month[key + "_days"] = month.get(key + "_days", 0.0) + 1

    rows = []
    for month in sorted(months.values(), key=lambda row: row["month"]):
        meetings = month.get("meetings")
        bookings = month.get("bookings")
        row = {"month": month["month"], "days": month["days"],
               "meetings": meetings, "calls": month.get("calls"),
               "bookings": bookings, "registering": month.get("registering")}
        # Бронь и сделку на регистрации отчёт показывает СОСТОЯНИЕМ дня, а не
        # событием: складывать их за месяц нельзя — выйдет «сколько раз бронь
        # упомянута». На июле это видно сразу: 26 «сделок на регистрации» при
        # эскроу, не выросшем ни на рубль. Берём среднее одновременно висящих.
        # Встречи и звонки, наоборот, события дня — их сумма осмысленна.
        if bookings is not None and month.get("bookings_days"):
            row["bookings_at_once"] = round(bookings / month["bookings_days"], 2)
            row.pop("bookings")
        if row.get("registering") is not None and month.get("registering_days"):
            row["registering_at_once"] = round(month["registering"] / month["registering_days"], 2)
            row.pop("registering")
        if meetings is not None and month.get("meetings_days"):
            row["meetings_per_day"] = round(meetings / month["meetings_days"], 2)
        if month.get("calls") is not None and month.get("calls_days"):
            row["calls_per_day"] = round(month["calls"] / month["calls_days"], 2)
        rows.append(row)

    # Тема считается долей месяца, а не числом: сообщений в месяце то тридцать,
    # то девяносто, и «стали чаще спрашивать про рассрочку» по голому счёту
    # означало бы «менеджеры стали писать длиннее».
    said_in_month: Counter = Counter(m["day"][:7] for m in messages)
    order = sorted(said_in_month)
    topics: list[dict[str, Any]] = []
    for name, pattern in TOPICS:
        hits = [m for m in messages if re.search(pattern, m["text"], re.I)]
        if not hits:
            continue
        seen: Counter = Counter(m["day"][:7] for m in hits)
        by_month = [{"month": month, "messages": float(seen.get(month, 0)),
                     "share": seen.get(month, 0) / said_in_month[month]}
                    for month in order]
        topics.append({"topic": name, "messages": float(len(hits)),
                       "share": len(hits) / len(messages),
                       "first": hits[0]["day"], "last": hits[-1]["day"],
                       "months": by_month,
                       "share_early": _slice_share(by_month, seen, said_in_month, order[:3]),
                       "share_recent": _slice_share(by_month, seen, said_in_month, order[-3:])})
    topics.sort(key=lambda row: -row["messages"])

    rivals = []
    for name, pattern in RIVALS:
        hits = [m for m in messages if re.search(pattern, m["text"], re.I)]
        if hits:
            rivals.append({"rival": name, "messages": float(len(hits)), "last": hits[-1]["day"]})
    rivals.sort(key=lambda row: -row["messages"])

    lots = _lots(messages)
    asked = []
    for message in messages:
        for area in _AREA.findall(message["text"]):
            value = float(area.replace(",", "."))
            if 15 <= value <= 200:
                asked.append(value)

    notes = [
        "Это отчёты менеджеров, а не слова покупателя: отсутствие площади в "
        "записи значит «не записали», а не «не спрашивали».",
        "Бронь повторяется в каждом дневном отчёте, пока держится: в месяце "
        "показано среднее число одновременно висящих броней, а не сумма.",
        "Рост доли темы значит, что о ней стали ЗАПИСЫВАТЬ чаще. Это может быть "
        "и переменой спроса, и переменой в том, как подробно ведут отчёт; "
        "различить одно от другого по чату нечем.",
    ]
    return {
        "chat": read.get("chat") or "",
        "from": messages[0]["day"], "to": messages[-1]["day"],
        "messages": float(len(messages)),
        "months": rows,
        "topics": topics,
        "rivals": rivals,
        "lots": lots,
        "asked_area_median": (round(statistics.median(asked), 1) if asked else None),
        "asked_mentions": float(len(asked)),
        "bands": _lots_by_band(lots, bands),
        "notes": notes,
    }


def _lots_by_band(lots: list[dict[str, Any]], bands: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Цена метра брони по тем же полосам площади, что и остальной свод.

    Свои полосы завести было бы вторым делением одной величины: полосы книги
    уже разбиты так, как разбит проект.
    """
    out = []
    for band in bands or []:
        inside = [row["price_per_sqm"] for row in lots
                  if band.get("low") is not None and band.get("high") is not None
                  and band["low"] <= row["area"] < band["high"]]
        out.append({"band": band.get("band"), "lots": float(len(inside)),
                    "price_per_sqm": (round(statistics.median(inside)) if inside else None)})
    return out
