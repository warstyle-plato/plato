"""Меню бота — путь работы, а не история появления команд.

Меню Telegram плоское: заголовков групп в нём нет, и единственное, чем можно
объяснить человеку устройство бота, — очерёдность и одинаковая форма подписей.
Стояло иначе: пять входов в ТЭП вперемешку с Платоном, «ТЭП по кадастровым
номерам» и «Посчитать ВРИ и ТЭП» на вид неразличимы, хотя это разные входы, а
`/mpt` дописывался расширением в самый конец — ниже «Статуса и версии».

Порядок: начало · входы в ТЭП · модель · отдельные расчёты · Платон · служебное.

Здесь же проверка, которой не было вовсе: каждая команда меню должна иметь
разбор. Команда в меню, которую бот не понимает, выглядит как поломка бота, а
не как забытая строка.

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

core = main_registry._base.core

MENU = core.TELEGRAM_BOT_COMMANDS
NAMES = [str(item["command"]) for item in MENU]


def sources() -> str:
    """Все модули, которые разбирают команды: движок, обёртка, расширения."""
    files = ["main_legacy.py", "main.py", "mpt_extension.py", "telegram_user_registry.py"]
    return "\n".join((ROOT / name).read_text(encoding="utf-8") for name in files)


# --- порядок ------------------------------------------------------------------

def test_the_menu_opens_with_the_main_screen():
    assert NAMES[0] == "start"


def test_the_five_ways_into_a_tep_stand_together():
    """Прежде между ними стояли модель и Платон, и выбрать способ было нельзя —
    их просто не видно как выбор."""
    entries = ["cadastre", "address", "vritep", "tep", "template"]
    positions = [NAMES.index(name) for name in entries]
    assert positions == sorted(positions), "входы в ТЭП идут не подряд"
    assert max(positions) - min(positions) == len(entries) - 1, "между входами вклинилось чужое"


def test_the_entries_are_named_the_same_way():
    """Четыре разные грамматические формы читались как четыре разных сущности."""
    for name in ("cadastre", "address", "vritep", "tep"):
        description = next(item["description"] for item in MENU if item["command"] == name)
        assert description.startswith("ТЭП"), f"/{name}: {description}"


def test_the_entries_differ_from_each_other():
    """«ТЭП по кадастровым номерам» и «Посчитать ВРИ и ТЭП» — разные входы, и
    подписи обязаны это показывать."""
    descriptions = [item["description"] for item in MENU]
    assert len(set(descriptions)) == len(descriptions)


def test_the_service_commands_close_the_list():
    """Служебное ищут в конце — там ему и место."""
    service = list(core.TELEGRAM_SERVICE_COMMANDS)
    tail = NAMES[-len(service):]
    assert set(tail) == set(service), f"хвост меню: {tail}"


def test_a_working_tool_is_not_below_the_version_number():
    """`/mpt` дописывался расширением в конец — после «Статуса и версии»."""
    assert "mpt" in NAMES, "расширение МПТ не добавило команду"
    assert NAMES.index("mpt") < NAMES.index("status")
    assert NAMES.index("mpt") < NAMES.index("help")


def test_the_extension_does_not_duplicate_its_command():
    from mpt_bot_menu import _ensure_command

    before = len(MENU)
    _ensure_command(core)
    assert len(MENU) == before


# --- меню и код не расходятся --------------------------------------------------

@pytest.mark.parametrize("name", NAMES)
def test_every_menu_command_has_a_handler(name):
    """Команда в меню, которую бот не понимает, выглядит поломкой бота."""
    text = sources()
    assert re.search(rf'["\{{,]\s*"/{name}"', text) or f'"/{name}"' in text, \
        f"/{name} есть в меню, но её разбора не нашлось"


def test_the_menu_has_no_duplicates():
    assert len(NAMES) == len(set(NAMES))


def test_the_descriptions_fit_telegram():
    """Ограничения Telegram: команда до 32 символов, описание до 256."""
    for item in MENU:
        assert 1 <= len(item["command"]) <= 32, item
        assert 1 <= len(item["description"]) <= 256, item
        assert re.fullmatch(r"[a-z0-9_]+", item["command"]), item


def test_the_admin_command_stays_out_of_the_menu():
    """`/stats` работает, но это свод для владельца, а не пункт меню."""
    assert "stats" not in NAMES
    assert '"/stats"' in sources(), "команда должна остаться рабочей"
