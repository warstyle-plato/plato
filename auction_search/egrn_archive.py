"""Архив выписок ЕГРН → записи. Второго разбора выписки здесь нет.

Выписки на Росэлторге называются выписками и лежат в зипах (владелец,
12.09.2026). Разбор одного файла уже есть — `egrn_extracts.read`, написанный по
59 живым выпискам квартала 77:05:0004001, — и здесь он не повторяется: этот
модуль отвечает только на «что в архиве лежит и что из этого выписка».

Три правила.

**Вид записи решает содержимое, а не расширение.** КУВИ приходит и как
`*.xml`, и без расширения вовсе, а `.xml` в том же архиве бывает таблицей
стилей. Выпиской запись становится, когда её корень — выписка об объекте; всё
прочее называется тем, что оно есть.

**Спутник выписки — не наша неудача.** Отсоединённая подпись (`.sig`, `.p7s`),
печатная форма и картинки плана лежат рядом по построению. Свалить их в один
список с непрочитанным значило бы обвинить архив там, где всё на месте, —
поэтому они стоят отдельной строкой и балла никому не снижают.

**Один номер дважды — это выбор, и его делаем не мы.** Две выписки на один
объект бывают разных дат, и «последняя выигрывает» здесь означало бы, что
порядок записей в архиве решает, чей ответ верен. Обе записи остаются, а
повторившиеся номера названы числом.

Запуск проверок: python3 -m pytest tests/test_the_egrn_archive_is_read.py -q
"""

from __future__ import annotations

from typing import Any

from auction_search import archives, egrn_extracts

# Спутники выписки: лежат в архиве по построению и выпиской не являются.
#
# Вид спутника назван рядом с причиной, и это не украшение. Подпись и таблица
# стилей лежат РЯДОМ с машинной выпиской, а печатная форма бывает единственным
# содержимым архива: у Росэлторга так приходят все выписки лотовой
# документации (измерено 13.09.2026 на пяти живых КРТ-лотах — 32 PDF и ни
# одного XML). «Рядом с выпиской лежала подпись» и «машинной выписки в лоте
# нет вовсе» — разные ответы, а одним числом `companions` они неразличимы.
COMPANION_SUFFIXES = {
    ".sig": ("signature", "отсоединённая подпись"),
    ".p7s": ("signature", "отсоединённая подпись"),
    ".sgn": ("signature", "отсоединённая подпись"),
    ".xsl": ("stylesheet", "таблица стилей выписки"),
    ".xslt": ("stylesheet", "таблица стилей выписки"),
    ".pdf": ("print_form", "печатная форма выписки"),
    ".html": ("print_form", "печатная форма выписки"),
    ".htm": ("print_form", "печатная форма выписки"),
    ".png": ("image", "картинка приложения"),
    ".jpg": ("image", "картинка приложения"),
    ".jpeg": ("image", "картинка приложения"),
    ".tif": ("image", "картинка приложения"),
    ".tiff": ("image", "картинка приложения"),
}


def looks_like_xml(data: bytes) -> bool:
    head = data[:400].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head[:1] == b"<"


def read(data: bytes, *, name: str = "") -> dict[str, Any]:
    """Архив (или одиночная выписка) → записи и названный остаток."""
    result: dict[str, Any] = {
        "records": [], "unread": [], "companions": [],
        "entries": 0, "archives": 0, "duplicates": [],
    }
    if archives.looks_like_zip(data):
        try:
            opened = archives.open_zip(data, name="")
        except archives.ArchiveProblem as exc:
            result["unread"].append({"name": name or "архив", "reason": str(exc)})
            return result
        entries = opened.entries
        result["unread"].extend(opened.refused)
        result["archives"] = opened.archives
    else:
        entries = [archives.Entry(name=name or "вложение", data=data)]
    result["entries"] = len(entries)

    seen: dict[str, int] = {}
    for entry in entries:
        # Спутник опознаётся ИМЕНЕМ и до разбора: таблица стилей — тоже XML, и
        # пущенная в разбор выписки она отвечает ошибкой, то есть попадала бы в
        # непрочитанное и обвиняла архив там, где всё на месте.
        companion = COMPANION_SUFFIXES.get(entry.suffix)
        if companion:
            kind, reason = companion
            result["companions"].append(
                {"name": entry.name, "kind": kind, "reason": reason})
            continue
        if not looks_like_xml(entry.data):
            result["unread"].append({"name": entry.name, "reason": "не XML выписки"})
            continue
        try:
            record = egrn_extracts.read(entry.data)
        except Exception as exc:  # noqa: BLE001 — негодный файл называется своей ошибкой
            result["unread"].append({
                "name": entry.name,
                "reason": (str(exc) if isinstance(exc, ValueError)
                           else f"{type(exc).__name__}: {exc}")[:200],
            })
            continue
        number = str(record.get("cadastral_number") or "")
        seen[number] = seen.get(number, 0) + 1
        record["source_entry"] = entry.name
        result["records"].append(record)
    result["duplicates"] = sorted(number for number, count in seen.items() if count > 1)
    result["read"] = len(result["records"])
    return result
