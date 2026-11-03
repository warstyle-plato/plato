"""Московские ступени площади на место действуют только в Москве.

Ступень 2151-ПП (ред. 2579-ПП) — ДОО 27 м²/место до 125 мест, 18 до 250, 16
свыше — применялась к любому проекту: калькулятор Подмосковья присылал свой
норматив 27 в поле `social_dou_norm_sqm`, а в режиме «по нормативу» ступень
города перебивала его на 18 — с подписью «норматив РНГП». У области нормативы
свои (решение владельца 16.10.2026, `docs/normative_audit_msk_mo_2026-10.md`
§6 п.3 «б»): регион проекта спрашивает ОДИН предикат
(`moscow_social_steps_apply` в движке, `moscowSocialStepsApply` на странице),
и все читатели ступени — движок очередей, книга, страница — отвечают им.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from tests import page_blocks  # noqa: E402
from tests.engine_source import engine_source  # noqa: E402


def _inputs(**over):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x["social_mode"] = "Строительство"
    x["social_area_source"] = "norm"
    x.update(over)
    return x


def _oblast(**over):
    # Как присылает калькулятор МО: регион, места и СВОЙ норматив в поле.
    return _inputs(**{"vri_region": "mo", "kindergarten_places": 250,
                      "social_dou_norm_sqm": 27, "social_dou_gba_sqm": 0, **over})


def _moscow(**over):
    return _inputs(**{"vri_region": "msk", "kindergarten_places": 250,
                      "social_dou_norm_sqm": 27, "social_dou_gba_sqm": 0, **over})


def test_the_predicate_reads_the_region_once():
    assert core.moscow_social_steps_apply({}) is True, "пустой регион — Москва"
    assert core.moscow_social_steps_apply({"vri_region": "msk"}) is True
    assert core.moscow_social_steps_apply({"vri_region": "mo"}) is False
    # Нормализация та же, что у региона класса: регистр и пробелы не решают.
    assert core.moscow_social_steps_apply({"vri_region": " MO "}) is False


def test_the_oblast_norm_mode_answers_with_the_field():
    """Область: 27 из поля, а не московская ступень 18; Москва: ступень."""
    assert core.social_area_per_place(_oblast(), "kindergarten") == 27
    assert core.social_area_per_place(_moscow(), "kindergarten") == 18
    assert core.social_area_per_place(
        _inputs(vri_region="mo", school_places=1000, social_school_norm_sqm=27),
        "school") == 27
    # Пустое поле у области — «не знаем», а не ступень соседнего региона.
    assert core.social_area_per_place(_oblast(social_dou_norm_sqm=0), "kindergarten") == 0


def test_the_oblast_row_is_measured_by_its_own_norm():
    """Строка ТЭП: площадь от мест нормативом области; присланная площадь не переписывается."""
    row = core.social_tep_row(_oblast(), "kindergarten")
    assert row["units"] == 250
    assert row["total_area"] == pytest.approx(250 * 27)
    # Калькулятор МО присылает и площадь: московская ступень не перебивает её
    # своими 250 × 18 = 4 500.
    sent = core.social_tep_row(_oblast(social_dou_gba_sqm=6750), "kindergarten")
    assert sent["total_area"] == pytest.approx(6750)
    assert core.social_tep_row(_moscow(), "kindergarten")["total_area"] == pytest.approx(250 * 18)


def test_a_requirement_does_not_fill_the_oblast_area_with_the_moscow_step():
    """Признак требования: объект без площади получает свою по нормативу — не чужому."""
    inputs = _oblast(social_dou_norm_sqm=0, school_places=500,
                     social_school_gba_sqm=9000)
    assert core.declare_social_requirement(inputs) is True
    assert float(inputs.get("social_dou_gba_sqm") or 0.0) == 0, (
        "площадь областного садика посчитана московской ступенью")
    filled = _oblast(school_places=500, social_school_gba_sqm=9000)
    core.declare_social_requirement(filled)
    assert filled["social_dou_gba_sqm"] == pytest.approx(250 * 27)


def test_every_engine_reader_goes_through_the_predicate():
    """Ступень читают через `social_area_step` — прямой вызов остался один, внутри неё."""
    source = engine_source()
    declaration = "def moscow_social_area_per_place("
    body = source[source.index(declaration) + len(declaration):]
    direct = body.count("moscow_social_area_per_place(")
    assert direct == 1, f"прямых обращений к ступени в движке {direct}, ожидался один"
    for reader in ("def social_area_per_place(", "def social_tep_row(",
                   "def declare_social_requirement("):
        at = source.index(reader)
        assert "social_area_step(" in source[at:at + 6000], reader
    # Книга v4 печатает норматив (колонка M) тем же ответом, что строка ТЭП.
    assert "social_area_per_place(x, typ))" in source


PRELUDE = "\n".join([
    page_blocks.constant("TEP_RATIOS"),
    page_blocks.constant("SOCIAL_AREA_STEPS"),
    "const TEP_SOCIAL_INPUTS={kindergarten:'social_dou_gba_sqm',"
    "school:'social_school_gba_sqm',clinic:'social_clinic_gba_sqm'};",
    "let inputs={},tep={},storageInsideParking=0;",
    "let tepBody=null;const document={activeElement:null,getElementById:()=>null};",
    "function renderTep(){}",
    "function updateTepTotals(){}",
])


def test_the_page_syncs_the_oblast_like_the_engine():
    """`syncTep` страницы: область держит поле, Москва — ступень; как движок."""
    cases = [_oblast(), _moscow(), _oblast(social_dou_gba_sqm=6750)]
    tail = """
const CASES=%s;
console.log(JSON.stringify(CASES.map(x=>{
  inputs=JSON.parse(JSON.stringify(x));
  tep=JSON.parse(JSON.stringify(%s));
  const step=socialAreaPerPlace('kindergarten',250);
  syncTep(false);
  return {step:step,norm:inputs.social_dou_norm_sqm,
          total_area:tep.kindergarten.total_area,units:tep.kindergarten.units};
})));
""" % (json.dumps(cases, ensure_ascii=False),
       json.dumps(core.TEP_DEFAULT, ensure_ascii=False))
    shown, taken = page_blocks.run(PRELUDE, tail)
    assert "syncTep" in taken, "стенд обязан гонять сам `syncTep`, а не его пересказ"
    oblast, moscow, sent = json.loads(shown)
    assert oblast["step"] == 0 and moscow["step"] == 18
    assert oblast["norm"] == 27 and oblast["total_area"] == pytest.approx(250 * 27)
    assert moscow["norm"] == 18 and moscow["total_area"] == pytest.approx(250 * 18)
    assert sent["total_area"] == pytest.approx(6750)
    for inputs, page_row in zip(cases, (oblast, moscow, sent)):
        row = {"kindergarten": copy.deepcopy(core.TEP_DEFAULT["kindergarten"])}
        core.apply_social_tep_rows(inputs, row)
        assert page_row["total_area"] == pytest.approx(row["kindergarten"]["total_area"]), (
            inputs["vri_region"])


def test_the_note_names_whose_norm_it_is():
    """Подпись фактического показателя: Москва — 2151-ПП, область — её норматив."""
    tail = """
const OUT={};
inputs=%s;OUT.msk=socialNormNote('kindergarten');
inputs=%s;OUT.mo=socialNormNote('kindergarten');
console.log(JSON.stringify(OUT));
""" % (json.dumps(_moscow(social_area_source="manual", social_dou_gba_sqm=5550),
                  ensure_ascii=False),
       json.dumps(_oblast(social_area_source="manual", social_dou_gba_sqm=5550),
                  ensure_ascii=False))
    out = page_blocks.run_json(PRELUDE, tail)
    assert "норматив Москвы (2151-ПП) 18" in out["msk"], out
    assert "РНГП" not in out["msk"]
    assert "норматив области (калькулятор МО)" in out["mo"], out
    assert "18" not in out["mo"], "областному садику названа московская ступень"
    # Запертая ячейка нормативного режима подписана тем же предикатом.
    assert "по нормативу РНГП" not in core.PAGE
    assert "if(!moscowSocialStepsApply())return 0;" in page_blocks.function("socialAreaPerPlace")
