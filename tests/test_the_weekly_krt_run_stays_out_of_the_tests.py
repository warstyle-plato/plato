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
    # Сторож каталога — вторая нить того же рода: он ходит к городу за
    # новостями и в тестах ему делать нечего.
    assert 'os.environ.setdefault("AUCTION_KRT_WATCH", "0")' in conftest
    assert conftest.index("AUCTION_KRT_WATCH") < conftest.index("import main as _wrapper")
    assert os.environ.get("AUCTION_KRT_WATCH") == "0"


def test_no_weekly_thread_is_alive_in_the_test_process() -> None:
    names = [thread.name for thread in threading.enumerate()]
    assert "krt-weekly" not in names, f"нить недельного прогона живёт в тестах: {names}"
    assert "krt-watch" not in names, f"нить сторожа каталога живёт в тестах: {names}"


def test_automatic_krt_runs_do_not_queue_addresses_at_a_public_geocoder() -> None:
    """Autonomous passes use only already-known KRT geometry."""
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")

    weekly = source[source.index("    def _weekly_ranking("):
                    source.index("\n\n    # main.py loads", source.index("    def _weekly_ranking("))]
    assert "_screen_for_background" in weekly
    assert "rows, _screen_for, scheduled=True" not in weekly

    rating = source[source.index("    def _rating_screen_only("):
                    source.index("\n\n    def _rating_background_loop(", source.index("    def _rating_screen_only("))]
    assert "_market_model_only(project, allow_remote_geocode=False)" in rating

    background = source[source.index("    def _screen_for_background("):
                        source.index("\n    @app.post(\"/auctions/krt/press/run\")",
                                     source.index("    def _screen_for_background("))]
    assert "allow_remote_geocode=False" in background

