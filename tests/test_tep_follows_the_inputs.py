"""Объект, добавленный во вводных, обязан появиться в ТЭП.

Владелец включил офисы и задал их площадь — экономика их посчитала, а в таблице
ТЭП строка «Офисы» осталась прежней (19.08.2026). Причина в том, что связь
«поле → ТЭП» жила строкой в обработчике `onchange`: там перечислены признаки
включения объектов, но не их площади. Поставил галочку — синхронизация прошла с
теми метрами, что были; поменял метры — не прошла вовсе.

Цена ошибки не в одной строке таблицы. ГНС проекта считается суммой ТЭП, и все
удельные показатели — выручка, себестоимость, прибыль на метр — делятся на
площадь, в которой офиса нет, хотя его стоимость и выручка в модели есть.

Второе, из той же семьи: соцобъекты в ТЭП обнулялись при режиме «Строительство
и компенсация» — там проверялось только «Строительство», а школа и садик в
совмещённом режиме строятся.

Запуск: python3 -m pytest tests/test_tep_follows_the_inputs.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _sync_source() -> str:
    body = core.PAGE[core.PAGE.index("function syncTep(rerender=true){"):]
    return body[:body.index("function addMonthsJS")]


def _declared() -> list[str]:
    block = core.PAGE[core.PAGE.index("const UNDERGROUND_PAIR_INPUTS"):]
    block = block[:block.index("function syncTep")]
    return re.findall(r"'([a-z_0-9]+)'", block)


def test_every_input_that_shapes_the_tep_is_declared():
    """Список полей сверяется с тем, что `syncTep` читает на самом деле."""
    used = set(re.findall(r"inputs\.([a-z_0-9]+)", _sync_source()))
    declared = set(_declared())
    forgotten = sorted(used - declared)
    assert not forgotten, f"поля не доедут до ТЭП при правке: {forgotten}"


def test_the_office_area_reaches_the_tep():
    """Площадь офиса — то самое поле, которого в списке не было."""
    declared = _declared()
    for field in ("offices_gba_sqm", "offices_saleable_sqm",
                  "retail_gba_sqm", "retail_saleable_sqm"):
        assert field in declared, field


def test_the_handler_uses_the_declared_list():
    """Обработчик обязан спрашивать список, а не хранить свою копию."""
    handler = core.PAGE[core.PAGE.index("el.onchange=()=>{"):]
    handler = handler[:handler.index("wrap.appendChild(el)")]
    assert "TEP_DERIVED_INPUTS.includes(id)" in handler
    assert "'offices_enabled','retail_enabled'" not in handler, "копия списка вернулась"


def test_social_objects_stay_in_the_tep_in_the_combined_mode():
    """«Строительство и компенсация» — тоже стройка."""
    source = _sync_source()
    condition = source[source.index("const socialBuild="):source.index(";", source.index("const socialBuild="))]
    assert "Строительство и компенсация" in condition


def _anomalies(inputs: dict, tep: dict) -> list[str]:
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    request = core.AgentChatRequest(message="аномалии", inputs=inputs, tep=tep, rates=[], phasing={})
    return [item["code"] for item in core._tool_find_anomalies(request, bundle, "all")["anomalies"]]


def test_a_saved_project_with_an_empty_row_is_called_out():
    """Сохранённый проект мог лечь на диск с пустой строкой ТЭП.

    Страницу починили, но старый файл она не переписывает: расхождение между
    вводными и ТЭП должно называться вслух, а не молча съедать знаменатель всех
    удельных показателей.
    """
    inputs = {**core.DEFAULT_INPUTS, "offices_enabled": True,
              "offices_gba_sqm": 26700, "offices_saleable_sqm": 18100}
    tep = {key: {**value} for key, value in core.TEP_DEFAULT.items()}
    tep["offices"] = {**tep["offices"], "gns": 0, "total_area": 0, "saleable": 0}
    assert "OBJECT_MISSING_IN_TEP" in _anomalies(inputs, tep)

    tep["offices"] = {**tep["offices"], "gns": 26700, "total_area": 26700, "saleable": 18100}
    assert "OBJECT_MISSING_IN_TEP" not in _anomalies(inputs, tep)
