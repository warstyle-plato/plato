"""Исходный текст движка целиком, как он выполняется.

Часть кода `main_legacy.py` лежит в `engine/*.py` и выполняется в
пространстве имён движка на месте строки `_engine_part("имя")`. Тест, который
проверяет текст движка, должен видеть этот код там же, где он выполняется,
поэтому здесь каждая такая строка заменяется текстом своего куска: порядок
объявлений в результате тот же, что у работающего движка.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_PART_CALL = re.compile(r'^_engine_part\("([a-z0-9_]+)"\)\n', re.MULTILINE)


def engine_source() -> str:
    text = (ROOT / "main_legacy.py").read_text(encoding="utf-8")

    def expand(match: re.Match[str]) -> str:
        return (ROOT / "engine" / f"{match.group(1)}.py").read_text(encoding="utf-8")

    return _PART_CALL.sub(expand, text)
