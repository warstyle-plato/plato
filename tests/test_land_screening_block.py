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
    # Рисунок пятна вызывается из renderLandScreening — заготовка обязана его
    # знать, иначе тест падает на отсутствии функции, а не на поведении.
    spot = re.search(r"(function screeningSpotSvg\(parcel\)\{.*?\n\})\n\nfunction screeningFlagLabel",
                     core.PAGE, re.S)
    match = re.search(r"(function screeningFlagLabel\(cls\)\{.*?\n\})\n\nfunction renderLandScreening",
                      core.PAGE, re.S)
    assert spot, "функция рисунка пятна не найдена на странице"
    render = re.search(r"(function renderLandScreening\(data\)\{.*?\n\})\n\nfunction landNum",
                       core.PAGE, re.S)
    assert match and render, "функции блока оценки не найдены на странице"
    return ("const escapeHtml=s=>String(s==null?'':s);\n"
            "const landNum=(v,d)=>String(v);\n"
            "const box={className:'',innerHTML:'',style:{}};\n"
            "const document={getElementById:()=>box};\n"
            + spot.group(1) + "\n" + match.group(1) + "\n" + render.group(1) + "\n")


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
    monkeypatch.setattr(core, "_LAND_RETRY_PAUSE_SECONDS", 0)
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
    assert "const queue=numbers.slice()" in body, "без поштучных запросов хода не видно"
    assert "Promise.all([worker(),worker()])" in body, (
        "по двое разом: двадцать два участка по очереди — это две минуты")
    assert "numbers.join(',')" in body, "свод считает движок, а не страница"
    assert "landScreeningRun" in body, "поздний ответ не должен перерисовывать новый участок"


def test_the_screening_does_not_wait_for_the_picture():
    """Ограничения не зависят от карточки участка: на 22 участках контур не
    нарисовался, и скрининг не показался вовсе (замечание владельца,
    19.08.2026). Карточка — украшение, скрининг — ответ на вопрос сделки."""
    body = core.PAGE[core.PAGE.index("async function drawLandPreviewQuiet("):]
    body = body[:body.index("\n}\n")]
    assert body.index("loadLandScreening(raw)") < body.index("if(!response.ok)return"), (
        "скрининг запускается до проверок, от которых он не зависит")


def test_a_cut_list_says_so(monkeypatch):
    """Больше десяти участков — шесть сотен запросов к НСПД. Режем, но вслух:
    молчаливое усечение читается как «проверено всё»."""
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_nspd_search_features", lambda q: [])
    monkeypatch.setattr(core, "_LAND_RETRY_PAUSE_SECONDS", 0)
    core._LAND_SCREENING_CACHE.clear()
    numbers = ", ".join(f"50:12:0101031:{n}" for n in range(1, 41))
    answer = core.land_screening(cad=numbers)
    assert answer["requested_count"] == 40
    assert answer["checked_count"] == 30, "предел тот же, что у поиска участков"

    cls, html = _render({
        "requested_count": 22, "checked_count": 10,
        "verdict": {"status": "WARNING", "headline": "Есть ограничения", "disclaimer": ""},
        "parcels": [{"found": True, "cadastral_number": "50:12:0101031:1", "findings": [
            {"flag_class": "economic", "name": "Охранная зона", "impact": "режет"}]},
            {"found": True, "cadastral_number": "50:12:0101031:2", "findings": []}],
    })
    assert "участков: 22" in html
    assert "не поместилось в запрос: 12" in html


def test_the_waiting_plate_estimates_what_is_left():
    """«41 с» без «осталось» читается как «зависло» (замечание владельца,
    19.08.2026). Оценка берётся из уже пройденного, а не выдумывается."""
    numbers = [f"50:12:0100131:{n}" for n in range(1, 23)]
    finished = [{"number": numbers[i], "parcel": {"found": True, "findings": []}}
                for i in range(4)]
    _, html = _working(numbers, finished, 20)
    assert "участок 5 из 22" in html
    assert "осталось примерно 90 с" in html, html

    # Ни один участок ещё не прошёл — оценивать нечем, и мы не выдумываем.
    _, first = _working(numbers, [], 3)
    assert "осталось" not in first


def test_the_waiting_plate_says_how_much_work_it_is():
    numbers = [f"50:12:0100131:{n}" for n in range(1, 23)]
    _, html = _working(numbers, [], 2)
    assert "шесть десятков слоёв" in html
    assert "22 раз" in html


# --- мелкие участки не стоят шести десятков запросов ------------------------------

def _parcel_of(area_sqm: float, number: str):
    return {"properties": {"options": {"cad_num": number, "area": area_sqm}},
            "geometry": {"type": "Polygon", "coordinates": [
                [[37.20, 55.62], [37.21, 55.62], [37.21, 55.63], [37.20, 55.63], [37.20, 55.62]]]}}


def test_a_small_parcel_is_not_screened(monkeypatch):
    """Нарезка по три сотки посадку не определяет, а стоит те же шесть
    десятков запросов к НСПД (решение владельца, 19.08.2026)."""
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_nspd_search_features",
                        lambda q: [_parcel_of(300.0, "50:12:0100131:29")])
    monkeypatch.setattr(core, "_land_screen_findings",
                        lambda *a, **k: pytest.fail("мелкий участок не спрашивают"))
    core._LAND_SCREENING_CACHE.clear()
    answer = core.land_screening(cad="50:12:0100131:29")

    parcel = answer["parcels"][0]
    assert parcel["too_small"] is True
    assert parcel["verdict"]["status"] == "NOT_SCREENED", "пропуск не выдаётся за проверку"
    assert answer["small_count"] == 1
    assert answer["min_area_sqm"] == 1000.0


def test_a_big_parcel_is_screened_as_before(monkeypatch):
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_nspd_search_features",
                        lambda q: [_parcel_of(21787.0, "50:20:0070312:8320")])
    monkeypatch.setattr(core, "_land_screen_findings", lambda *a, **k: [])
    core._LAND_SCREENING_CACHE.clear()
    answer = core.land_screening(cad="50:20:0070312:8320")
    assert answer["parcels"][0]["too_small"] is False
    assert answer["small_count"] == 0


def test_the_threshold_can_be_lifted(monkeypatch):
    """Ноль — проверять всё: порог удобство, а не запрет."""
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_nspd_search_features",
                        lambda q: [_parcel_of(300.0, "50:12:0100131:29")])
    monkeypatch.setattr(core, "_land_screen_findings", lambda *a, **k: [])
    core._LAND_SCREENING_CACHE.clear()
    answer = core.land_screening(cad="50:12:0100131:29", min_area_sqm=0)
    assert answer["parcels"][0]["too_small"] is False


def test_the_block_says_what_was_skipped():
    _, html = _render({
        "requested_count": 22, "checked_count": 22, "small_count": 14,
        "min_area_sqm": 1000.0,
        "verdict": {"status": "WARNING", "headline": "Есть ограничения", "disclaimer": "Оговорка."},
        "parcels": [{"found": True, "cadastral_number": "50:12:0100131:497", "findings": [
            {"flag_class": "economic", "name": "Охранная зона", "impact": "режет"}]},
            {"found": True, "cadastral_number": "50:12:0100131:29", "too_small": True,
             "findings": []}],
    })
    assert "мелких пропущено: 14" in html
    assert "мельче 10 соток не проверялись" in html
    assert "посадку они не определяют" in html


def test_the_progress_line_names_the_skip():
    numbers = ["50:12:0100131:497", "50:12:0100131:29"]
    _, html = _working(numbers, [
        {"number": "50:12:0100131:29", "parcel": {"found": True, "too_small": True, "findings": []}},
    ], 5)
    assert "50:12:0100131:29 — меньше порога — не проверялся" in html


def test_the_counts_add_up_to_what_was_typed():
    """Владелец ввёл 22 номера и увидел «участков: 10» (19.08.2026).

    Двенадцать участков исчезли из шапки и из разбивки: восемь мелких были
    пропущены по порогу, по четырём не пришли сведения ЕГРН. Ни то ни другое
    не потеря участка, но выглядело именно ей. Шапка обязана сходиться с тем,
    что человек ввёл: проверено + мелкие + без сведений = запрошено.
    """
    parcels = [
        {"found": True, "cadastral_number": "50:12:0100131:497", "area_ha": 7.3156,
         "findings": [{"flag_class": "killer", "name": "ООПТ", "impact": "нельзя"}]},
        {"found": True, "cadastral_number": "50:12:0100131:492", "area_ha": 8.2697,
         "findings": [{"flag_class": "killer", "name": "ООПТ", "impact": "нельзя"}]},
    ]
    parcels += [{"found": True, "cadastral_number": f"50:12:0100131:{n}", "area_ha": 0.05,
                 "too_small": True, "findings": []} for n in range(20, 28)]
    parcels += [{"found": False, "cadastral_number": f"50:12:0100131:{n}",
                 "note": "Сведения ЕГРН по номеру не получены."} for n in range(40, 52)]
    _, html = _render({
        "requested_count": 22, "checked_count": 22, "small_count": 8, "min_area_sqm": 1000.0,
        "verdict": {"status": "CRITICAL", "headline": "Найдены ограничения", "disclaimer": ""},
        "parcels": parcels,
    })
    assert "участков: 22" in html
    assert "проверено: 2" in html
    assert "мелких пропущено: 8" in html
    assert "без сведений ЕГРН: 12" in html


def test_a_skipped_parcel_is_not_called_clean():
    """«Чисто» на непроверенном участке — тот же разрешительный вывод на пустоте."""
    _, html = _render({
        "requested_count": 3, "checked_count": 3, "small_count": 1, "min_area_sqm": 1000.0,
        "verdict": {"status": "NO_CRITICAL_FLAGS", "headline": "Критических ограничений не обнаружено",
                    "disclaimer": ""},
        "parcels": [
            {"found": True, "cadastral_number": "50:12:0100131:497", "area_ha": 7.3, "findings": []},
            {"found": True, "cadastral_number": "50:12:0100131:29", "area_ha": 0.05,
             "too_small": True, "findings": []},
            {"found": False, "cadastral_number": "50:12:0100131:777"},
        ],
    })
    small = html.split("50:12:0100131:29")[1].split("</div>")[0]
    assert "не проверялся" in small and "чисто" not in small
    lost = html.split("50:12:0100131:777")[1].split("</div>")[0]
    assert "нет сведений ЕГРН" in lost and "чисто" not in lost
    # Проверенный участок по-прежнему называется чистым — иначе теряется ответ.
    checked = html.split("50:12:0100131:497")[1].split("</div>")[0]
    assert "чисто" in checked


def test_a_parcel_without_egrn_still_gets_a_line():
    """Номер, по которому нет сведений, не исчезает из разбивки молча."""
    _, html = _render({
        "requested_count": 2, "checked_count": 2,
        "verdict": {"status": "WARNING", "headline": "Есть ограничения", "disclaimer": ""},
        "parcels": [
            {"found": True, "cadastral_number": "50:12:0100131:497", "findings": [
                {"flag_class": "economic", "name": "Охранная зона", "impact": "режет"}]},
            {"found": False, "cadastral_number": "50:12:0100131:999"},
        ],
    })
    assert "50:12:0100131:999" in html


def test_a_missed_number_is_asked_twice(monkeypatch):
    """НСПД отвечает не на каждый запрос — повтор возвращает участок.

    На площадке из двадцати двух номеров сведения пришли по десяти, и
    двенадцать участков выглядели несуществующими. Ни один из них не исчез с
    кадастрового учёта — просто сервис не ответил.
    """
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_LAND_RETRY_PAUSE_SECONDS", 0)
    monkeypatch.setattr(core, "_land_screen_findings", lambda *a, **k: [])
    calls = {"count": 0}

    def flaky(query):
        calls["count"] += 1
        return [] if calls["count"] < 2 else [_parcel_of(21787.0, "50:12:0100131:497")]

    monkeypatch.setattr(core, "_nspd_search_features", flaky)
    core._LAND_SCREENING_CACHE.clear()
    answer = core.land_screening(cad="50:12:0100131:497")
    assert calls["count"] == 2, "промах спрашивается второй раз"
    assert answer["parcels"][0]["found"] is True


def test_a_refused_request_is_not_a_verdict_about_the_parcel(monkeypatch):
    """Сорванный запрос — не «участка нет»: это про нас, а не про участок."""
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_LAND_RETRY_PAUSE_SECONDS", 0)

    def refused(query):
        raise RuntimeError("Сервис НСПД недоступен")

    monkeypatch.setattr(core, "_nspd_search_features", refused)
    core._LAND_SCREENING_CACHE.clear()
    answer = core.land_screening(cad="50:12:0100131:497")
    parcel = answer["parcels"][0]
    assert parcel["found"] is False
    assert parcel["probe_failed"] is True
    assert "не прошёл" in parcel["note"]

    _, html = _render({
        "requested_count": 1, "checked_count": 1,
        "verdict": {"status": "NOT_SCREENED", "headline": "Скрининг не выполнен", "disclaimer": ""},
        "parcels": [parcel],
    })
    assert "НСПД не ответил: 1" in html or "запрос в НСПД не прошёл" in html
    assert "без сведений ЕГРН: 1" not in html


def test_the_reason_for_a_skip_is_the_real_one():
    """Мелкий участок и неответивший НСПД получали чужой диагноз — «нет ЕГРН»."""
    _, small = _render({
        "requested_count": 1, "checked_count": 1, "small_count": 1, "min_area_sqm": 1000.0,
        "verdict": {"status": "NOT_SCREENED", "headline": "Скрининг не выполнен", "disclaimer": ""},
        "parcels": [{"found": True, "cadastral_number": "50:12:0100131:29", "area_ha": 0.05,
                     "too_small": True, "findings": []}],
    })
    assert "мельче 10 соток" in small
    assert "нет сведений ЕГРН" not in small

    _, unreached = _render({
        "requested_count": 1, "checked_count": 1,
        "verdict": {"status": "NOT_SCREENED", "headline": "Скрининг не выполнен", "disclaimer": ""},
        "parcels": [{"found": False, "probe_failed": True, "cadastral_number": "50:12:0100131:29"}],
    })
    assert "НСПД не ответил" in unreached
    assert "нет сведений ЕГРН" not in unreached


def test_an_unscreened_site_still_lists_its_parcels():
    """Свод «не проверялось» не имеет права съедать разбивку по участкам."""
    _, html = _render({
        "requested_count": 3, "checked_count": 3,
        "verdict": {"status": "NOT_SCREENED", "headline": "Скрининг не выполнен", "disclaimer": ""},
        "parcels": [{"found": False, "cadastral_number": f"50:12:0100131:{n}"} for n in (1, 2, 3)],
    })
    for number in ("50:12:0100131:1", "50:12:0100131:2", "50:12:0100131:3"):
        assert number in html
