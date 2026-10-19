"""Подпись норматива называет тот акт, в котором стоит число.

Ревизия нормативного блока (`docs/normative_audit_msk_mo_2026-10.md`, § 5)
нашла подписи, у которых число верное, а акт — чужой:

* 33 м² квартир на человека звались «приложение 5 к 945-ПП», хотя число
  стоит в 2152-ПП (табл. 1.4.1), а приложение 5 лишь читает его как S₁ в
  формуле машино-мест;
* ступени площади на место ДОО и СОШ звались «РНГП» — словом области, —
  хотя это 2151-ПП Москвы;
* областная таблица приобъектных мест ссылалась на СП 42.13330.2016 как на
  действующий, а он отменён с 12.07.2026;
* Кд в книге подписан «по видам использования», а у 1745-ПП он по округам
  (таблица 3);
* льгота МПТ отнесена к 3135-ПП, а её основание — 1874-ПП.

Числа не менялись — только подписи, и каждая проверка здесь падает на
прежнем тексте. Смотрим на владельца подписи: функцию, константу, страницу
и книгу — а не на копии.

Запуск: python3 -m pytest tests/test_the_labels_name_the_right_act.py -q
"""

from __future__ import annotations

import copy
import html
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import mo_rngp_reference as ref  # noqa: E402
import parking_norms  # noqa: E402


# --- T1: 33 м²/чел — 2152-ПП, приложение 5 лишь читает его как S₁ ------------

def test_the_population_norm_names_2152_not_the_parking_appendix() -> None:
    _people, basis = core.project_population(core.TEP_DEFAULT, "msk")
    assert "2152-ПП" in basis and "табл. 1.4.1" in basis, basis
    assert "33 м²" in basis, basis
    assert not basis.startswith("приложение 5 к 945-ПП"), basis
    # Область — своим словом: «РНГП» — термин области, и там он на месте.
    _people, oblast = core.project_population(core.TEP_DEFAULT, "mo")
    assert oblast.startswith("РНГП Московской области"), oblast


def test_the_parking_formula_names_both_acts() -> None:
    """В формуле машино-мест 33 — это S₁: формула из приложения 5, число из 2152-ПП."""
    _places, basis = core.moscow_permanent_parking_by_average(10_000.0, 0)
    assert basis.startswith("приложение 5 к 945-ПП в редакции 2118-ПП, пункт 1"), basis
    assert "S₁ = 33 м² по 2152-ПП" in basis, basis


def test_the_book_row_of_the_population_norm_names_2152(sheets: str) -> None:
    assert "2152-ПП, п. 1.4.2, табл. 1.4.1" in sheets
    assert "приложение 5 к 945-ПП для Москвы" not in sheets


# --- T2: ступени ННП — 2151-ПП Москвы, не «РНГП» -----------------------------

def test_the_page_calls_the_steps_by_the_moscow_act() -> None:
    page = core.PAGE
    # Подсказки полей и подпись режима — из реестра полей движка.
    assert "27 м² на место, если мест до 124" in page
    assert "(2151-ПП, табл. 1.4.1 в ред. 2579-ПП)" in page
    assert "18 м² на место, если мест до 550" in page
    assert "(2151-ПП, табл. 1.4.2 в ред. 2579-ПП)" in page
    # Подписи рядом с полем площади — из JS страницы.
    assert "норматив Москвы (2151-ПП)" in page
    assert "по нормативу Москвы (2151-ПП)" in page
    for old in ("норматив РНГП", "Норматив РНГП", "по нормативу РНГП", "РНГП: 27 до 124"):
        assert old not in page, old


def test_platon_knows_whose_steps_these_are() -> None:
    rules = {rule["id"]: rule["rule"] for rule in core._DevelopAid_METHODOLOGY}
    steps = rules["SOCIAL_AREA_VS_BUDGET"]
    assert "2151-ПП" in steps and "норматив РНГП" not in steps, steps
    # Пример цитирования акта в инструкции — верный: 33 м² — 2152-ПП.
    assert "33 м² на человека — 2152-ПП, табл. 1.4.1" in core._AGENT_INSTRUCTIONS
    assert "называй с актом («приложение 5 к 945-ПП»)" not in core._AGENT_INSTRUCTIONS


# --- T7: 2,1 — размер домовладения Москвы, не норма области -------------------

def test_platon_does_not_call_2_1_an_oblast_norm() -> None:
    rules = {rule["id"]: rule["rule"] for rule in core._DevelopAid_METHODOLOGY}
    flat = rules["AVERAGE_FLAT"]
    assert "РНГП области: 28 м² на человека при размере домовладения 2,1" not in flat, flat
    assert "945-ПП" in flat and "03.09.2026" in flat, flat
    assert "58,8" in flat, flat


# --- T3: СП 42.13330.2016 отменён с 12.07.2026 --------------------------------

def test_the_oblast_parking_label_does_not_claim_the_cancelled_sp() -> None:
    label = core.PARKING_NORM_OF[core.parking_norms.MOSCOW_OBLAST]
    assert "приложение № 10 к 713/30" in label, label
    assert "СП 42.13330.2016 отменён" in label, label
    assert "СП 42.13330.2016, табл. Ж.1" not in label, label
    # Москва на месте — предохранитель от правки не того ключа.
    assert core.PARKING_NORM_OF[core.parking_norms.MOSCOW] == "приложения 6 к 945-ПП"


def test_the_oblast_rules_source_is_the_appendix_not_the_sp() -> None:
    source = parking_norms.MO_RULES_SOURCE
    assert source.startswith("приложение № 10 к 713/30"), source
    assert "отменён с 12.07.2026" in source, source
    assert "текст на руках" not in source, source
    # Текста СП 42.13330.2026 у нас нет — его чисел подпись не обещает.
    assert "СП 42.13330.2026" not in source, source
    assert parking_norms.MO_RULES_CONFIRMED is False


# --- T8: Кд — по округам, таблица 3 к 1745-ПП ---------------------------------

def test_the_book_names_table_3_of_1745_for_kd(sheets: str) -> None:
    assert "1745-ПП, таблица 3: коэффициент доходности Кд по городским округам" in sheets
    assert "по видам использования" not in sheets


# --- T4: основание льготы МПТ — 1874-ПП -----------------------------------------

def test_the_mpt_relief_basis_names_1874() -> None:
    inputs = dict(core.DEFAULT_INPUTS, vri_relief_mode="off")
    _ours, reasons = core._glavapu_scenario_ours(
        inputs, copy.deepcopy(core.TEP_DEFAULT), {"params": {}, "numbers": []})
    reason = reasons["vri_relief.total"]
    assert "проверить основание (1874-ПП, прил. 1 п. 1.6" in reason, reason
    assert "593-ПП прил. 2 п. 86" in reason, reason
    assert "3135-ПП" not in reason, reason


# --- T9: 1/50 — редакция 1080-ПП --------------------------------------------------

def test_the_ground_floor_rule_is_read_from_1080() -> None:
    rule = ref.PARKING_NONRESIDENTIAL_GROUND_FLOOR
    assert rule["document"] == ref.PP_1080["document"]
    assert rule["effective_from"] == ref.PP_1080["effective_from"] == "01.09.2026"
    assert rule["official_source"] == ref.PP_1080["official_source"]
    assert rule["point_table"].startswith("п. 5.12")
    assert rule["value"] == 50.0
    assert "многоуровневых паркингов независимо от функции" in rule["quote"]
    # Цитата — из разобранного текста 1080-ПП, а не пересказ.
    pack = (ROOT / "data" / "normatives" / "mo" / "pp_1080_2026-09-01.md").read_text(encoding="utf-8")
    assert rule["quote"].split(" - из расчета")[0] in pack


def test_the_market_price_example_names_the_current_order() -> None:
    from engine_source import engine_source
    text = engine_source()
    assert "от 28.04.2026 № 114-Р на III–IV кварталы 2026" in text
    assert "№ 89-Р на III–IV кварталы 2025" not in text


# --- T10: 135 мест — показатель без сведений о демографии ---------------------

def test_the_school_fallback_is_called_a_fallback() -> None:
    from engine_source import engine_source
    text = engine_source()
    head = text.index('"school_places_per_1000": 135.0')
    assert "при отсутствии сведений о демографическом составе" in text[head - 600:head]
    assert "п. 5.18" in text[head - 600:head]


# --- книга: один раз на модуль ---------------------------------------------------

@pytest.fixture(scope="module")
def sheets() -> str:
    """Тексты всех листов областной книги: подписи Кд и нормы населения."""
    x = dict(core.DEFAULT_INPUTS)
    x["vri_region"] = "mo"
    content, _, meta = core.build_project_workbook(
        x, copy.deepcopy(core.TEP_DEFAULT), [], None, project_name="Подписи актов")
    assert not [item for item in (meta.get("missing") or []) if "Источники" in str(item)], \
        meta.get("missing")
    texts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as book:
        for name in book.namelist():
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                xml = book.read(name).decode("utf-8")
                texts.extend(html.unescape(value) for value in
                             re.findall(r"<x:t[^>]*>(.*?)</x:t>|<x:v>(.*?)</x:v>", xml, re.S)
                             for value in [value[0] or value[1]] if value)
    return " ".join(texts)
