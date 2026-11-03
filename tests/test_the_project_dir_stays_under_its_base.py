"""Каталог проекта — один сегмент под каталогом снимков, и никак иначе.

Имя проекта приходит от человека: из чата (`/site Кутузов Сити`), из кабинета,
а с 0.23.66 — из внесения выгрузки Telegram (`POST /monitor/daily/import`).
Дальше оно становится ИМЕНЕМ КАТАЛОГА на диске, и все десять читателей в пяти
модулях идут через одну дверь — `monitor._project_dir`.

Чистит имя `_slug`, и чистит честно: замер на четырнадцати враждебных вводах
даёт «etcpasswd» из «../../etc/passwd» и «project» из «..». Но это защита
регулярочная, а CodeQL её санитайзером не считает: на PR #417 он поднял четыре
находки высокой важности — `developaid_monitor.py:47` и три ниже по течению.
Кричащая зря проверка хуже отсутствующей, поэтому рядом со `_slug` стоит
замок на РЕЗУЛЬТАТ: `path.parent` обязан быть самим каталогом снимков.

Проверка держит ровно это утверждение и падает на подделке: со снятым `_slug`
(диверсант ниже) «../../etc/passwd» обязан получить отказ, а не каталог за
пределами базы. Иначе она зелена на любом коде — в том числе на том, где
замка нет вовсе.

Запуск: python3 -m pytest tests/test_the_project_dir_stays_under_its_base.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import developaid_monitor as monitor  # noqa: E402
import developaid_monitor_daily as daily  # noqa: E402

HOSTILE = [
    "../../etc/passwd",
    "..",
    ".",
    "/etc/passwd",
    "a/../../b",
    "....//....//x",
    "\\..\\..\\x",
    "..%2f..%2fx",
    "",
    "." * 80,
]


@pytest.fixture()
def base(tmp_path, monkeypatch):
    home = tmp_path / "monitor"
    home.mkdir()
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", home)
    return home.resolve()


@pytest.mark.parametrize("name", HOSTILE)
def test_a_hostile_name_never_leaves_the_base(base, name) -> None:
    """Либо каталог прямо под базой, либо отказ — третьего нет."""
    try:
        got = monitor._project_dir(name)
    except ValueError:
        return
    assert got.resolve().parent == base, name


def test_an_ordinary_name_still_works(base) -> None:
    """Предохранитель: замок, запирающий всё, прошёл бы проверку выше."""
    got = monitor._project_dir("Кутузов Сити")
    assert got.resolve().parent == base
    assert got.name == "Кутузов-Сити"
    assert got.is_dir()


def test_the_daily_folder_stays_under_the_base_too(base) -> None:
    """Сводки живут под тем же замком: своей двери у них нет."""
    got = daily._daily_dir("Кутузов Сити").resolve()
    assert got.parent.parent == base
    assert got.name == "daily"


def test_the_lock_holds_when_the_slug_is_taken_away(base, monkeypatch) -> None:
    """Диверсант: `_slug` снят, значит работает ровно замок.

    Без него `_SNAPSHOT_DIR / '../../etc/passwd'` уходит за пределы базы —
    и отказ обязан прийти оттуда, где он и написан.
    """
    monkeypatch.setattr(monitor, "_slug", lambda name: str(name))
    with pytest.raises(ValueError):
        monitor._project_dir("../../etc/passwd")
    assert not (base.parent.parent / "etc").exists()


def test_a_sibling_with_the_same_prefix_is_outside(base, monkeypatch) -> None:
    """Разделитель в конце базы — часть замка, а не украшение.

    База зовётся «…/monitor»; каталог «…/monitorX» начинается с неё буква в
    букву и лежит СНАРУЖИ. Без `os.sep` в конце `startswith` пускает его как
    «внутри» — классическая ошибка префикса, и ловится она только этим
    примером: под `_slug` он недостижим, поэтому диверсант снят и здесь.
    """
    monkeypatch.setattr(monitor, "_slug", lambda name: str(name))
    outside = base.parent / (base.name + "X")
    with pytest.raises(ValueError):
        monitor._project_dir(f"../{outside.name}")
    assert not outside.exists()
