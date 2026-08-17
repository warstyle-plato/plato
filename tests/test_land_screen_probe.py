"""Проба слоёв НСПД для скрининга: GetFeatureInfo по кандидатам в точке.

Первый инструмент архитектуры град-скрининга
(docs/land_screening_architecture.md): по точке спросить у слоёв НСПД, что
отдаёт GetFeatureInfo, — какой номер какому слою отвечает и несёт ли слой
«Территориальные зоны» параметры застройки атрибутами. Живой НСПД закрыт WAF
для песочницы, поэтому здесь закреплено поведение вокруг сети, а не сама сеть:

- запрос форвардится на ядро, если задан адрес ядра (как /land/map-probe):
  с Render и телефона НСПД недоступен, перебор идёт с ядра;
- без адреса ядра проба идёт локально: перебирает слои, а по каждому кладёт
  число объектов, ключи и образец properties первого объекта;
- список слоёв читается из `?layers=имя=номер,...`, дефолт — кандидаты
  `_NSPD_SCREEN_LAYER_CANDIDATES`; недоступный слой не роняет пробу, а
  попадает в ответ своим http-кодом.

Запуск: python3 -m pytest tests/test_land_screen_probe.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def _land_feature(**options):
    return {"type": "Feature", "properties": {"options": dict(options)}}


def test_local_probe_reports_attributes_per_layer(monkeypatch):
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")

    calls: list[int] = []

    def fake_getfeatureinfo(lat, lng, layer_id, api_version="v3"):
        calls.append(layer_id)
        if layer_id == 36048:
            return {"features": [_land_feature(
                cadastral_number="77:01:0001001:1", area_sqm=1200.0)]}
        raise core.HTTPException(status_code=404, detail="нет слоя")

    monkeypatch.setattr(core, "_nspd_getfeatureinfo", fake_getfeatureinfo)

    result = core.land_screen_probe(lat=55.75, lng=37.62, layers="parcels=36048,terr=99999")

    assert result["point"] == {"lat": 55.75, "lng": 37.62}
    parcels = result["layers"]["parcels"]
    assert parcels["layer_id"] == 36048
    assert parcels["features"] == 1
    assert "cadastral_number" in parcels["keys"]
    assert parcels["sample"]["area_sqm"] == "1200.0"
    # Недоступный слой не роняет пробу — приходит своим http-кодом.
    assert result["layers"]["terr"] == {"layer_id": 99999, "http": 404}
    assert calls == [36048, 99999]


def test_a_cadastral_number_sets_the_point_to_the_parcel_centre(monkeypatch):
    """cad резолвится в центр участка — бить по знакомому участку с ЗОУИТ
    удобнее, чем по координатам (тот же путь, что overlay-probe)."""
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_nspd_search_features", lambda q: [
        {"geometry": {"type": "Polygon", "coordinates": [
            [[37.4, 55.7], [37.5, 55.7], [37.5, 55.8], [37.4, 55.8], [37.4, 55.7]]]}}])
    seen_points: list[tuple[float, float]] = []

    def fake_getfeatureinfo(lat, lng, layer_id, api_version="v3"):
        seen_points.append((lat, lng))
        return {"features": []}

    monkeypatch.setattr(core, "_nspd_getfeatureinfo", fake_getfeatureinfo)
    result = core.land_screen_probe(cad="50:20:0070312:8321", layers="z=37577")

    assert result["point"] == {"lat": pytest.approx(55.75), "lng": pytest.approx(37.45)}
    assert seen_points == [(pytest.approx(55.75), pytest.approx(37.45))]


def test_empty_layers_falls_back_to_the_candidate_registry(monkeypatch):
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    seen: list[tuple[int, str]] = []

    def fake_getfeatureinfo(lat, lng, layer_id, api_version="v3"):
        seen.append((layer_id, api_version))
        return {"features": []}

    monkeypatch.setattr(core, "_nspd_getfeatureinfo", fake_getfeatureinfo)

    result = core.land_screen_probe()

    # Дефолтная точка — центр Москвы, дефолтные слои — кандидаты реестра,
    # версия пути — v3 (GetFeatureInfo; v4 на GetFeatureInfo отвечает 502).
    assert result["point"]["lat"] == pytest.approx(55.751244)
    assert {layer for layer, _ in seen} == set(core._NSPD_SCREEN_LAYER_CANDIDATES.values())
    assert all(version == "v3" for _, version in seen), "GetFeatureInfo идёт на v3"
    a_key = next(iter(core._NSPD_SCREEN_LAYER_CANDIDATES))
    assert result["layers"][a_key]["features"] == 0
    assert "keys" not in result["layers"][a_key]


def test_probe_forwards_to_core_when_configured(monkeypatch):
    monkeypatch.setattr(core, "_core_api_url",
                        lambda path: "https://core.example" + path)

    captured: dict[str, str] = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"point": {"lat": 1.0, "lng": 2.0}, "layers": {}}'

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        return _Resp()

    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    # Сеть НСПД трогать не должны — форвард уходит на ядро.
    monkeypatch.setattr(core, "_nspd_getfeatureinfo", lambda *a, **k:
                        pytest.fail("проба обязана форвардиться, а не звать НСПД"))

    result = core.land_screen_probe(lat=1.0, lng=2.0, layers="terr=100")

    assert result == {"point": {"lat": 1.0, "lng": 2.0}, "layers": {}}
    assert captured["url"].startswith("https://core.example/land/screen-probe?")
    assert "layers=terr%3D100" in captured["url"]
    assert "ver=v3" in captured["url"], "версия пути обязана доехать до ядра"


def test_the_sweep_reports_only_answering_layers(monkeypatch):
    """Перебор номеров: возвращаются только ответившие слои, с их именем.

    Каталога слоёв НСПД не публикует, а ответ самоописателен (`categoryName`),
    поэтому номера ищутся перебором с ядра. Диапазон ограничен, чтобы не
    молотить портал.
    """
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")

    def fake(lat, lng, layer_id, api_version="v3"):
        if layer_id == 37581:
            return {"features": [_land_feature(
                categoryName="Зоны с особыми условиями использования территории",
                type_zone="Приаэродромная территория", label="50:00-6.3453")]}
        if layer_id == 37579:
            raise core.HTTPException(status_code=400, detail="капризный слой")
        return {"features": []}

    monkeypatch.setattr(core, "_nspd_getfeatureinfo", fake)
    monkeypatch.setattr(core, "_NSPD_SWEEP_PAUSE_SECONDS", 0)
    result = core.land_layer_sweep(lat=55.6, lng=37.2, start=37577, end=37581)

    assert list(result["found"]) == ["37581"], "молчащие и сбойные слои в улов не идут"
    assert result["found"]["37581"]["type_zone"] == "Приаэродромная территория"
    assert result["range"] == [37577, 37581]
    # Отказы обязаны быть видны: пустой улов при отбитых запросах читался бы
    # как «ограничений нет» — а это неверный вывод (пустая разведка 17.08.2026).
    assert result["failures"] == {"http 400": 1}
    assert result["stats"] == {"probed": 5, "answered": 1, "empty": 3, "failed": 1}


def test_the_sweep_refuses_a_huge_range(monkeypatch):
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    with pytest.raises(core.HTTPException) as exc:
        core.land_layer_sweep(lat=55.6, lng=37.2, start=1, end=5000)
    assert exc.value.status_code == 400
