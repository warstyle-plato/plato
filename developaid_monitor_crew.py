"""Работы дня: кто должен был работать и кто вышел.

«Кто должен был работать судя по договорам и типу работ (это РСС) и кто реально
работал и в каком количестве» (владелец, 29.08.2026).

План берётся из двух источников, которые у нас уже есть, и ни одного нового не
заводится: ГПР говорит, какие работы идут в этот день, а РСС — какой подрядчик
стоит за статьёй этих работ (реестры выполненных работ и платежей несут пару
«код ССР → контрагент»). Факт берётся из ежедневного отчёта с площадки:
подрядчик, ИТР и рабочие.

Сшивка по именам — единственное слабое место, и она названа вслух. «НУР ООО» в
реестре и «Нур» в отчёте — один подрядчик, «СК Термоформ» и «Термоформ» тоже; а
вот несшитое имя не выбрасывается, а показывается отдельной строкой: молча
потерянный подрядчик читается как «его не было».

Здесь ничего не считается о деньгах и сроках — только сопоставление имён и дат.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

# Слова, которые есть у всех и ничего не различают. Без их удаления «ООО НУР» и
# «ООО СТАЛКО» совпадают по слову «ООО».
_NOISE = ("ооо", "оао", "зао", "пао", "ао", "ип", "тд", "гк", "ск", "сз")
_WORD = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def name_key(value: Any) -> str:
    """Ключ имени подрядчика: буквы и цифры, без формы собственности."""
    words = [word.lower().replace("ё", "е") for word in _WORD.findall(str(value or ""))]
    kept = [word for word in words if word not in _NOISE]
    return "".join(kept or words)


def _words(value: Any) -> list[str]:
    """Слова имени без формы собственности."""
    words = [word.lower().replace("ё", "е") for word in _WORD.findall(str(value or ""))]
    kept = [word for word in words if word not in _NOISE]
    return kept or words


def is_acronym(short: str, words: list[str]) -> bool:
    """Сокращение ли `short` от `words`: «СПМ» от «СП Менеджмент».

    Сокращение обязано разобраться на приставки ВСЕХ слов по порядку, и каждое
    слово должно дать хотя бы букву: иначе «СПМ» сойдётся с чем угодно, где
    есть буква «с». Двух знаков мало — на них совпадают половина подрядчиков.
    """
    text = str(short or "")
    if len(text) < 3 or not words:
        return False

    def walk(rest: str, index: int) -> bool:
        if index == len(words):
            return not rest
        word = words[index]
        for take in range(1, min(len(word), len(rest)) + 1):
            if rest[:take] != word[:take]:
                break
            if walk(rest[take:], index + 1):
                return True
        return False

    return walk(text, 0)


def same_party(left: str, right: str) -> bool:
    """Одно ли это лицо.

    Три способа, и каждый со своим ограничением. Равенство ключей — всегда.
    Вхождение — с четырёх знаков: «Нур» внутри «Стройэнергонур» это совпадение
    по букве, а не по лицу. И сокращение по первым буквам слов: «СПМ» и есть
    «СП Менеджмент» (владелец, 30.08.2026) — реестр пишет полное имя, отчёт с
    площадки сокращает.
    """
    first, second = name_key(left), name_key(right)
    if not first or not second:
        return False
    if first == second:
        return True
    if is_acronym(first, _words(right)) or is_acronym(second, _words(left)):
        return True
    if min(len(first), len(second)) < 4:
        return False
    return first in second or second in first


def contractors_by_code(*registers: Any) -> dict[str, list[str]]:
    """Пара «код ССР → подрядчики» из реестров РСС.

    Берётся из того, что уже прочитано: реестр выполненных работ и реестр
    платежей несут и код статьи, и контрагента. Своего справочника договоров не
    заводим — он стал бы вторым мнением о том, кто за статью отвечает.
    """
    found: dict[str, dict[str, str]] = {}
    for register in registers:
        for row in ((register or {}).get("rows") or []):
            code = str(row.get("estimate_code") or row.get("code") or "").strip()
            name = str(row.get("contractor") or row.get("counterparty") or "").strip()
            if not code or not name:
                continue
            found.setdefault(code, {}).setdefault(name_key(name), name)
    return {code: sorted(names.values()) for code, names in found.items()}


def _day(value: Any) -> datetime.date | None:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def planned(rows: list[dict[str, Any]], by_code: dict[str, list[str]],
            day: Any) -> list[dict[str, Any]]:
    """Работы, которые по ГПР идут в этот день, и подрядчики их статей."""
    when = _day(day)
    if when is None:
        return []
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        start, finish = _day(row.get("plan_start")), _day(row.get("plan_finish"))
        if not start or not finish or not (start <= when <= finish):
            continue
        code = str(row.get("code") or "").strip()
        item = out.setdefault(code or f"без кода:{row.get('name')}", {
            "code": code, "works": [], "contractors": by_code.get(code, [])})
        item["works"].append(str(row.get("name") or row.get("wbs") or "").strip())
    return sorted(out.values(), key=lambda item: item["code"])


def crew_day(rows: list[dict[str, Any]], by_code: dict[str, list[str]],
             report: dict[str, Any] | None, day: Any) -> dict[str, Any]:
    """Сопоставление плана и факта одного дня.

    Ни одна сторона не выбрасывается молча: подрядчик, которого нет в плане,
    и работа, на которую никто не вышел, — обе стороны разрыва, и обе видны.
    """
    when = _day(day)
    plan = planned(rows, by_code, when)
    parsed = (report or {}).get("parsed") or report or {}
    actual = [
        {"name": str(item.get("name") or "").strip(),
         "itr": int(item.get("itr") or 0),
         "workers": int(item.get("workers") or 0)}
        for item in (parsed.get("contractors") or [])
    ]
    lines: dict[str, list[str]] = {}
    for work in parsed.get("works") or []:
        lines.setdefault(name_key(work.get("contractor")), []).append(
            str(work.get("line") or "").strip())

    expected: list[str] = []
    for item in plan:
        for name in item["contractors"]:
            if not any(same_party(name, seen) for seen in expected):
                expected.append(name)

    matched, missing, extra = [], [], []
    for name in expected:
        found = next((item for item in actual if same_party(name, item["name"])), None)
        if found:
            matched.append({**found, "planned_as": name,
                            "lines": lines.get(name_key(found["name"]), [])})
        else:
            missing.append({"name": name,
                            "codes": [item["code"] for item in plan
                                      if any(same_party(name, other)
                                             for other in item["contractors"])]})
    for item in actual:
        if not any(same_party(item["name"], name) for name in expected):
            extra.append({**item, "lines": lines.get(name_key(item["name"]), [])})

    notes: list[str] = []
    if not rows:
        notes.append("график (ГПР) не загружен — кто должен был работать, сказать нечем")
    elif not plan:
        notes.append("по графику в этот день не идёт ни одна работа")
    if not by_code:
        notes.append("в реестрах РСС нет пары «код статьи — контрагент»: "
                     "подрядчиков к работам привязать нечем")
    if report is None:
        notes.append("ежедневного отчёта за этот день нет")
    elif not actual:
        notes.append("в отчёте за этот день нет численности по подрядчикам")
    if extra and not missing and not matched:
        notes.append("ни одно имя из отчёта не сошлось с реестрами — "
                     "проверьте написание подрядчиков")

    return {
        "date": when.isoformat() if when else "",
        "planned": plan,
        "expected": expected,
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "people": {"itr": sum(item["itr"] for item in actual),
                   "workers": sum(item["workers"] for item in actual),
                   "contractors": len(actual)},
        "notes": notes,
    }
