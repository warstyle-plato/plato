"""Оценка участка до финмодели: самостоятельная ценность продукта.

Человек вводит кадастровый номер и сразу видит, что мешает строить — ЗОУИТ,
ООПТ, красные линии — с реестровым номером и документом-основанием, не
запуская расчёт экономики. Здесь закреплено:

- маршрут `/land/screening` собирает по участку сведения ЕГРН и ограничения,
  сортируя их по весу (запрет → влияет на экономику → справка);
- вывод НЕ разрешительный: «критических ограничений не обнаружено» и оговорка,
  что видно лишь внесённое в ЕГРН (архитектура, раздел 8);
- один участок — коротко, несколько — свод плюс разбивка;
- блок страницы рисуется настоящей функцией из PAGE через node.

Запуск: python3 -m pytest tests/test_land_screening_block.py -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
NODE = shutil.which("node")

_PARCEL = {
    "properties": {"options": {
        "cad_num": "50:20:0070312:8320", "area": 4200.0,
        "readable_address": "Московская область, Одинцовский округ",
        "land_record_category_type": "Земли населённых пунктов",
        "permitted_use_established_by_document": "для многоэтажной застройки",
    }},
    "geometry": {"type": "Polygon", "coordinates": [
        [[37.20, 55.62], [37.21, 55.62], [37.21, 55.63], [37.20, 55.63], [37.20, 55.62]]]},
}


def _screening(monkeypatch, findings):
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_nspd_search_features", lambda q: [_PARCEL])
    monkeypatch.setattr(core, "_land_screen_findings",
                        lambda lat, lng, geometry=None: list(findings))
    core._LAND_SCREENING_CACHE.clear()
    return core.land_screening(cad="50:20:0070312:8320")


def test_the_screening_answers_before_any_model(monkeypatch):
    result = _screening(monkeypatch, [
        {"flag_class": "info", "name": "Справочное", "impact": "—"},
        {"flag_class": "killer", "name": "СЗЗ завода", "impact": "жильё запрещено",
         "reg_number": "50:00-6.1"},
        {"flag_class": "economic", "name": "Приаэродромная", "impact": "ограничение высоты",
         "reg_number": "50:00-6.3453", "document_number": "394-П"},
    ])
    parcel = result["parcels"][0]
    assert parcel["found"] is True
    assert parcel["area_ha"] == pytest.approx(0.42)
    assert parcel["permitted_use"].startswith("для многоэтажной")
    # Порядок: запрет → экономика → справка.
    assert [f["flag_class"] for f in parcel["findings"]] == ["killer", "economic", "info"]
    assert result["verdict"]["status"] == "CRITICAL"
    assert result["single"] is True


def test_a_clean_parcel_gets_no_permission_to_build(monkeypatch):
    """Разрешительный вывод запрещён: максимум — «не обнаружено», и с оговоркой."""
    result = _screening(monkeypatch, [])
    verdict = result["verdict"]
    assert verdict["status"] == "NO_CRITICAL_FLAGS"
    assert "не обнаружено" in verdict["headline"]
    assert "подходит" not in verdict["headline"].lower()
    assert "ЕГРН" in verdict["disclaimer"] and "не доказывает" in verdict["disclaimer"]


def test_only_economic_flags_give_a_warning(monkeypatch):
    result = _screening(monkeypatch, [
        {"flag_class": "economic", "name": "Охранная зона", "impact": "режет пятно"}])
    assert result["verdict"]["status"] == "WARNING"


def test_a_junk_number_is_refused(monkeypatch):
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    with pytest.raises(core.HTTPException) as exc:
        core.land_screening(cad="не номер")
    assert exc.value.status_code == 400


def _page_harness() -> str:
    match = re.search(r"(function screeningFlagLabel\(cls\)\{.*?\n\})\n\nfunction renderLandScreening",
                      core.PAGE, re.S)
    render = re.search(r"(function renderLandScreening\(data\)\{.*?\n\})\n\nfunction landNum",
                       core.PAGE, re.S)
    assert match and render, "функции блока оценки не найдены на странице"
    return ("const escapeHtml=s=>String(s==null?'':s);\n"
            "const landNum=(v,d)=>String(v);\n"
            "const box={className:'',innerHTML:'',style:{}};\n"
            "const document={getElementById:()=>box};\n"
            + match.group(1) + "\n" + render.group(1) + "\n")


def _render(payload) -> tuple[str, str]:
    if not NODE:
        pytest.skip("node недоступен")
    script = _page_harness() + f"""
renderLandScreening({json.dumps(payload, ensure_ascii=False)});
console.log(JSON.stringify({{cls: box.className, html: box.innerHTML}}));
"""
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    got = json.loads(out.stdout)
    return got["cls"], got["html"]


def test_the_page_paints_the_flags_by_weight():
    cls, html = _render({
        "calculated_at": "18.08.2026 02:00",
        "verdict": {"status": "CRITICAL", "headline": "Найдены ограничения",
                    "disclaimer": "Проверены ограничения ЕГРН."},
        "parcels": [{"found": True, "cadastral_number": "50:20:0070312:8320",
                     "findings": [
                         {"flag_class": "killer", "name": "СЗЗ завода",
                          "impact": "жильё запрещено", "reg_number": "50:00-6.1"},
                         {"flag_class": "economic", "name": "Приаэродромная",
                          "impact": "ограничение высоты", "document": "Приказ",
                          "document_number": "394-П", "document_date": "17.04.2020"}]}],
    })
    assert cls == "land-screening critical"
    assert "СТОП" in html and "ВЛИЯЕТ" in html
    assert "СЗЗ завода" in html and "реестровый № 50:00-6.1" in html
    assert "394-П" in html and "17.04.2020" in html
    assert "Проверены ограничения ЕГРН." in html


def test_a_clean_parcel_says_so_honestly():
    cls, html = _render({
        "verdict": {"status": "NO_CRITICAL_FLAGS",
                    "headline": "Критических ограничений не обнаружено", "disclaimer": ""},
        "parcels": [{"found": True, "cadastral_number": "77:01:0001:1", "findings": []}],
    })
    assert cls == "land-screening clean"
    assert "не обнаружено" in html
    assert "подходит" not in html.lower()


def test_several_parcels_get_a_breakdown():
    cls, html = _render({
        "verdict": {"status": "WARNING", "headline": "Есть ограничения", "disclaimer": ""},
        "parcels": [
            {"found": True, "cadastral_number": "50:20:1:1", "area_ha": 1.5,
             "findings": [{"flag_class": "economic", "name": "Охранная зона", "impact": "режет"}]},
            {"found": True, "cadastral_number": "50:20:1:2", "area_ha": 0.8, "findings": []},
        ],
    })
    assert "участков: 2" in html
    assert "50:20:1:1" in html and "50:20:1:2" in html
    assert "чисто" in html, "участок без ограничений в разбивке помечается"


def test_the_block_is_wired_to_the_card():
    body = core.PAGE[core.PAGE.index("async function lookupLand"):]
    body = body[:body.index("function renderStoredLand")]
    assert "loadLandScreening(raw)" in body, "оценка не запускается после поиска участка"


def test_a_dense_parcel_does_not_become_a_wall():
    """На плотном участке ограничений бывает три десятка, и блок превращался в
    стену (боевая проверка 18.08.2026). Показываем шесть, остальные — счётчиком;
    полный перечень остаётся в отчёте."""
    flags = [{"flag_class": "killer", "name": f"Ограничение {i}", "impact": "нельзя",
              "reg_number": f"77:00-6.{i}"} for i in range(1, 13)]
    cls, html = _render({
        "verdict": {"status": "CRITICAL", "headline": "Найдены ограничения", "disclaimer": ""},
        "parcels": [{"found": True, "cadastral_number": "77:01:1:1", "findings": flags}],
    })
    assert html.count('class="flag') == 6, "показываем только главные строки"
    assert "и ещё 6 ограничений" in html
    assert "в отчёте перечислены полностью" in html


def test_the_report_carries_the_screening_before_the_money(monkeypatch):
    """Раздел «Реализуемость посадки» стоит ПЕРЕД финансовым выводом
    (архитектура): сначала что мешает строить, потом деньги. Отчёт не имеет
    права падать из-за внешнего сервиса — при сбое раздел просто пропускается.
    """
    order = core.PAGE  # заглушка, чтобы линтер не ругался на неиспользуемое
    assert order is not None
    source = Path(core.__file__).read_text(encoding="utf-8")
    body = source[source.index("def _build_developaid_pdf"):]
    body = body[:body.index("# Состав выгружаемой модели")]
    assert 'story.append(_PdfSection("screening"))' in body
    assert body.index('_PdfSection("screening")') < body.index('_PdfSection("summary")'), \
        "скрининг обязан стоять раньше ключевой экономики"
    assert '("screening", True), ("summary", False)' in body, "порядок разделов не задан"
    assert "except Exception:\n        screening = None" in body, "сбой сервиса не роняет отчёт"


def test_the_report_numbers_come_from_the_project(monkeypatch):
    numbers = core._pdf_screening_numbers({"_land_lookup": {"query": "50:20:0070312:8320, мусор"}})
    assert numbers == ["50:20:0070312:8320"]
    assert core._pdf_screening_numbers({}) == []


def test_the_report_headline_is_not_raw_markup():
    """P() экранирует HTML, поэтому <b> печатался буквально: «<b>Критических
    ограничений не обнаружено</b>» в боевом отчёте (18.08.2026). Жирный —
    стилем, а не тегом."""
    source = Path(core.__file__).read_text(encoding="utf-8")
    body = source[source.index('story.append(_PdfSection("screening"))'):]
    body = body[:body.index('story.append(_PdfSection("summary"))')]
    assert "<b>" not in body, "разметка в тексте будет напечатана буквально"
    assert 'fontName=bold' in body, "заголовок должен быть жирным стилем"


def test_reference_layers_are_not_shown_as_restrictions():
    """«Здания», «Кадастровые округа», «Машино-места» попали в отчёт как
    «ограничение неизвестного типа» (боевой отчёт 18.08.2026) — это справочные
    слои публичной карты."""
    for junk in ("ПКК. Здания", "Кадастровые округа", "Сооружения",
                 "Машино-места", "Объекты незавершённого строительства"):
        assert any(n in junk.lower() for n in core._LAND_SCREEN_NOISE), junk


def test_the_territorial_zone_reads_as_a_useful_note():
    got = core._land_screen_classify({"type_zone": "", "name": "ПКК. Территориальные зоны"})
    assert got["flag_class"] == "info"
    assert "ВРИ" in got["impact"], "зона по ПЗЗ — самая нужная справка, а не «неизвестный тип»"


def test_a_parcel_without_egrn_is_not_declared_clean(monkeypatch):
    """Зелёная плашка на пустоте. На запросе, где не нашёлся ни один номер,
    экран показывал «Критических ограничений не обнаружено» — разрешающий вывод
    без единого запроса к НСПД: без границ участка спрашивать было нечего
    (боевая проверка владельца, 18.08.2026)."""
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_nspd_search_features", lambda q: [])
    monkeypatch.setattr(core, "_land_screen_findings",
                        lambda *a, **k: pytest.fail("без границ НСПД не спрашивают"))
    core._LAND_SCREENING_CACHE.clear()
    result = core.land_screening(cad="77:02:0021018:3577, 77:02:0021018:7")

    verdict = result["verdict"]
    assert verdict["status"] == "NOT_SCREENED"
    assert "не обнаружено" not in verdict["headline"], "нечего было обнаруживать"
    assert verdict["probed"] is False
    assert "не спрашивали" in verdict["disclaimer"]


def test_a_found_parcel_is_screened_as_before(monkeypatch):
    result = _screening(monkeypatch, [])
    assert result["verdict"]["status"] == "NO_CRITICAL_FLAGS"
    assert result["verdict"]["probed"] is True


def test_the_unscreened_plate_is_not_green():
    cls, html = _render({
        "verdict": {"status": "NOT_SCREENED",
                    "headline": "Скрининг не выполнен: сведений ЕГРН по участку нет",
                    "disclaimer": "Границы участка не получены."},
        "parcels": [{"found": False, "cadastral_number": "77:02:0021018:7"}],
    })
    assert cls == "land-screening unknown", "серая плашка, не зелёная"
    assert "не проверялись" in html
    assert "не обнаружено" not in html


def _working(numbers, finished, seconds) -> tuple[str, str]:
    """Настоящая функция ожидания из PAGE, прогнанная через node."""
    if not NODE:
        pytest.skip("node недоступен")
    match = re.search(r"(function screeningWorkingHtml\(numbers,finished,seconds\)\{.*?\n\})\n",
                      core.PAGE, re.S)
    assert match, "плашка ожидания не найдена на странице"
    script = ("const escapeHtml=s=>String(s==null?'':s);\n" + match.group(1) + "\n"
              + f"console.log(JSON.stringify(screeningWorkingHtml("
                f"{json.dumps(numbers)},{json.dumps(finished, ensure_ascii=False)},{seconds})));")
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    got = json.loads(out.stdout)
    return got["cls"], got["html"]


def test_the_waiting_plate_is_visible_at_all():
    """Плашка ожидания была невидимой: класс тона не ставился, а текст шапки
    белый — на белом фоне ничего не читалось, и ограничения появлялись внезапно
    (замечание владельца, 18.08.2026)."""
    cls, html = _working(["77:02:0021018:7"], [], 3)
    assert "working" in cls, "без тона шапка белым по белому"
    assert "Проверяю градостроительные ограничения" in html
    assert "3 с" in html, "сколько идёт — видно"
    assert "ЗОУИТ" in html, "видно, что именно проверяется"

    css = core.PAGE[core.PAGE.index(".land-screening{"):core.PAGE.index(".land-screening ul{")]
    assert ".land-screening.working header{background:" in css


def test_the_progress_moves_with_the_parcels():
    numbers = ["50:20:1:1", "50:20:1:2", "50:20:1:3"]
    _, first = _working(numbers, [], 1)
    assert "участок 1 из 3" in first and 'width:0%' in first

    _, second = _working(numbers, [
        {"number": "50:20:1:1", "parcel": {"found": True, "findings": [
            {"flag_class": "killer"}, {"flag_class": "economic"}]}},
    ], 12)
    assert "участок 2 из 3" in second
    assert "width:33%" in second
    assert "50:20:1:1 — есть запрет" in second, "результат участка виден сразу, а не в конце"

    _, third = _working(numbers, [
        {"number": "50:20:1:1", "parcel": {"found": True, "findings": []}},
        {"number": "50:20:1:2", "parcel": {"found": False}},
    ], 20)
    assert "50:20:1:1 — ограничений не найдено" in third
    assert "50:20:1:2 — сведений ЕГРН нет" in third


def test_the_screening_asks_parcel_by_parcel():
    body = core.PAGE[core.PAGE.index("async function loadLandScreening"):]
    body = body[:body.index("function screeningWorkingHtml")]
    assert "for(const number of numbers)" in body, "без поштучных запросов хода не видно"
    assert "numbers.join(',')" in body, "свод считает движок, а не страница"
    assert "landScreeningRun" in body, "поздний ответ не должен перерисовывать новый участок"

