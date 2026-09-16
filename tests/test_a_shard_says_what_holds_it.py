"""Доля называет, кто держит её после итога, а не ждёт молча.

Пять прогонов подряд Доля 3 кончала работу через десять–тринадцать минут ПОСЛЕ
итога pytest (замер 15.09.2026: итог 11:08, конец 24:44; у остальных долей
разрыв 34–46 секунд). Снаружи это неотличимо от медленной доли, а цена — треть
потолка, который считается от ХУДШЕЙ доли.

Замер в песочнице причину не показал: подозреваемый файл в одиночку и вся
третья доля целиком выходят с разрывом в секунду-две. Значит ждать надо на
раннере — а для этого молчание обязано заговорить.

Сторож, который молчит всегда, неотличим от отсутствующего, поэтому здесь
проверяется именно то, что он ГОВОРИТ, когда нить есть.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import conftest  # noqa: E402


def test_a_clean_finish_says_nothing():
    """Нитей нет — не печатается ничего: приписку в каждой доле перестают читать."""
    assert conftest.hanging_report([]) == ""


def test_a_lingering_thread_is_named():
    """Нить названа по имени, и сказано, чем это выглядит в логе."""
    said = conftest.hanging_report(["krt-catalogue-refresh", "плато-сторож"])

    assert "krt-catalogue-refresh" in said and "плато-сторож" in said
    assert "(2)" in said, said
    assert "медленная доля" in said, said


def test_the_counter_sees_a_real_non_daemon_thread():
    """Счёт мерит НАСТОЯЩИЕ нити, а не пересказ.

    Предохранитель: сперва убеждаемся, что до запуска нити её в ответе нет, —
    иначе проверка зелена при любом счёте.
    """
    name = "проверочная-нить-доли"
    assert name not in conftest.live_threads()

    stop = threading.Event()
    thread = threading.Thread(target=stop.wait, name=name, daemon=False)
    thread.start()
    try:
        assert name in conftest.live_threads()
    finally:
        stop.set()
        thread.join(timeout=5)
    assert name not in conftest.live_threads()


def test_a_daemon_thread_is_not_named():
    """Демон процесс не держит — называть его значит кричать зря."""
    stop = threading.Event()
    thread = threading.Thread(target=stop.wait, name="демон-доли", daemon=True)
    thread.start()
    try:
        assert "демон-доли" not in conftest.live_threads()
    finally:
        stop.set()
        thread.join(timeout=5)
