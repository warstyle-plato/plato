"""Карточка КРТ рисует официальный контур из файла карты, а не метку по адресу.

Карточка ставила метку геокодером и писала «официальный полигон границ каталогом
не публикуется» — при том что файл карты реестра несёт полигон каждой из 263
площадок, и обзорная карта их уже рисовала. Точка по адресу вставала в чужой
квартал («и карта», владелец, 02.09.2026). Теперь `/point` берёт площадку из
файла карты первой, геокодер — только когда её там нет, и говорит об этом.

Запуск: python3 -m pytest tests/test_the_krt_card_draws_the_official_outline.py -q
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_registry as registry_mod  # noqa: E402


def _registry(tmp_path):
    reg = registry_mod.KrtRegistry(tmp_path, fetch=lambda url: b"[]")
    payload = {
        "schema_version": registry_mod.MAP_CACHE_SCHEMA_VERSION,
        "retrieved_at": int(time.time()), "source": "map2025.json", "step_m": 40.0,
        "stale": False, "count": 1, "bbox_merc": [0, 0, 1, 1],
        "sites": [{"slug": "varshavskoe-37", "name": "Варшавское шоссе, вл. 37",
                   "rings_merc": [[[4187000, 7500000], [4187400, 7500000],
                                   [4187400, 7500400], [4187000, 7500400]]],
                   "centre_merc": [4187200, 7500200], "area_ha": 14.62}],
    }
    reg.map_path.parent.mkdir(parents=True, exist_ok=True)
    reg.map_path.write_text(json.dumps(payload), encoding="utf-8")
    return reg


def test_the_site_is_found_in_the_map_file_by_slug(tmp_path) -> None:
    reg = _registry(tmp_path)
    site = reg.map_site("varshavskoe-37")
    assert site and site["centre_merc"] == [4187200, 7500200]
    assert len(site["rings_merc"][0]) == 4
    # Нет в файле — None, а не выдуманный контур.
    assert reg.map_site("nowhere") is None
    assert reg.map_site("") is None


def test_the_point_route_asks_the_map_file_before_the_geocoder() -> None:
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    body = source[source.index("async def auction_krt_point"):]
    body = body[: body.index("async def auction_krt_ranking(")]
    assert body.index("map_site") < body.index("market.resolve_subject"), \
        "геокодер спрашивается раньше файла карты"
    assert '"rings_merc": rings' in body and '"geometry_status": geometry_status' in body
    assert "official_polygon" in body and "geocoded_point" in body
    assert "_mercator_to_wgs84" in body, "центр из меркатора не переводится в широту и долготу"
    # Откат на геокодер назван, а не молчит.
    assert "точка поставлена геокодером по адресу" in body


def test_the_card_draws_the_outline_and_names_its_source() -> None:
    page = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")
    body = page[page.index("function krtSiteMap("):]
    body = body[: body.index("\nfunction krtModelCell(")]
    assert "subject.rings_merc" in body, "контур с сервера не читается"
    assert "<path d=" in body and "vector-effect=\"non-scaling-stroke\"" in body
    assert "официальные границы территории из файла карты реестра КРТ" in body
    # Без контура — метка и честная причина, а не «не публикуется».
    assert "Этой площадки в файле карты реестра нет" in body
    assert "каталогом не публикуется" not in body
    # Живая карта — движковая, с этим контуром; своей проекции здесь нет.
    assert "openLandMap({" in body and "shapes:[{rings:rings" in body
    # Рисовальщик один: определение и один вызов.
    assert page.count("krtSiteMap(") == 2


def test_the_bridge_clears_the_previous_cadastre() -> None:
    """Кадастр и контур прошлого участка оставались в поле — и читались как
    участок площадки КРТ."""
    bridge = (ROOT / "auction_search" / "bridge.py").read_text(encoding="utf-8")
    krt = bridge[bridge.index("if(pending.krt_model){"):]
    krt = krt[: krt.index("return;\n  }")]
    assert "'cadastralNumbers'" in krt and "'landQuery'" in krt
    assert "landPreview" in krt
