"""Плата за смену ВРИ на участке, который уже «многоэтажная жилая» (2.6).

Ночная проверка «Посадка ↔ нормативы» спросила, почему сайт берёт плату за
смену ВРИ (851, 2 379 и 1 458 млн ₽) там, где вид использования уже 2.6.
Прямой нормы для неизменного кода в актах нет (разбор «Нормативки»); решение
владельца 25.10.2026 — «ВРИ всё равно считается заново, так как это новое
строительство». Плата остаётся, подпись на странице называет основание — так
же, как в Московской области.

Строки основания по региону отдаёт сервер (`vri_fee_basis_by_region`) в ответе
`/land/lookup`; страница берёт строку региона проекта (`classRegion`) и
показывает её под суммой платы. Акт назван по региону: 593-ПП в Москве,
1745-ПП в области. Решает код 2.6 или точное имя вида, а не слово «многоэтажн»
(рецензия «Нормативки» к #924). Проверка — на настоящем коде
страницы (node) и настоящем эндпоинте.

Запуск: python3 -m pytest tests/test_vri_fee_basis_on_a_multistorey_site.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

MULTISTOREY = "Многоэтажная жилая застройка (высотная застройка)"
IZHS = "Для индивидуального жилищного строительства"


PARKING_271 = ("Хранение автотранспорта (2.7.1): размещение отдельно стоящих и "
               "пристроенных гаражей, в том числе многоэтажных стоянок")


def test_the_predicate_reads_the_code_and_the_classifier_name():
    assert core.vri_already_multistorey([MULTISTOREY])
    assert core.vri_already_multistorey(["Многоэтажная  жилая застройка"])
    assert core.vri_already_multistorey(["2.6"])
    assert core.vri_already_multistorey([IZHS, "код 2.6"])
    # Контрпримеры: слово «многоэтажн» в чужом виде, другой код, похожий номер.
    assert not core.vri_already_multistorey([PARKING_271])
    assert not core.vri_already_multistorey([IZHS])
    assert not core.vri_already_multistorey(["Среднеэтажная жилая застройка (2.5)"])
    assert not core.vri_already_multistorey(["12.6", "2.6.1"])
    assert not core.vri_already_multistorey([])


def test_the_text_names_the_act_of_the_region():
    assert "593-ПП" in core.vri_fee_basis_text([MULTISTOREY], "msk")
    assert "1745-ПП" in core.vri_fee_basis_text([MULTISTOREY], "mo")
    assert core.vri_fee_basis_text([MULTISTOREY], "other") == ""
    assert core.vri_fee_basis_text([PARKING_271], "msk") == ""


def _lookup(monkeypatch, use: str) -> dict:
    parcel = {"found": True, "cadastral_number": "77:07:0008006:3", "kind": "land",
              "permitted_use": use, "area_ha": 0.5808}
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_land_lookup_by_numbers", lambda numbers: [dict(parcel)])
    return core.land_lookup(core.LandLookupRequest(query="77:07:0008006:3"))


def test_the_lookup_carries_the_basis_only_for_a_multistorey_site(monkeypatch):
    by_region = _lookup(monkeypatch, MULTISTOREY)["vri_fee_basis_by_region"]
    assert set(by_region) == {"msk", "mo"}
    assert "как за новое строительство" in by_region["msk"] and "593-ПП" in by_region["msk"]
    assert "1745-ПП" in by_region["mo"]
    assert _lookup(monkeypatch, IZHS)["vri_fee_basis_by_region"] == {}
    assert _lookup(monkeypatch, PARKING_271)["vri_fee_basis_by_region"] == {}


def _note(lookup: dict, region: str = "") -> str:
    import page_blocks

    prelude = ("let inputs={land_rights_cost_mln:851.315,vri_region:%s,"
               "_field_origin:{'inputs.land_rights_cost_mln':{source:'glavapu'}},"
               "_land_lookup:%s};" % (json.dumps(region),
                                      json.dumps(lookup, ensure_ascii=False)))
    out, _ = page_blocks.run(prelude, "console.log(vriRequiredNote());")
    return out.strip()


def test_the_page_names_the_basis_and_the_act_of_the_project_region(monkeypatch):
    lookup = _lookup(monkeypatch, MULTISTOREY)
    note = _note(lookup, "msk")
    assert "851" in note and "(из ГлавАПУ)" in note
    assert "как за новое строительство" in note and "593-ПП" in note, \
        "плата на участке 2.6 обязана назвать основание и акт Москвы"
    mo = _note(lookup, "mo")
    assert "1745-ПП" in mo and "593-ПП" not in mo
    assert "новое строительство" not in _note(lookup, "other")


def test_the_page_stays_quiet_where_the_use_really_changes(monkeypatch):
    for use in (IZHS, PARKING_271):
        note = _note(_lookup(monkeypatch, use), "msk")
        assert "851" in note
        assert "новое строительство" not in note
