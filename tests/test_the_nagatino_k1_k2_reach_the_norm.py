"""К1 и К2 пресета доходят до нормы приобъектной парковки.

Пресет КРТ Нагатино объявлял `territory_coefficients` — К1 0,75 и К2 0,5 из
выгрузки ГлавАПУ по кварталу 77:05:0004001, — но загрузчик их не читал: поля
`parking_k1` / `parking_k2` оставались пустыми, норма брала верхний край
К1 = К2 = 1, и гаражи ОСЗ строились по максимуму (владелец, 06.10.2026).
Выгрузка калькулятора ГлавАПУ считает приобъектные с теми же 0,75 × 0,5.

Запуск: python3 -m pytest tests/test_the_nagatino_k1_k2_reach_the_norm.py -q
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
for _key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "DEVELOPAID_WORKBOOK_CACHE",
             "NORMATIVES_WATCH", "NAGATINO_EGRN_READ"):
    os.environ.setdefault(_key, "0")

import project_preset  # noqa: E402

PRESET = ROOT / "presets" / "КРТ_Нагатино.json"


def _preset() -> dict:
    return json.loads(PRESET.read_text(encoding="utf-8"))


def test_the_preset_coefficients_land_in_the_engine_fields() -> None:
    preview = project_preset.build_preview(_preset())
    assert preview["inputs"]["parking_k1"] == 0.75
    assert preview["inputs"]["parking_k2"] == 0.5
    sourced = [note for note in preview["notes"]
               if note["origin"] == "source" and note["note"].startswith(("К1", "К2"))]
    assert len(sourced) == 2
    assert all("ГлавАПУ" in note["note"] for note in sourced)


def test_a_coefficient_out_of_range_is_named_not_carried() -> None:
    data = _preset()
    data["territory_coefficients"]["k2_business"] = 5
    preview = project_preset.build_preview(data)
    assert "parking_k2" not in preview["inputs"]
    assert any(note["origin"] == "tbd" and note["note"].startswith("К2")
               for note in preview["notes"])


def test_no_coefficients_leave_the_fields_empty() -> None:
    data = _preset()
    del data["territory_coefficients"]
    preview = project_preset.build_preview(data)
    assert "parking_k1" not in preview["inputs"] and "parking_k2" not in preview["inputs"]


def test_the_nagatino_object_garages_follow_the_city_coefficients() -> None:
    import golden_snapshot

    core = golden_snapshot.load_core(ROOT)
    case = golden_snapshot.s_nagatino(core, ROOT)
    bundle = core._run_authoritative_model(case["inputs"], case["tep"], [], case["phasing"])
    parking = bundle["consolidated"]["parking"]
    assert parking["k_origin"] == {"k1": "glavapu", "k2": "glavapu"}
    assert (parking["k1"], parking["k2"]) == (0.75, 0.5)
    rows = {row["tep_key"]: row for row in parking["rows"]}
    own = {item["tep_key"]: item for item in parking["own"] if item["enabled"]}
    for key in ("offices", "standalone_retail"):
        row = rows[key]
        expected = math.ceil(row["input_value"] / row["x2"] * 0.75 * 0.5)
        assert row["required_spaces"] == expected
        assert own[key]["by_norm"] and own[key]["under_spaces"] == expected
        # Верхний край дал бы в 2,67 раза больше — ловим именно его.
        assert own[key]["under_spaces"] < math.ceil(row["input_value"] / row["x2"]) / 2
