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

from auction_search import archives, egrn_extracts, egrn_print_form

# Сколько печатных форм БЕЗ текстового слоя распознаём на один архив.
# Распознавание стоит до минуты на страницу (`pdf_ocr.PAGE_TIMEOUT_SECONDS`), а
# архив приходит с чужой машины: четыреста сканов держали бы человека часами.
# Предел назван числом, и упёршийся в него файл стоит в непрочитанном со своей
# причиной — обрезка без слов неотличима от архива без выписок.
OCR_BUDGET_DOCUMENTS = 3

# Версия правил чтения вложения. Стоит рядом с каждой записью склада, и это не
# украшение: свод территории считается из РАЗОБРАННОГО на диске, а проход за
# извещениями прочитанное больше не спрашивает — значит починка читателя до уже
# прочитанных лотов не доезжает НИКОГДА. 14.09.2026 это стоило видимого
# результата выпуска: краткая форма выписки уже читалась, а на 1-й Горловской
# по-прежнему стояло «выписки на объект нет» у всех 19 участков, и собственники
# (ООО «СОКОЛ», физлицо) появились только после того, как лот перечитали рукой.
# На экране НАШ пробел читался как молчание документа.
#
# Правило то же, что у привязки публикаций (`ANCHOR_RULES_VERSION`) и у
# диагноза съехавшей карточки: хранимая производная расходится с правилом
# молча. Версия поднимается, когда меняется ОТВЕТ читателя на те же байты, —
# не на всякую правку рядом.
#
# 1 — до краткой формы: читалась только «об объекте недвижимости», всё прочее
#     уходило в непрочитанное («не выписка ЕГРН об объекте»).
# 2 — краткая форма «об основных характеристиках и зарегистрированных правах»
#     и печатная форма PDF.
READER_VERSION = 2

# Записи без этого поля разобраны до того, как версию завели, — то есть
# читателем первой версии. Ноль тут был бы третьим ответом на тот же вопрос.
READER_VERSION_BEFORE = 1

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
    # HTML-формы в руках не было ни одной: разбор написан по PDF, и пускать в
    # него чужой вид значило бы отвечать ошибкой там, где файл цел.
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
    # Печатные формы читаются ВТОРЫМ проходом: машинная выписка отвечает на то,
    # чего печатная не раскрывает вовсе (имя правообладателя), и при двух
    # документах на один объект выбор между ними делаем не порядком записей в
    # архиве. Печатная форма того же объекта не выбрасывается молча — она
    # названа спутником с причиной.
    print_forms: list[archives.Entry] = []
    ocr_spent = 0
    for entry in entries:
        companion = COMPANION_SUFFIXES.get(entry.suffix)
        if companion:
            kind, reason = companion
            result["companions"].append(
                {"name": entry.name, "kind": kind, "reason": reason})
            continue
        if entry.suffix == ".pdf" or archives.looks_like_pdf(entry.data):
            print_forms.append(entry)
            continue
        # Спутник опознаётся ИМЕНЕМ и до разбора: таблица стилей — тоже XML, и
        # пущенная в разбор выписки она отвечает ошибкой, то есть попадала бы в
        # непрочитанное и обвиняла архив там, где всё на месте.
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
        record["source"] = "xml"
        record["source_entry"] = entry.name
        result["records"].append(record)

    from_xml = {str(record.get("cadastral_number") or "")
                for record in result["records"]}
    for entry in print_forms:
        try:
            record = egrn_print_form.read(
                entry.data, ocr=ocr_spent < OCR_BUDGET_DOCUMENTS)
        except egrn_print_form.NoTextLayer as exc:
            ocr_spent += 1
            result["unread"].append({"name": entry.name, "reason": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001
            result["unread"].append({
                "name": entry.name,
                "reason": (str(exc) if isinstance(exc, ValueError)
                           else f"{type(exc).__name__}: {exc}")[:200],
            })
            continue
        if record.get("text_source") == "ocr":
            ocr_spent += 1
        number = str(record.get("cadastral_number") or "")
        if number in from_xml:
            result["companions"].append({
                "name": entry.name, "kind": "print_form",
                "reason": f"печатная форма {number} рядом с машинной выпиской",
            })
            continue
        seen[number] = seen.get(number, 0) + 1
        record["source_entry"] = entry.name
        result["records"].append(record)

    result["duplicates"] = sorted(number for number, count in seen.items() if count > 1)
    result["read"] = len(result["records"])
    # Чем прочитана запись — часть записи, и версия правил здесь же: у склада
    # нет другого способа узнать, что разбор устарел. Ставится в ОДНОМ месте на
    # обоих читателей: две копии версии разошлись бы, и половина записей
    # выглядела бы свежей.
    for record in result["records"]:
        record["reader_version"] = READER_VERSION
    result["reader_version"] = READER_VERSION
    return result
