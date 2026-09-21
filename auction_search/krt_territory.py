"""Состав территории любой площадки КРТ — теми же вопросами, что у Нагатино.

«Цель была чтобы все крт с торгов разбирались по образу и подобию Нагатино»
(владелец, 13.09.2026). Вопросы у площадки те же — что за участки входят в
территорию, чьи они, сколько метров и какой кадастровой стоимости, что стоит на
каждом участке и что из этого сносят, — а источники другие: у Нагатино владелец
прислал выгрузку по кварталу, у площадки с торгов её нет и не будет.

Отсюда устройство: свод считает ОДИН сборщик (`nagatino_parcels.territory`),
а этот модуль отвечает только на «откуда документы». Второй сборки не
заводим — разойдясь, две сборки дали бы два достоверных на вид ответа об одной
территории; ровно так уже расходились бот с сайтом, отчёт с книгой и книга с
движком.

Источников у площадки с торгов два, и оба уже читаются:

- **состав территории** — приложение 2 к извещению о торгах, разобранное
  `krt_notice` при чтении вложений лота. Оно свежее проекта решения и оно
  основание торгов;
- **свойства и собственники** — выписки ЕГРН из лотовой документации и
  присланные руками зипы, сложенные в `egrn_store` по ключу лота.

Три правила, каждое стоит ошибки, которую иначе не увидеть.

**Пустой состав — это «не читали», а не «территория пуста».** У шести КРТ из
одиннадцати с живым лотом перечня участков нет ни в извещении, ни в проекте
решения (замер прода 13.09.2026), и молча показанная пустая карта читалась бы
как площадка без объектов. Причина называется у самой карты.

**Перечень проекта решения — запасной состав, и он беднее.** Он называет
участки поимённо и НЕ говорит, что на каком стоит и что сносят: привязки
«объект → участок» в нём нет. Подставленный молча, он выглядел бы как полный
состав из извещения, поэтому у свода стоит, каким документом он собран.

**Группы владельца — только у Нагатино.** «Брынцалов красный, Москва зелёная»
— его слова о конкретных лицах конкретной площадки (07.09.2026). У прочих
площадок групп нет, и приписанная группа на экране выглядит ровно так же
уверенно, как названная; остаётся зелёный у города и жёлтая гамма по владельцу.

Запуск проверок: python3 -m pytest tests/test_a_krt_site_is_read_like_nagatino.py -q
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from auction_search import egrn_store, nagatino_parcels

SCHEMA_VERSION = 1


def data_dir() -> Path:
    """Где лежат склады. Спрашивается при обращении, а не на импорте: в прогоне
    `DATA_DIR` подменяется временным каталогом, и запомненный путь увёл бы
    проверки писать в рабочее дерево репозитория."""
    return Path(os.getenv("DATA_DIR", "data")) / "market"


def notice_path(key: str, *, root: Path | None = None) -> Path:
    return ((root or data_dir()) / "krt" / "notice"
            / f"{egrn_store.slug(key)}.json")


def remember_notice(key: str, notice: dict[str, Any], *,
                    document: str = "", root: Path | None = None) -> None:
    """Положить разобранный состав территории. Хранится РАЗОБРАННОЕ.

    Пустой состав не вытесняет прочитанный: у лота несколько вложений, и
    таблица стоит в одном из них — записав пустоту поверх, мы стёрли бы
    прочитанное соседним вложением.
    """
    lands = list(notice.get("lands") or [])
    if not lands:
        return
    place = notice_path(key, root=root)
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "key": str(key),
        "document": str(document or ""),
        "read_at": int(time.time()),
        "notice": notice,
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def attempt_path(key: str, *, root: Path | None = None) -> Path:
    return ((root or data_dir()) / "krt" / "notice"
            / f"{egrn_store.slug(key)}.attempt.json")


# Своя длительность у каждого ответа. Успех вечен — состав лежит разобранным и
# второй раз не спрашивается вовсе; «таблицы в вложениях нет» — ответ
# ДОКУМЕНТОВ, и он живёт сутки: лотовую документацию площадка дополняет, но не
# каждый час; отказ площадки — полчаса, потому что Росэлторг отдаёт файл через
# раз и его «нет» свойством лота не является. Правило то же, что у отказа
# карточки города: запасной ответ не живёт в кэше наравне со штатным.
NO_TABLE_TTL_SECONDS = 86400
REFUSED_TTL_SECONDS = 1800


def remember_attempt(key: str, *, outcome: str, why: str = "",
                     documents: int = 0, root: Path | None = None) -> None:
    """Записать, чем кончилась попытка прочитать извещение лота.

    Незаписанный отказ нельзя посчитать, а непосчитанный отказ выглядит как
    отсутствие состава у площадки: ровно так «прогон до лота ещё не дошёл» и
    «вложения прочитаны, таблицы в них нет» сливались в одну немую строку.
    Отметка нужна и прогону — чтобы не платить минутами внешних запросов за
    один и тот же ответ каждые три часа.
    """
    place = attempt_path(key, root=root)
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "key": str(key),
        "outcome": str(outcome),
        "why": str(why or "")[:400],
        "documents": int(documents or 0),
        "at": int(time.time()),
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def stored_attempt(key: str, *, root: Path | None = None) -> dict[str, Any]:
    """Отметка попытки. Нет отметки — «не спрашивали», а не «спросили и пусто»."""
    place = attempt_path(key, root=root)
    if not place.exists():
        return {}
    try:
        got = json.loads(place.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — негодная отметка равна отсутствию
        return {}
    if not isinstance(got, dict) or got.get("schema_version") != SCHEMA_VERSION:
        return {}
    return got


def notice_due(key: str, *, root: Path | None = None,
               now: float | None = None) -> bool:
    """Надо ли спрашивать площадку об извещении этого лота.

    Состав уже разобран — не надо вовсе: он не устаревает, торги идут по одному
    извещению. Иначе решает срок ответа, которым кончилась прошлая попытка.
    """
    if stored_notice(key, root=root).get("lands"):
        return False
    attempt = stored_attempt(key, root=root)
    if not attempt:
        return True
    # Срок берётся по ЧЬЕМУ это пробелу. Перебой площадки лечится вторым
    # заходом через полчаса; «таблицы в прочитанном нет», «читателя лота у нас
    # нет» и «вложение не прочитали мы» вторым заходом не лечатся вовсе —
    # байты уже на складе, и до починки читателя ответ тот же.
    ttl = (NO_TABLE_TTL_SECONDS
           if attempt.get("outcome") in {"no_table", "unsupported", "unread"}
           else REFUSED_TTL_SECONDS)
    return float(now if now is not None else time.time()) - float(
        attempt.get("at") or 0) >= ttl


def _attempt_problem(attempt: dict[str, Any]) -> str:
    """Чей это пробел — наш, документов или площадки. Три разных ответа.

    «Извещение лота ещё не разбиралось» было верно и немо: оно не различало
    «прогон до него ещё не дошёл» (наш пробел, придёт само), «вложения
    прочитаны, таблицы состава в них нет» (ответ документов) и «площадка не
    отдала вложения» (ответ площадки, спросим снова).

    Четвёртый ответ пришёл с МКАД, 41 км: площадка отдала все 27 вложений
    (`asked 27, fetched 27`), а текст трёх не извлёк наш читатель — два скана
    PDF и архив со скриншотами. Прежде это печаталось как «площадка не отдала
    вложения лота», то есть наш пробел приписывался Росэлторгу, и рядом
    обещалось «спросим снова», хотя второй заход ничего не меняет.
    """
    if not attempt:
        return ("состав территории ещё не читали: прогон до извещения этого "
                "лота не дошёл — это наш пробел, а не ответ документов")
    when = ""
    try:
        when = time.strftime("%d.%m.%Y %H:%M",
                             time.localtime(float(attempt.get("at") or 0)))
    except Exception:  # noqa: BLE001
        when = ""
    seen = f" (прочитано {when})" if when else ""
    count = int(attempt.get("documents") or 0)
    if attempt.get("outcome") == "no_table":
        return (f"вложения лота прочитаны{seen}"
                + (f", их {count}" if count else "")
                + " — таблицы состава территории в них нет")
    why = str(attempt.get("why") or "").strip()
    if attempt.get("outcome") == "unread":
        # Площадка отдала всё, а текст из части вложений не извлёк НАШ
        # читатель: сканы PDF и архивы картинок. Это наш пробел, и «спросим
        # снова» здесь было бы обещанием, которого второй заход не исполнит:
        # байты лежат на складе, лечит распознавание.
        return ("вложения лота площадка отдала"
                + (f", их {count} прочитано" if count else "")
                + f", но {why} — таблицы состава нет в прочитанных, а в "
                  "непрочитанных её не искали. Это наш пробел: заново качать "
                  "нечего, нужен читатель" + seen)
    if attempt.get("outcome") == "unsupported":
        # Отказ, который вторым заходом не лечится: у площадки нет читателя
        # или лот прочитан не как КРТ. Спрашивать её об этом каждые полчаса
        # значит платить за один и тот же ответ.
        return ("лот этой площадки нашим разбором не читается"
                + (f": {why}" if why else ""))
    return ("площадка не отдала вложения лота"
            + (f": {why}" if why else "") + seen + ". Спросим снова")


def run_path(*, root: Path | None = None) -> Path:
    return (root or data_dir()) / "krt" / "notice" / "run.json"


def remember_run(summary: dict[str, Any], *, root: Path | None = None) -> None:
    """Свод последнего прохода за извещениями. У молчащего прогона обязан быть
    счётчик молчания: снаружи «состава ни у кого нет», «прогон выключен» и
    «прогон сломан» — одно и то же молчание."""
    place = run_path(root=root)
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(json.dumps({"schema_version": SCHEMA_VERSION,
                                 **dict(summary or {})},
                                ensure_ascii=False, indent=1), encoding="utf-8")


def stored_run(*, root: Path | None = None) -> dict[str, Any]:
    """Свод прохода. Нет файла — «проход здесь ещё не заходил»."""
    place = run_path(root=root)
    if not place.exists():
        return {}
    try:
        got = json.loads(place.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return got if isinstance(got, dict) else {}


def stored_notice(key: str, *, root: Path | None = None) -> dict[str, Any]:
    """Состав территории со склада. Нечитаемый файл — пустой состав с причиной."""
    place = notice_path(key, root=root)
    if not place.exists():
        # Причина называет, ЧЬЁ это молчание: без отметки попытки — наше,
        # с отметкой — документов или площадки.
        return {"lands": [], "objects": [], "rows": 0,
                "problem": _attempt_problem(stored_attempt(key, root=root))}
    try:
        got = json.loads(place.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — негодный файл называется
        return {"lands": [], "objects": [], "rows": 0,
                "problem": f"склад состава не прочитан: {type(exc).__name__}: {exc}"[:200]}
    if not isinstance(got, dict) or got.get("schema_version") != SCHEMA_VERSION:
        return {"lands": [], "objects": [], "rows": 0,
                "problem": "у склада состава чужая схема"}
    notice = got.get("notice")
    if not isinstance(notice, dict):
        return {"lands": [], "objects": [], "rows": 0,
                "problem": "в складе состава нет самого состава"}
    return {**notice, "document": str(got.get("document") or ""),
            "read_at": got.get("read_at")}


def _from_decision(numbers: list[str]) -> dict[str, Any]:
    """Запасной состав: перечень участков проекта решения.

    Беднее извещения намеренно — привязки «объект → участок» в решении нет, и
    выдумывать её нельзя. Что состав собран так, стоит полем `source`.
    """
    return {
        "lands": [{"cadastral_number": number, "part": False,
                   "area_raw": "", "area_sqm": None, "objects": []}
                  for number in numbers],
        "objects": [],
        "rows": len(numbers),
        "source": "decision",
        "problem": "",
    }


def composition(key: str, decision_numbers: list[str] | None = None, *,
                root: Path | None = None) -> dict[str, Any]:
    """Состав территории: извещение, а нет его — перечень проекта решения."""
    notice = stored_notice(key, root=root)
    if notice.get("lands"):
        return {**notice, "source": "notice"}
    numbers = [str(number) for number in (decision_numbers or []) if number]
    if numbers:
        return {**_from_decision(numbers),
                "problem": notice.get("problem") or ""}
    return {**notice, "source": "",
            "problem": (notice.get("problem")
                        or "ни извещение, ни проект решения не назвали участков")}


def _records(key: str, *, root: Path | None = None) -> dict[str, dict[str, Any]]:
    kept = egrn_store.load((root or data_dir()), key)
    out: dict[str, dict[str, Any]] = {}
    for record in kept.get("records") or []:
        number = str(record.get("cadastral_number") or "")
        if number:
            out[number] = record
    return out


def documents_for(key: str, decision_numbers: list[str] | None = None, *,
                  root: Path | None = None) -> dict[str, Any]:
    """Первоисточники площадки в той же форме, в какой их ждёт сборщик свода."""
    records = _records(key, root=root)
    builds = {number: record for number, record in records.items()
              if record.get("kind") != "land"}
    lands = {number: record for number, record in records.items()
             if record.get("kind") == "land"}
    notice = composition(key, decision_numbers, root=root)
    return {"builds": builds, "lands": lands, "notice": notice, "problems": []}


def site_for(slug: str, title: str = "", *, key: str = "",
             decision_numbers: list[str] | None = None,
             root: Path | None = None) -> nagatino_parcels.Site:
    """Площадка с торгов как источник для общего сборщика свода.

    Ключ склада — ключ ЛОТА (по нему лежат выписки), а ключ кэша контуров —
    слаг площадки: у одной площадки лотов бывает несколько, а территория у неё
    одна. Смешать их значило бы потерять контуры при смене лота.
    """
    store_key = str(key or slug)
    return nagatino_parcels.Site(
        key=f"site-{egrn_store.slug(slug)}",
        title=str(title or slug),
        registry=nagatino_parcels.empty_registry,
        documents=lambda: documents_for(store_key, decision_numbers, root=root),
        slug=str(slug),
    )
