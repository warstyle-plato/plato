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
С 02.11.2026 строки «Наполнение эскроу» и «Зарегистрированные ДДУ» читаются
как наблюдение отдела продаж (`registration_check`): рядом со своим числом,
с подписью источника, а не вместо проводок и выгрузки договоров.
"""

from __future__ import annotations

import datetime
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
#
# Формат 2026-10 («Отчёт за 23.10.2026 г.»): «ЦО за день - 1», «Встречи за
# день - 1», «Брокер тур за день - 1», «ДДУ на регистрации: 0», «Текущих
# броней: 3». Берётся «за день»: «за месяц» — нарастающий итог, и сложенный по
# дням он считался бы многократно. ЦО — целевые обращения, та же ступень
# воронки, что прежние «целевые звонки».
_COUNTS = {
    "meetings": r"(?:встреч[а-яё]*\s*в\s*офисе|встреч[а-яё]*\s*за\s*день)\s*[-–—:]?\s*(\d+)",
    # Целевой звонок пишут и «целевых звонков», и «целевые звонки», и «ЦО
    # (целевые обращения) за день» — ступень воронки одна.
    "calls": r"(?:целев[а-яё]*\s*(?:звонк|обращени)[а-яё]*(?:\s*за\s*день)?|ЦО\s*за\s*день)"
             r"\s*[-–—:]?\s*(\d+)",
    "broker_tours": r"брокер[\s-]*тур[а-яё]*\s*за\s*день\s*[-–—:]?\s*(\d+)",
    "bookings": r"текущих\s*брон[а-яё]*[^\d]{0,20}(\d+)",
    "registering": r"(?:сделк[аи]|ДДУ)\s*на\s*регистрации\s*[-–—:]?\s*(\d+)",
}
# События дня складываются; брони и сделки на регистрации — состояние дня.
_EVENTS = ("calls", "meetings", "broker_tours")
_STATES = ("bookings", "registering")

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

# Что не подошло. Слова взяты из самих записей — каждая строка стоит в живом
# экспорте 01.09.2026, а не придумана по списку типовых возражений. Правило то
# же, что у причин отказа в CRM: считаем то, что рядом с однозначной уликой, а
# не слово «отказ» в пересказе.
#
# Возражение — это НЕ «не купил»: человек, назвавший цену высокой, назавтра
# берёт бронь. Строка отвечает на «что мешало», а не на «почему не продали».
OBJECTIONS: tuple[tuple[str, str], ...] = (
    ("бюджет и цена",
     r"не проход\w*\s*по\s*бюджет|по\s*бюджет\w*\s*не\s*под|ограничен\w*\s*в\s*бюджет"
     r"|слишком дорог|\bдорого\b|не по бюджет|по цене не проход|цены.{0,30}негатив"
     r"|локация не соответствует цене|не хватает бюджет"),
    ("соседний дом рядом",
     r"(?:инград|кутузов\s*град)(?=[^.!?]{0,80}(?:не нрав|смуща|давит|близко|слишком))"
     r"|(?:не нрав|смуща|давит)[^.!?]{0,80}(?:инград|кутузов\s*град)"),
    ("много стройки вокруг", r"много\s*стро|стройк\w*\s*рядом"),
    ("этаж и виды", r"смуща\w*\s*этаж|видов\w*\s*характеристик|виды\s*из\s*окон"),
    ("планировка и комнаты",
     r"маленьким\w*\s*комнат|комнаты\s*от\s*\d+|планировк\w*\s*котор\w*\s*нрав"),
    ("район как статус", r"понижени\w*\s*уровн|район.{0,30}не подход"),
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


# Описание визита внутри дневного отчёта: кусок после счёта встреч и до счёта
# звонков. Владелец, 01.09.2026: «анализировать надо только отчёты о встречах,
# простую болтовню не надо».
#
# Мерить темы по ВСЕМУ сообщению нельзя, и по всему чату тем более. В отчёте
# рядом стоит список действующих броней, и он повторяется каждый день, пока
# бронь держится: «квартира №20, башня Гармония, 90,2 кВ.м» приносила тему
# «площадь» тридцать раз подряд — та же ошибка, от которой брони считаются по
# одному разу. А в чате помимо отчётов живёт рабочая переписка: план эскроу,
# ссылки на дом.рф, «где новые фото». Её 69% за всё время и 91% в декабре, и со
# временем её стало меньше — доля темы от всего чата росла бы сама собой.
_VISIT = re.compile(
    r"(?:встреч\w*\s*в\s*офисе|в\s*офисе)[\s:\-–—]*(\d+)\s*(?:шт\.?|встреч\w*)?[\s\.\)\-–—:]*(.*?)"
    r"(?=целев\w*\s*звонк|на\s+завтра|$)", re.I | re.S)

# Короче этого — не описание разговора, а «Встреч в офисе - 0» с хвостом.
_VISIT_MIN = 40

# Меньше этого числа визитов на куске — сравнивать не с чем.
_SLICE_MIN = 10


def visit_of(text: str) -> str:
    """Что записано про сам визит. Пусто — в этот день визит не описывали."""
    found = _VISIT.search(text)
    if not found:
        return ""
    said = found.group(2).strip()
    return said if len(said) >= _VISIT_MIN else ""


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


# Бюджет и площадь, названные на встрече. «бюджет 35 млн», «до 40 млн»,
# «рассматривает 100 метров». Разрыв между тем и другим — это и есть ответ на
# «почему не покупают», причём словами покупателя, а не нашей догадкой.
_BUDGET = re.compile(r"бюджет\w*\s*(?:до\s*|около\s*|порядка\s*|в\s*)?(\d{1,3})\s*млн", re.I)
_WANT_AREA = re.compile(r"(?:рассматрива\w*|смотр\w*|ище\w*|нужн\w*|хоч\w*|интересу\w*)"
                        r"[^.!?]{0,40}?(\d{2,3})\s*(?:\+\s*)?(?:кв\.?\s?м|м2|м²|метр)", re.I)


def _asked(visits: list[dict[str, Any]]) -> dict[str, Any]:
    """Что просят: бюджет и метры, названные на встречах.

    Считается по описаниям визитов, поэтому одна встреча даёт одну пару, а не
    столько, сколько раз в отчёте повторилась действующая бронь.
    """
    budgets, areas = [], []
    for visit in visits:
        found = [int(x) for x in _BUDGET.findall(visit["text"])]
        budgets += [x for x in found if 5 <= x <= 300]
        found = [int(x) for x in _WANT_AREA.findall(visit["text"])]
        areas += [x for x in found if 20 <= x <= 250]
    return {
        "budget_median_mln": (round(statistics.median(budgets), 1) if budgets else None),
        "budget_said": float(len(budgets)),
        "area_median": (round(statistics.median(areas), 1) if areas else None),
        "area_said": float(len(areas)),
    }


def _objections(visits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Что мешало — по словам самих записей.

    Возражение это не отказ: назвавший цену высокой назавтра берёт бронь.
    Строка отвечает на «что мешало», и так она и подписана.
    """
    out = []
    for name, pattern in OBJECTIONS:
        hits = [v for v in visits if re.search(pattern, v["text"], re.I)]
        if hits:
            out.append({"objection": name, "visits": float(len(hits)),
                        "share": len(hits) / len(visits) if visits else None,
                        "last": hits[-1]["day"]})
    out.sort(key=lambda row: -row["visits"])
    return out


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



def _slice_share(seen: Counter, said: Counter, months: list[str]) -> float | None:
    """Доля темы в куске месяцев. Мало визитов — ответа нет, а не ноль.

    Описывать разговор в отчёте начали не сразу: в феврале 2026 таких записей
    нет вовсе, в марте шесть. Доля, посчитанная на четырёх визитах, читается на
    экране ровно так же, как посчитанная на пятидесяти, — и «стали спрашивать
    чаще» выходило бы из того, что стали ПИСАТЬ подробнее.
    """
    if len(months) < 3:
        return None
    total = sum(said[month] for month in months)
    return (sum(seen.get(month, 0) for month in months) / total) if total >= _SLICE_MIN else None



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
               "broker_tours": month.get("broker_tours"),
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

    # Темы меряются ТОЛЬКО по описаниям визитов — по тому, что менеджер
    # записал про разговор. Всё остальное в чате про покупателя не говорит, а
    # повторяющийся блок броней говорит про него тридцать раз подряд.
    visits = [{"day": m["day"], "text": visit_of(m["text"])} for m in messages]
    visits = [v for v in visits if v["text"]]
    said_in_month: Counter = Counter(v["day"][:7] for v in visits)
    order = sorted(said_in_month)
    topics: list[dict[str, Any]] = []
    for name, pattern in TOPICS:
        hits = [v for v in visits if re.search(pattern, v["text"], re.I)]
        if not hits:
            continue
        seen: Counter = Counter(v["day"][:7] for v in hits)
        by_month = [{"month": month, "messages": float(seen.get(month, 0)),
                     "share": seen.get(month, 0) / said_in_month[month]}
                    for month in order]
        topics.append({"topic": name, "messages": float(len(hits)),
                       "share": len(hits) / len(visits) if visits else None,
                       "first": hits[0]["day"], "last": hits[-1]["day"],
                       "months": by_month,
                       "share_early": _slice_share(seen, said_in_month, order[:3]),
                       "share_recent": _slice_share(seen, said_in_month, order[-3:])})
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
        f"Темы считаются по описаниям визитов ({len(visits)} из {len(messages)} "
        "сообщений), а не по всему чату: в отчёте рядом лежит список действующих "
        "броней, и он повторяется каждый день, пока бронь держится.",
    ]
    return {
        "chat": read.get("chat") or "",
        "from": messages[0]["day"], "to": messages[-1]["day"],
        "messages": float(len(messages)),
        # База названа числом: «47% разговоров» и «47% чата» — разные
        # утверждения, а на экране они выглядят одинаково.
        "visits": float(len(visits)),
        "months": rows,
        "topics": topics,
        "rivals": rivals,
        "lots": lots,
        "asked_area_median": (round(statistics.median(asked), 1) if asked else None),
        "asked_mentions": float(len(asked)),
        "bands": _lots_by_band(lots, bands),
        "objections": _objections(visits),
        "asked": _asked(visits),
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


# --- отчёты из чата по одному: бот в группе ----------------------------------
# Владелец (24.10.2026): «может туда тоже бота посадить? Для отчётов по
# звонкам, броням и т. п.». Выгрузка чата руками остаётся, бот дописывает те же
# сообщения по одному — источник один, «чат отдела продаж».

# Отчёт продаж узнаётся по подписям строк, а не по слову «отчёт»: так зовут и
# сводку стройки. Двух подписей хватает, одной мало — «встреча» бывает и в
# рабочей переписке.
_REPORT_MIN_LINES = 2


def is_sales_report(text: str) -> bool:
    """Похоже ли сообщение на ежедневный отчёт отдела продаж."""
    found = sum(1 for pattern in _COUNTS.values() if re.search(pattern, text or "", re.I))
    return found >= _REPORT_MIN_LINES


def append_message(read: dict[str, Any] | None, day: str, author: str,
                   text: str, chat: str = "") -> dict[str, Any]:
    """Дописать сообщение к источнику «чат отдела продаж».

    Тот же день с тем же текстом второй раз не пишется: Telegram повторяет
    доставку, а повтор удвоил бы встречи дня.
    """
    got = dict(read or {"messages": [], "chat": chat, "missing": []})
    messages = list(got.get("messages") or [])
    entry = {"day": day, "author": author, "text": " ".join(str(text or "").split())}
    if not any(m.get("day") == entry["day"] and m.get("text") == entry["text"] for m in messages):
        messages.append(entry)
    got["messages"] = messages
    got["chat"] = got.get("chat") or chat
    return got


def _counted(text: str) -> dict[str, float]:
    got = {}
    for key, pattern in _COUNTS.items():
        found = re.search(pattern, text or "", re.I)
        if found:
            got[key] = float(found.group(1))
    return got


def _reports(read: dict[str, Any] | None, first: str, last: str) -> dict[str, str]:
    """{день: текст} — последний отчёт продаж за день.

    Ежедневный отчёт — сводка отдела, и пишет его дежурный: в живой выгрузке
    чата (24.10.2026) за 65 дней отчётов шесть разных авторов и ни одного дня
    с двумя отчётами. Сложить два отчёта одного дня значило бы посчитать
    отдел дважды; автор сообщения — не менеджер сделки.
    """
    out: dict[str, str] = {}
    for message in (read or {}).get("messages") or []:
        day = str(message.get("day") or "")
        text = message.get("text") or ""
        if (first <= day <= last) and (_counted(text) or booked_lots(text) is not None):
            out[day] = text
    return out


def funnel(read: dict[str, Any] | None, first: str, last: str) -> dict[str, Any] | None:
    """Воронка отдела продаж за дни ``first``…``last`` включительно (ГГГГ-ММ-ДД).

    События (обращения, встречи, брокер-туры) складываются по дням — в дне
    берётся последний отчёт. Брони и ДДУ на регистрации — состояние: берётся
    последний день периода, где они названы. Дней без отчёта ноль не
    приписывается: в ответе сказано, за сколько дней отчёты были.
    """
    reported = {day: _counted(text) for day, text in _reports(read, first, last).items()}
    reported = {day: row for day, row in reported.items() if row}
    if not reported:
        return None
    out: dict[str, Any] = {"days": len(reported), "first": min(reported), "last": max(reported)}
    for key in _EVENTS:
        values = [row[key] for row in reported.values() if key in row]
        out[key] = sum(values) if values else None
    for key in _STATES:
        named = [day for day in sorted(reported) if key in reported[day]]
        out[key] = reported[named[-1]][key] if named else None
    return out


# --- зарегистрированные ДДУ: сверка отчёта отдела продаж с выгрузкой договоров --
# Владелец (02.11.2026): отчёт чата «за 01.11.2026» пишет «Зарегистрированные
# ДДУ: Количество — 7, Метры — 500,1, ДС — …», а сводка за октябрь — 5
# договоров. Отдел продаж считает договор по дате регистрации, сводка — по
# дате подписания, как план финмодели. Даты регистрации в выгрузке договоров
# нет, поэтому сверка идёт по числу договоров, метрам и сумме: какие договоры
# последних дней прошлого месяца (или конца этого) закрывают разницу.
#
# Число отдела продаж — наблюдение, а не второй счёт продаж: сводка
# по-прежнему считает по подписанию, а строка отдела стоит рядом с подписью
# источника. Наполнение эскроу из того же отчёта читается так же — как
# наблюдение отдела, деньги сводки по-прежнему из проводок и книги.
#
# Блок «Зарегистрированные ДДУ» — нарастающий итог месяца, как «за месяц» у
# ЦО и встреч: берётся последний отчёт месяца, по дням не складывается.
#
# К какому месяцу относится отчёт за 1-е число, решает формат, а не догадка:
# если «за месяц» у ЦО, встреч или брокер-туров больше, чем «за день», счётчик
# месяца ещё не обнулился — отчёт подводит итог прошлого месяца. Если «за
# месяц» равно «за день», а в предыдущем отчёте месячный счётчик был больше —
# обнулился, отчёт уже нового месяца. Иначе отчёт не относится никуда, и это
# сказано.
REGISTRATION_DAYS = 14
# Округление в отчёте отдела: метры — до десятых, деньги — до копеек, но
# копейки в отчёте и в выгрузке расходятся (в живом случае на 20 копеек).
_AREA_TOLERANCE = 0.15
_AMOUNT_TOLERANCE = 1000.0
# Сколько договоров с каждого края перебирать: больше — уже не «последние дни».
_EDGE_POOL = 12
_EDGE_PICK = 4

_HEADER = re.compile(r"отч[её]т\s*за\s*(\d{2})\.(\d{2})\.(\d{4})", re.I)
_NUMBER = r"(\d{1,3}(?:\s\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
_DASH = r"\s*[-–—:]?\s*"
_REGISTERED = re.compile(r"зарегистрированн\w*\s*ДДУ\s*:?\s*(.{0,160}?)"
                         r"(?=количество\s*ЦО|ЦО\s*за|встреч|брокер|ДДУ\s*на\s*регистрации"
                         r"|текущих|наполнение|$)", re.I)
_REG_FIELDS = {"contracts": re.compile(r"количество" + _DASH + r"(\d+)", re.I),
               "area": re.compile(r"метр\w*" + _DASH + _NUMBER, re.I),
               "amount": re.compile(r"\bДС" + _DASH + _NUMBER, re.I)}
_ESCROW = {"total": re.compile(r"наполнение\s*эскроу\s*за\s*весь\s*период" + _DASH + _NUMBER
                               + r"\s*(млрд|млн)?", re.I),
           "month": re.compile(r"наполнение\s*эскроу\s*за\s*текущий\s*месяц" + _DASH + _NUMBER
                               + r"\s*(млрд|млн)?", re.I)}
_MONTH_COUNTS = {"calls": re.compile(r"ЦО\s*за\s*месяц" + _DASH + r"(\d+)", re.I),
                 "meetings": re.compile(r"встреч\w*\s*за\s*месяц" + _DASH + r"(\d+)", re.I),
                 "broker_tours": re.compile(r"брокер[\s-]*тур\w*\s*за\s*месяц" + _DASH + r"(\d+)",
                                            re.I)}
_IN_MONTH = ("январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе",
             "сентябре", "октябре", "ноябре", "декабре")
_OF_MONTH = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
             "сентября", "октября", "ноября", "декабря")


def _figure(text: str) -> float:
    return float(text.replace(" ", "").replace(",", "."))


def _money(number: str, scale: str | None) -> float:
    """Рубли из отчёта. «1 591 490 225,9 млрд.» — число уже в рублях, и
    подпись «млрд» при нём ошибка набора: множитель берётся, только когда
    число короткое («1,59 млрд»)."""
    value = _figure(number)
    if scale and value < 10_000:
        value *= 1e9 if scale.lower() == "млрд" else 1e6
    return value


def registered_of(text: str) -> dict[str, Any] | None:
    """Блок «Зарегистрированные ДДУ» отчёта: число, метры, деньги.
    Блока нет — ``None``: «не сказано», а не «ноль»."""
    found = _REGISTERED.search(text or "")
    if not found:
        return None
    got: dict[str, Any] = {}
    for key, pattern in _REG_FIELDS.items():
        value = pattern.search(found.group(1))
        got[key] = (int(value.group(1)) if key == "contracts" else _figure(value.group(1))) \
            if value else None
    return got if got["contracts"] is not None else None


def escrow_of(text: str) -> dict[str, float | None]:
    """«Наполнение эскроу за весь период / за текущий месяц» — как пишет отдел."""
    out: dict[str, float | None] = {}
    for key, pattern in _ESCROW.items():
        value = pattern.search(text or "")
        out[key] = _money(value.group(1), value.group(2)) if value else None
    return out


def _report_day(message: dict[str, Any]) -> str:
    """День отчёта — из заголовка «Отчёт за ДД.ММ.ГГГГ», иначе день сообщения."""
    head = _HEADER.search(message.get("text") or "")
    if head:
        return f"{head.group(3)}-{head.group(2)}-{head.group(1)}"
    return str(message.get("day") or "")[:10]


def _month_counts(text: str) -> dict[str, float]:
    out = {}
    for key, pattern in _MONTH_COUNTS.items():
        value = pattern.search(text or "")
        if value:
            out[key] = float(value.group(1))
    return out


def _previous_month(key: str) -> str:
    year, month = int(key[:4]), int(key[5:7])
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def report_month(text: str, day: str, before: str | None = None) -> str | None:
    """Месяц, итог которого подводит отчёт за ``day`` (ГГГГ-ММ-ДД).

    ``before`` — текст предыдущего отчёта. Отчёт не за 1-е число — месяц
    заголовка. Отчёт за 1-е — по счётчикам «за месяц» (см. выше); не видно —
    ``None``.
    """
    if not day:
        return None
    if day[8:10] != "01":
        return day[:7]
    daily, monthly = _counted(text), _month_counts(text)
    pairs = [(daily[key], monthly[key]) for key in monthly if key in daily]
    if any(month > today for today, month in pairs):
        return _previous_month(day[:7])
    earlier = _month_counts(before or "")
    if pairs and any(earlier.get(key, 0.0) > monthly[key] for key in monthly):
        return day[:7]
    return None


def _month_reports(read: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Отчёты с блоком «Зарегистрированные ДДУ», с днём и месяцем итога."""
    messages = [m for m in (read or {}).get("messages") or []
                if _counted(m.get("text") or "") or registered_of(m.get("text") or "")]
    messages.sort(key=_report_day)
    out, before = [], None
    for message in messages:
        text = message.get("text") or ""
        day = _report_day(message)
        registered = registered_of(text)
        if registered is not None:
            out.append({"day": day, "month": report_month(text, day, before),
                        "registered": registered, "escrow": escrow_of(text)})
        before = text
    return out


def _sums(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Число, метры и сумма договоров — по тому же правилу, что сводка: метры
    только у того, что продаётся метром."""
    from market_search import contracting

    totals = contracting._totals(rows) if rows else {"contracts": 0.0, "amount": 0.0}
    area = sum(float(row.get("area") or 0.0) for row in rows
               if contracting.product_measure(contracting.product_name(row["product"])) == "area")
    return {"contracts": int(totals["contracts"]), "area": area,
            "amount": float(totals["amount"])}


def _close(sums: dict[str, Any], seen: dict[str, Any]) -> bool:
    if sums["contracts"] != seen["contracts"]:
        return False
    if seen.get("area") is not None and abs(sums["area"] - seen["area"]) > _AREA_TOLERANCE:
        return False
    if seen.get("amount") is not None and abs(sums["amount"] - seen["amount"]) > _AMOUNT_TOLERANCE:
        return False
    return True


def _explain(signed: list[dict[str, Any]], before: list[dict[str, Any]],
             seen: dict[str, Any]) -> list[tuple[list, list]]:
    """Наборы (подписанные в конце прошлого месяца, подписанные в конце этого
    и ещё не зарегистрированные), с которыми числа отдела сходятся. Не больше
    двух: два подходящих набора — уже неоднозначность."""
    import itertools

    def latest(rows):
        return sorted(rows, key=lambda row: str(row.get("signed") or ""), reverse=True)[:_EDGE_POOL]

    pool_before, pool_late = latest(before), latest(signed)
    gap = seen["contracts"] - len(signed)
    found: list[tuple[list, list]] = []
    for size in range(0, 2 * _EDGE_PICK + 1):
        for late in range(0, _EDGE_PICK + 1):
            early = late + gap
            if early < 0 or early > _EDGE_PICK or early + late != size:
                continue
            for add in itertools.combinations(pool_before, early):
                for drop in itertools.combinations(pool_late, late):
                    dropped = {id(row) for row in drop}
                    kept = [row for row in signed if id(row) not in dropped] + list(add)
                    if _close(_sums(kept), seen):
                        found.append((list(add), list(drop)))
                        if len(found) > 1:
                            return found
        if found:
            return found
    return found


def _ru(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def _sums_words(sums: dict[str, Any]) -> str:
    count = int(sums["contracts"])
    word = "договор" if count % 10 == 1 and count % 100 != 11 else (
        "договора" if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14) else "договоров")
    parts = []
    if sums.get("area") is not None:
        parts.append(f"{_ru(sums['area'], 1)} м²")
    if sums.get("amount") is not None:
        parts.append(f"{_ru(sums['amount'] / 1e6, 1)} млн ₽")
    return f"{count} {word}" + (" на " + " и ".join(parts) if parts else "")


def _days_words(rows: list[dict[str, Any]]) -> str:
    days = sorted({str(row.get("signed") or "")[:10] for row in rows})
    shown = [f"{day[8:10]}.{day[5:7]}" for day in days]
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " и " + shown[-1]


def registration_check(read: dict[str, Any] | None, contracts: list[dict[str, Any]],
                       month: str | None = None, upto: str | None = None,
                       uploaded: str | None = None) -> dict[str, Any] | None:
    """Подписано в месяце (выгрузка договоров) рядом с «зарегистрировано в
    месяце» (последний отчёт отдела продаж за месяц) и объяснение разницы.

    ``month`` — ГГГГ-ММ; не задан — последний месяц, за который отдел продаж
    назвал зарегистрированные ДДУ. ``upto`` — последний день периода сводки:
    если месяц не кончился, берутся договоры и отчёт до этого дня. Одна
    функция для сводки руководству и кабинета; тексты — отсюда же.
    ``uploaded`` — дата выгрузки договоров: на неё деньги на эскроу.
    Отчётов с блоком нет — ``None``.
    """
    reports = _month_reports(read)
    if not reports:
        return None
    if month is None:
        dated = [item["month"] for item in reports if item["month"]]
        if not dated:
            return None
        month = max(dated)
    first = datetime.date.fromisoformat(month + "-01")
    following = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    end = following - datetime.timedelta(days=1)
    if upto and datetime.date.fromisoformat(upto[:10]) < end:
        end = datetime.date.fromisoformat(upto[:10])
    whole = end == following - datetime.timedelta(days=1)
    mine = [item for item in reports if item["month"] == month
            and (whole or item["day"] <= end.isoformat())]
    undecided = [item for item in reports if item["month"] is None
                 and item["day"] in (month + "-01", following.isoformat())]
    if not mine:
        if not undecided:
            return None
        day = undecided[-1]["day"]
        return {"month": month, "report_day": None, "match": "unknown",
                "lines": [f"Отчёт отдела продаж за {day[8:10]}.{day[5:7]}.{day[:4]} не отнесён "
                          "ни к одному месяцу: по счётчикам «за месяц» в нём не видно, "
                          "начался ли уже новый месяц."]}
    last = mine[-1]
    seen = last["registered"]

    def day_of(row):
        try:
            return datetime.date.fromisoformat(str(row.get("signed") or "")[:10])
        except ValueError:
            return None

    signed = [row for row in contracts if (d := day_of(row)) and first <= d <= end]
    before = [row for row in contracts if (d := day_of(row))
              and first - datetime.timedelta(days=REGISTRATION_DAYS) <= d < first]
    ours = _sums(signed)
    name = _IN_MONTH[first.month - 1]
    span = (f"в {name}" if whole
            else f"с 1 по {end.day} {_OF_MONTH[first.month - 1]}")
    report_day = last["day"]
    lines = [f"Подписано {span} — по выгрузке договоров: {_sums_words(ours)}.",
             f"Зарегистрировано {span} — по отчёту отдела продаж за "
             f"{report_day[8:10]}.{report_day[5:7]}.{report_day[:4]}: {_sums_words(seen)}."]
    out = {"month": month, "report_day": report_day, "whole_month": whole,
           "signed": ours, "registered": seen, "escrow": last["escrow"],
           "earlier": [], "later": []}
    if _close(ours, seen):
        out["match"] = "same"
        lines.append("Числа совпадают.")
        out["lines"] = lines
        return out
    found = (_explain(signed, before, seen)
             if seen.get("area") is not None or seen.get("amount") is not None else [])
    if len(found) == 1:
        add, drop = found[0]
        out["match"] = "explained"
        out["earlier"] = [{"signed": row.get("signed"), "area": row.get("area"),
                           "amount": row.get("amount")} for row in add]
        out["later"] = [{"signed": row.get("signed"), "area": row.get("area"),
                         "amount": row.get("amount")} for row in drop]
        parts = []
        if add:
            parts.append(
                f"{_sums_words(_sums(add))}, "
                f"{'подписанный' if len(add) == 1 else 'подписанные'} {_days_words(add)}, в "
                f"последние дни {_OF_MONTH[(first.month - 2) % 12]}: сводка относит "
                f"{'его' if len(add) == 1 else 'их'} к {_month_dative(first.month - 2)} — по дате "
                f"подписания, а отдел продаж — к {_month_dative(first.month - 1)} — по дате регистрации")
        if drop:
            parts.append(
                f"{_sums_words(_sums(drop))}, "
                f"{'подписанный' if len(drop) == 1 else 'подписанные'} {_days_words(drop)}: в "
                f"сводке {'он' if len(drop) == 1 else 'они'} уже есть, а в отчёте отдела продаж "
                f"{'его' if len(drop) == 1 else 'их'} ещё нет — регистрация, судя по сверке, "
                "ещё не прошла")
        lines.append("Разницу дают " + "; и ".join(parts) + ". С ними числа сходятся.")
    else:
        out["match"] = "ambiguous" if found else "unexplained"
        if found:
            lines.append("Разницу можно закрыть разными наборами договоров конца "
                         f"{_OF_MONTH[(first.month - 2) % 12]} и {_OF_MONTH[first.month - 1]}, "
                         "поэтому какие именно договоры посчитал отдел продаж, не сказать.")
        else:
            lines.append(f"Разницу не удаётся объяснить договорами, подписанными в последние "
                         f"дни {_OF_MONTH[(first.month - 2) % 12]} или в конце "
                         f"{_OF_MONTH[first.month - 1]}: числа не сходятся.")
    if out["match"] == "explained":
        add, drop = found[0]
        dropped = {id(row) for row in drop}
        _paid_lines(out, [row for row in signed if id(row) not in dropped] + list(add),
                    lines, uploaded)
    lines.append("Даты регистрации в выгрузке договоров нет, поэтому сверка идёт по числу "
                 "договоров, метрам и сумме, а не по самим датам.")
    out["lines"] = lines
    return out


def _to_contracts(count: int) -> str:
    """«по 1 договору», «по 7 договорам»."""
    return f"{count} " + ("договору" if count % 10 == 1 and count % 100 != 11 else "договорам")


def _paid_lines(out: dict[str, Any], rows: list[dict[str, Any]], lines: list[str],
                uploaded: str | None) -> None:
    """Сколько по договорам, которые отдел продаж посчитал зарегистрированными,
    уже пришло на эскроу (владелец, 02.11.2026: «при этом из 400 почти ничего
    не оплачено?»). Сумма договора и деньги на счёте расходятся на ипотеку,
    которую банк перечисляет после регистрации, и на рассрочку. Разбивка по
    вариантам оплаты — тем же правилом, что в отчёте о продажах
    (`contracting._payment_structure`)."""
    from market_search import contracting

    if not rows:
        return
    amount = sum(float(row.get("amount") or 0.0) for row in rows)
    paid = sum(float(row.get("escrow_paid") or 0.0) for row in rows)
    parts = [{"name": item["name"], "count": item["count"], "amount": item["amount"],
              "escrow": item["escrow"]} for item in contracting._payment_structure(rows)]
    out["paid"] = {"contracts": len(rows), "amount": amount, "escrow": paid, "by_payment": parts}
    when = (f" на {uploaded[8:10]}.{uploaded[5:7]}.{uploaded[:4]}, дату выгрузки договоров"
            if uploaded else " по выгрузке договоров")
    share = f" ({_ru(paid / amount * 100, 0)}%)" if amount else ""
    text = (f"Из {_ru(amount / 1e6, 1)} млн ₽ по {_to_contracts(len(rows))} "
            f"на эскроу{when} поступило {_ru(paid / 1e6, 1)} млн ₽{share}.")
    waiting = [item for item in parts if item["amount"] - item["escrow"] >= 1.0]
    if waiting:
        text += " Не поступило: " + "; ".join(
            f"{item['name']} — {_ru((item['amount'] - item['escrow']) / 1e6, 1)} млн ₽ "
            f"по {_to_contracts(item['count'])}" for item in waiting) + "."
        if any(item["name"] == "ипотека" for item in waiting):
            text += (" Деньги по ипотеке банк перечисляет на эскроу только после регистрации "
                     "договора.")
        if any(item["name"] == "рассрочка" for item in waiting):
            text += " По рассрочке остаток приходит платежами по графику."
    lines.append(text)


_TO_MONTH = ("январю", "февралю", "марту", "апрелю", "маю", "июню", "июлю", "августу",
             "сентябрю", "октябрю", "ноябрю", "декабрю")


def _month_dative(index: int) -> str:
    return _TO_MONTH[index % 12]


# --- брони: какие ушли в договор, какие сорвались -----------------------------
# Владелец (24.10.2026): «надо следить, сколько броней не вышло в сделку в
# итоге». Ежедневный отчёт под «Текущих броней: N» перечисляет брони по одной:
# «- квартира № 20, башня Гармония, 5 этаж, 90,2 кв.м.». Бронь, пропавшая из
# списка, либо стала договором, либо снята; договор ищется в контрактации по
# номеру квартиры и площади. Башня в чате и корпус в контрактации названы
# по-разному («башня Гармония» и «корп 2»), карты между ними нет — поэтому
# ключ — номер плюс площадь, а не номер плюс дом.
_BOOKINGS_HEAD = re.compile(r"текущих\s*брон[а-яё]*", re.I)
_BOOKINGS_STOP = re.compile(r"наполнение\s*эскроу|зарегистрированн|количество\s*ЦО|встречи\s*:"
                            r"|брокер\s*тур\w*\s*:|ДДУ\s*на\s*регистрации", re.I)
_BOOKED = re.compile(r"квартир\w*\s*№?\s*(\d{1,4})", re.I)
_TOWER = re.compile(r"башн\w*\s+[^\s,.;]+", re.I)
# Менеджер брони — в скобках у самой брони: «АГЕНТСКАЯ (Помазанова Александра)».
# Порядок слов пишут по-разному («Мария Вольпи» и «Вольпи Мария») — это один
# человек: ключ — набор слов, имя — как написано впервые.
_MANAGER = re.compile(r"\(\s*([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2})\s*\)")
_UNIT_NUMBER = re.compile(r"кв\.?\s*(\d{1,4})", re.I)
# Площадь в чате и в договоре округлены по-разному; метр разницы — та же
# квартира, больше — другая.
_AREA_SLACK = 1.0
# Договор, подписанный чуть раньше, чем бронь впервые попала в отчёт, — та же
# сделка: отчёт пишется вечером, а бронь могла быть оформлена накануне.
_SIGNED_BEFORE_DAYS = 7


# Канал брони — пометка у самой брони (владелец, 02.11.2026: «в переписке
# менеджеров чётко стоит напротив брони „Агентская“. Значит это не по звонку»).
# Узнаются только явные написания: «агентская», «агент.», «через агента»,
# «АН Этажи» (агентство недвижимости — заглавными, отдельным словом). Пометка
# с отрицанием («не агентская», «без агента») и слова «прямая», «собственная»
# — явный прямой канал. Пометки нет — бронь считается прямой, но «канал не
# указан» считается отдельно и называется: отсутствие пометки — не решение.
_AGENT_WORD = re.compile(r"(?<![а-яё])агент", re.I)
# «АН» — только заглавными и отдельным словом: строчное «ан» — часть слов.
_AGENCY = re.compile(r"(?<![А-ЯЁA-Za-zа-яё])АН(?![А-ЯЁA-Za-zа-яё])")
_NO_AGENT = re.compile(r"(?:(?<![а-яё])не|без)\s+агент", re.I)
_DIRECT_MARK = re.compile(r"(?<![а-яё])(?:прям(?:ая|ой|ые)|собственн[а-яё]*)(?![а-яё])", re.I)
CHANNELS = ("direct", "agent")


def booking_channel(piece: str) -> str:
    """«agent» / «direct» по пометке у брони, «» — пометки нет."""
    text = piece or ""
    if _NO_AGENT.search(text) or _DIRECT_MARK.search(text):
        return "direct"
    if _AGENT_WORD.search(text) or _AGENCY.search(text):
        return "agent"
    return ""


def booked_lots(text: str) -> list[dict[str, Any]] | None:
    """Брони из списка под «Текущих броней». Нет раздела — ``None``: это «не
    сказано», а не «броней нет»."""
    head = _BOOKINGS_HEAD.search(text or "")
    if not head:
        return None
    tail = text[head.end():]
    stop = _BOOKINGS_STOP.search(tail)
    if stop:
        tail = tail[:stop.start()]
    found = list(_BOOKED.finditer(tail))
    out = []
    for i, match in enumerate(found):
        piece = tail[match.start():found[i + 1].start() if i + 1 < len(found) else len(tail)]
        area = _AREA.search(piece)
        tower = _TOWER.search(piece)
        manager = _MANAGER.search(piece)
        out.append({"apartment": match.group(1),
                    "area": float(area.group(1).replace(",", ".")) if area else None,
                    "tower": tower.group(0) if tower else "",
                    "manager": " ".join(manager.group(1).split()) if manager else "",
                    "channel": booking_channel(piece)})
    return out


def _lot_key(lot: dict[str, Any]) -> tuple[str, str]:
    """Бронь узнаётся по квартире и башне, а не по площади: площадь в отчёте
    уточняют («126 кВ.м» назавтра стала «121.1»), и по площади одна бронь
    распалась бы на снятую и новую."""
    return (lot["apartment"], str(lot.get("tower") or "").lower())


def _day(value: str) -> datetime.date:
    return datetime.date.fromisoformat(str(value)[:10])


def _deal_for(lot: dict[str, Any], contracts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Договор на ту же квартиру: номер из «корп 3 кв.168» и площадь."""
    earliest = _day(lot["first"]) - datetime.timedelta(days=_SIGNED_BEFORE_DAYS)
    matches = []
    for row in contracts:
        number = _UNIT_NUMBER.search(str(row.get("unit") or ""))
        if not number or number.group(1) != lot["apartment"] or not row.get("signed"):
            continue
        if lot["area"] is not None and abs(float(row.get("area") or 0.0) - lot["area"]) > _AREA_SLACK:
            continue
        if _day(row["signed"]) < earliest:
            continue
        matches.append(row)
    return min(matches, key=lambda row: row["signed"]) if matches else None


def booking_outcomes(read: dict[str, Any] | None, contracts: list[dict[str, Any]],
                     uploaded: str | None, first: str, last: str) -> dict[str, Any] | None:
    """Что стало с бронями: в договор, снята без договора или ещё держится.

    Бронь ушла из списка в день первого отчёта, где её уже нет. Договор на эту
    квартиру — «в договор»; договора нет, а контрактация загружена после ухода
    брони — «снята без сделки»; контрактация старше — «договора пока не видно»:
    отсутствие договора в старой выгрузке ещё не значит, что его нет.
    """
    lists: dict[str, list[dict[str, Any]]] = {}
    for message in (read or {}).get("messages") or []:
        day = str(message.get("day") or "")
        lots = booked_lots(message.get("text") or "")
        if day and lots is not None:
            lists[day] = lots          # в дне — последний отчёт
    days = sorted(day for day in lists if day <= last)
    if not days:
        return None
    tracks: dict[tuple[str, str], dict[str, Any]] = {}
    for day in days:
        for lot in lists[day]:
            track = tracks.setdefault(_lot_key(lot), {**lot, "first": day})
            # Площадь и менеджер — по последнему отчёту: их уточняют.
            track.update({k: v for k, v in lot.items() if v not in (None, "")}, last=day)
    latest = days[-1]
    gone_out, held = [], []
    for track in tracks.values():
        if track["last"] == latest:
            held.append({**track, "days": (_day(latest) - _day(track["first"])).days})
            continue
        gone = next(day for day in days if day > track["last"])
        item = {**track, "gone": gone, "days": (_day(gone) - _day(track["first"])).days}
        deal = _deal_for(track, contracts)
        if deal:
            item.update(outcome="deal", signed=deal["signed"])
        elif uploaded and str(uploaded)[:10] < gone:
            item["outcome"] = "unknown"
        else:
            item["outcome"] = "dropped"
        gone_out.append(item)
    period = [item for item in gone_out if first <= item["gone"] <= last]

    def count(items: list[dict[str, Any]], outcome: str) -> int:
        return sum(1 for item in items if item["outcome"] == outcome)

    return {"since": days[0], "latest": latest,
            "period": sorted(period, key=lambda item: item["gone"]),
            "total": {key: count(gone_out, key) for key in ("deal", "dropped", "unknown")},
            "held": sorted(held, key=lambda item: item["first"])}


# --- воронка целиком и по менеджерам ------------------------------------------
# Владелец (24.10.2026): «Почему в воронке нет целевых звонков? Звонок —
# встреча — бронь»; «и плюс статистика менеджеров». Один расчёт для сводки
# руководству и для отчёта о продажах кабинета.


def _share(part: float | None, whole: float | None) -> float | None:
    return (float(part) / float(whole)) if part is not None and whole else None


# Встреч бывает больше, чем целевых звонков: на встречу приходят без звонка —
# от агентов, с брокер-тура, повторно. Доля больше 100% конверсией не
# является, и она не показывается; вместо неё — эта фраза. Владелец фразы —
# здесь, сводка и кабинет её читают.
MORE_MEETINGS = ("встреч больше, чем целевых звонков: часть клиентов пришла без звонка "
                 "(агенты, брокер-туры, повторные встречи)")


def _stages(calls: float | None, meetings: float | None, bookings: int | None,
            deals: int | None) -> dict[str, Any]:
    more = calls is not None and meetings is not None and float(meetings) > float(calls)
    return {"calls": calls, "meetings": meetings, "bookings": bookings, "deals": deals,
            "meetings_share": None if more else _share(meetings, calls),
            "more_meetings": more,
            "bookings_share": _share(bookings, meetings),
            "deals_share": _share(deals, bookings)}


def channel_of(lot: dict[str, Any]) -> str:
    """Канал брони для счёта: без пометки — прямая (и считается отдельно)."""
    return lot.get("channel") or "direct"


def _person(name: str, people: dict[frozenset, dict[str, Any]]) -> dict[str, Any]:
    return people.setdefault(frozenset(name.lower().split()),
                             {"author": name, "bookings": 0, "deals": 0,
                              **{f"{c}_{k}": 0 for c in CHANNELS for k in ("bookings", "deals")}})


def _gaps(texts: dict[str, str]) -> dict[str, list[str]]:
    """Дни с отчётом, где строка звонков или встреч не распознана: недосчёт
    ступени виден, а не спрятан в сумме."""
    rows = {day: _counted(text) for day, text in texts.items()}
    return {key: sorted(day for day, row in rows.items() if key not in row)
            for key in ("calls", "meetings")}


def _gap_note(key: str, days: list[str], total: int) -> str:
    word = {"calls": "целевых звонков", "meetings": "встреч"}[key]
    shown = ", ".join(_day(day).strftime("%d.%m") for day in days[:10])
    more = f" и ещё {len(days) - 10}" if len(days) > 10 else ""
    return (f"в {len(days)} из {total} дневных отчётов строка {word} не распознана "
            f"({shown}{more}) — за эти дни {word} в воронке нет")


def sales_funnel(read: dict[str, Any] | None, contracts: list[dict[str, Any]],
                 first: str, last: str) -> dict[str, Any] | None:
    """Воронка продаж за период, по отделу и по менеджерам, двумя путями.

    - Прямой путь: целевые звонки → встречи → прямые брони → их договоры.
      Звонки и встречи — из ежедневных отчётов чата (сводка отдела, в дне —
      последний отчёт). По менеджерам отчёт их не делит, и так и сказано.
    - Через агентов: агентские брони → их договоры; брокер-туры — рядом.
      Канал — пометка у брони («АГЕНТСКАЯ»), хранится у брони, и договор на
      эту квартиру наследует канал брони.
    - Новые брони — квартиры, впервые появившиеся в списке «Текущих броней» в
      этот период. Брони из самого первого отчёта новыми не считаются: когда
      их взяли, отчёт не говорит.
    - Договоры отдела — подписанные в период (контрактация, по дате
      подписания); договор без брони в чате ни одному каналу не приписан.
    - Менеджер — имя в скобках у самой брони, а не автор сообщения.
    """
    every = _reports(read, "", last)
    if not every:
        return None
    since = min(every)
    days = [day for day in every if first <= day <= last]
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for day in sorted(every):
        for lot in booked_lots(every[day]) or []:
            track = seen.setdefault(_lot_key(lot), {**lot, "first": day})
            track.update({k: v for k, v in lot.items() if v not in (None, "")})
    counted = funnel(read, first, last) or {}
    signed = [row for row in contracts
              if row.get("signed") and first <= str(row["signed"])[:10] <= last]
    lists_known = any(booked_lots(every[day]) is not None for day in days)
    new = [lot for lot in seen.values() if first <= lot["first"] <= last and lot["first"] > since]
    people: dict[frozenset, dict[str, Any]] = {}
    unnamed = 0
    booked = {c: 0 for c in CHANNELS}
    unmarked = 0
    for lot in new:
        channel = channel_of(lot)
        booked[channel] += 1
        unmarked += not lot.get("channel")
        if lot.get("manager"):
            person = _person(lot["manager"], people)
            person["bookings"] += 1
            person[f"{channel}_bookings"] += 1
        else:
            unnamed += 1
    attributed = 0
    dealt = {c: 0 for c in CHANNELS}
    claimed: set[int] = set()
    for lot in seen.values():
        deal = _deal_for(lot, signed)
        if deal and id(deal) not in claimed:
            claimed.add(id(deal))
            attributed += 1
            channel = channel_of(lot)
            dealt[channel] += 1
            if lot.get("manager"):
                person = _person(lot["manager"], people)
                person["deals"] += 1
                person[f"{channel}_deals"] += 1
    from market_search import contracting

    deals = int(contracting._totals(signed)["contracts"]) if signed else 0
    known = lists_known
    total = _stages(counted.get("calls"), counted.get("meetings"),
                    len(new) if lists_known else None, deals)
    direct = _stages(counted.get("calls"), counted.get("meetings"),
                     booked["direct"] if known else None, dealt["direct"] if known else None)
    agent = {"bookings": booked["agent"] if known else None,
             "deals": dealt["agent"] if known else None,
             "deals_share": _share(dealt["agent"], booked["agent"]) if known else None,
             "broker_tours": counted.get("broker_tours")}
    managers = [dict(_stages(None, None, row["bookings"], row["deals"]), author=row["author"],
                     **{key: row[key] for key in row if key.startswith(CHANNELS)})
                for row in sorted(people.values(), key=lambda r: (-r["deals"], -r["bookings"]))]
    gaps = _gaps({day: every[day] for day in days})
    notes = []
    if not days:
        notes.append("за период отчётов отдела продаж в чате нет")
    for key in ("calls", "meetings"):
        if gaps[key]:
            notes.append(_gap_note(key, gaps[key], len(days)))
    if unmarked:
        notes.append(f"у {unmarked} {_plural_brone(unmarked)} канал не указан — пометки "
                     "«агентская» нет, они посчитаны прямыми")
    if managers:
        notes.append("целевые звонки и встречи отчёт даёт только по отделу — по менеджерам "
                     "их нет; брони и договоры — по менеджеру, указанному у брони")
    if unnamed:
        notes.append(f"у {unnamed} новых броней менеджер не указан")
    if first <= since <= last:
        notes.append("брони из первого отчёта в чате новыми не считаются — когда их взяли, "
                     "отчёт не говорит")
    if deals > attributed:
        notes.append(f"договоров без брони в отчётах чата — {deals - attributed}: "
                     "менеджера и канала в выгрузке договоров нет, им они не приписаны")
    return {"since": since, "days": len(days), "total": total, "direct": direct,
            "agent": agent, "unmarked": unmarked, "unattributed_deals": deals - attributed,
            "gaps": gaps, "managers": managers,
            "more_meetings_text": MORE_MEETINGS if total["more_meetings"] else "",
            "notes": notes}


def _plural_brone(count: int) -> str:
    """«у 1 новой брони», «у 2 новых броней», «у 11 новых броней»."""
    return "новой брони" if count % 10 == 1 and count % 100 != 11 else "новых броней"
