"""Ежедневные отчёты с площадки: люди по подрядчикам и живость работ.

КС показывает темп с опозданием на месяц — ежедневник говорит, что происходит
сегодня. Отсюда три сигнала монитору: численность по дням (опережающий
индикатор темпа — демобилизация видна за неделю до провала актов), «живость»
работ для сомнений Платона (работа просрочена и без актов, но упоминается в
ежедневнике — значит идёт, а не стоит) и вехи из текста (демонтаж кранов —
монолит кончился).

Текст приходит живой, из мессенджера: нумерация кривая (пункты пропускаются и
повторяются), «Итр- 3чел.» пишется десятью способами. Разбор держится за
устойчивое: числа при словах «ИТР» и «рабочие» и границы секций «По работам /
Поставка / Вывоз». Строки работ хранятся как есть — их читает человек и
сверка по словам, а не парсер. Фото не обязательны: весь рабочий сигнал в
тексте (решение владельца, 27.08.2026).

Запуск проверок: python3 -m pytest tests -q
"""

from __future__ import annotations

import datetime
import json
import re
from html.parser import HTMLParser
from typing import Any

import developaid_monitor as monitor

_ITR = re.compile(r"итр\D{0,12}?(\d+)", re.IGNORECASE)
_WORKERS = re.compile(r"рабоч\w*\D{0,12}?(\d+)", re.IGNORECASE)
_LEAD_NUM = re.compile(r"^\s*\d+\s*[.)\-—–]*\s*")
# Секции опознаются РАЗБОРОМ, а не регуляркой. Регулярки здесь стояли вида
# `^\s*слово\s*:?\s*$` — два звёздочных пробельных куска подряд у якоря конца
# строки, и на строке «поставка» с полусотней тысяч пробелов такой шаблон
# уходит в перебор. Пока текст приходил загрузкой из кабинета, это было
# теоретическим; с 13.09.2026 его пишет кто угодно в групповом чате, и CodeQL
# честно назвал три таких места высокой важностью. Разбор по словам линеен и
# заодно понятнее шаблона.
_SECTION_SUPPLY_WORDS = ("поставк", "завоз")


def _section_of(line: str) -> str:
    """Какую секцию открывает строка: works / supply / removal или пусто."""
    norm = " ".join(str(line or "").split()).lower()
    if norm.startswith("по работам"):
        return "works"
    bare = norm.rstrip(":").strip()
    if not bare or " " in bare:
        return ""
    if bare == "вывоз":
        return "removal"
    for word in _SECTION_SUPPLY_WORDS:
        if bare.startswith(word) and bare[len(word):].isalpha() or bare == word:
            return "supply"
    return ""
_GREETING = re.compile(r"^\s*(добрый|доброе|здравствуй|привет)", re.IGNORECASE)
# Слово короче четырёх букв («на», «эт», «и») совпадает со всем подряд и
# превращает сверку по словам в шум.
_WORD = re.compile(r"[а-яёa-z]{4,}", re.IGNORECASE)


def _daily_dir(project: str):
    path = monitor._project_dir(project) / "daily"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _day(value: Any) -> datetime.date:
    day = monitor._day(value)
    if day is None:
        raise ValueError("дата отчёта нужна в виде ГГГГ-ММ-ДД")
    return day


# Разделители, которыми в отчёте отбивают имя подрядчика от его работы:
# «Сталко -сборка лесов», «Бизнес Инжиниринг : устройство плитки»,
# «Моэк ( теплосети)- монтаж ограждения».
# Разделитель ищется перебором, а не шаблоном `\s*[:\-—–]\s*`: звёздочка по обе
# стороны от одного знака даёт перебор на строке из одних пробелов — та же
# болезнь, что была у секций, и CodeQL назвал её тем же правилом. Поиск первого
# разделителя линеен и делает ровно то же: приставка без хвостовых пробелов,
# остаток без ведущих.
_INLINE_SEPARATORS = ":-—–"


def _split_inline(line: str) -> list[str]:
    """Приставка и остаток по первому разделителю. Нет разделителя — один кусок."""
    for index, char in enumerate(str(line or "")):
        if char in _INLINE_SEPARATORS:
            return [line[:index].rstrip(), line[index + 1:].lstrip()]
    return [str(line or "")]


def _known_party(prefix: str, known: list[str]) -> str:
    """Имя из списка известных, если приставка строки — оно.

    Сравнение то же, что у сверки дня: ключ без формы собственности, вхождение
    с четырёх знаков, сокращение по первым буквам слов. Копии правила здесь
    нет — модуль сверки один на приложение.
    """
    import developaid_monitor_crew as crew

    text = str(prefix or "").strip(" \t.,;:-—–")
    if not text:
        return ""
    for name in known:
        if crew.same_party(text, name):
            return name
    return ""


def attribute_works(works: list[dict[str, Any]], known: list[str]) -> list[dict[str, Any]]:
    """Приписать строку работ тому, кто в ней назван.

    Разбор вёл строки за последним заголовком-подрядчиком, а в отчёте имя
    следующего подрядчика стоит В САМОЙ строке: «Клодо( кладка): Сталко —
    сборка лесов» на экране читалось как работа Клодо (владелец, 30.08.2026:
    «что такое Клодо кладка и потом другие подрядчики? бред какой-то»).

    Переприписываем ТОЛЬКО по доказательству: приставка строки должна совпасть
    с известным именем — из численности того же отчёта, из реестров РСС или из
    реестра ГУ. Иначе «Бетонирование ПП - 68,5 м3» стало бы подрядчиком
    «Бетонирование ПП».

    Имя, названное в строке, ведёт и СЛЕДУЮЩИЕ строки — до нового имени или
    нового заголовка. Прежде оно правило только собственную строку, и на живом
    отчёте с Гродненской «Монтаж кранштейнов и стоек…» — продолжение Сталко —
    возвращалось к последнему нумерованному заголовку «4. Клодо( кладка)»: у
    Клодо выходило шесть строк вместо четырёх, и две из них чужие. Заголовок
    при этом сильнее задержавшегося имени: сменился он — рассказ начался
    заново.
    """
    out: list[dict[str, Any]] = []
    running = ""
    last_header = None
    for item in works or []:
        header = item.get("contractor", "")
        if header != last_header:
            last_header, running = header, ""
        line = str(item.get("line") or "")
        parts = _split_inline(line)
        name = _known_party(parts[0], known) if len(parts) == 2 else ""
        if name:
            running = name
        elif len(parts) == 2:
            # Приставка с разделителем похожа на имя, а доказать его нечем:
            # «Моэк ( теплосети)- монтаж ограждения» (он вывел работы и не
            # выводил людей, значит в численности его нет) и «Корпус 3 -
            # 3,4,5,7 эт.» выглядят одинаково. Такая строка возвращается
            # заголовку И ОБРЫВАЕТ задержавшееся имя: увести за собой
            # следующие строки значило бы подписать их именем, которое мы
            # только что не смогли подтвердить.
            running = ""
        out.append({**item, "contractor": running or header,
                    **({"named_inline": True} if name else {})})
    return out


def parse_daily_report(text: str) -> dict[str, Any]:
    contractors: list[dict[str, Any]] = []
    works: list[dict[str, Any]] = []
    supplies: list[str] = []
    removals: list[str] = []
    unparsed: list[str] = []
    mode = "head"
    current = ""
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        section = _section_of(line)
        if section == "works":
            mode, current = "works", ""
            continue
        if section == "supply":
            mode = "supply"
            continue
        if section == "removal":
            mode = "removal"
            continue
        if mode == "head":
            itr = _ITR.search(line)
            workers = _WORKERS.search(line)
            if itr or workers:
                cut_at = min(m.start() for m in (itr, workers) if m)
                name = _LEAD_NUM.sub("", line[:cut_at]).strip(" \t:—–-.,;")
                # «Рабочие - 54чел.» переносом на свою строку — продолжение
                # предыдущего подрядчика, а не «без имени»: числа без имени
                # склеиваются с последней строкой, где имя было.
                if (not name and contractors
                        and (not itr or not contractors[-1]["itr"])
                        and (not workers or not contractors[-1]["workers"])):
                    if itr:
                        contractors[-1]["itr"] += int(itr.group(1))
                    if workers:
                        contractors[-1]["workers"] += int(workers.group(1))
                    continue
                contractors.append({
                    "name": name or "без имени",
                    "itr": int(itr.group(1)) if itr else 0,
                    "workers": int(workers.group(1)) if workers else 0,
                })
            elif not _GREETING.match(line):
                # Строка шапки без чисел — не потеря молчком: она видна в
                # ответе загрузки, и кривой отчёт замечают сразу.
                unparsed.append(line)
        elif mode == "works":
            body = _LEAD_NUM.sub("", line).strip()
            if body.endswith(":") and not (_ITR.search(body) or _WORKERS.search(body)):
                current = body.rstrip(":").strip()
                continue
            works.append({"contractor": current, "line": body})
        elif mode == "supply":
            supplies.append(_LEAD_NUM.sub("", line).strip())
        elif mode == "removal":
            removals.append(_LEAD_NUM.sub("", line).strip())
    # Имя подрядчика в самой строке сильнее заголовка выше: заголовок ставится
    # один раз, а имена идут по строкам.
    works = attribute_works(works, [c["name"] for c in contractors])
    return {
        "contractors": contractors,
        "itr_total": sum(c["itr"] for c in contractors),
        "workers_total": sum(c["workers"] for c in contractors),
        "works": works,
        "supplies": supplies,
        "removals": removals,
        "unparsed": unparsed,
    }


def store_daily_report(project: str, text: str, taken_at: Any) -> dict[str, Any]:
    day = _day(taken_at)
    parsed = parse_daily_report(text)
    if not parsed["contractors"] and not parsed["works"]:
        raise ValueError(
            "В тексте не нашлось ни численности (строк с «ИТР…рабочие…»), "
            "ни секции «По работам» — это не ежедневный отчёт или формат "
            "изменился до неузнаваемости.")
    path = _daily_dir(project) / f"{day.isoformat()}.json"
    replaced = path.exists()
    path.write_text(json.dumps({
        "date": day.isoformat(),
        "text": str(text or ""),
        "parsed": parsed,
        "stored_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "date": day.isoformat(),
        "replaced": replaced,
        "contractors": len(parsed["contractors"]),
        "itr_total": parsed["itr_total"],
        "workers_total": parsed["workers_total"],
        "works": len(parsed["works"]),
        "unparsed": parsed["unparsed"],
    }


# Выгрузка Telegram — HTML, и читается она РАЗБОРОМ, а не образцами.
# Первая версия искала три поля регулярками, и CodeQL был прав, назвав их
# опасными: `<div class="text">(.*?)</div>` и `<[^>]+>` по файлу, который
# приносит человек, уходят в перебор на строке из одних «<». Та же болезнь уже
# ловилась в `_section_of` на строке «поставка» с полусотней тысяч пробелов.
# Разбор при этом не дороже: `html.parser` лежит в стандартной библиотеке,
# идёт по документу один раз и сам разворачивает сущности.
class _TelegramExport(HTMLParser):
    """Пары «день, текст» из выгрузки Telegram.

    Опознаём по разметке экспорта: сообщение — `div.message`, дата — `title`
    у `div.pull_right.date.details`, текст — `div.text`. Служебные сообщения
    (`message service`) пропускаем: это «вошёл в группу», а не сводка.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str]] = []
        self._depth = 0
        self._message_at = -1
        self._service = False
        self._day = ""
        self._text_at = -1
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and self._text_at >= 0:
            self._parts.append("\n")
        if tag != "div":
            return
        self._depth += 1
        classes = ""
        title = ""
        for name, value in attrs:
            if name == "class":
                classes = str(value or "")
            elif name == "title":
                title = str(value or "")
        words = classes.split()
        if "message" in words:
            # Новое сообщение закрывает прежнее: Telegram склеивает подряд
            # идущие сообщения одного автора, и закрывающего тега у каждого
            # не найти — границей служит начало следующего.
            self._flush()
            self._message_at = self._depth
            self._service = "service" in words
            self._day = ""
        elif "date" in words and "details" in words and self._message_at >= 0:
            # Дата берётся из САМОГО сообщения, а не из разделителя дней:
            # разделитель стоит один на день, и сообщение, приехавшее после
            # полуночи, получило бы вчерашний день.
            head = title[:10]
            if len(head) == 10 and head[2] == "." and head[5] == ".":
                day, month, year = head[:2], head[3:5], head[6:]
                if day.isdigit() and month.isdigit() and year.isdigit():
                    self._day = f"{year}-{month}-{day}"
        elif "text" in words and self._message_at >= 0 and self._text_at < 0:
            self._text_at = self._depth
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return
        if self._text_at == self._depth:
            self._text_at = -1
        if self._message_at == self._depth:
            self._flush()
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._text_at >= 0:
            self._parts.append(data)

    def _flush(self) -> None:
        text = "".join(self._parts).strip()
        if text and self._day and not self._service:
            self.rows.append((self._day, text))
        self._message_at = -1
        self._text_at = -1
        self._service = False
        self._day = ""
        self._parts = []

    def close(self) -> None:  # noqa: D102 - хвост документа тоже сообщение
        super().close()
        self._flush()


def read_telegram_export(raw: str) -> list[tuple[str, str]]:
    """Пары «день, текст» из выгрузки Telegram, в порядке чата.

    Служебные сообщения и медиа пропускаются молча — их в стройчате
    большинство (на живой выгрузке 1441 из 1636), и называть каждое значило бы
    утопить в них находку. А вот сколько сообщений прочитано и сколько из них
    оказалось сводками, зовущий обязан сказать вслух: «внесено 44» без «из
    1636 прочитано 139 текстовых» не отвечает, потерялось ли что-нибудь.
    """
    reader = _TelegramExport()
    reader.feed(str(raw or ""))
    reader.close()
    return reader.rows


def store_telegram_export(project: str, raw: str) -> dict[str, Any]:
    """Внести в проект все сводки выгрузки. Разбор и хранение — те же.

    Второго пути к диску не заводим: `store_daily_report` — то же, чем кладёт
    сводку бот, и разойдись они, один и тот же день лёг бы по-разному в
    зависимости от того, пришёл он из чата или из файла.

    День в проекте один, и повторная сводка того же дня его ЗАМЕЩАЕТ — так же,
    как замещает присланная в чат. На живой выгрузке таких дней один из 44;
    молча это выглядело бы потерей, поэтому число замещённых стоит в ответе.
    """
    rows = read_telegram_export(raw)
    stored: list[dict[str, Any]] = []
    skipped = 0
    for day, text in rows:
        try:
            stored.append(store_daily_report(project, text, day))
        except ValueError:
            # Не сводка — обычная переписка. Это норма, а не отказ.
            skipped += 1
    days = sorted({row["date"] for row in stored})
    return {
        "messages": len(rows),
        "stored": len(stored),
        "skipped": skipped,
        "days": len(days),
        "replaced": sum(1 for row in stored if row.get("replaced")),
        "first": days[0] if days else "",
        "last": days[-1] if days else "",
        "reports": stored,
    }


def _load_reports(project: str) -> list[dict[str, Any]]:
    reports = []
    directory = monitor._project_dir(project) / "daily"
    if not directory.is_dir():
        return reports
    for path in sorted(directory.glob("*.json")):
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return reports


def daily_summary(project: str, upto: Any = None, days: int = 45,
                  known: list[str] | None = None) -> dict[str, Any]:
    """Ряды для плитки «Люди на площадке» и последний день словами."""
    reports = _load_reports(project)
    if upto:
        limit = _day(upto)
        reports = [r for r in reports if r.get("date", "") <= limit.isoformat()]
    if not reports:
        return {"available": False,
                "reason": "ежедневные отчёты пока не загружались"}
    reports = reports[-max(1, int(days)):]
    rows = [{
        "date": r["date"],
        "itr": (r.get("parsed") or {}).get("itr_total", 0),
        "workers": (r.get("parsed") or {}).get("workers_total", 0),
        "contractors": len((r.get("parsed") or {}).get("contractors") or []),
    } for r in reports]
    latest = reports[-1]
    parsed = latest.get("parsed") or {}
    # Разрыв в днях между последним отчётом и предпоследним — молчание тоже
    # сигнал: отчёты шли каждый день и перестали.
    gap_days = None
    if len(reports) >= 2:
        gap_days = (monitor._day(reports[-1]["date"])
                    - monitor._day(reports[-2]["date"])).days
    return {
        "available": True,
        "rows": rows,
        "latest": {
            "date": latest["date"],
            "contractors": sorted((parsed.get("contractors") or []),
                                  key=lambda c: -(c["itr"] + c["workers"])),
            # Имена из реестров доезжают сюда же: подрядчик, названный в
            # строке, но не выводивший людей в этот день, в численности
            # отчёта не значится — а работу его назвать надо.
            "works": attribute_works(parsed.get("works") or [],
                                     [c["name"] for c in (parsed.get("contractors") or [])]
                                     + [str(name) for name in (known or [])]),
            "supplies": parsed.get("supplies") or [],
            "removals": parsed.get("removals") or [],
        },
        "gap_days": gap_days,
    }


def _tokens(value: str) -> set[str]:
    return {w.lower().replace("ё", "е") for w in _WORD.findall(str(value or ""))}


def work_liveness(project: str, name: str, cut: Any = None,
                  days: int = 14) -> dict[str, Any]:
    """Упоминалась ли работа в ежедневниках за окно до среза.

    Сверка — пересечением слов от четырёх букв, без лемматизации: «опалубки»
    и «опалубка» не совпадут, поэтому порог — два общих слова, а ответ несёт
    саму строку ежедневника: решает человек, сверка только показывает.
    """
    reports = _load_reports(project)
    if not reports:
        return {"checked": False, "reason": "ежедневников нет"}
    cut_day = _day(cut) if cut else monitor._day(reports[-1]["date"])
    floor = cut_day - datetime.timedelta(days=max(1, int(days)))
    window = [r for r in reports
              if floor.isoformat() <= r.get("date", "") <= cut_day.isoformat()]
    if not window:
        return {"checked": False,
                "reason": f"в окне {days} дн до среза ежедневников нет"}
    want = _tokens(name)
    need = 2 if len(want) >= 2 else 1
    best: dict[str, Any] | None = None
    for report in window:
        for work in ((report.get("parsed") or {}).get("works") or []):
            got = _tokens(work.get("line")) | _tokens(work.get("contractor"))
            overlap = want & got
            if len(overlap) >= need:
                if best is None or report["date"] >= best["date"]:
                    best = {"date": report["date"], "line": work.get("line"),
                            "contractor": work.get("contractor"),
                            "matched": sorted(overlap)}
    return {
        "checked": True,
        "reports_in_window": len(window),
        "days": days,
        "mention": best,
    }
