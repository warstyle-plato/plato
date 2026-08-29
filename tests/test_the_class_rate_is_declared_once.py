"""Ставка СМР класса объявлена один раз — в профиле класса.

Бот держал свою таблицу 110 / 190 / 300 рядом с `PROJECT_CLASS_PRESETS`, где
стоят те же числа. Сегодня они совпадают — этим и опасно: поправят профиль, а
бот останется на прежнем, и экспресс-расчёт из чата разойдётся с сайтом молча.
Ровно та же болезнь, что была у `VERSION`, у списка полей страницы и у пресетов
классов на ней (вопрос 7 в дневнике, 22.08.2026).

Запуск: python3 -m pytest tests/test_the_class_rate_is_declared_once.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

BODY = (ROOT / "main_legacy.py").read_text(encoding="utf-8")


def test_the_bot_has_no_table_of_its_own() -> None:
    assert "_TELEGRAM_CLASS_SMR_PRESETS" not in BODY, "вторая таблица ставок вернулась"


def test_the_bot_takes_the_rate_from_the_class_profile() -> None:
    for key, preset in core.PROJECT_CLASS_PRESETS.items():
        assert core._telegram_class_smr(key) == float(preset["main_above_th_per_sqm"])


def test_a_changed_profile_reaches_the_chat(monkeypatch) -> None:
    """Проверка не на совпадении чисел, а на связи: совпадающие числа
    выглядят одинаково и при двух копиях, и при одной."""
    changed = {key: dict(value) for key, value in core.PROJECT_CLASS_PRESETS.items()}
    changed["business"]["main_above_th_per_sqm"] = 222
    monkeypatch.setattr(core, "PROJECT_CLASS_PRESETS", changed)
    assert core._telegram_class_smr("business") == 222.0


def test_an_unknown_class_is_refused_by_the_same_list() -> None:
    """Список классов тоже один: у бота не должно быть своего представления
    о том, какие классы существуют."""
    assert "not in PROJECT_CLASS_PRESETS" in BODY
