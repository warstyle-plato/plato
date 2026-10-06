"""Приобъектные места не раздувают подземный паркинг МКД.

«У нас посчитано, что парковок в МКД 2778. Но 1000 из них по ГлавАПУ —
приобъектные» (владелец, 06.10.2026). Пресет КРТ Нагатино клал в гараж дома
все 2 503 места своей же разбивки: 1 619 постоянных + 162 гостевых, а с ними
703 приобъектных (встроенная коммерция 47, офис 328, ТЦ 328) и 19 мест
остановки. Эти 722 места строились под землёй — 25 270 м² метров и СМР — и
продавались, а места офиса и ТЦ модель строила ещё раз собственными гаражами
объектов.

945-ПП, п. 6.1.2: постоянные — в гаражах в приоритетном порядке, гостевые —
в гараже или на плоскостной парковке; приобъектные — гараж, плоскостная
парковка или сторона улицы в красных линиях УДС до 200 м; места остановки —
до 150 м от входа и «размещаются дополнительно». Число мест — норма, место
размещения — решение ППТ. Гараж МКД модели — постоянные и гостевые, как и у
выгрузки ГлавАПУ (строки 42.1–42.2; 42.3 и 43 — отдельно).

Запуск: python3 -m pytest tests/test_the_nagatino_garage_holds_no_attached_parking.py -q
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
for _key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "DEVELOPAID_WORKBOOK_CACHE",
             "NORMATIVES_WATCH", "NAGATINO_EGRN_READ"):
    os.environ.setdefault(_key, "0")

import document_intake  # noqa: E402
import project_preset  # noqa: E402

PRESET = ROOT / "presets" / "КРТ_Нагатино.json"


def _preset() -> dict:
    return json.loads(PRESET.read_text(encoding="utf-8"))


def test_the_split_is_read_from_the_preset_breakdown() -> None:
    split = project_preset.preset_parking_split(_preset())
    assert (split["permanent"], split["guest"], split["garage"]) == (1619, 162, 1781)
    assert split["attached"] == 703 and split["short_stop"] == 19
    assert split["attached_by"] == {"ground_commercial": 47, "office": 328, "retail": 328}


def test_no_breakdown_is_not_zero_attached() -> None:
    data = _preset()
    del data["tep_derived"]["parking"]
    assert project_preset.preset_parking_split(data) is None


def test_the_nagatino_garage_is_permanent_plus_guest() -> None:
    preview = project_preset.build_preview(_preset())
    row = preview["tep"]["underground_parking"]
    assert row["units"] == 1781 and row["gns"] == pytest.approx(1781 * 35)
    assert preview["inputs"]["underground_manual_spaces"] == 1781
    phases = [p["products"]["underground_parking"]["units"]
              for p in preview["phasing"]["phases"]]
    assert sum(phases) == 1781, "очереди строят другой гараж, чем проект"


def test_the_places_outside_the_garage_are_a_line_with_its_source() -> None:
    notes = [n for n in project_preset.build_preview(_preset())["notes"]
             if "вне подземного паркинга" in n["note"]]
    assert len(notes) == 1
    note = notes[0]
    assert note["value"] == 722 and note["origin"] == "source"
    assert "703 приобъектных" in note["note"] and "19 мест остановки" in note["note"]
    assert "945-ПП п. 6.1.2.3" in note["note"] and "tep_derived.parking" in note["note"]


def test_a_garage_holding_attached_places_is_refused() -> None:
    """Прежние числа пресета: 2 503 места в гараже при разбивке 1 619 + 162."""
    data = _preset()
    data["planning"]["underground"].update(spaces=2503, area_m2=87605)
    for phase, units in zip(data["phasing"]["phases"], (464, 464, 796, 779)):
        phase["underground_parking"] = {"units": units, "gns": units * 35}
    with pytest.raises(project_preset.PresetError) as err:
        project_preset.build_preview(data)
    assert "разница 722" in str(err.value) and "Приобъектные (703)" in str(err.value)


def test_the_model_builds_the_nagatino_house_garage_without_attached_places() -> None:
    """То, что видит человек: строка подземного паркинга посчитанной модели."""
    import golden_snapshot
    core = golden_snapshot.load_core(ROOT)
    case = golden_snapshot.s_nagatino(core, ROOT)
    bundle = core._run_authoritative_model(case["inputs"], case["tep"], [], case["phasing"])
    row = next(r for r in bundle["consolidated"]["tep"]["rows"]
               if r["key"] == "underground_parking")
    assert row["units"] == 1781
    assert row["gns"] == pytest.approx(1781 * 35)


@pytest.mark.parametrize("quote", [
    "Машино-места — 2 778, в том числе приобъектные — 1 000",
    "машино-мест всего 2778 (включая кратковременные)",
])
def test_intake_refuses_a_total_with_attached_places(quote) -> None:
    extraction = {"fields": [{"key": "underground_manual_spaces", "value": "2778",
                              "unit": "шт.", "quote": quote}]}
    got = document_intake.apply_intake(extraction, {"underground_manual_spaces": 0}, {},
                                       accept=["underground_manual_spaces"])
    assert got["inputs"]["underground_manual_spaces"] == 0
    assert got["refused"] and "945-ПП" in got["refused"][0]["reason"]


def test_intake_takes_a_garage_number() -> None:
    extraction = {"fields": [{"key": "underground_manual_spaces", "value": "1778",
                              "unit": "шт.",
                              "quote": "подземный паркинг на 1 778 машино-мест"}]}
    got = document_intake.apply_intake(copy.deepcopy(extraction), {}, {},
                                       accept=["underground_manual_spaces"])
    assert got["inputs"]["underground_manual_spaces"] == 1778 and not got["refused"]
