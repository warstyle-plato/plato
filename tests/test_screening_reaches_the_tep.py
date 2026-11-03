"""Ограничения, найденные скринингом, доходят до ТЭП и посадки.

Прогон «Посадка ↔ нормативы» (25.10.2026, `docs/site_norms_check.md`) прошёл
двенадцать настоящих участков путём посетителя и нашёл, что скрининг и ТЭП
живут порознь:

- ООПТ на всём участке в Мытищах (50:12:0100131:497) — сайт сажал 453 тыс. м²
  квартир без единого слова;
- приаэродромная Внуково и зона охраны памятника — 17–25 этажей молча;
- охранные зоны сетей на 21 % Коммунарки (50:21:0120316:1221) — калькулятору
  ГлавАПУ уходило `restrictArea=0`, ТЭП считался на всю площадь;
- территориальная зона ПЗЗ не получена у 11 из 12 участков: опрос контура
  отдавал пятьдесят чужих зон (предел ответа), своя в список не влезала, а
  вердикт об этом молчал;
- «Береговые линии» шли «ограничением неизвестного типа».

Решения владельца (25.10.2026): запрет — красная оговорка, ТЭП считается и
подставляется; высота — оговорка без потолка; береговая линия — справка про
водоохранную зону; нежилой ВРИ — оговорка. Площадь под охранными зонами и
красными линиями уходит в калькулятор («площадь ограничений»).

Живой НСПД из песочницы закрыт — портал подменён, проверяется, что мы делаем
с его ответом.

Запуск: python3 -m pytest tests/test_screening_reaches_the_tep.py -q
"""

from __future__ import annotations

import urllib.parse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

# Участок примерно 100 × 60 м.
PARCEL = {"type": "Polygon", "coordinates": [[
    [37.5500, 55.7200], [37.5516, 55.7200], [37.5516, 55.7206],
    [37.5500, 55.7206], [37.5500, 55.7200]]]}
WHOLE = {"type": "Polygon", "coordinates": [[
    [37.5490, 55.7190], [37.5530, 55.7190], [37.5530, 55.7215],
    [37.5490, 55.7215], [37.5490, 55.7190]]]}
# Западная четверть участка.
QUARTER = {"type": "Polygon", "coordinates": [[
    [37.5490, 55.7190], [37.5504, 55.7190], [37.5504, 55.7215],
    [37.5490, 55.7215], [37.5490, 55.7190]]]}
FAR = {"type": "Polygon", "coordinates": [[
    [37.6000, 55.8000], [37.6010, 55.8000], [37.6010, 55.8010],
    [37.6000, 55.8010], [37.6000, 55.8000]]]}


# --- классы зон ---------------------------------------------------------------

def test_a_shoreline_is_water_not_an_unknown_restriction():
    for name in ("ПКК. Береговые линии (границы водных объектов) (линейный)",
                 "ПКК. Береговые линии (границы водных объектов) (полигональный)"):
        got = core._land_screen_classify({"type_zone": "", "name": name})
        assert got["effect"] == "water", got
        assert "неизвестного типа" not in got["impact"]
        assert "водоохранн" in got["impact"]
        # Справка, а не «влияет»: долю под линией не измерить (решение владельца).
        assert got["flag_class"] == "info"


@pytest.mark.parametrize("name, effect", [
    ("Охранная зона инженерных коммуникаций", "area"),
    ("Красные линии", "area"),
    ("Приаэродромная территория аэродрома Москва (Внуково)", "height"),
    ("Зона охраны объекта культурного наследия", "height"),
    ("ПКК. Особо охраняемые природные территории", "ban"),
    ("ПКК. Территориальные зоны", "frame"),
    ("Водоохранная зона реки Москвы", "water"),
])
def test_each_zone_says_what_it_does_to_the_massing(name, effect):
    assert core._land_screen_classify({"type_zone": "", "name": name})["effect"] == effect


# --- территориальная зона: обрезанный список -----------------------------------

def _portal(monkeypatch, contour_answer, point_answer):
    asked: list[str] = []

    def fake(params: str, layer_id: int, api_version: str):
        fields = dict(urllib.parse.parse_qsl(params))
        if int(fields["QUERY_LAYERS"]) != 875838:
            return {"features": []}
        by_contour = fields["WIDTH"] == "1"
        asked.append("contour" if by_contour else "point")
        return {"features": contour_answer if by_contour else point_answer}

    monkeypatch.setattr(core, "_nspd_getfeatureinfo_request", fake)
    return asked


def _zone(number: str, geometry) -> dict:
    return {"geometry": geometry, "properties": {"options": {
        "categoryName": "ПКК. Территориальные зоны", "reg_numb_border": number}}}


def test_a_full_answer_is_a_cut_list_and_the_centre_is_asked(monkeypatch):
    """Пятьдесят чужих зон — не «зоны на участке нет», а обрезанный ответ."""
    strangers = [_zone(f"77:07-7.{i}", FAR) for i in range(core._NSPD_CONTOUR_FEATURE_LIMIT)]
    asked = _portal(monkeypatch, strangers, [_zone("77:06-7.745", WHOLE)])
    found = core._land_screen_findings(55.7203, 37.5508, PARCEL)
    assert asked == ["contour", "point"]
    here = [f for f in found if f["effect"] == "frame" and f["on_parcel"]]
    # Своя зона — отдельной строкой со своим номером, чужие — «рядом».
    assert [f["reg_numbers"] for f in here] == [["77:06-7.745"]]
    assert any(f["effect"] == "frame" and not f["on_parcel"] for f in found)
    verdict = core._land_screening_verdict(found, probed=True, method="contour")
    assert verdict["zone_found"] is True


def test_a_short_answer_is_not_asked_again(monkeypatch):
    asked = _portal(monkeypatch, [_zone("77:06-7.1", WHOLE)], [])
    core._land_screen_findings(55.7203, 37.5508, PARCEL)
    assert asked == ["contour"]


# --- доля, которую режут зоны --------------------------------------------------

def test_only_area_zones_cut_the_buildable_share(monkeypatch):
    """Приаэродромная накрывает всё, но площади не отнимает; охранная — четверть."""
    def fake(params: str, layer_id: int, api_version: str):
        fields = dict(urllib.parse.parse_qsl(params))
        layer = int(fields["QUERY_LAYERS"])
        zones = {37578: (QUARTER, "Охранная зона инженерных коммуникаций", "77:06-6.20"),
                 37581: (WHOLE, "Приаэродромная территория", "50:00-6.1")}
        if layer not in zones or fields["WIDTH"] != "1":
            return {"features": []}
        geometry, kind, number = zones[layer]
        return {"features": [{"geometry": geometry, "properties": {"options": {
            "categoryName": "Зоны с особыми условиями использования территории",
            "type_zone": kind, "reg_numb_border": number, "name_by_doc": kind}}}]}

    monkeypatch.setattr(core, "_nspd_getfeatureinfo_request", fake)
    found = core._land_screen_findings(55.7203, 37.5508, PARCEL)
    cut = {f["cut_pct"] for f in found}
    assert len(cut) == 1
    assert 20 <= cut.pop() <= 30


# --- свод ограничений ------------------------------------------------------------

def _screening(number: str, area_ha: float, findings: list[dict], *, zone=False,
               permitted_use="2.6 Многоэтажная жилая застройка") -> dict:
    if zone:
        findings = findings + [{"flag_class": "info", "effect": "frame",
                                "name": "ПКК. Территориальные зоны", "coverage_pct": 100.0}]
    return {"parcels": [{
        "cadastral_number": number, "found": True, "area_ha": area_ha,
        "permitted_use": permitted_use, "findings": findings,
        "verdict": {"probed": True, "zone_found": zone}}]}


KOMMUNARKA = _screening("50:21:0120316:1221", 17.3494, [
    {"flag_class": "economic", "effect": "area", "name": "Охранная зона инженерных коммуникаций",
     "coverage_pct": 21.4, "cut_pct": 21.4, "reg_number": "77:06-6.20"},
    {"flag_class": "economic", "effect": "area", "name": "Красные линии", "coverage_pct": None,
     "cut_pct": 21.4},
], permitted_use="Многофункциональные общественные центры")
MYTISHCHI = _screening("50:12:0100131:497", 7.3156, [
    {"flag_class": "killer", "effect": "ban", "name": "ПКК. Особо охраняемые природные территории",
     "coverage_pct": 100.0, "reg_number": "50:15-6.3"}],
    permitted_use="Для ведения личного подсобного хозяйства")
VNUKOVO = _screening("77:17:0110504:18151", 2.6266, [
    {"flag_class": "economic", "effect": "height", "name": "Приаэродромная территория",
     "coverage_pct": 100.0}], zone=True)
OFFICE = _screening("77:06:0003002:18", 0.5461, [],
                    permitted_use="деловое управление (4.1)")


def test_the_cut_share_becomes_the_restricted_area():
    summary = core._land_restrictions_summary(KOMMUNARKA)
    assert summary["restrict_ha"] == pytest.approx(17.3494 * 0.214, abs=0.001)
    text = " ".join(summary["warnings"])
    assert "калькулятору ГлавАПУ" in text and "21,4 %" in text
    # Красные линии без измеренной доли: не вычтены — и это сказано.
    assert any("Красные линии" in w and "не вычтена" in w for w in summary["warnings"])


def test_a_ban_is_said_first_and_plainly():
    summary = core._land_restrictions_summary(MYTISHCHI)
    assert summary["ban"] and summary["ban_whole"]
    assert summary["warnings"][0].startswith("Строить нельзя")
    assert "Особо охраняемые" in summary["warnings"][0]
    assert summary["restrict_ha"] == 0  # запрет — оговорка, площадь не срезается
    assert summary["massing_notes"] and summary["massing_notes"][0].startswith("Строить нельзя")


def test_a_height_limit_is_a_caveat_for_the_massing():
    summary = core._land_restrictions_summary(VNUKOVO)
    note = next(w for w in summary["warnings"] if w.startswith("Высота ограничена"))
    assert "Приаэродромная" in note and "не сверена" in note
    assert note in summary["massing_notes"]


def test_an_office_parcel_without_a_zone_does_not_pass_as_housing():
    summary = core._land_restrictions_summary(OFFICE)
    text = " ".join(summary["warnings"])
    assert "Территориальная зона" in text and "не получена" in text
    assert "многоквартирные дома по нему не предусмотрены" in text


def test_an_unreached_portal_is_not_a_missing_parcel():
    summary = core._land_restrictions_summary({"parcels": [{
        "cadastral_number": "77:01:0001001:1", "found": False, "probe_failed": True,
        "note": "Запрос в НСПД не прошёл: 503"}]})
    assert summary["checked"] is False
    assert "НСПД не прошёл" in summary["warnings"][0]
    assert "ЕГРН" not in summary["warnings"][0]


@pytest.mark.parametrize("use, allows", [
    ("2.6 - Многоэтажная жилая застройка (высотная застройка)", True),
    ("Среднеэтажная жилая застройка (2.5)", True),
    ("деловое управление (4.1)", False),
    ("Для индивидуального жилищного строительства", False),
    ("", None),
])
def test_the_vri_predicate(use, allows):
    assert core._vri_allows_apartments(use) is allows


# --- ТЭП Москвы ------------------------------------------------------------------

def _analysis(area_ha: float) -> dict:
    return {"territory": {"area_ha": area_ha, "district": "Коммунарка"},
            "recognized": ["50:21:0120316:1221"],
            "coefficients": {"rail": 0.75, "business_outside_ttc": 0.5, "rent": 0.1281,
                             "base_cost_zh_high": 229036.29}}


def test_the_calculator_gets_the_restricted_area(monkeypatch):
    seen: dict = {}

    def fake_rows(numbers, area_ha, restrict_ha=0.0):
        seen["restrict"] = restrict_ha
        return [{"code": "60", "name": "Озеленение", "unit": "га", "value": "1"}]

    monkeypatch.setattr(core, "land_screening", lambda **kw: KOMMUNARKA)
    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", True)
    monkeypatch.setattr(core, "_glavapu_headless_rows", fake_rows)
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: _analysis(17.3494))
    monkeypatch.setattr(core, "import_cadastral_tep", lambda req: {
        "normalized": {}, "source": {}, "warnings": []})
    result = core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers="50:21:0120316:1221"))
    assert seen["restrict"] == pytest.approx(3.7128, abs=0.001)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(result["source"]["calculator_url"]).query)
    assert float(query["restrictArea"][0]) == pytest.approx(3.7128, abs=0.001)
    assert any("охранн" in w.lower() for w in result["warnings"])
    assert result["site_restrictions"]["restrict_ha"] == pytest.approx(3.7128, abs=0.001)


def test_the_drive_url_carries_the_restricted_area():
    import inspect
    source = inspect.getsource(core._glavapu_drive_page)
    assert '"&restrictArea=0' not in source
    assert "restrict_ha" in source


def test_the_formulas_count_on_what_is_left(monkeypatch):
    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", False)
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: _analysis(17.3494))
    monkeypatch.setattr(core, "land_screening", lambda **kw: _screening(
        "50:21:0120316:1221", 17.3494, [], zone=True))
    whole = core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers="50:21:0120316:1221"))["normalized"]["apartment_area_sqm"]
    core._GLAVAPU_TEP_CACHE.clear()
    monkeypatch.setattr(core, "land_screening", lambda **kw: KOMMUNARKA)
    cut = core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers="50:21:0120316:1221"))["normalized"]["apartment_area_sqm"]
    assert cut < whole * 0.85


def test_a_ban_heads_the_moscow_tep(monkeypatch):
    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", False)
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: _analysis(7.3156))
    monkeypatch.setattr(core, "land_screening", lambda **kw: MYTISHCHI)
    result = core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers="50:12:0100131:497"))
    assert result["warnings"][0].startswith("Строить нельзя")
    # Решение владельца: ТЭП при запрете считается и подставляется.
    assert result["normalized"]["apartment_area_sqm"] > 0


def test_a_silent_screening_is_named_not_taken_for_clean(monkeypatch):
    def down(**kw):
        raise core.HTTPException(status_code=502, detail="Ядро недоступно: timed out")

    monkeypatch.setattr(core, "_GLAVAPU_HEADLESS_ENABLED", False)
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: _analysis(1.0))
    monkeypatch.setattr(core, "land_screening", down)
    result = core.cadastral_tep_server(core.CadastralAnalysisRequest(
        cadastral_numbers="77:06:0003002:18"))
    said = [w for w in result["warnings"] if "Ограничения участка не проверены" in w]
    assert said and "Ядро недоступно" in said[0]


# --- Московская область -------------------------------------------------------------

def _mo(monkeypatch, screening):
    feature = {"properties": {"options": {
        "cad_num": "50:12:0100131:497", "area": 73156.0,
        "readable_address": "Московская область, г.о. Мытищи",
        "land_record_category_type": "Земли населённых пунктов",
        "permitted_use_established_by_document": "Для ведения личного подсобного хозяйства"}},
        "geometry": PARCEL}
    monkeypatch.setattr(core, "_nspd_search_features", lambda q: [feature])
    monkeypatch.setattr(core, "land_screening", lambda **kw: screening)
    return core.mo_calculate(core.MoCalculateRequest(query="50:12:0100131:497",
                                                     density_sqm_per_ha=10000))


def test_the_oblast_says_the_ban(monkeypatch):
    result = _mo(monkeypatch, MYTISHCHI)
    assert result["warnings"][0].startswith("Строить нельзя")
    assert "Особо охраняемые" in result["warnings"][0]
    assert result["site_restrictions"]["ban_whole"] is True


def test_the_oblast_counts_flats_on_what_is_left(monkeypatch):
    clean = _mo(monkeypatch, _screening("50:12:0100131:497", 7.3156, [], zone=True))
    cut = _mo(monkeypatch, _screening("50:12:0100131:497", 7.3156, [
        {"flag_class": "economic", "effect": "area", "name": "Охранная зона газопровода",
         "coverage_pct": 25.0, "cut_pct": 25.0}], zone=True))
    assert cut["territory"]["restrict_ha"] == pytest.approx(7.3156 * 0.25, abs=0.001)
    assert cut["social"]["apartments_sqm"] == pytest.approx(
        clean["social"]["apartments_sqm"] * 0.75, rel=0.001)


# --- схема посадки ---------------------------------------------------------------

def test_the_massing_carries_the_height_caveat():
    summary = core._land_restrictions_summary(VNUKOVO)
    inputs = {**core.DEFAULT_INPUTS, "_glavapu_import": {"site_restrictions": summary}}
    notes = core.site_restriction_massing_notes(inputs)
    assert notes and notes[0].startswith("Высота ограничена")
    # Ручной ТЭП без свода — без оговорок: скрининга по нему не было.
    assert core.site_restriction_massing_notes(dict(core.DEFAULT_INPUTS)) == []
