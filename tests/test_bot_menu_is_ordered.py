"""Меню бота — шесть решений, а не тринадцать команд.

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


# --- шесть решений -------------------------------------------------------------

def test_the_menu_holds_six_decisions():
    """Седьмой пункт — повод спросить, решение ли это или ещё одна команда."""
    assert NAMES == ["calc", "model", "vritep", "mpt", "platon", "feedback", "help"], NAMES


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


# --- один продукт — один словарь -------------------------------------------------

def _welcome_keyboard(monkeypatch) -> list[list[dict]]:
    sent: list[dict] = []
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kw: sent.append(kw))
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda chat_id, cads, **kw: "https://t/")
    monkeypatch.setattr(core, "_telegram_dialog_clear", lambda chat_id: None)
    core._telegram_start_message(1, 1)
    return sent[-1]["reply_markup"]["inline_keyboard"]


def _labels(rows) -> list[str]:
    return [str(button.get("text") or "") for row in rows for button in row]


def test_the_welcome_speaks_the_language_of_the_menu(monkeypatch):
    """Список команд слева внизу показывал шесть решений, а приветствие —
    восемь конкретных входов: один продукт объяснялся двумя словарями
    (замечание владельца, 18.08.2026). Теперь решения те же и в том же
    порядке."""
    rows = _welcome_keyboard(monkeypatch)
    labels = _labels(rows)
    assert labels[0] == "Расчёт модели"
    assert "Открыть готовую модель" in labels
    assert "Расчёт ВРИ и ТЭП" in labels
    assert "Платон Сергеевич" in labels
    assert labels[-1] == "Что умеет DevelopAid", "помощь закрывает список, как в меню"
    assert not any("кадастров" in label.lower() for label in labels), (
        "способ расчёта — второй уровень, а не вход")


def test_the_calculation_does_not_stand_below_the_help(monkeypatch):
    """То же правило, что у списка команд: расчёт МПТ встаёт среди расчётов.
    Расширение дописывало свою кнопку в конец — ниже «Что умеет»."""
    labels = _labels(_welcome_keyboard(monkeypatch))
    mpt = [index for index, label in enumerate(labels) if "МПТ" in label]
    if mpt:
        assert mpt[0] < labels.index("Что умеет DevelopAid")


def test_the_first_button_opens_the_same_second_level_as_the_command():
    """«Расчёт модели» в приветствии и команда /calc ведут в одно меню, а не в
    два похожих."""
    engine = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    branch = engine[engine.index('if data == "calc_menu"'):]
    assert "_telegram_calc_menu(chat_id)" in branch[:400]
    assert engine.count("def _telegram_calc_menu(") == 1


def test_the_help_menu_of_the_wrapper_speaks_the_same_words(monkeypatch):
    """Третьим словарём говорила помощь обёртки: «Прокомментировать ТЭП» и
    «Спросить Платона» вперемешку со входами. Проверяем сами кнопки, а не
    исходник: комментарий рядом с ними — не кнопка."""
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda chat_id, cads, **kw: "https://t/")
    labels = _labels(wrapper._help_markup(1)["inline_keyboard"])
    assert labels[0] == "Расчёт модели"
    assert "Расчёт ВРИ и ТЭП" in labels and "Платон Сергеевич" in labels
    assert not any("кадастров" in label.lower() for label in labels)
    assert "Прокомментировать ТЭП" not in labels, "второй уровень Платона — не решение"
