"""Фоновое чтение завершается у владельца, сетевой guard МО остаётся строгим."""
import socket
import threading

import pytest

import conftest
from market_search import krt_registry


def test_real_catalogue_daemon_finishes_before_its_source_is_unpatched(tmp_path):
    patch = pytest.MonkeyPatch()
    lifecycle = conftest.krt_catalogue_threads.__wrapped__(patch)
    entered, release, finished = (threading.Event() for _ in range(3))
    threads = []
    join = threading.Thread.join
    calls = []

    def fetch(url, **_):
        calls.append(url)
        entered.set()
        assert release.wait(5), "обход не дождался teardown владельца"
        assert krt_registry.request_bytes is fetch
        finished.set()
        return (b'<a href="/projects/fixture">Fixture</a>'
                b'<p>Area: 1</p><p>Status: Planned</p>')

    def release_on_join(thread, *args, **kwargs):
        if thread in threads:
            assert krt_registry.request_bytes is fetch
            release.set()
        return join(thread, *args, **kwargs)

    next(lifecycle)
    try:
        # Именно defaultfetch: он читает request_bytes при каждом запросе,
        # поэтому ранний monkeypatch.undo действительно вернул бы живую сеть.
        patch.setattr(krt_registry, "request_bytes", fetch)
        patch.setattr(threading.Thread, "join", release_on_join)
        registry = krt_registry.KrtRegistry(tmp_path)
        assert registry.refresh_in_background() is True
        assert entered.wait(5)
        threads.extend(one for one in threading.enumerate()
                       if one.name == "krt-catalogue-refresh")
        assert len(threads) == 1 and threads[0].daemon
        assert registry._refreshing
        with pytest.raises(StopIteration):
            next(lifecycle)
        assert finished.is_set() and not threads[0].is_alive()
        assert not registry._refreshing
        assert calls == ["https://api.krt.mos.ru/projects/"]
    finally:
        release.set()
        for thread in threads:
            join(thread, timeout=5)
        lifecycle.close()
        patch.undo()


def test_unfinished_catalogue_daemon_is_an_owner_failure(tmp_path):
    entered, release = threading.Event(), threading.Event()
    threads = []

    def fetch(url):
        entered.set()
        assert release.wait(5)
        return b""

    registry = krt_registry.KrtRegistry(tmp_path, fetch=fetch)
    assert registry.refresh_in_background()
    try:
        assert entered.wait(5)
        threads = [one for one in threading.enumerate()
                   if one.name == "krt-catalogue-refresh"]
        assert len(threads) == 1
        with pytest.raises(AssertionError, match="незавершённый обход КРТ"):
            conftest._join_krt_catalogue_threads(threads, timeout=0)
        assert threads[0].is_alive(), "проверка не должна гасить daemon молча"
    finally:
        release.set()
        conftest._join_krt_catalogue_threads(threads)


def test_other_job_threads_keep_their_own_lifecycle():
    patch = pytest.MonkeyPatch()
    lifecycle = conftest.krt_catalogue_threads.__wrapped__(patch)
    stop = threading.Event()
    thread = threading.Thread(target=stop.wait, name="another-job-family", daemon=True)
    next(lifecycle)
    try:
        thread.start()
        with pytest.raises(StopIteration):
            next(lifecycle)
        assert thread.is_alive(), "fixture КРТ не владеет другими семействами задач"
    finally:
        stop.set()
        thread.join(timeout=5)
        lifecycle.close()
        patch.undo()


def test_mo_page_dns_guard_still_rejects_an_external_call():
    from test_mo_vri_full_page import served

    fixture = served.__wrapped__()
    next(fixture)
    try:
        with pytest.raises(AssertionError, match="localhost only"):
            socket.getaddrinfo("unexpected-mo-source.example", 443)
    finally:
        # Попытка не очищается и не игнорируется: настоящий fixture отдельно
        # отказывает и в момент вызова, и при завершении стенда.
        with pytest.raises(AssertionError, match="unexpected-mo-source.example"):
            next(fixture)
