"""Заполненный шаблон ТЭП на сайте: раньше он молча превращался в прочерки.

Владелец заполнил шаблон, который сам бот и выдаёт по `/template`, и загрузил
его на страницу. Страница ответила «Файл распознан» и показала таблицу из
прочерков: площадь территории «—», площадь квартир «—», смена ВРИ «—».

Причина в том, что страница знала один формат. Единственное поле загрузки
слало файл в `/import/glavapu`, разбор ГлавАПУ не отказывался от чужой книги,
не находил ни одного своего показателя и возвращал набор из одних None. Пустой
разбор считался успехом — та же ошибка, что была в боте, только здесь она не
приводила к сбою, а показывала пустоту с видом ответа.

При этом всё нужное уже существовало: `/import/manual-tep` разбирает шаблон
целиком, а `applyTelegramManualTep` умеет разложить его по вкладкам — этим
путём приходят проекты из Telegram. Не хватало одной попытки.

Проверено в живом Chromium: файл владельца даёт квартиры 29 308,89 м² и
355 штук, коммерцию 2 451,09 м², паркинг 266 мест, участок 2,084 га.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def upload_source() -> str:
    match = re.search(r"async function uploadGlavapu\(\)\{.*?\n\}", core.PAGE, re.S)
    assert match, "функция загрузки не найдена"
    return match.group(0)


# --- свой шаблон пробуется первым ---------------------------------------------

def test_the_page_tries_our_own_template_first():
    """Шаблон строгий — он несёт версию, и его разбор либо узнаёт файл, либо
    отказывается. Поэтому он и идёт первым: ошибиться нельзя."""
    body = upload_source()
    assert "/import/manual-tep" in body
    assert body.index("/import/manual-tep") < body.index("/import/glavapu")


def test_a_recognised_template_is_applied_not_just_shown():
    """Сводку с кнопкой «применить» строит разбор ГлавАПУ по своей структуре.
    У шаблона структура другая, и показывать его тем же блоком нечем — значит
    применяем сразу, тем же путём, что и проект из Telegram."""
    body = upload_source()
    assert "applyTelegramManualTep" in body


def test_the_person_learns_which_format_was_recognised():
    """«Файл распознан» без имени формата не даёт понять, что произошло."""
    body = upload_source()
    assert "Шаблон ТЭП DevelopAid применён" in body


# --- пустой разбор не успех ----------------------------------------------------

def test_an_empty_glavapu_parse_is_not_a_success():
    """Ни одного числа значит «формат не наш», а не «в файле нули»."""
    body = upload_source()
    assert "Формат файла не распознан" in body
    assert "typeof v==='number'" in body.replace(" ", "").replace("\n", "") \
        or "typeof v==='number'" in body


def test_the_refusal_says_what_to_do():
    body = upload_source()
    assert "Скачайте шаблон" in body


def test_the_field_names_both_formats():
    """Прежде подпись обещала только файл калькулятора ГлавАПУ."""
    body = upload_source()
    assert "шаблон ТЭП DevelopAid" in body and "ГлавАПУ" in body


# --- разбор шаблона на сервере -------------------------------------------------

def a_filled_template() -> bytes:
    """Тот же формат, что бот отдаёт по /template."""
    import io

    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "ТЭП DevelopAid"
    sheet["A4"], sheet["B4"] = "Версия шаблона", core.MANUAL_TEP_TEMPLATE_VERSION
    sheet["A5"], sheet["B5"] = "Название проекта", "Проверка"
    sheet["A6"], sheet["B6"] = "Регион / город", "Москва"
    sheet["A7"], sheet["B7"] = "Площадь территории", 2.084
    headers = ["Код", "Продукт", "ГНС / СПП, м²", "Общая площадь, м²",
               "Полезная площадь, м²", "Продаваемая площадь, м²",
               "Передаваемая площадь, м²", "Количество"]
    for index, title in enumerate(headers):
        sheet.cell(row=12, column=1 + index, value=title)
    sheet.append([])
    # Шаблон требует все строки продуктов: отсутствующая читается как порча
    # структуры, а не как «этого продукта нет».
    products = [("apartments", 43201.96, 29308.89, 355),
                ("ground_commercial", 2634.85, 2451.09, 0),
                ("standalone_retail", 0, 0, 0),
                ("offices", 0, 0, 0),
                ("above_parking", 0, 0, 0),
                ("underground_parking", 0, 0, 266),
                ("storage", 0, 0, 0),
                ("kindergarten", 0, 0, 0),
                ("school", 0, 0, 0),
                ("clinic", 0, 0, 0)]
    for row, (code, gns, saleable, units) in enumerate(products, start=13):
        sheet.cell(row=row, column=1, value=code)
        sheet.cell(row=row, column=3, value=gns)
        sheet.cell(row=row, column=4, value=gns)
        sheet.cell(row=row, column=5, value=saleable)
        sheet.cell(row=row, column=6, value=saleable)
        sheet.cell(row=row, column=8, value=units)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_the_template_parser_reads_the_whole_file():
    """То, чего страница не спрашивала, хотя оно работало."""
    parsed = core.parse_manual_tep_xlsx(a_filled_template(), "шаблон.xlsx")
    assert parsed["site_area_ha"] == pytest.approx(2.084)
    assert parsed["tep"]["apartments"]["saleable"] == pytest.approx(29308.89)
    assert parsed["tep"]["apartments"]["units"] == 355
    assert parsed["tep"]["ground_commercial"]["saleable"] == pytest.approx(2451.09)
    assert parsed["tep"]["underground_parking"]["units"] == 266


def test_a_foreign_workbook_is_refused_by_the_template_parser():
    """Отказ разбора шаблона — то, что переводит файл на путь ГлавАПУ."""
    import io

    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.title = "ТЭП DevelopAid"
    book.active["A1"] = "Чужая книга без версии"
    buffer = io.BytesIO()
    book.save(buffer)
    with pytest.raises(ValueError):
        core.parse_manual_tep_xlsx(buffer.getvalue(), "чужая.xlsx")
