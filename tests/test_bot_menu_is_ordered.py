"""Меню бота — пять решений, а не тринадцать команд.

Список Telegram плоский: заголовков групп в нём нет, и тринадцать строк
читались простынёй, где всё одинаково важно. Пять входов в ТЭП стояли
вперемешку с Платоном и служебным, «ТЭП по кадастровым номерам» и «Посчитать
ВРИ и ТЭП» на вид не отличались, а `/mpt` дописывался расширением в самый конец
— ниже «Статуса и версии».

Человек выбирает из пяти вещей: войти, посчитать ВРИ и ТЭП, посчитать льготу
МПТ, спросить Платона, разобраться. Столько в меню и осталось.

Остальные команды работают по-прежнему. Четыре входа в ТЭП стоят кнопками на
главном экране, где виден выбор между ними, а полный список даёт `/help`.
Отсюда главное правило этого файла: **команда вне меню обязана быть названа в
помощи и иметь разбор** — иначе она просто спрятана.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_registry  # noqa: E402  (собирает бота целиком, вместе с расширениями)
import main as wrapper  # noqa: E402

core = main_registry._base.core

MENU = core.TELEGRAM_BOT_COMMANDS
EXTRA = core.TELEGRAM_EXTRA_COMMANDS
NAMES = [str(item["command"]) for item in MENU]
EXTRA_NAMES = [str(item["command"]) for item in EXTRA]


def sources() -> str:
    """Все модули, которые разбирают команды: движок, обёртка, расширения."""
    files = ["main_legacy.py", "main.py", "mpt_extension.py", "telegram_user_registry.py"]
    return "\n".join((ROOT / name).read_text(encoding="utf-8") for name in files)


# --- пять решений --------------------------------------------------------------

def test_the_menu_holds_five_decisions():
    """Шестой пункт — повод спросить, решение ли это или ещё одна команда."""
    assert NAMES == ["start", "vritep", "mpt", "platon", "help"], NAMES


def test_the_calculations_stand_together():
    """ВРИ с ТЭП и льгота МПТ — оба расчёта, между ними ничего не вклинивается."""
    assert NAMES.index("mpt") == NAMES.index("vritep") + 1


def test_a_calculation_is_not_below_the_help():
    """`/mpt` дописывался расширением в конец — оказывался последним пунктом."""
    assert NAMES.index("mpt") < NAMES.index("help")


def test_the_help_closes_the_list():
    assert NAMES[-1] == "help"


def test_the_extension_lands_on_the_anchor_not_at_the_end():
    """Место расширения задаёт движок якорем, а не порядок установки."""
    assert core.TELEGRAM_MENU_EXTENSION_ANCHOR in NAMES
    assert NAMES.index("mpt") == NAMES.index(core.TELEGRAM_MENU_EXTENSION_ANCHOR) - 1


def test_the_extension_does_not_duplicate_its_command():
    from mpt_bot_menu import _ensure_command

    before = len(MENU)
    _ensure_command(core)
    assert len(MENU) == before


# --- команды вне меню не спрятаны ---------------------------------------------

def test_the_working_commands_did_not_disappear():
    """Сокращение меню не должно быть тихим удалением возможностей."""
    for name in ("cadastre", "address", "tep", "template", "model", "comment",
                 "cancel", "status"):
        assert name in EXTRA_NAMES, f"/{name} потерялась при сокращении меню"


def test_the_help_names_every_command_outside_the_menu():
    """Единственное место, где о них можно узнать."""
    block = wrapper._commands_block()
    for item in EXTRA:
        assert f"/{item['command']}" in block, item
        assert item["description"] in block, item


def test_the_help_names_the_menu_itself():
    block = wrapper._commands_block()
    for name in NAMES:
        assert f"/{name}" in block


def test_the_four_ways_into_a_tep_are_on_the_main_screen():
    """Из меню они ушли — значит выбор между ними должен быть виден кнопками,
    иначе он исчез."""
    text = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    for callback in ("flow_cad_yes", "flow_address", "flow_cad_no", "vritep_start",
                     "tep_template"):
        assert f'"callback_data": "{callback}"' in text, callback


# --- меню и код не расходятся --------------------------------------------------

@pytest.mark.parametrize("name", NAMES + EXTRA_NAMES)
def test_every_command_has_a_handler(name):
    """Команда, которую бот не понимает, выглядит поломкой бота."""
    assert f'"/{name}"' in sources(), f"/{name} объявлена, но её разбора не нашлось"


def test_no_duplicates_anywhere():
    both = NAMES + EXTRA_NAMES
    assert len(both) == len(set(both))


def test_the_descriptions_fit_telegram():
    """Ограничения Telegram: команда до 32 символов, описание до 256."""
    for item in MENU:
        assert 1 <= len(item["command"]) <= 32, item
        assert 1 <= len(item["description"]) <= 256, item
        assert re.fullmatch(r"[a-z0-9_]+", item["command"]), item


def test_the_admin_command_stays_out_of_both_lists():
    """`/stats` работает, но это свод для владельца, а не пункт для всех."""
    assert "stats" not in NAMES + EXTRA_NAMES
    assert '"/stats"' in sources(), "команда должна остаться рабочей"
