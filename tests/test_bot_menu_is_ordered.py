"""Меню бота — решения, а не тринадцать команд.

Список Telegram плоский: заголовков групп в нём нет, и тринадцать строк
читались простынёй, где всё одинаково важно. Пять входов в ТЭП стояли
вперемешку с Платоном и служебным, «ТЭП по кадастровым номерам» и «Посчитать
ВРИ и ТЭП» на вид не отличались, а `/mpt` дописывался расширением в самый конец
— ниже «Статуса и версии».

Вложенности в меню нет, но есть второй уровень — inline-кнопки. Отсюда правило,
которое здесь и закреплено: **пункт меню — решение, второй уровень —
уточнение.** «Расчёт модели» спрашивает, откуда взять ТЭП; «Расчёт ВРИ и ТЭП»
— где участок. Способ выбирается там, где видно, что это выбор одного и того
же, а не четыре разные функции подряд.

Остальные команды работают по-прежнему, но команда вне меню, о которой негде
узнать, просто спрятана — поэтому помощь обязана называть каждую.

Число пунктов здесь не закреплено — закреплён их состав и порядок. Пункт
добавляется осознанно: `market` встал потому, что «оценить рынок конкурентов»
— решение того же порядка, что «посчитать ВРИ и ТЭП», а не уточнение внутри
расчёта.

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
    files = ["main_legacy.py", "main.py", "mpt_extension.py", "telegram_user_registry.py",
             "market_search/bot.py"]
    return "\n".join((ROOT / name).read_text(encoding="utf-8") for name in files)


# --- шесть решений -------------------------------------------------------------

def test_the_menu_holds_the_decisions_we_agreed_on():
    """Новый пункт — повод спросить, решение ли это или ещё одна команда.

    `market` признан решением: «оценить рынок конкурентов» человек делает до
    экономики и отдельно от неё, как и «посчитать ВРИ и ТЭП».
    """
    assert NAMES == ["calc", "model", "vritep", "mpt", "market", "platon", "help"], NAMES


def test_the_calculations_stand_together():
    """ВРИ с ТЭП, льгота МПТ и рынок — расчёты, между ними ничего не вклинивается."""
    block = NAMES[NAMES.index("vritep"):NAMES.index("vritep") + 3]
    assert block == ["vritep", "mpt", "market"], NAMES


def test_a_calculation_is_not_below_the_help():
    """`/mpt` дописывался расширением в конец — оказывался последним пунктом."""
    for name in ("mpt", "market"):
        assert NAMES.index(name) < NAMES.index("help"), name


def test_the_help_closes_the_list():
    assert NAMES[-1] == "help"


def test_every_extension_lands_on_the_anchor_not_at_the_end():
    """Место расширения задаёт движок якорем, а не порядок установки.

    Пунктов расширений уже два, и привязывать каждый к своему номеру значит
    править тест при каждом следующем. Проверяется правило: оба стоят между
    расчётами движка и якорем, в порядке установки.
    """
    anchor = core.TELEGRAM_MENU_EXTENSION_ANCHOR
    assert anchor in NAMES
    for name in ("mpt", "market"):
        assert NAMES.index("vritep") < NAMES.index(name) < NAMES.index(anchor), name


def test_the_extension_does_not_duplicate_its_command():
    from mpt_bot_menu import _ensure_command

    before = len(MENU)
    _ensure_command(core)
    assert len(MENU) == before


def test_no_empty_word_stands_in_the_menu():
    """«Вход» и «Главное меню» — не то, что человек собирается сделать."""
    words = " ".join(item["description"] for item in MENU).lower()
    for empty in ("вход", "главное меню"):
        assert empty not in words, f"в меню вернулось пустое слово «{empty}»"


def test_the_analyst_says_what_he_is():
    """«Платон Сергеевич» само по себе не объясняет, что это ИИ-аналитик."""
    description = next(item["description"] for item in MENU if item["command"] == "platon")
    assert "ИИ" in description and "аналитик" in description


# --- второй уровень ------------------------------------------------------------

def test_the_calc_screen_offers_all_four_ways():
    """Способы ушли из меню — значит выбор между ними живёт здесь, иначе он
    просто исчез."""
    replies = []
    original = core._telegram_send_message
    core._telegram_send_message = lambda chat_id, text, **kw: replies.append((text, kw))
    try:
        core._telegram_calc_menu(1)
    finally:
        core._telegram_send_message = original

    assert len(replies) == 1
    text, kw = replies[0]
    assert "Расчёт модели" in text
    buttons = [row[0]["callback_data"] for row in kw["reply_markup"]["inline_keyboard"]]
    assert buttons == ["flow_cad_no", "flow_address", "flow_cad_yes", "tep_template"]


def test_the_calc_command_opens_that_screen():
    assert '"/calc"' in sources()


def test_the_vritep_screen_splits_moscow_and_the_region():
    """Второй уровень у ВРИ с ТЭП существовал и до нас — методики там разные."""
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"callback_data": "vritep_msk"' in text
    assert '"callback_data": "vritep_mo"' in text


def test_the_welcome_screen_still_shows_everything():
    """`/start` ушёл из списка команд, но кнопка Start у Telegram есть всегда, и
    за ней должен быть тот же выбор."""
    text = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    for callback in ("flow_cad_yes", "flow_address", "flow_cad_no", "vritep_start",
                     "tep_template", "ask_platon"):
        assert f'"callback_data": "{callback}"' in text, callback


# --- команды вне меню не спрятаны ---------------------------------------------

def test_the_working_commands_did_not_disappear():
    """Сокращение меню не должно быть тихим удалением возможностей."""
    for name in ("start", "tep", "address", "cadastre", "template", "comment",
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
