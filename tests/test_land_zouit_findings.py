"""Скрининг: пересекающие точку ЗОУИТ из НСПД, структурировано.

Развилка «атрибуты или геометрия» закрыта пробой 17.08.2026: НСПД по
GetFeatureInfo (v3) отдаёт ЗОУИТ с полями — тип, наименование по документу,
реестровый номер границы, текст ограничения, реквизиты документа. Здесь
закреплено, что движковая функция собирает эти поля из реального ответа НСПД:

- находка несёт тип зоны, имя, реестровый номер и документ-основание;
- один реестровый номер из нескольких подслоёв — одна находка, не дубль;
- слой, ответивший ошибкой, пропускается, а не рушит скрининг;
- пустой ответ — пустой список (ограничений в точке не обнаружено).

Образец — настоящий ответ по участку 50:20:0070312:8320 (приаэродромная
территория Внуково, слой 37581).

Запуск: python3 -m pytest tests/test_land_zouit_findings.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core

# Настоящий объект из НСПД (сокращённый), слой 37581.
_VNUKOVO = {
    "type": "Feature",
    "properties": {"options": {
        "type_zone": "Приаэродромная территория",
        "name_by_doc": "Третья подзона приаэродромной территории аэродрома Москва (Внуково)",
        "reg_numb_border": "50:00-6.3453",
        "descr": "50:00-6.3453",
        "content_restrict_encumbrances": "В соответствии с Решением об установлении приаэродромной территории…",
        "legal_act_document_name": "Приказ Об установлении приаэродромной территории аэродрома Москва (Внуково)",
        "legal_act_document_number": "394-П",
        "legal_act_document_date": "17.04.2020",
        "legal_act_document_issuer": "Росавиация",
        "interactionId": "1746829977",
    }},
}


def test_the_finding_carries_type_number_and_document(monkeypatch):
    def fake(lat, lng, layer_id, api_version="v3"):
        assert api_version == "v3", "ЗОУИТ опрашиваются на v3"
        if layer_id == 37578:
            raise core.HTTPException(status_code=400, detail="слой капризничает")
        if layer_id == 37581:
            return {"features": [_VNUKOVO]}
        return {"features": []}

    monkeypatch.setattr(core, "_nspd_getfeatureinfo", fake)
    findings = core._land_zouit_findings(55.627122, 37.205404)

    assert len(findings) == 1, "ошибочный слой не должен ни ронять, ни задваивать"
    found = findings[0]
    assert found["type_zone"] == "Приаэродромная территория"
    assert found["name"].startswith("Третья подзона")
    assert found["reg_number"] == "50:00-6.3453"
    assert found["document_number"] == "394-П"
    assert found["document_date"] == "17.04.2020"
    assert found["layer_id"] == 37581


def test_the_same_border_from_two_sublayers_is_one_finding(monkeypatch):
    monkeypatch.setattr(core, "_nspd_getfeatureinfo",
                        lambda *a, **k: {"features": [_VNUKOVO]})
    findings = core._land_zouit_findings(55.6, 37.2)
    assert len(findings) == 1, "один реестровый номер — одна находка"


def test_no_restrictions_gives_an_empty_list(monkeypatch):
    monkeypatch.setattr(core, "_nspd_getfeatureinfo", lambda *a, **k: {"features": []})
    assert core._land_zouit_findings(55.75, 37.62) == []


def test_the_flag_class_follows_the_zone_type():
    """Класс флага — по типу зоны словами, а не по номеру слоя: номера
    подслоёв меняются, тип приходит в ответе."""
    cases = {
        "Приаэродромная территория": ("economic", "высот"),
        "Санитарно-защитная зона предприятия": ("killer", "СЗЗ"),
        "Особо охраняемая природная территория": ("killer", "ООПТ"),
        "Лесничество": ("killer", "лесного фонда"),
        "Водоохранная зона реки": ("economic", "водоохранной"),
        "Охранная зона газопровода": ("economic", "пятно"),
    }
    for zone, (expected_class, expected_words) in cases.items():
        got = core._land_screen_classify({"type_zone": zone, "name": zone})
        assert got["flag_class"] == expected_class, zone
        assert expected_words.lower() in got["impact"].lower(), zone


def test_an_unknown_zone_is_flagged_honestly():
    """Неопознанный тип — info с пометкой «проверить вручную», а не молчаливое
    «ничего страшного»: неизвестное ограничение не равно его отсутствию."""
    got = core._land_screen_classify({"type_zone": "Зона неведомая", "name": ""})
    assert got["flag_class"] == "info"
    assert "вручную" in got["impact"]


def test_classification_keeps_the_original_fields():
    got = core._land_screen_classify(dict(_VNUKOVO["properties"]["options"]))
    assert got["reg_numb_border"] == "50:00-6.3453"
    assert got["flag_class"] == "economic"


def test_the_screening_needs_no_layer_names_in_advance(monkeypatch):
    """Имена слоёв заранее не нужны: слой называет себя сам в ответе.

    Это снимает всю ручную разведку «какой номер чему соответствует»
    (18.08.2026): каталог id снят с консоли карты, а смысл приходит в момент
    запроса. Административная обвязка ПКК отсеивается по имени.
    """
    def fake(lat, lng, layer_id, api_version="v3"):
        if layer_id == 875831:  # шум: населённые пункты
            return {"features": [{"properties": {"options": {
                "categoryName": "ПКК. Населённые пункты (полигоны)",
                "descr": "77:08-7.45"}}}]}
        if layer_id == 875845:  # ограничение, имя заранее неизвестно
            return {"features": [{"properties": {"options": {
                "categoryName": "Особо охраняемые природные территории",
                "type_zone": "Особо охраняемая природная территория",
                "reg_numb_border": "77:00-6.111"}}}]}
        if layer_id == 37581:
            return {"features": [_VNUKOVO]}
        return {"features": []}

    monkeypatch.setattr(core, "_nspd_getfeatureinfo", fake)
    found = core._land_screen_findings(55.75, 37.42)

    names = {f["reg_number"]: f for f in found}
    assert "77:08-7.45" not in names, "административная обвязка ПКК — не ограничение"
    assert names["77:00-6.111"]["flag_class"] == "killer", "ООПТ опознана без словаря имён"
    assert names["50:00-6.3453"]["flag_class"] == "economic"
    assert names["77:00-6.111"]["category"] == "Особо охраняемые природные территории"


def test_every_screening_layer_is_probed(monkeypatch):
    seen: list[int] = []
    monkeypatch.setattr(core, "_nspd_getfeatureinfo",
                        lambda lat, lng, layer_id, api_version="v3":
                        (seen.append(layer_id), {"features": []})[1])
    core._land_screen_findings(55.75, 37.62)
    assert seen == list(core._NSPD_SCREEN_LAYERS)
    assert set(core._NSPD_ZOUIT_LAYERS) <= set(core._NSPD_SCREEN_LAYERS)
