"""Недельный прогон КРТ не стартует внутри тестов.

02.09.2026 нить `krt-weekly` проснулась в прогоне на GitHub — с рынком-заглушкой
из соседнего теста, — сходила в сеть за каталогом и залила хвост лога 134
трассировками. Набор при этом зелёный, а строку «N passed» под трассировками
пришлось искать скриптом. Фоновая работа приложения — не часть теста.

Запуск: python3 -m pytest tests/test_the_weekly_krt_run_stays_out_of_the_tests.py -q
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_switch_is_set_before_the_app_is_imported() -> None:
    conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("AUCTION_KRT_WEEKLY", "0")' in conftest
    assert conftest.index("AUCTION_KRT_WEEKLY") < conftest.index("import main as _wrapper"), \
        "выключатель взводится после импорта приложения — нить уже стартовала"
    assert os.environ.get("AUCTION_KRT_WEEKLY") == "0"


def test_no_weekly_thread_is_alive_in_the_test_process() -> None:
    names = [thread.name for thread in threading.enumerate()]
    assert "krt-weekly" not in names, f"нить недельного прогона живёт в тестах: {names}"
