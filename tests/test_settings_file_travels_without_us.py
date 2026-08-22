"""Проект передаётся файлом настроек, а не только ссылкой.

Ссылка живёт на нашем сервере: он должен отвечать, а код — не протухнуть.
Файл не зависит ни от чего — его пересылают почтой, кладут в папку проекта,
открывают через год (просьба владельца, 21.08.2026). Внутри тот же снимок,
что и по ссылке: вводные, ТЭП, очерёдность, сценарий — и ничего сверх того.

Запуск: python3 -m pytest tests/test_settings_file_travels_without_us.py -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def page_function(name: str) -> str:
    start = core.PAGE.index(f"function {name}(")
    depth = 0
    for position in range(core.PAGE.index("{", start), len(core.PAGE)):
        if core.PAGE[position] == "{":
            depth += 1
        elif core.PAGE[position] == "}":
            depth -= 1
            if depth == 0:
                return core.PAGE[start:position + 1]
    raise AssertionError(f"не найдена функция {name}")


def test_both_ways_of_sharing_are_offered():
    """Ссылка и файл — разные способы передачи, один другого не заменяет."""
    page = core.PAGE
    assert "downloadSettingsFile(" in page and "shareProject(" in page
    assert "Загрузить файл настроек" in page
    assert "Скачать настройки текущего" in page, (
        "выгрузка не должна требовать сначала сохранить проект на сервер")


def test_the_file_carries_the_snapshot_and_nothing_else():
    """Тот же набор, что уходит по ссылке: вводные, ТЭП, очерёдность, сценарий."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = (
        "const SETTINGS_FILE_KIND='developaid.project.settings';\n"
        "const Date2=Date;\n"
        + page_function("settingsFileFrom") + "\n"
        + "console.log(JSON.stringify(settingsFileFrom('Тест',"
          "{inputs:{a:1},tep:{apartments:{gns:10}},phasing:null,scenario:'base'})));"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    data = json.loads(done.stdout)
    assert data["kind"] == "developaid.project.settings"
    assert data["app_version"] == core.VERSION, (
        "версия подставляется плейсхолдером — копии VERSION нет")
    assert data["inputs"] == {"a": 1}
    assert data["tep"] == {"apartments": {"gns": 10}}
    assert set(data) == {"kind", "version", "app_version", "name", "saved_at",
                         "inputs", "tep", "phasing", "scenario"}


def test_a_foreign_file_is_data_not_a_command():
    """Чужой файл проверяется на свой формат и накладывается на умолчания.

    Подмена умолчаний вместо наложения роняет поле, добавленное после выгрузки,
    — на этом уже обжигались с сохранённым состоянием браузера.
    """
    body = page_function("applySettingsFile")
    assert "data.kind!==SETTINGS_FILE_KIND" in body, "формат файла проверяется"
    assert "Это не файл настроек DevelopAid" in body
    assert "structuredClone(INPUT_DEFAULT)" in body, "наложение, а не подмена"
    assert "structuredClone(TEP_DEFAULT)" in body
    assert "confirm(" in body, "замена вводных на экране — с подтверждением"


def test_the_name_is_taken_where_saving_takes_it():
    """Своего поля с именем нет, и заводить второе значило бы развести их."""
    body = page_function("currentProjectName")
    assert "_manual_tep_import" in body and "projectCadastral()" in body
