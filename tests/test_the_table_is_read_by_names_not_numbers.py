"""Готовность таблицы ГлавАПУ не держится на номере чужой строки.

Живой снимок ядра (01.09.2026), проба по 77:09:0004014:13:

    «таблица есть (79 строк), кодов 77, нет кодов 60; прочитаны: 1, 10, 11,
     12, 12.1, 12.2, 13, 14, 15, 16, 17, 18, 19, 2…»
    хвост таблицы: 57.1, 57.2, 58

Кода 60 у ГлавАПУ больше нет — таблица перенумерована и кончается на 58. Наше
условие готовности требовало кодов 60 и 54, то есть ждало несуществующую
строку девяносто секунд: на каждом участке, у каждого человека, каждый раз с
откатом на формулы. Ни одна проверка этого не ловила, потому что все они
собирали таблицу сами и клали в неё код 60.

Разбор при этом читает таблицу ПО ИМЕНАМ. Номер означает только место строки,
имя — саму величину, и держаться надо за второе. А ждать надо того, что от
нумерации не зависит вовсе: таблица набралась и перестала меняться.

Запуск: python3 -m pytest tests/test_the_table_is_read_by_names_not_numbers.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

# Строки живого снимка: как ГлавАПУ отдаёт таблицу СЕЙЧАС — без кода 60.
LIVE = [
    {"code": "1", "name": "Площадь территории проектирования", "unit": "га", "value": "0,651"},
    {"code": "2", "name": "Плотность от СПП", "unit": "тыс.кв.м./га", "value": "35"},
    {"code": "3", "name": "Плотность от НП", "unit": "тыс.кв.м./га", "value": "31,5"},
    {"code": "4", "name": "Население", "unit": "чел.", "value": "422"},
    {"code": "5", "name": "Количество квартир", "unit": "шт.", "value": "201"},
    {"code": "10", "name": "Площадь квартир", "unit": "тыс.кв.м.", "value": "12,0"},
    {"code": "57.1", "name": "Территории, занятые зелеными насаждениями", "unit": "га",
     "value": "0,1477"},
    {"code": "58", "name": "Озелененные территории общего пользования", "unit": "га",
     "value": "0,0296"},
]


def test_the_live_table_without_code_60_is_complete():
    """Главная проверка: живая таблица без кода 60 больше не считается неполной."""
    assert "60" not in {row["code"] for row in LIVE}
    assert core._glavapu_missing_controls(LIVE) == []


def test_a_missing_row_is_named_by_its_name():
    without = [row for row in LIVE if row["name"] != "Население"]
    assert core._glavapu_missing_controls(without) == ["население"]


def test_the_name_key_survives_case_and_yo():
    rows = [dict(row, name=row["name"].upper().replace("Е", "Ё")) for row in LIVE]
    assert core._glavapu_missing_controls(rows) == [], \
        "имя строки перестало опознаваться из-за регистра или «ё»"


def test_the_readiness_waits_for_the_table_to_settle():
    """Отпечаток таблицы — это её значения, а не её нумерация."""
    same = core._glavapu_table_shot(LIVE)
    assert same == core._glavapu_table_shot(list(LIVE)), "отпечаток неустойчив"
    changed = core._glavapu_table_shot(
        [dict(row, value="9") if row["code"] == "4" else row for row in LIVE])
    assert same != changed, "изменившееся значение отпечаток не заметил"
    assert core._glavapu_table_shot([]) == ""


def test_the_refusal_tells_a_missing_row_from_a_moving_table():
    ready = {"calc_table": True, "sample": [["1", "Площадь", "га", "0,651"]]}
    settled = core._glavapu_not_ready_message(LIVE, ready)
    assert "не перестала меняться" in settled, \
        "полная таблица подана как неполная"
    short = core._glavapu_not_ready_message(LIVE[:2], ready)
    assert "нет строк, которые мы читаем" in short and "количество квартир" in short


def test_no_magic_row_number_is_left_in_the_gate():
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    body = source[source.index("def _glavapu_drive_page("):]
    body = body[:body.index("\ndef _glavapu_browser_worker(")]
    assert '"60" in codes' not in body and '"54" in codes' not in body, \
        "готовность снова держится на номере чужой строки"
    assert "_glavapu_missing_controls(" in body and "_glavapu_table_shot(" in body


def test_the_import_control_is_by_names_too():
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    body = source[source.index("def import_cadastral_tep("):]
    body = body[:body.index("\ndef ", 10)]
    assert '{"1", "10", "42", "54", "60"}' not in body, \
        "контроль полноты снова по номерам строк"
    assert "_glavapu_missing_controls(" in body


def test_the_gate_is_declared_once():
    """Одноимённая функция съедает предыдущую молча — это уже бывало."""
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    assert source.count("def _glavapu_not_ready_message(") == 1
    assert source.count("def _glavapu_missing_controls(") == 1
