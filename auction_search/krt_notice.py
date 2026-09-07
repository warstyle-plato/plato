"""Приложение № 2 к извещению о торгах: участки, объекты на них и их судьба.

Извещение ДГП-Р-54/26 от 14.08.2026 (КРТ нежилой застройки 14,62 га по адресам
Варшавское ш., влд. 37 и Нагатинская ул., влд. 3А/6) несёт таблицу состава
территории: земельный участок, его площадь, объекты капитального строительства
на нём с площадью и пометкой «снос/реконструкция/сохранение».

Зачем читать её, когда рядом есть проект решения. Это **два разных документа
города, и они не совпадают**: в проекте решения (mos.ru, январь) 40 объектов на
51 777,2 м², в извещении (август) — 39 на 54 871,9 м². Выбыли `:1053` (29,3 м²)
и `:2077` (23,2 м²), добавилось `:1951` (2 490,9 м²), а у `:2091` в решении в
графе площади стоит слово «часть», в извещении — 656,3 м². Извещение свежее и
оно основание торгов, поэтому состав территории берётся из него, а расхождение
с решением называется, а не выбирается молча.

Три правила разбора, каждое стоило отдельного захода.

**Колонку задаёт координата, а не порядок в тексте.** Адреса переносятся на
несколько строк, и текст страницы идёт вперемешку: номер участка стоит при
x≈90, объекта — при x≈390, площадь объекта — при x≈630, судьба — при x≈700.

**Слово в графе числа — это не число.** У `:2091` там «часть»; разбор, который
подбирает ближайший похожий токен, дал 4,0 м² и завысил итог документа ровно на
столько. Пустая площадь возвращается как `None` и называется своей причиной.

**Один объект стоит на нескольких участках.** В таблице он повторяется строкой
под каждым, и складывать эти строки нельзя: 47 строк — это 39 объектов.

Запуск проверок: python3 -m pytest tests/test_the_krt_notice_is_read.py -q
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CAD = re.compile(r"^\d+:\d+:\d+:\d+$")

# Границы колонок таблицы приложения, в точках PDF. Читаются они по координате
# слова, а не по его месту в тексте: адрес переносится на несколько строк.
COLUMNS = {
    "land": (80, 140),
    "land_area": (315, 350),
    "object": (380, 435),
    "object_area": (615, 665),
    "fate": (690, 745),
}


class NoticeProblem(RuntimeError):
    """Таблицы в документе нет или она не разобралась. Это отказ, а не пустой состав."""


# Число графы — ОДНО, а не склейка всех цифр ячейки. Прежняя строка выбрасывала
# из текста всё, кроме цифр, и на строке участка 77:05:0004001:8 ячейка пришла
# с чужим хвостом («2 896 6 097 недвижимого особыми…» — соседняя колонка
# заехала в окно координат): выходило 28 966 097 м² вместо 2 896, и сумма
# площадей участков давала 2 910 га на территории в 14. Тот же род ошибки, что
# «3 306 021 ₽/м²» → 306 021: число берут целиком и одно.
#
# Разряды по-русски идут ровно по три цифры, поэтому «2 896 6 097» честно
# рвётся после «2 896», а «43 288,61» читается целиком.
# Первая группа — любой длины: «2490,9» пишут и без разделителя разрядов, а
# `\\d{1,3}` резал его до 249. Разделённые пробелом группы по-прежнему ровно
# по три цифры, поэтому «2 896 6 097» рвётся после «2 896».
_ONE_NUMBER = re.compile("\\d+(?:[ \u00a0]\\d{3})*(?:[.,]\\d+)?")


def _number(text: str) -> float | None:
    """Число из графы. Слово («часть», «отсутствуют») — это не число.

    Хвост после числа не выбрасывается молча: сырая ячейка возвращается полем
    `area_raw`, и на экране видно, что именно прочитано.
    """
    match = _ONE_NUMBER.search(text or "")
    if not match:
        return None
    clean = match.group(0).replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return None


def _lines(pdf_path: Path) -> list[dict[str, str]]:
    try:
        import pymupdf
    except Exception as exc:  # noqa: BLE001 — отсутствие растеризатора называется
        raise NoticeProblem(f"нечем прочитать PDF: {exc}") from exc
    document = pymupdf.open(pdf_path)
    rows: list[dict[str, str]] = []
    for page in document:
        by_line: dict[float, list[tuple[float, str]]] = {}
        for x0, y0, _x1, _y1, word, *_rest in page.get_text("words"):
            by_line.setdefault(round(y0 / 3) * 3, []).append((x0, word))
        for key in sorted(by_line):
            tokens = sorted(by_line[key])
            rows.append({name: " ".join(word for x, word in tokens if left <= x < right)
                         for name, (left, right) in COLUMNS.items()})
    return rows


def read(pdf_path: str | Path) -> dict[str, Any]:
    """Состав территории по извещению: участки и объекты на них."""
    lands: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_object: dict[str, Any] | None = None
    for line in _lines(Path(pdf_path)):
        head = line["land"].split()[0] if line["land"] else ""
        if CAD.match(head):
            current = {"cadastral_number": head, "part": "часть" in line["land"],
                       "area_raw": "", "objects": []}
            lands.append(current)
            current_object = None
        # Земля БЕЗ кадастрового номера — тоже часть площадки: «Территории, в
        # границах которых земельные участки не сформированы — 6 097 м²».
        # Прежде эта строка не начиналась номером и не заводила своей записи, а
        # её площадь дописывалась в ячейку предыдущего участка: 6 097 м²
        # пропадали, и сумма земли не сходилась с площадкой извещения ровно на
        # них (14,01 га против 14,62). Без этой строки «у тебя сумма участков
        # 19 почти, а по решению 14» объяснялось наполовину.
        elif line["land"].startswith("Территори"):
            current = {"cadastral_number": "", "part": False, "area_raw": "",
                       "unformed": True, "objects": []}
            lands.append(current)
            current_object = None
        if current is None:
            continue
        if "часть" in line["land"]:
            current["part"] = True
        if line["land_area"]:
            current["area_raw"] = (current["area_raw"] + " " + line["land_area"]).strip()
        head = line["object"].split()[0] if line["object"] else ""
        if CAD.match(head):
            current_object = {"cadastral_number": head, "part": "часть" in line["object"],
                              "area_raw": "", "fate": ""}
            current["objects"].append(current_object)
        if current_object is None:
            continue
        if "часть" in line["object"]:
            current_object["part"] = True
        if line["object_area"]:
            current_object["area_raw"] = (current_object["area_raw"] + " "
                                          + line["object_area"]).strip()
        if line["fate"]:
            current_object["fate"] = (current_object["fate"] + " " + line["fate"]).strip()
    if not lands:
        raise NoticeProblem("в документе не нашлось таблицы состава территории")
    objects: dict[str, dict[str, Any]] = {}
    for land in lands:
        land["area_sqm"] = _number(land["area_raw"])
        for item in land["objects"]:
            item["area_sqm"] = _number(item["area_raw"])
            item["fate"] = " ".join(item["fate"].replace("/ ", "/").split())
            known = objects.setdefault(item["cadastral_number"], {
                "cadastral_number": item["cadastral_number"],
                "area_sqm": item["area_sqm"], "area_raw": item["area_raw"],
                "fate": item["fate"], "part": item["part"], "lands": []})
            known["lands"].append(land["cadastral_number"])
    return {
        # Записи без кадастрового номера стоят отдельно: это площадь площадки,
        # но не участок, и в списке участков ей делать нечего.
        "lands": [land for land in lands if land["cadastral_number"]],
        "unformed": [land for land in lands if not land["cadastral_number"]],
        # Объект, стоящий на нескольких участках, в таблице повторяется строкой
        # под каждым: 47 строк — это 39 объектов, и складывать строки нельзя.
        "objects": sorted(objects.values(), key=lambda item: item["cadastral_number"]),
        "rows": sum(len(land["objects"]) for land in lands),
    }
