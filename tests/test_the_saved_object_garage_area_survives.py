"""Число удалённого поля площади места гаража объекта не теряется молча.

#541 удалил поле `object_parking_area_per_space_sqm`: площадь подземного
места гаража объекта стала нормативом класса. Проекты, сохранённые раньше,
несут прежний ключ, и вписанное туда число просто перестало действовать —
КРТ «Варшавское ш., вл. 37» (класс «Бизнес») получил гараж ТЦ 26 813 м²
вместо 25 025 и CAPEX +345 млн без единого слова (аудит регрессий
29.09.2026, №5).

Правило: отсутствие данных не решение пользователя, а сохранённое состояние
накладывается на умолчания. Поэтому:
- число, вписанное руками (≠ норматива класса и ≠ прежнего умолчания 35 м²),
  действует для гаража объекта и названо в плашке паркинга «вписана руками»;
- прежнее умолчание 35 м² решением человека не было — действует норматив
  класса, а плашка говорит, что число заменено;
- страница даёт снять сохранённое число кнопкой: своего поля у него нет.

Запуск: python3 -m pytest tests/test_the_saved_object_garage_area_survives.py -q
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402
import page_blocks  # noqa: E402

UNDER = 715


def _saved_project(saved_area=None, project_class="business") -> dict:
    """Проект, сохранённый до #541: ТЦ со своим подземным гаражом."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(core.PROJECT_CLASS_PRESETS[project_class])
    x.pop("label", None)
    x.update(project_class=project_class, retail_enabled=True,
             retail_gba_sqm=60_000, retail_saleable_sqm=40_000,
             retail_parking_under_spaces=UNDER,
             retail_parking_over_spaces=0,
             _parking_by_hand=["retail"])
    if saved_area is not None:
        x["object_parking_area_per_space_sqm"] = saved_area
    return x


def _parking(inputs: dict) -> dict:
    result = core.calculate(core.CalcRequest(
        inputs=inputs, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))
    return result["parking"]


def _retail_garage(parking: dict) -> float:
    return {item["tep_key"]: item for item in parking["own"]}["standalone_retail"]["under_gns"]


def test_a_hand_written_area_keeps_working() -> None:
    norm = core.PROJECT_CLASS_PRESETS["business"]["underground_area_per_space_sqm"]
    assert norm == 37.5  # предохранитель: иначе сценарий ничего не проверяет
    parking = _parking(_saved_project(saved_area=33))
    assert _retail_garage(parking) == pytest.approx(UNDER * 33)
    assert parking["area_per_space_sqm"] == 33
    assert parking["area_per_space_source"] == "saved_manual"
    assert parking["area_per_space_saved"]["origin"] == "manual"
    # Происхождение видно человеку, а не только полю ответа.
    assert "33 м² — из сохранённого проекта, вписана руками" in parking["note"]
    assert "норматив класса 37,5 м²" in parking["note"]


def test_the_book_reads_the_same_area() -> None:
    """K158 книги пишет то же число, что строит гараж движок."""
    derive = core._V4_DERIVED_INPUTS["object_parking_area_per_space_sqm"]
    assert derive(_saved_project(saved_area=33)) == 33
    assert derive(_saved_project(saved_area=35)) == 37.5
    assert derive(_saved_project()) == 37.5


def test_the_old_default_is_replaced_by_the_norm_out_loud() -> None:
    parking = _parking(_saved_project(saved_area=35))
    assert _retail_garage(parking) == pytest.approx(UNDER * 37.5)
    assert parking["area_per_space_source"] == "class_norm"
    assert parking["area_per_space_saved"]["origin"] == "old_default"
    assert "стояла 35 м² — прежнее умолчание; теперь берётся норматив класса 37,5 м²" in parking["note"]


def test_a_new_project_says_nothing() -> None:
    parking = _parking(_saved_project())
    assert _retail_garage(parking) == pytest.approx(UNDER * 37.5)
    assert parking["area_per_space_saved"] is None
    assert "сохранённ" not in parking["note"]
    # Совпадение с нормативом — тоже не повод для слов.
    parking = _parking(_saved_project(saved_area=37.5))
    assert parking["area_per_space_saved"] is None
    assert "сохранённ" not in parking["note"]


@pytest.mark.parametrize("raw", ["", None, 0, -5, "abc", True])
def test_an_empty_saved_key_is_not_a_decision(raw) -> None:
    assert core.object_parking_area_saved(_saved_project(saved_area=raw)) is None


def _page_note(parking: dict) -> dict:
    prelude = (
        "const box={innerHTML:''};let clicked=null;let calcs=0;\n"
        "const button={addEventListener:(e,f)=>{clicked=f}};\n"
        "const document={getElementById:id=>id==='objectParkingNote'?box:"
        "(id==='objectParkingAreaSavedDrop'&&box.innerHTML.includes(id)?button:null)};\n"
        "function renderObjectParkingFieldNotes(){}\n"
        "function persistLocalSilently(){}\n"
        "function calculate(){calcs++}\n"
        "const phaseBundle=null;\n"
        f"const lastResult={{parking:{json.dumps(parking, ensure_ascii=False)}}};\n"
        "const inputs={object_parking_area_per_space_sqm:33,project_class:'business'};\n"
    )
    tail = ("renderObjectParkingNote();const html=box.innerHTML;if(clicked)clicked();"
            "process.stdout.write(JSON.stringify({html,calcs,"
            "left:'object_parking_area_per_space_sqm' in inputs}));")
    out, _ = page_blocks.run(prelude, tail)
    return json.loads(out)


def test_the_page_offers_to_take_the_norm() -> None:
    parking = _parking(_saved_project(saved_area=33))
    got = _page_note(parking)
    assert "вписана руками" in got["html"]
    assert "Взять норматив класса" in got["html"]
    assert got["calcs"] == 1 and got["left"] is False


def test_the_page_has_no_button_without_a_saved_number() -> None:
    got = _page_note(_parking(_saved_project()))
    assert "objectParkingAreaSavedDrop" not in got["html"]
    assert got["calcs"] == 0 and got["left"] is True
