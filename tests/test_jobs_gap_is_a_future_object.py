"""Дефицит рабочих мест — будущий объект, а не строка справки.

РНГП Подмосковья требует полрабочего места на жителя. Часть закрывают
нормативные соцобъекты, торговля, общепит и быт; остаток закрывать девелоперу —
офисным центром или дополнительной торговлей. На экране это стояло строкой
«Офисы под рабочие места — N м²» без слова «нужно», рядом с озеленением и
компенсацией в бюджет, и читалось как справка. Между тем это объект: он стоит
денег, занимает площадку и меняет ТЭП.

Замечание владельца, 19.08.2026: «может и писать в ТЭП потребность в МПТ — и
дальше человек будет знать, что ему скорее всего надо будет что-то построить,
типа офисника или ТЦ».

Запуск: python3 -m pytest tests/test_jobs_gap_is_a_future_object.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _jobs(apartments_sqm: float) -> dict:
    return core.mo_social_program(apartments_sqm, None)["jobs"]


def test_the_gap_says_what_closes_it():
    jobs = _jobs(100000.0)
    assert jobs["deficit"] > 0
    # Норматив офиса — 10 м² на место, торговли — 15 м²: те же числа, которыми
    # места считаются в обратную сторону.
    assert jobs["office_sqm"] == jobs["deficit"] * jobs["office_sqm_per_job"]
    assert jobs["retail_sqm"] == jobs["deficit"] * jobs["retail_sqm_per_job"]
    assert jobs["office_sqm_per_job"] == 10.0
    assert jobs["retail_sqm_per_job"] == 15.0


def test_the_retail_norm_is_declared_once():
    """Один и тот же метр на место считает и места от торговли, и торговлю под места."""
    source = core.inspect.getsource(core.mo_social_program) if hasattr(core, "inspect") else ""
    if not source:
        import inspect

        source = inspect.getsource(core.mo_social_program)
    assert "retail_gba / retail_sqm_per_job" in source, (
        "места от торговли считаются своим числом, а не общим нормативом")
    assert source.count("retail_sqm_per_job = 15.0") == 1


def test_the_page_calls_the_gap_a_task_and_not_a_note():
    body = core.PAGE[core.PAGE.index("function jobsGapText"):]
    body = body[:body.index("function moTable")]
    assert "офисы" in body and "торговля" in body
    assert "дефицита нет" in body, "нулевой дефицит должен называться нулём, а не пустотой"

    block = core.PAGE[core.PAGE.index("Социальная нагрузка по РНГП МО"):]
    block = block[:block.index("Смена ВРИ")]
    assert "Чем закрыть дефицит" in block
    assert "дают нормативные объекты" in block


def test_the_gap_reaches_the_warnings(monkeypatch):
    """Свод обязательств должен нести дефицит, а не оставлять его в таблице."""
    social = core.mo_social_program(100000.0, None)
    gap = social["jobs"]["deficit"]
    assert gap > 0
    source = __import__("inspect").getsource(core.mo_calculate)
    assert "рабочих мест сверх тех" in source
    assert "В ТЭП он не включён" in source
