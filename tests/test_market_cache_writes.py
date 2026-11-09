"""Обновление JSON двумя воркерами оставляет целый файл и не теряет temp."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from market_search import http


def test_two_writers_use_separate_temporary_files(tmp_path, monkeypatch):
    path = tmp_path / "projects.json"
    barrier = Barrier(2)
    original = json.dump

    def dump(payload, handle, **kwargs):
        # Оба файла уже открыты: прежний общий projects.json.tmp столкнулся бы.
        barrier.wait(timeout=5)
        return original(payload, handle, **kwargs)

    monkeypatch.setattr(http.json, "dump", dump)
    values = [[{"id": "first"}], [{"id": "second", "name": "длинное имя"}]]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda value: http.save_json(path, value), values))
    assert http.load_json(path) in values
    assert list(tmp_path.iterdir()) == [path]


def test_failed_serialization_preserves_the_previous_file_and_removes_its_temp(tmp_path):
    path = tmp_path / "projects.json"
    http.save_json(path, [{"id": "old"}])
    with pytest.raises(TypeError):
        http.save_json(path, [{"id": object()}])
    assert http.load_json(path) == [{"id": "old"}]
    assert list(tmp_path.iterdir()) == [path]
