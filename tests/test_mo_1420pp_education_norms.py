"""Места в детских садах и школах Подмосковья — по 1420-ПП.

Постановление Правительства Московской области от 26.10.2026 № 1420-ПП (в силе
со дня опубликования 26.10.2026) заменило в п. 5.18 нормативов 65 мест в ДОО на
50 и 135 мест в школах на 109 на 1000 жителей. Норма живёт в двух местах —
справочнике с цитатой (`mo_rngp_reference`) и умолчаниях движка
(`MO_NORMS_DEFAULT`), — и разойтись они могут молча. Сверка методики —
официальный пример приложения № 7, пересчитанный тем же постановлением:
300 жителей → 15 мест ДОО и 33 места школы.

Запуск: python3 -m pytest tests/test_mo_1420pp_education_norms.py -q
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import mo_rngp_reference as ref  # noqa: E402


def test_the_engine_counts_by_the_rule_with_the_quote():
    assert core.MO_NORMS_DEFAULT["kindergarten_places_per_1000"] == ref.SOCIAL_KINDERGARTEN_PLACES["value"] == 50.0
    assert core.MO_NORMS_DEFAULT["school_places_per_1000"] == ref.SOCIAL_SCHOOL_PLACES["value"] == 109.0
    for rule in (ref.SOCIAL_KINDERGARTEN_PLACES, ref.SOCIAL_SCHOOL_PLACES):
        assert "1420-ПП" in rule["document"], rule["rule_id"]
        assert rule["effective_from"] == "26.10.2026"
        assert "п. 5.18" in rule["point_table"]
        assert rule in ref.ALL_RULES


def test_the_official_example_of_appendix_7():
    """«300 × 50 / 1000 = 15 мест и 300 × 109 / 1000 = 33 места»."""
    out = core.mo_social_program(300 * core.MO_NORMS_DEFAULT["living_space_per_person_sqm"])
    assert out["population"] == 300
    assert out["kindergarten"]["places"] == 15
    assert math.ceil(out["school"]["required_places"]) == 33


def test_the_source_pack_carries_the_same_numbers():
    pack = (ROOT / "data" / "normatives" / "mo" / "pp_1420_2026-10-26.md").read_text(encoding="utf-8")
    assert ref.PP_1420["official_source"].split("/")[-1] in pack
    assert "26.10.2026" in pack
    assert "цифры «65» заменить цифрами «50»" in pack
    assert "цифры «135» заменить цифрами «109»" in pack
    assert "300 × 50 / 1000 = 15 мест" in pack and "300 × 109 / 1000 = 33 места" in pack
    # Переходное правило: старые обязательства по КРТ меняют стороны договора.
    assert "разрешение на строительство" in pack
    text = ROOT / "docs" / "normative" / "mo_rngp_chain" / "2026-10-26_1420-ПП.ocr.txt"
    assert text.is_file()
    assert "цифры «135» заменить цифрами «109»" in text.read_text(encoding="utf-8")
    assert "SHA-256 скана" in pack


def test_the_registry_names_1420_as_the_current_edition():
    import json

    rows = {row["id"]: row for row in json.loads(
        (ROOT / "data" / "normatives" / "registry.json").read_text(encoding="utf-8"))}
    row = rows["mo-713-30"]
    chain = {step["number"]: step for step in row["amendment_chain"]}
    step = chain["1420-ПП"]
    assert step["eo_number"] == "5000202610260001"
    assert step["status"] == "разобран"
    assert (ROOT / step["text_file"]).is_file()
    assert (ROOT / step["pack"]).is_file()
    assert row["current_as_of"] >= "2026-11-12"
