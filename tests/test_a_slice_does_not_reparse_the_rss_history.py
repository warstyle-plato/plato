"""Срез не разбирает заново всю историю РСС.

«Почему пересчёт среза идёт около двух минут?» (владелец, 20.10.2026).
Тренд строит полный срез по каждому недельному снимку, а каждый срез читает
РСС четырьмя читателями. Кэш в памяти держал 24 записи — шесть снимков, и
тренд по пятнадцати неделям вытеснял сам себя: каждый срез заново разбирал
все РСС (около 8 с на снимок). Теперь кэш ограничен объёмом, а разбор снимка
лежит на диске рядом с ним — второй воркер и перезапуск его не повторяют.

Запуск: python3 -m pytest tests/test_a_slice_does_not_reparse_the_rss_history.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_actuals as actuals  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
import developaid_monitor_page  # noqa: E402,F401 — слои среза, как на проде
from test_monitor_keeps_every_snapshot import _baseline_book, _rss_book  # noqa: E402

WEEKS = [f"2026-0{m}-{d:02d}" for m in (7, 8, 9) for d in (3, 10, 17, 24)]


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setattr(actuals, "_READ_CACHE", type(actuals._READ_CACHE)())
    monitor.store_schedule("Тест", _baseline_book(), None, "2026-07-01")
    for day in WEEKS:
        monitor.store_estimate("Тест", _rss_book(acts=[("15.07.2026", 1e6)],
                                                  payments=[(day, 1e6)]), day)
    return tmp_path


def _count_parses(monkeypatch):
    parsed: list[str] = []
    real = actuals._sheet

    def counting(path, name, **kwargs):
        if "ГПР" not in name:  # ГПР приходит байтами и читается быстро
            parsed.append(name)
        return real(path, name, **kwargs)

    monkeypatch.setattr(actuals, "_sheet", counting)
    return parsed


def test_the_trend_over_twelve_weeks_reads_each_rss_once(project, monkeypatch):
    parsed = _count_parses(monkeypatch)
    monitor.trend("Тест", cut=WEEKS[-1])
    first = len(parsed)
    monitor.trend("Тест", cut=WEEKS[-1])
    # Загрузка уже разобрала снимки: тренд их не читает, второй тем более.
    assert len(parsed) == first == 0, parsed


def test_a_fresh_worker_takes_the_parse_from_disk(project, monkeypatch):
    monkeypatch.setattr(actuals, "_READ_CACHE", type(actuals._READ_CACHE)())
    parsed = _count_parses(monkeypatch)
    monitor.trend("Тест", cut=WEEKS[-1])
    assert parsed == [], parsed
    cached = list((project / "monitor" / "Тест" / "estimate" / ".parsed").glob("*.pickle"))
    assert len(cached) == len(WEEKS) * 4


def test_a_changed_file_is_read_again(project, monkeypatch):
    path = project / "monitor" / "Тест" / "estimate" / f"{WEEKS[0]}.xlsx"
    path.write_bytes(_rss_book(acts=[("15.07.2026", 2e6)], payments=[(WEEKS[0], 5e6)]))
    monkeypatch.setattr(actuals, "_READ_CACHE", type(actuals._READ_CACHE)())
    assert actuals.read_payments(path)["total"] == pytest.approx(5e6)
    # Старый разбор того же снимка убран, а не копится.
    left = list(path.parent.joinpath(".parsed").glob(f"{WEEKS[0]}.read_payments.*.pickle"))
    assert len(left) == 1


def test_a_result_change_does_not_spoil_the_cache(project):
    path = project / "monitor" / "Тест" / "estimate" / f"{WEEKS[0]}.xlsx"
    first = actuals.read_payments(path)
    first["rows"].clear()
    assert actuals.read_payments(path)["rows"], "правка результата испортила кэш"


def test_files_outside_snapshots_are_not_cached_on_disk(tmp_path):
    outside = tmp_path / "рядом.xlsx"
    outside.write_bytes(_rss_book(payments=[("2026-07-03", 1e6)]))
    actuals.read_payments(outside)
    assert not (tmp_path / ".parsed").exists()


def test_trend_skips_unused_ahr_and_the_next_normal_view_keeps_it(project, monkeypatch):
    import developaid_admin_expenses_cash as cash
    calls = []
    model = {'budget': 100, 'paid_observed_net': None}
    def collect(project, cut):
        calls.append((project, cut))
        return model
    monkeypatch.setattr(cash, 'for_project', collect)
    points = monitor.trend('Тест', cut=WEEKS[-1])
    assert len(points) == len(WEEKS)
    assert calls == []
    view = monitor.build('Тест', cut=WEEKS[-1])
    assert calls == [('Тест', WEEKS[-1])]
    assert view['admin_expenses_cash'] is model


def test_failed_trend_does_not_disable_the_next_normal_view_ahr(project, monkeypatch):
    import developaid_admin_expenses_cash as cash
    original = monitor.build
    calls = []
    def fail(*args, **kwargs):
        raise ValueError('synthetic trend point failure')
    monkeypatch.setattr(monitor, 'build', fail)
    assert monitor.trend('Тест', cut=WEEKS[-1]) == []
    monkeypatch.setattr(monitor, 'build', original)
    monkeypatch.setattr(cash, 'for_project', lambda *args: calls.append(args) or {'budget': 100})
    view = monitor.build('Тест', cut=WEEKS[-1])
    assert calls == [('Тест', WEEKS[-1])] and view['admin_expenses_cash']['budget'] == 100


def test_historical_trend_context_does_not_disable_another_thread_view(project, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import developaid_admin_expenses_cash as cash
    original = monitor.build
    entered = threading.Event(); release = threading.Event(); calls = []
    def point(project, cut, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(project, cut, **kwargs)
    monkeypatch.setattr(monitor, 'build', point)
    monkeypatch.setattr(cash, 'for_project', lambda *args: calls.append(args) or {'budget': 100})
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(monitor.trend, 'Тест', WEEKS[-1])
        try:
            assert entered.wait(10)
            view = original('Тест', WEEKS[-1])
            assert view['admin_expenses_cash']['budget'] == 100
        finally:
            release.set()
        assert len(running.result(timeout=20)) == len(WEEKS)
    assert calls == [('Тест', WEEKS[-1])]
