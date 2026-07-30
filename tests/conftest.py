"""Общая подготовка тестов.

Контекст Платона Сергеевича дублируется на диск, чтобы переживать переход между
воркерами. В тестах это состояние обязано быть временным: иначе один тест
оставляет проект в рабочем каталоге, а следующий, проверяющий поведение «проекта
нет», находит чужой и падает. Заодно репозиторий не засоряется.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_platon_state(tmp_path, monkeypatch):
    monkeypatch.setattr(_wrapper, "_STATE_DIR", tmp_path / "platon_state")
    for name in ("_PLATON_CONTEXT_BY_SESSION", "_PLATON_LAST_SESSION",
                 "_PLATON_TEP_CONTEXT", "_PLATON_MODE", "_PLATON_HISTORY",
                 "_PLATON_PENDING", "_PLATON_LAST_URL"):
        monkeypatch.setattr(_wrapper, name, {})
    yield
