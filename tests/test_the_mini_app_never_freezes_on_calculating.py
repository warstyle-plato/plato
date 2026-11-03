"""Мини-приложение не остаётся на «Считаю…».

«Перенёс тизер из бота, и мини-апп завис на этапе „Считаю…“» (владелец,
31.08.2026). Полоса ставится перед расчётом и снимается СТРОКОЙ ПОСЛЕ него —
а если расчёт бросил, до этой строки не доходит вовсе. Окно замирало навсегда
и не говорило ничего: на экране одновременно «Считаю…» сверху и «Расчёт
актуален» ниже, потому что следующий пересчёт по правке поля уже прошёл.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def body_of(name: str) -> str:
    place = core.PAGE.index(f"function {name}(")
    return core.PAGE[place: core.PAGE.index("\n}\n", place)]


def test_the_launch_clears_the_banner_whatever_happens() -> None:
    wrapper = body_of("initializeTelegramLaunch")
    assert "runTelegramLaunch()" in wrapper, "запуск больше не обёрнут"
    assert "catch" in wrapper and "telegramProgress('')" in wrapper, \
        "полоса переживает ошибку запуска"
    # И причина называется: замершее окно не говорит человеку ничего.
    assert "Расчёт из чата не прошёл" in wrapper


def test_a_banner_that_hangs_says_so() -> None:
    """Полоса без признака жизни неотличима от зависшей."""
    banner = body_of("telegramProgress")
    assert "setTimeout" in banner and "Дольше обычного" in banner
    # Таймер снимается при каждой смене текста, иначе прошлый допишет своё
    # поверх нового состояния.
    assert "clearTimeout(telegramProgress.timer)" in banner


def test_every_working_banner_belongs_to_a_path_that_clears_it() -> None:
    """Полоса ставится в четырёх местах, и снимать её должно каждое."""
    shown = len(re.findall(r"telegramProgress\('Считаю…'\)", core.PAGE))
    cleared = len(re.findall(r"telegramProgress\(''\)", core.PAGE))
    assert shown >= 3, "полоса больше не ставится — проверка потеряла смысл"
    assert cleared >= shown, "мест, где полоса снимается, меньше, чем где ставится"
