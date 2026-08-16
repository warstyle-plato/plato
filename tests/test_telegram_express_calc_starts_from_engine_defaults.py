"""Экспресс-расчёт из чата начинается с умолчаний движка, а не с WebView.

Бот и сайт разошлись на одном и том же «адрес + класс бизнес» (16.08.2026):
WebView телеграма однажды сохранил проект со старой структурой расходов
(сети 7,5 вместо 10,25, проектирование 5 вместо 14,5) и двумя миллиардами
собственных средств чужого эксперимента — и каждый экспресс-расчёт из бота
молча наследовал это через loadLocal(). Сайт в чистой вкладке считал с
умолчаний, и два отчёта по одному участку выглядели одинаково достоверно.

Здесь закреплено:

- запуск по кадастру из чата сбрасывает состояние канонической функцией
  resetAll() до получения ТЭП — обещание бота «класс + цены + СМР, остальное
  умолчания» выполняется буквально;
- запуск с присланным ТЭП (шаблон, свободный ввод) — так же;
- режим редактирования НЕ сбрасывает: он открывает проект своей карточки,
  и терять правки человека нельзя;
- бот говорит об этом прямо в «Параметрах перед расчётом».

Запуск: python3 -m pytest tests/test_telegram_express_calc_starts_from_engine_defaults.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _launch() -> str:
    body = core.PAGE[core.PAGE.index("async function initializeTelegramLaunch()"):]
    return body[:body.index("async function initializeApp()")]


def test_the_cadastral_launch_resets_before_fetching_tep():
    launch = _launch()
    cad = launch[launch.index("if(telegramCad){"):]
    reset = cad.index("resetAll()")
    assert reset != -1, "запуск по кадастру не сбрасывает состояние WebView"
    assert reset < cad.index("obtainCadastralTep()"), "сброс должен идти до получения ТЭП"
    # Кадастровые номера вписываются после сброса — resetAll чистит это поле.
    assert reset < cad.index("field.value=telegramCad")


def test_the_manual_tep_launch_resets_too():
    launch = _launch()
    manual = launch[launch.rindex("if(sessionData.manual_tep){"):]
    assert manual.index("resetAll()") < manual.index("applyTelegramManualTep"), (
        "запуск с присланным ТЭП наследует состояние WebView"
    )


def test_the_edit_mode_keeps_the_project_of_its_card():
    """Правки человека — не мусор: режим редактирования не сбрасывает."""
    launch = _launch()
    edit = launch[launch.index("if(telegramMode==='edit'){"):]
    edit = edit[:edit.index("if(telegramCad){")]
    assert "resetAll()" not in edit


def test_the_bot_says_the_rest_are_engine_defaults():
    source = Path(core.__file__).read_text(encoding="utf-8")
    button = source[source.index("def _telegram_send_cad_calculate_button"):]
    button = button[:button.index("def _telegram_mo_parsed")]
    assert "умолчания DevelopAid" in button, "бот не предупреждает про умолчания"
    assert "не переносятся" in button
