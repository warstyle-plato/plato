"""Куски движка из engine/*.py живут в пространстве имён самого движка.

`main.py` подменяет атрибуты движка (`core._telegram_send_message = ...`), и
тесты делают то же. Подмена обязана доходить до вызовов внутри куска: если
кусок станет обычным модулем со своими глобальными именами, бот молча начнёт
звать исходную функцию мимо обёртки.
"""

from __future__ import annotations

import re
from pathlib import Path

import main

ROOT = Path(__file__).resolve().parent.parent


def test_every_part_is_included_exactly_once() -> None:
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    included = re.findall(r'^_engine_part\("([a-z0-9_]+)"\)$', source, flags=re.MULTILINE)
    parts = sorted(path.stem for path in (ROOT / "engine").glob("*.py"))
    assert sorted(included) == parts
    assert len(included) == len(set(included))


def test_part_code_shares_the_engine_namespace() -> None:
    core = main.core
    # Исходный обработчик из куска; под этим именем у движка уже обёртка main.py.
    handler = main._ORIGINAL_HANDLE_MESSAGE
    assert "_telegram_send_message" in handler.__code__.co_names
    assert handler.__code__.co_filename.endswith("engine/bot_telegram.py")
    assert handler.__globals__ is vars(core)
    # Обёртка main.py видна коду куска под тем же именем, что и снаружи.
    assert handler.__globals__["_telegram_send_message"] is core._telegram_send_message
    assert core._telegram_send_message is not main._ORIGINAL_SEND_MESSAGE
