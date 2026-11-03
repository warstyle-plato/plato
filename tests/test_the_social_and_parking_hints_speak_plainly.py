"""«Экономика» 4/4 — соцнагрузка, объекты, паркинг, кладовые простым языком.

Гайд — `docs/plain_language.md`. Пояснение начинается с единицы, объяснение
идёт отдельным предложением; телеграфа «; … — …» нет; ДОО, СОШ, «пос./смену»
расшифрованы. Поле `social_area_source` называется по тому, что делает:
выбор между нормативом и ручным вводом (решение владельца 19.10.2026: «не
обязательно писать „Требование КРТ“. Просто „ручной ввод“?»). Ключи вариантов
прежние — сохранённые проекты открываются как были.

Запуск: python3 -m pytest tests/test_the_social_and_parking_hints_speak_plainly.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_legacy as core  # noqa: E402

GROUPS = ("Социальная нагрузка", "Нормативы парковки нежилья (общие на объекты)",
          "Подземный паркинг", "Кладовые", "МФОЦ / офисы", "ТЦ / коммерция ОСЗ",
          "ФОК / медцентр", "Наземный паркинг")


def _fields() -> dict[str, list]:
    out: dict[str, list] = {}
    for name, fields in core.FIELD_GROUPS:
        if name in GROUPS:
            out.update({f[0]: f for f in fields})
    missing = set(GROUPS) - {name for name, _ in core.FIELD_GROUPS}
    assert not missing, missing
    return out


def test_no_telegraph_and_no_shorthand():
    for key, field in _fields().items():
        hint = str(field[2])
        # Точка с запятой в образце графика («60%@0; 40%@12») — синтаксис поля.
        assert ";" not in re.sub(r"«[^»]*»", "", hint), (key, hint)
        assert "пос./смену" not in hint, (key, hint)
        assert "Требование КРТ" not in hint, (key, hint)


def test_units_come_first():
    units = {key: core.class_field_unit(key) for key in (
        "kindergarten_places", "clinic_capacity", "clinic_cost_mln_per_unit",
        "social_dou_norm_sqm", "social_clinic_norm_sqm", "underground_manual_spaces",
        "underground_area_per_space_sqm", "storage_area_per_unit_sqm",
        "offices_cost_th_per_sqm", "above_parking_cost_mln_per_space",
        "offices_direct_sale_offset_months", "offices_parking_rent_th_month")}
    assert units == {
        "kindergarten_places": "мест", "clinic_capacity": "посещений в смену",
        "clinic_cost_mln_per_unit": "млн ₽ на одно посещение в смену",
        "social_dou_norm_sqm": "м²/место", "social_clinic_norm_sqm": "м²/посещение в смену",
        "underground_manual_spaces": "шт.", "underground_area_per_space_sqm": "м²/место",
        "storage_area_per_unit_sqm": "м²/шт.", "offices_cost_th_per_sqm": "тыс. ₽/м² GBA",
        "above_parking_cost_mln_per_space": "млн ₽/место",
        "offices_direct_sale_offset_months": "мес.",
        "offices_parking_rent_th_month": "тыс. ₽/место/мес. с НДС"}, units


def test_the_book_still_counts_visits():
    """Книга берёт формат ячейки по единице: посещения — целое число."""
    assert core._v4_input_format_code("number", "посещений в смену. Мощность…", 120) \
        == core._V4_FMT_COUNT


def test_the_short_names_are_spelled_out():
    fields = _fields()
    assert "ДОО — детский сад" in fields["kindergarten_places"][2]
    assert "СОШ — общеобразовательная школа" in fields["school_places"][2]
    assert "медико-техническое задание" in fields["social_clinic_norm_sqm"][2]
    assert "отдельно стоящих зданий" in fields["underground_area_per_space_sqm"][2]


def test_the_social_source_is_named_by_what_it_does():
    field = _fields()["social_area_source"]
    assert field[1] == "Как задаются соцобъекты"
    # Подписи короткие: на ширине телефона длинный вариант обрезается.
    assert dict(field[4]) == {"norm": "По нормативу", "manual": "Ручной ввод"}
    assert "например по решению о КРТ" in field[2]
    # Ручной ввод запирает не только площади: подпись это говорит.
    assert "компенсация за соцобъекты и плата за смену ВРИ" in field[2]
    for gone in ("Требование КРТ — вписываю руками", "— поле заперто требованием КРТ'",
                 "'Не тронуто — вписано требованием КРТ", "«Соцобъекты и плата за ВРИ»"):
        assert gone not in core.PAGE, gone


def test_the_object_rate_hint_is_a_sentence():
    hints = _fields()
    assert hints["offices_cost_th_per_sqm"][2] == "тыс. ₽/м² GBA. " + core.OBJECT_TURNKEY_HINT
    for text in (core.OBJECT_TURNKEY_HINT, core.OBJECT_SMR_HINT):
        assert ";" not in text and text[0].isupper() and text.endswith("."), text
