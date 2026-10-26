"""Плата за смену ВРИ на участке, который уже «многоэтажная жилая» (2.6).

Ночная проверка «Посадка ↔ нормативы» спросила, почему сайт берёт плату за
смену ВРИ (851, 2 379 и 1 458 млн ₽) там, где вид использования уже 2.6.
Прямой нормы для неизменного кода в актах нет (разбор «Нормативки»); решение
владельца 25.10.2026 — «ВРИ всё равно считается заново, так как это новое
строительство». Плата остаётся, подпись на странице называет основание — так
же, как в Московской области.

Строку основания отдаёт сервер (`vri_fee_basis_text`) в ответе `/land/lookup`;
страница её показывает под суммой платы. Проверка — на настоящем коде
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


def test_the_predicate_reads_the_name_and_the_code():
    assert core.vri_already_multistorey([MULTISTOREY])
    assert core.vri_already_multistorey(["2.6"])
    assert core.vri_already_multistorey([IZHS, "код 2.6"])
    # Контрпримеры: другой код, похожий номер, пусто.
    assert not core.vri_already_multistorey([IZHS])
    assert not core.vri_already_multistorey(["Среднеэтажная жилая застройка (2.5)"])
    assert not core.vri_already_multistorey(["12.6", "2.6.1"])
    assert not core.vri_already_multistorey([])


def _lookup(monkeypatch, use: str) -> dict:
    parcel = {"found": True, "cadastral_number": "77:07:0008006:3", "kind": "land",
              "permitted_use": use, "area_ha": 0.5808}
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_land_lookup_by_numbers", lambda numbers: [dict(parcel)])
    return core.land_lookup(core.LandLookupRequest(query="77:07:0008006:3"))


def test_the_lookup_carries_the_basis_only_for_a_multistorey_site(monkeypatch):
    basis = _lookup(monkeypatch, MULTISTOREY)["vri_fee_basis"]
    assert "как за новое строительство" in basis and "решению владельца" in basis
    assert _lookup(monkeypatch, IZHS)["vri_fee_basis"] == ""


def _note(lookup: dict) -> str:
    import page_blocks

    prelude = ("let inputs={land_rights_cost_mln:851.315,"
               "_field_origin:{'inputs.land_rights_cost_mln':{source:'glavapu'}},"
               "_land_lookup:%s};" % json.dumps(lookup, ensure_ascii=False))
    out, _ = page_blocks.run(prelude, "console.log(vriRequiredNote());")
    return out.strip()


def test_the_page_names_the_basis_under_the_fee(monkeypatch):
    note = _note(_lookup(monkeypatch, MULTISTOREY))
    assert "851" in note and "(из ГлавАПУ)" in note
    assert "как за новое строительство" in note, \
        "плата на участке 2.6 обязана назвать основание"


def test_the_page_stays_quiet_where_the_use_really_changes(monkeypatch):
    note = _note(_lookup(monkeypatch, IZHS))
    assert "851" in note
    assert "новое строительство" not in note
