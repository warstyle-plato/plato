"""Имя файла из запроса не уводит путь за свой каталог.

Каждое место, где имя файла собирается из пришедшего снаружи (номер проекта,
код ссылки, номер задания Платона, имя картинки, дата снимка монитора),
проверяет РЕЗУЛЬТАТ одной дверью: `_safe_child` в движке и `_inside` в
мониторе. Регулярки у маршрутов остаются, но замок не должен от них зависеть:
здесь дверь спрашивают напрямую теми именами, которые регулярка бы не пустила.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402
import developaid_monitor  # noqa: E402

core = wrapper.core

_ESCAPES = ["../x.json", "../../etc/passwd", "..", "a/../../x", "/etc/passwd",
            "sub/x.json", "", "."]


@pytest.mark.parametrize("name", _ESCAPES)
def test_the_engine_door_refuses_to_leave_its_folder(tmp_path, name):
    with pytest.raises(ValueError):
        core._safe_child(tmp_path, name)
    with pytest.raises(HTTPException) as refused:
        core._safe_child(tmp_path, name, http_detail="Неверное имя")
    assert refused.value.status_code == 400
    assert refused.value.detail == "Неверное имя"


@pytest.mark.parametrize("name", _ESCAPES)
def test_the_monitor_door_refuses_to_leave_its_folder(tmp_path, name):
    with pytest.raises(ValueError):
        developaid_monitor._inside(tmp_path, name)


@pytest.mark.parametrize("door", ["engine", "monitor"])
def test_an_ordinary_name_lands_directly_in_the_folder(tmp_path, door):
    safe = core._safe_child if door == "engine" else developaid_monitor._inside
    for name in ("abcdef012345.json", "2026-09-27.xlsx", "job_ab12cd34.taken"):
        got = safe(tmp_path, name)
        assert got == tmp_path / name
        assert os.path.dirname(got) == os.path.normpath(tmp_path)


def test_a_sibling_folder_with_the_same_prefix_is_not_inside(tmp_path):
    """Без разделителя в конце базы «/x/assets-чужое» сошло бы за «внутри»."""
    base = tmp_path / "assets"
    with pytest.raises(ValueError):
        core._safe_child(base, "../assets-чужое/x.png")


def test_every_request_derived_path_goes_through_the_door(tmp_path, monkeypatch):
    """Читатели, а не только объявление: сами помощники путей зовут дверь."""
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    with pytest.raises(HTTPException):
        core._project_path(1, "../../x")
    assert core._project_path(1, "abcdef012345").parent == tmp_path / "projects" / "1"
    with pytest.raises(ValueError):
        core._plato_stage_path("trace", "../x")
    with pytest.raises(ValueError):
        core._plato_job_path("../x")
    with pytest.raises(HTTPException) as refused:
        core.developaid_asset("..")
    assert refused.value.status_code == 404
    monkeypatch.setattr(developaid_monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    with pytest.raises(ValueError):
        developaid_monitor.store_programme("p", b"x", None, "../../escape")
    assert not (tmp_path / "escape.xlsx").exists()
