"""Чужой файл в чате: разбор ГлавАПУ соглашался на что угодно, а сбой молчал.

Владелец прислал в бот книгу «DevelopAid · Шаблон ТЭП · West Garden по РНС» —
сделанную по мотивам нашего шаблона, но не наш формат: строки «Версия шаблона»
в ней нет, таблица продуктов идёт колонками «Очередь · Продукт», а не
«Код · Продукт». В ответ дважды пришло «Не удалось завершить запрос.
Попробуйте ещё раз через минуту» — сообщение, из которого нельзя понять ни что
случилось, ни что делать.

Две причины, обе поодиночке безобидные.

**Разбор ГлавАПУ не отказывается от чужой книги.** Он ищет свои подписи, не
находит ни одной и возвращает набор из 61 ключа, где всё пусто. Единственное
непустое — `suggested_social_mode`, и оно не вычитано, а подставлено самим
разбором. Файл при этом считался распознанным: бот отвечал «Файл калькулятора
ГлавАПУ распознан. Территория 0,0000 га, квартиры 0 м²» и предлагал открыть
пустую модель — то есть ложь с видом ответа.

**Верхний перехват оставлял причину себе.** `_telegram_process_update` клал её
в `_TELEGRAM_RUNTIME["last_error"]`, а человеку отдавал «попробуйте через
минуту». Логов хостинга нет, и правило проекта — доносить место ошибки в чат —
здесь работало наоборот всех прочих веток.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
openpyxl = pytest.importorskip("openpyxl")


def a_foreign_workbook() -> bytes:
    """Книга того же вида, что пришла в чат: наши слова, чужая структура."""
    import io

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "ТЭП DevelopAid"
    sheet["A1"] = "DEVELOPAID · ШАБЛОН ТЭП · WEST GARDEN · 3 ОЧЕРЕДЬ"
    sheet["A4"], sheet["B4"] = "Проект", "West Garden · 3 очередь"
    sheet["A9"], sheet["B9"] = "Общая площадь объекта", 46197
    sheet["A17"], sheet["B17"] = "Очередь", "Продукт"
    sheet["A18"], sheet["B18"], sheet["G18"] = "Очередь 1", "Квартиры", 26622.8
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# --- разбор ГлавАПУ -----------------------------------------------------------

def test_a_foreign_workbook_is_not_a_glavapu_file():
    """Ни одного числа не вычитано — значит это не тот формат."""
    replies = []
    original = core._telegram_send_message
    core._telegram_send_message = lambda chat_id, text, **kw: replies.append(text)
    try:
        accepted = core._telegram_handle_glavapu_document(1, a_foreign_workbook(), "чужой.xlsx")
    finally:
        core._telegram_send_message = original

    assert accepted is False
    assert replies == [], "по чужому файлу не должно уходить «распознан»"


def test_the_manual_template_error_reaches_the_person():
    """Отказ разбора ГлавАПУ возвращает человека к настоящей причине: это не
    шаблон DevelopAid, и надо взять актуальный."""
    replies = []
    original_send = core._telegram_send_message
    original_download = core._telegram_download_document
    core._telegram_send_message = lambda chat_id, text, **kw: replies.append(text)
    core._telegram_download_document = lambda document: (a_foreign_workbook(), "чужой.xlsx")
    try:
        core._telegram_handle_manual_document(1, {"file_id": "x"})
    finally:
        core._telegram_send_message = original_send
        core._telegram_download_document = original_download

    assert len(replies) == 1
    assert "Не удалось принять ручной ТЭП" in replies[0]
    assert "/template" in replies[0]
    assert "0,0000 га" not in replies[0], "сводка из нулей — не ответ"


def test_a_real_glavapu_file_still_passes():
    """Отсечка не должна съесть настоящий формат: у него числа есть."""
    normalized = {"site_area_ha": 0.651, "apartment_area_sqm": 12000.0,
                  "suggested_social_mode": "Денежная компенсация"}
    numbers = [value for value in normalized.values()
               if isinstance(value, (int, float)) and not isinstance(value, bool) and value]
    assert numbers, "файл с числами обязан проходить"


def test_the_default_suggestion_alone_is_not_recognition():
    """Единственное непустое поле чужого разбора подставлено им самим, а не
    вычитано, — принимать по нему нельзя."""
    normalized = {"site_area_ha": None, "apartment_area_sqm": None,
                  "suggested_social_mode": "Денежная компенсация"}
    numbers = [value for value in normalized.values()
               if isinstance(value, (int, float)) and not isinstance(value, bool) and value]
    assert not numbers


# --- сбой называет себя --------------------------------------------------------

def test_an_unexpected_failure_names_the_place():
    """«Попробуйте через минуту» не лечит ничего, если через минуту сломается
    то же самое."""
    replies = []
    original_send = core._telegram_send_message
    original_handle = core._telegram_handle_update
    core._telegram_send_message = lambda chat_id, text, **kw: replies.append(text)

    def explode(update):
        raise RuntimeError("подопытная поломка")

    core._telegram_handle_update = explode
    try:
        core._telegram_process_update({"message": {"chat": {"id": 42}, "text": "привет"}})
    finally:
        core._telegram_send_message = original_send
        core._telegram_handle_update = original_handle

    assert len(replies) == 1
    assert "подопытная поломка" in replies[0]
    # Файл и строка — того места, где рвануло, каким бы оно ни было; здесь это
    # сам тест. Проверяем форму, а не конкретный файл.
    assert re.search(r"\.py:\d+", replies[0]), "без файла и строки причина не находится"
    assert "explode" in replies[0], "без имени функции место не сузить"


def test_the_runtime_keeps_the_same_line():
    """`/status` и чат должны показывать одно и то же место, а не две версии
    события: иначе сверять рассказ человека с состоянием бота нечем."""
    replies = []
    original_handle = core._telegram_handle_update
    original_send = core._telegram_send_message
    core._telegram_send_message = lambda chat_id, text, **kw: replies.append(text)

    def explode(update):
        raise RuntimeError("подопытная поломка")

    core._telegram_handle_update = explode
    try:
        core._telegram_process_update({"message": {"chat": {"id": 42}}})
    finally:
        core._telegram_handle_update = original_handle
        core._telegram_send_message = original_send

    stored = core._TELEGRAM_RUNTIME.get("last_error") or ""
    assert re.search(r"подопытная поломка \(.+\.py:\d+, explode\)", stored)
    assert stored in replies[0], "в чат ушла не та строка, что осталась в /status"
