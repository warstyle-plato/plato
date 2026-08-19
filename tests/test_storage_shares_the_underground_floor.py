"""Кладовые лежат на том же подземном этаже, что и гараж.

Их площадь входит в подземную ГНС, а не прибавляется к ней: этаж один, и
считать его дважды — и в ГНС проекта, и в себестоимости подземной части —
значит выдумать метры, которых не строят (замечание владельца, 19.08.2026).

Вычитание идёт только из посчитанной площади. Если человек вписал площадь
гаража руками, это его число: подземный этаж мог быть спроектирован с запасом,
и молча его ужимать нельзя.

Запуск: python3 -m pytest tests/test_storage_shares_the_underground_floor.py -q
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


def _run(tep: dict) -> dict:
    """Гоняет настоящую функцию страницы через node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    body = re.search(r"function underlayStorageInParking\(\)\{.*?\n\}", core.PAGE, re.S)
    assert body, "underlayStorageInParking не найдена"
    script = (
        f"const tep={json.dumps(tep, ensure_ascii=False)};\n"
        + body.group(0)
        + "\nconst taken=underlayStorageInParking();"
        + "\nconsole.log(JSON.stringify({tep, taken}));"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_storage_comes_out_of_the_garage_not_on_top():
    answer = _run({"storage": {"gns": 2000}, "underground_parking": {"gns": 52850}})
    assert answer["tep"]["underground_parking"]["gns"] == pytest.approx(50850.0)
    assert answer["tep"]["underground_parking"]["total_area"] == pytest.approx(50850.0)
    assert answer["taken"] == pytest.approx(2000.0)


def test_the_underground_envelope_stays_the_same():
    """Сумма подземных метров не меняется — меняется их назначение."""
    before = {"storage": {"gns": 2000}, "underground_parking": {"gns": 52850}}
    after = _run(before)["tep"]
    assert after["underground_parking"]["gns"] + after["storage"]["gns"] == pytest.approx(52850.0)


def test_it_is_idempotent():
    """Пересчёт повторяется на каждый чих: второе вычитание из того же числа
    съело бы гараж."""
    once = _run({"storage": {"gns": 2000}, "underground_parking": {"gns": 52850}})["tep"]
    twice = _run(once)["tep"]
    assert twice["underground_parking"]["gns"] == pytest.approx(48850.0), (
        "функция не идемпотентна сама по себе — её зовут только после пересчёта площади")


def test_nothing_happens_without_storage():
    answer = _run({"storage": {"gns": 0}, "underground_parking": {"gns": 52850}})
    assert answer["tep"]["underground_parking"]["gns"] == pytest.approx(52850.0)
    assert answer["taken"] == 0


def test_the_storage_never_eats_more_than_the_floor():
    answer = _run({"storage": {"gns": 60000}, "underground_parking": {"gns": 52850}})
    assert answer["tep"]["underground_parking"]["gns"] == 0
    assert answer["taken"] == pytest.approx(52850.0)


def test_only_a_recalculated_area_is_touched():
    """Вписанная руками площадь гаража — число человека, а не наша производная."""
    page = core.PAGE.replace("\n", "")
    assert "if(repairParkingFromGlavapu())storageInsideParking=underlayStorageInParking()" in page
    assert page.count("storageInsideParking=underlayStorageInParking()") == 2, (
        "вычитание должно идти и в syncTep, и в updateTepTotals — и только там")


def test_the_table_says_where_the_metres_went():
    assert "лежат на этом же этаже" in core.PAGE
    assert "вычтена из гаража" in core.PAGE
