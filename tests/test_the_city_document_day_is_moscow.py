"""День городского документа — по Москве, а не по часам зрителя.

Отметку ставит город и хранит полуночью московской: свежайшее распоряжение о
проведении аукциона лежит на 02.09.2026 21:00 UTC, то есть 03.09.2026 00:00
МСК (замер прода 09.09.2026). Печаталось оно `toLocaleDateString` без зоны —
значит в Москве «3 сентября», а западнее «2 сентября», и ни один читатель не
знает, какое из двух написано в самом документе.

Та же болезнь уже закрыта у срока подачи заявки (0.22.80) и осталась
незакрытой в соседнем месте: правило, закрытое в одном месте, соседнее не
защищает.

Проверять надо ЧУЖИМИ часами: в `Europe/Moscow` сломанный код и верный
печатают одно и то же, а владелец сидит в Москве — то есть сам он этого не
увидит никогда.

Запуск: python3 -m pytest tests/test_the_city_document_day_is_moscow.py -q
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import page_blocks

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402

# 03.09.2026 00:00 МСК. В UTC это ещё второе сентября — на том и ловится.
CITY_STAMP = 1_788_382_800
VIEWER_ZONES = ("Europe/Moscow", "UTC", "America/Los_Angeles", "Asia/Vladivostok")


def _run_in_zone(script: str, zone: str) -> dict:
    blocks = page_blocks.auctions_function("moscowFormat", "krtWhen", "krtCityDay")
    proc = subprocess.run(
        ["node", "-e", blocks + "\n" + script],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "TZ": zone},
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("zone", VIEWER_ZONES)
def test_the_document_day_is_the_same_in_any_viewer_zone(zone: str) -> None:
    answer = _run_in_zone(
        f"console.log(JSON.stringify({{shown:krtCityDay({CITY_STAMP})}}))", zone)
    assert answer["shown"] == "3 сентября 2026 г.", zone


def test_our_own_moments_stay_in_the_viewer_zone() -> None:
    """Наш собственный момент — не городская отметка, и часы зрителя ему рамка.

    Сделать московским ВСЁ было бы проще и неверно: возраст снимка, «посчитано»
    и «отмечено вручную» — это наши мгновения, и человек читает их своими
    часами.
    """
    here = _run_in_zone(
        f"console.log(JSON.stringify({{shown:krtWhen({CITY_STAMP})}}))", "UTC")
    assert here["shown"] == "2 сентября 2026 г.", (
        "наш момент пришпилен к Москве — тогда у зрителя он не его")


CITY_FIELDS = ("published_at", "draft_decision_at")


def test_no_city_stamp_goes_through_the_viewer_formatter() -> None:
    """Запрещено МЕСТО: городская отметка не печатается часами зрителя.

    Ищется вызов `krtWhen(...)`, внутри которого стоит городское поле, — а не
    слово `krtWhen` вообще: у наших собственных отметок он законен.
    """
    source = Path(ui.__file__).read_text(encoding="utf-8")
    offenders = [call for call in re.findall(r"krtWhen\(([^)]*)\)", source)
                 if any(field in call for field in CITY_FIELDS)]
    assert not offenders, (
        "городская дата печатается в зоне зрителя: " + "; ".join(offenders))


def test_the_zone_is_still_named_once() -> None:
    """Вторая копия зоны разошлась бы с первой молча."""
    source = Path(ui.__file__).read_text(encoding="utf-8")
    assert source.count("Europe/Moscow") == 1, "зона названа не один раз"
