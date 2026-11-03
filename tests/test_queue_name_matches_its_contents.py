"""Очередь строит то, что написано в пресете рядом с её именем.

Пресет КРТ Нагатино объявлял метры прямо на очереди — `"offices": {...}`,
`"standalone_retail": {...}`, — а движок читал только вложенный `products`.
Всё, что стояло рядом с именем очереди, до расчёта не доезжало вовсе: жильё,
коммерция, паркинг и оба отдельно стоящих объекта раскладывались умолчаниями.
Подпись «Очередь 4 · ТЦ» при этом выглядела верной, а ТЦ по умолчанию движка
стоял во второй очереди — заметить это можно было только по тому, в какой
очереди дорожает себестоимость.

Вторая половина той же ошибки: объект, размещённый явно, умолчание `discrete`
сажало ещё раз. Пока пресет не доезжал, это молчало; как только доехал бы —
92 845 м² ГНС строились и продавались дважды.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main_legacy as core  # noqa: E402
import project_preset  # noqa: E402


PRESET = Path(__file__).resolve().parent.parent / "presets" / "КРТ_Нагатино.json"


def preview() -> dict:
    return project_preset.build_preview(json.loads(PRESET.read_text(encoding="utf-8")))


def _model(data: dict) -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(data["inputs"])
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for key, values in data["tep"].items():
        tep.setdefault(key, {})
        tep[key].update(values)
    return core._run_authoritative_model(
        inputs, tep, copy.deepcopy(core.RATE_CURVE), copy.deepcopy(data["phasing"]))


def test_products_written_next_to_the_queue_name_reach_the_engine() -> None:
    phases = preview()["phasing"]["phases"]
    assert "offices" in phases[2]["products"], "офисы объявлены в третьей очереди"
    assert "standalone_retail" in phases[3]["products"], "ТЦ объявлен в четвёртой"
    for index, phase in enumerate(phases):
        assert "apartments" in phase["products"], f"жильё очереди {index + 1}"
        assert "underground_parking" in phase["products"], f"паркинг очереди {index + 1}"


def test_the_standalone_objects_stand_where_the_queue_name_says() -> None:
    bundle = _model(preview())
    offices = [n(item, "offices_gba_sqm") for item in _phase_inputs(bundle)]
    retail = [n(item, "retail_gba_sqm") for item in _phase_inputs(bundle)]
    assert offices == pytest.approx([0.0, 0.0, 92845.0, 0.0])
    assert retail == pytest.approx([0.0, 0.0, 0.0, 92845.0])


def test_an_explicitly_placed_object_is_not_placed_a_second_time() -> None:
    """Умолчание `discrete` сажает ТЦ во вторую очередь — и не должно."""
    data = preview()
    data["phasing"]["discrete"] = {"offices": 3, "standalone_retail": 2}
    bundle = _model(data)
    retail = [n(item, "retail_gba_sqm") for item in _phase_inputs(bundle)]
    assert retail == pytest.approx([0.0, 0.0, 0.0, 92845.0]), (
        "явное размещение сильнее умолчания: ТЦ строится один раз")


def test_the_queues_add_up_to_the_project() -> None:
    data = preview()
    bundle = _model(data)
    master = bundle["consolidated"]["summary"]
    saleable = sum(item["result"]["summary"]["monetizable_saleable_sqm"]
                   for item in bundle["phases"])
    assert saleable == pytest.approx(master["monetizable_saleable_sqm"], rel=1e-6)


def test_the_preset_splits_the_whole_project_and_no_more() -> None:
    """Сумма метров по очередям равна проекту: иначе расчёт считает не тот ТЭП."""
    data = preview()
    phases = data["phasing"]["phases"]
    for key, field in (("apartments", "gns"), ("apartments", "saleable"),
                       ("ground_commercial", "gns"),
                       ("underground_parking", "gns"),
                       ("underground_parking", "units")):
        declared = sum(float((phase["products"].get(key) or {}).get(field) or 0.0)
                       for phase in phases)
        whole = float(data["tep"][key].get(field) or 0.0)
        assert declared == pytest.approx(whole, abs=1.0), f"{key}.{field}"


def _phase_inputs(bundle: dict) -> list[dict]:
    return [item["inputs"] for item in bundle["phases"]]


def n(row: dict, key: str) -> float:
    return float(row.get(key) or 0.0)
