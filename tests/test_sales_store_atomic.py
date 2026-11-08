"""Два процесса сохраняют разные части проекта без потери соседнего источника."""
from __future__ import annotations

import multiprocessing
import stat
from pathlib import Path

import pytest

from market_search import sales_store


def _snapshot(corpus, as_of="2026-11-06"):
    return {"buildings": {str(corpus): {"as_of": as_of, "lots": []}}}


def _save_worker(where, parts, started, entered_load, release_load, outcome):
    """Первый writer можно задержать ПОСЛЕ чтения, пока второй входит в save."""
    original = sales_store.load

    def paused_load(*args):
        value = original(*args)
        entered_load.set()
        if release_load is not None and not release_load.wait(10):
            raise RuntimeError("test writer was not released")
        return value

    sales_store.load = paused_load
    started.set()
    try:
        sales_store.save(Path(where), "Тест", parts, "synthetic.xlsx")
        outcome.put("ok")
    except Exception as exc:
        outcome.put(type(exc).__name__)
        raise


@pytest.mark.parametrize("different_sources", [False, True])
def test_two_processes_preserve_corpora_and_other_sources(tmp_path, different_sources):
    sales_store.save(tmp_path, "Тест", {"ledger": {"rows": [{"amount": 12}]}}, "initial.xlsx")
    ctx = multiprocessing.get_context("fork")
    first_started, second_started = ctx.Event(), ctx.Event()
    first_read, second_read, release = ctx.Event(), ctx.Event(), ctx.Event()
    outcome = ctx.Queue()
    first_parts = {"contracting": {"rows": [{"contract": "A"}]}} if different_sources else {
        "chessboard": _snapshot(1)}
    second_parts = {"bank_plan": {"quarters": [{"amount": 30}]}} if different_sources else {
        "chessboard": _snapshot(2)}
    first = ctx.Process(target=_save_worker, args=(str(tmp_path), first_parts,
                        first_started, first_read, release, outcome))
    second = ctx.Process(target=_save_worker, args=(str(tmp_path), second_parts,
                         second_started, second_read, None, outcome))
    try:
        first.start()
        assert first_read.wait(10)
        second.start()
        assert second_started.wait(10)
        # The first writer has read the old version but has not committed yet.
        # A second process must not read a stale copy of that same version.
        assert not second_read.wait(.25)
        release.set()
        first.join(10)
        second.join(10)
        assert first.exitcode == second.exitcode == 0
        assert [outcome.get(timeout=2), outcome.get(timeout=2)] == ["ok", "ok"]
        sources = sales_store.load(tmp_path, "Тест")["sources"]
        assert sources["ledger"]["data"] == {"rows": [{"amount": 12}]}
        if different_sources:
            assert sources["contracting"]["data"] == first_parts["contracting"]
            assert sources["bank_plan"]["data"] == second_parts["bank_plan"]
        else:
            assert set(sources["chessboard"]["data"]["buildings"]) == {"1", "2"}
    finally:
        release.set()
        for worker in (first, second):
            if worker.pid is not None:
                worker.join(2)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)
        outcome.close()
        outcome.join_thread()


@pytest.mark.parametrize("stage", ["serialize", "fsync", "replace"])
def test_error_before_replace_preserves_previous_bytes_and_cleans_temporary_file(tmp_path, monkeypatch, stage):
    sales_store.save(tmp_path, "Тест", {"ledger": {"rows": [1]}}, "initial.xlsx")
    place = sales_store._path(tmp_path, "Тест")
    before = place.read_bytes()
    if stage == "serialize":
        payload = {"bad": object()}
        expected = TypeError
    else:
        payload = {"bank_plan": {"amount": 40}}
        expected = OSError

        def fail(*_args):
            raise OSError("synthetic disk failure")

        monkeypatch.setattr(sales_store.os, stage, fail)
    with pytest.raises(expected):
        sales_store.save(tmp_path, "Тест", payload, "new.xlsx")
    assert place.read_bytes() == before
    assert not list(place.parent.glob(".sources-write-*"))
    assert sales_store.load(tmp_path, "Тест")["sources"]["ledger"]["data"] == {"rows": [1]}


def test_old_snapshot_rejects_entire_upload_without_changing_other_sources(tmp_path):
    sales_store.save(tmp_path, "Тест", {"ledger": {"amount": 12},
                     "chessboard": _snapshot(1)}, "initial.xlsx")
    place = sales_store._path(tmp_path, "Тест")
    before = place.read_bytes()
    with pytest.raises(ValueError, match="старше"):
        sales_store.save(tmp_path, "Тест", {"ledger": {"amount": 99},
                         "chessboard": _snapshot(1, "2026-11-05")}, "old.xlsx")
    assert place.read_bytes() == before


@pytest.mark.parametrize("raw", [b"{broken", b"[]", b'{"sources": []}'])
def test_damaged_store_is_not_replaced_with_one_new_source(tmp_path, raw):
    place = sales_store._path(tmp_path, "Тест")
    place.parent.mkdir(parents=True)
    place.write_bytes(raw)
    with pytest.raises(ValueError, match="повреждены"):
        sales_store.save(tmp_path, "Тест", {"chessboard": _snapshot(1)}, "new.xlsx")
    assert place.read_bytes() == raw


def test_sources_and_lock_are_private_and_list_contains_no_partial_file(tmp_path):
    sales_store.save(tmp_path, "Тест", {"chessboard": _snapshot(1)}, "synthetic.xlsx")
    place = sales_store._path(tmp_path, "Тест")
    assert stat.S_IMODE(place.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(place.stat().st_mode) == 0o600
    assert stat.S_IMODE(place.with_suffix(".sources.lock").stat().st_mode) == 0o600
    assert [p["project"] for p in sales_store.projects(tmp_path)] == ["Тест"]
