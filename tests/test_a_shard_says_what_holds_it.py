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
    """Ничего живого — не печатается ничего: приписку в доле перестают читать."""
    assert conftest.hanging_report([], []) == ""
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


def test_a_child_is_named_apart_from_a_thread():
    """Нить и ребёнок названы порознь: это разные поломки.

    Сторож нитей на прогоне 16.09.2026 промолчал во всех четырёх долях, а Доля
    3 всё равно молчала одиннадцать с половиной минут после итога (итог
    00:32:55, следующая строка лога 00:44:37 «Post job cleanup»). Значит держит
    не нить: незакрытый ребёнок наследует вывод шага, и раннер ждёт закрытия
    трубы. Одно число их бы скрыло, а чинятся они по-разному.
    """
    said = conftest.hanging_report(["нить-а"], ["999 chromium --headless"])

    assert "недемонические нити (1)" in said, said
    assert "дочерние процессы (1)" in said, said
    assert said.index("нити (1)") < said.index("процессы (1)"), said


def test_the_child_counter_sees_a_real_subprocess():
    """Счёт мерит НАСТОЯЩИХ детей, а не пересказ.

    Предохранитель: до запуска ребёнка его в ответе нет — иначе проверка зелена
    при любом счёте.
    """
    import subprocess
    import sys as _sys

    before = conftest.live_children()
    assert not any("уснувший-ребёнок" in one for one in before), before

    child = subprocess.Popen(
        [_sys.executable, "-c", "import sys, time; sys.stderr.write('уснувший-ребёнок'); time.sleep(30)"])
    try:
        found = conftest.live_children()
        assert any(one.startswith(f"{child.pid} ") for one in found), (child.pid, found)
    finally:
        child.kill()
        child.wait(timeout=10)
    assert not any(one.startswith(f"{child.pid} ") for one in conftest.live_children())
