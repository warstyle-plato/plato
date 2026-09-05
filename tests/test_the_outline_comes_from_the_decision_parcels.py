"""Площадки нет в файле карты — контур собирается из участков проекта решения.

Файл карты реестра (`map2025.json`, 263 записи) — не весь реестр: у 35 строк
каталога из 268 записи в нём нет, и у Варшавского ш., вл. 37 контур не
приезжал никаким сопоставлением имён — починка 03.09 искала площадку там, где
её не было (владелец, 04.09.2026: «и что с контуром КРТ Нагатино? почему его
до сих пор нет»). Проект решения о КРТ перечисляет состав территории — участки
и здания с кадастровыми номерами, — а ЕГРН отдаёт контур каждого участка.

Запуск: python3 -m pytest tests/test_the_outline_comes_from_the_decision_parcels.py -q
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402
from market_search import krt_registry as registry_mod  # noqa: E402
from market_search import krt_requirements as requirements_mod  # noqa: E402

DECISION = """
Проект решения о комплексном развитии территории нежилой застройки
Предельный срок реализации решения о КРТ составляет 9 лет со дня заключения договора.
Перечень земельных участков и объектов капитального строительства
1 77:05:0004006:12 г. Москва, Варшавское ш., влд. 37 77:05:0004006:1041 727,8 Снос
2 77:05:0004006:15 г. Москва, Нагатинская ул., влд. 3А/6 77:05:0004006:1031 66,8 Сохранение
3 77:05:0004006:12 повтор той же строки 77:05:0004006:1050 100,0 Снос
"""


def test_the_appendix_numbers_are_read_in_order_without_repeats() -> None:
    facts = requirements_mod.parse_decision_requirements(DECISION, "проект решения")
    assert facts["cadastral_numbers"] == [
        "77:05:0004006:12", "77:05:0004006:1041", "77:05:0004006:15",
        "77:05:0004006:1031", "77:05:0004006:1050"]
    assert facts["cadastral_numbers_source"] == "appendix"
    # Перечня нет — номера берутся из текста, и это названо иной уверенностью.
    loose = requirements_mod.parse_decision_requirements(
        "в границах участка 77:05:0004006:99 и никакого перечня", "")
    assert loose["cadastral_numbers"] == ["77:05:0004006:99"]
    assert loose["cadastral_numbers_source"] == "text"
    assert requirements_mod.parse_decision_requirements("без номеров", "")[
        "cadastral_numbers_source"] == "none"
    # Слияние с карточкой номера не теряет.
    merged = requirements_mod.merge_decision_requirements(
        {"construction": []}, facts, {"title": "проект решения"})
    assert merged["cadastral_numbers"] == facts["cadastral_numbers"]


def _registry(tmp_path, numbers, *, decision=True):
    reg = registry_mod.KrtRegistry(tmp_path, fetch=lambda url: b"[]")
    reg.requirements_dir.mkdir(parents=True, exist_ok=True)
    cached = {
        "schema_version": registry_mod.REQUIREMENTS_CACHE_SCHEMA_VERSION,
        "slug": "varshavskoe-37", "available": True, "retrieved_at": int(time.time()),
        "cadastral_numbers": numbers, "cadastral_numbers_source": "appendix",
    }
    if decision:
        cached["decision"] = {"title": "Проект решения о КРТ Варшавское ш., влд. 37",
                              "page_url": "https://www.mos.ru/dgp/documents/view/1/",
                              "pdf_url": "https://www.mos.ru/upload/1.pdf"}
    (reg.requirements_dir / "varshavskoe-37.json").write_text(
        json.dumps(cached, ensure_ascii=False), encoding="utf-8")
    # Каталога у стенда нет — требования отдаются из того же кэша, что на диске.
    reg.requirements = lambda slug, refresh=False: json.loads(  # type: ignore[method-assign]
        (reg.requirements_dir / f"{slug}.json").read_text(encoding="utf-8"))
    return reg


def _egrn(asked: list[str]) -> list[dict]:
    square = [[[4187000, 7500000], [4187400, 7500000], [4187400, 7500400], [4187000, 7500400]]]
    answers = {
        "77:05:0004006:12": {"found": True, "kind": "land", "contour_merc": square,
                             "area_sqm": 80000.0},
        "77:05:0004006:15": {"found": True, "kind": "land",
                             "contour_merc": [[[4187400, 7500000], [4187800, 7500000],
                                               [4187800, 7500400]]], "area_sqm": 40000.0},
        "77:05:0004006:1041": {"found": True, "kind": "building", "contour_merc": square},
    }
    return [dict(answers.get(n, {"found": False}), cadastral_number=n) for n in asked]


def test_the_outline_is_built_from_land_parcels_only(tmp_path) -> None:
    reg = _registry(tmp_path, ["77:05:0004006:12", "77:05:0004006:1041",
                               "77:05:0004006:15", "77:05:0004006:0"])
    calls: list[list[str]] = []

    def lookup(numbers):
        calls.append(list(numbers))
        return _egrn(numbers)

    outline = reg.decision_outline("varshavskoe-37", lookup=lookup)
    assert outline["counts"] == {"numbers": 4, "asked": 4, "land": 2, "buildings": 1,
                                 "missing": 1}
    # Два участка — два кольца; здание своего кольца не добавляет.
    assert len(outline["rings_merc"]) == 2
    assert outline["centre_merc"] == [4187400.0, 7500200.0]
    assert outline["area_ha"] == 12.0
    assert outline["problem"] == ""
    assert outline["decision"]["title"].startswith("Проект решения")
    # Второе открытие карточки ЕГРН не спрашивает: контур лежит на диске.
    again = reg.decision_outline("varshavskoe-37", lookup=lookup)
    assert again["rings_merc"] == outline["rings_merc"] and len(calls) == 1


def test_a_missing_list_is_a_named_reason_not_an_empty_outline(tmp_path) -> None:
    reg = _registry(tmp_path, [], decision=True)
    outline = reg.decision_outline("varshavskoe-37", lookup=lambda n: _egrn(n))
    assert outline["rings_merc"] == [] and "нет кадастровых номеров" in outline["problem"]
    reg = _registry(tmp_path, ["77:05:0004006:12"], decision=False)
    outline = reg.decision_outline("varshavskoe-37", lookup=lambda n: _egrn(n), refresh=True)
    assert "не найден" in outline["problem"]
    # Ни одного участка с контуром — тоже причина, а не пустой контур.
    reg = _registry(tmp_path, ["77:05:0004006:1041", "77:05:0004006:0"])
    outline = reg.decision_outline("varshavskoe-37", lookup=lambda n: _egrn(n), refresh=True)
    assert outline["rings_merc"] == [] and "ни один номер" in outline["problem"]
    assert outline["counts"]["buildings"] == 1 and outline["counts"]["missing"] == 1
    # Неответ ЕГРН — тоже названная причина, и он не запоминается на неделю.
    reg = _registry(tmp_path, ["77:05:0004006:12"])

    def broken(numbers):
        raise RuntimeError("НСПД не отвечает")

    outline = reg.decision_outline("varshavskoe-37", lookup=broken, refresh=True)
    assert "ЕГРН не ответил" in outline["problem"]
    path = reg.outline_dir / "varshavskoe-37.json"
    stale = time.time() - reg.card_facts_failure_ttl_seconds - 1
    import os
    os.utime(path, (stale, stale))
    fixed = reg.decision_outline("varshavskoe-37", lookup=lambda n: _egrn(n))
    assert fixed["counts"]["land"] == 1


def test_the_point_route_asks_the_decision_before_the_geocoder() -> None:
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    body = source[source.index("async def auction_krt_point"):]
    body = body[: body.index("async def auction_krt_ranking(")]
    assert body.index("map_lookup") < body.index("_decision_outline(slug)") < body.index(
        "market.resolve_subject"), "порядок: файл карты → перечень решения → геокодер"
    assert '"decision_parcels"' in body
    # Ответ подписан своим именем — состав по документу, не официальный полигон.
    assert "не официальный" in body and "по документу" in body
    # Откат на геокодер называет, почему и перечень не помог.
    assert "Контур из участков проекта решения не собрался" in body
    helper = source[source.index("async def _decision_outline("):]
    helper = helper[: helper.index("@app.get(")]
    assert "_land_lookup_by_numbers" in helper, "ЕГРН спрашивает путь движка, а не свой клиент"


def test_the_page_names_the_document_outline() -> None:
    page = ui.auctions_page()
    note = page[page.index("function krtOutlineNote("):]
    note = note[: note.index("\nfunction ")]
    assert "decision_parcels" in note and "не официальный полигон" in note
    # Геокодерная точка теперь значит: и перечня участков не нашлось.
    assert "перечня участков" in note
    site_map = page[page.index("function krtSiteMap("):]
    site_map = site_map[: site_map.index("\nfunction krtModelCell(")]
    assert site_map.count("decision_parcels") == 2, \
        "подпись под кадром и подпись живой карты обе различают источник контура"
