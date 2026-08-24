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
import main_legacy as _engine  # noqa: E402

# Обёртка грузит движок отдельным модулем (`developaid_core`), а тесты
# импортируют `main_legacy` напрямую: это два разных объекта с двумя разными
# наборами путей. Изолировать надо оба — иначе половина тестов пишет во
# временный каталог, а половина в рабочий, и найти это можно только по
# странному падению соседа.
_MODULES = (_wrapper.core, _engine) if _wrapper.core is not _engine else (_engine,)


@pytest.fixture(autouse=True)
def empty_glavapu_tep_cache():
    """ТЭП участка кэшируется на шесть часов — в жизни это ускорение, в тестах
    чужой ответ: один тест кладёт результат по номеру, следующий проверяет
    поведение при сбое и получает вчерашний успех."""
    _wrapper.core._GLAVAPU_TEP_CACHE.clear()
    # Предохранитель после сбоя держит браузер закрытым пять минут — в жизни
    # это спасает от полутора минут ожидания на каждом расчёте, в тестах
    # сбой одного проверяющего сценария молча отключал бы браузер соседям.
    _wrapper.core._GLAVAPU_HEADLESS_BLOCKED_UNTIL["at"] = 0.0
    yield
    _wrapper.core._GLAVAPU_TEP_CACHE.clear()
    _wrapper.core._GLAVAPU_HEADLESS_BLOCKED_UNTIL["at"] = 0.0


@pytest.fixture(autouse=True)
def isolated_platon_state(tmp_path, monkeypatch):
    monkeypatch.setattr(_wrapper, "_STATE_DIR", tmp_path / "platon_state")
    # Кэш ответов агента и стадии запросов тоже живут на диске — иначе ответ,
    # положенный одним тестом, приходит другому вместо похода в модель, и тест
    # «свободный вопрос доходит до модели» падает через раз.
    monkeypatch.setattr(_wrapper.core, "_PLATO_STAGE_DIR", tmp_path / "agent_state")
    # Журнал обращений тоже на диске: без изоляции тесты писали бы в рабочий
    # каталог, а свод одного теста считал бы события соседнего.
    for module in _MODULES:
        monkeypatch.setattr(module, "_USAGE_DIR", tmp_path / "usage")
        # Анкеты и реестр людей лежат рядом с проектами и живут вечно — тем
        # более им нужна изоляция: без неё свод читал анкеты, записанные
        # соседним тестом и оставшиеся в рабочем каталоге (падение
        # test_the_free_texts_are_not_folded, 23.08.2026 — вместо «адрес
        # ищется, а ТЭП нет» приходило «ок» с диска).
        monkeypatch.setattr(module, "_PROJECTS_DIR", tmp_path / "projects")
        module._USAGE_SWEPT.clear()
    for name in ("_PLATON_CONTEXT_BY_SESSION", "_PLATON_LAST_SESSION",
                 "_PLATON_TEP_CONTEXT", "_PLATON_MODE", "_PLATON_HISTORY",
                 "_PLATON_PENDING", "_PLATON_LAST_URL"):
        monkeypatch.setattr(_wrapper, name, {})
    yield
