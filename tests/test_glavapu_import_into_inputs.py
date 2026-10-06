"""Выгрузка ГлавАПУ — источник входов московского проекта, с происхождением.

Цель владельца (06.10.2026): калькулятор не переигрывать, а брать его данные
во вводные и ТЭП московского проекта с пометкой «ГлавАПУ, выгрузка от <дата>,
лист, строка». Ручное значение пользователя остаётся ручным. В Подмосковье и
других регионах калькулятор не участвует вовсе: ни подстановки, ни справки.
Регион — по данным проекта (поле региона, кадастровые номера), а не по имени
файла.

Страница проверяется настоящим `applyGlavapu` через node.

Запуск: python3 -m pytest tests/test_glavapu_import_into_inputs.py -q
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import page_blocks  # noqa: E402
from test_live_import_reaches_the_engine import page_function  # noqa: E402

XLSX = ROOT / "tests" / "fixtures" / "glavapu_scenario_nagatino_vendored.xlsx"


def _dated(data: bytes, when: datetime | None) -> bytes:
    """Та же книга со свойствами (дата выгрузки) или вовсе без них."""
    import openpyxl
    book = openpyxl.load_workbook(io.BytesIO(data))
    if when is not None:
        book.properties.created = when
        book.properties.modified = when
    out = io.BytesIO()
    book.save(out)
    if when is not None:
        return out.getvalue()
    stripped = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as src, \
            zipfile.ZipFile(stripped, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename != "docProps/core.xml":
                dst.writestr(item, src.read(item.filename))
    return stripped.getvalue()


# --------------------------------------------------------------- сервер --

def test_every_mapped_value_has_its_sheet_and_row() -> None:
    parsed = core.parse_glavapu_xlsx(_dated(XLSX.read_bytes(), datetime(2026, 10, 6, 15, 31)), "n.xlsx")
    assert parsed["source"]["export_date"] == "06.10.2026"
    provenance = parsed["provenance"]
    expected = {f"inputs.{k}" for k in parsed["mappings"]["inputs"]}
    expected |= {f"tep.{obj}.{field}" for obj, fields in parsed["mappings"]["tep"].items()
                 for field in fields if (obj, field) in core._GLAVAPU_TEP_SOURCE}
    assert expected <= set(provenance)
    assert all(item["sheet"] and item["row"] for item in provenance.values()), [
        k for k, v in provenance.items() if not v["sheet"]]
    assert provenance["inputs.land_rights_cost_mln"]["text"] == \
        "ГлавАПУ, выгрузка от 06.10.2026, лист «ТЭП», строка 44"
    assert provenance["tep.apartments.gns"]["row"] == "строка 7.1"
    assert "Параметры территории" in provenance["inputs.parking_k1"]["text"]


def test_no_date_in_the_book_is_said_not_guessed() -> None:
    parsed = core.parse_glavapu_xlsx(_dated(XLSX.read_bytes(), None), "06.10.2026.xlsx")
    assert parsed["source"]["export_date"] is None
    text = parsed["provenance"]["inputs.land_rights_cost_mln"]["text"]
    assert "дата в файле не указана" in text and "06.10.2026" not in text


# -------------------------------------------------------------- страница --

def _apply(parsed: dict, inputs_extra: dict, *, before: dict | None = None,
           manual: dict | None = None) -> dict:
    """Настоящий applyGlavapu. `before` — выгрузка, применённая прежде;
    `manual` — поля, вписанные руками между двумя импортами."""
    if not shutil.which("node"):
        pytest.skip("node недоступен")
    import re
    keys = re.search(r"(const TERRITORY_INPUT_KEYS=.*?)\nfunction resetTerritoryData", core.PAGE, re.S)
    body = re.search(r"(function resetTerritoryData\(.*?)\nfunction getGlavapuUnderground", core.PAGE, re.S)
    inputs = dict(core.DEFAULT_INPUTS, **inputs_extra)
    tep = json.loads(json.dumps(core.TEP_DEFAULT))
    stubs = (
        "const document={getElementById:()=>({style:{},innerHTML:''})};\n"
        "const glavapuStatus={innerHTML:''};\n"
        "let phasing=null;let cadastralAnalysis=null;let moResult=null;\n"
        "function makeDefaultPhasing(){return {enabled:false,phase_count:1}}\n"
        "function applyRequiredSocialProgramFromGlavapu(){}\nfunction syncTep(){}\n"
        "function applyServerPresetProjectConfig(){return ''}\n"
        "function applyTelegramCalcOverrides(){}\nfunction renderInputs(){}\n"
        "function renderTep(){}\nfunction renderPhasing(){}\n"
        "function renderGlavapuPreview(){}\n"
        "async function calculate(){}\nasync function sendTelegramResult(){}\n"
        f"let inputs={json.dumps(inputs, ensure_ascii=False)};\n"
        f"let tep={json.dumps(tep)};\nlet glavapuImport=null;\n"
        f"const PARKING_2118={json.dumps(core.PARKING_2118_PARAMS)};\n"
        "function num(v){return Number(v||0).toLocaleString('ru-RU')}\n"
        "function scheduleTepAutoRecalc(){}\n")
    real = page_blocks.krt_lock() + "\n" + "\n".join(page_function(name) for name in (
        "getGlavapuUnderground", "undergroundAreaPerSpace", "normativeUnderground",
        "parkingRequirement", "repairParkingFromGlavapu", "fillUndergroundFromTep"))
    prelude = (f"const payload={json.dumps(parsed, ensure_ascii=False, default=str)};\n"
               f"const earlier={json.dumps(before, ensure_ascii=False, default=str)};\n"
               + stubs + real + "\n" + keys.group(1) + "\n" + body.group(1))
    tail = ("\n(async()=>{if(earlier){glavapuImport=earlier;await applyGlavapu();}"
            "for(const [k,v] of Object.entries(MANUAL)){const p=k.split('.');"
            "if(p[0]==='inputs')inputs[p[1]]=v;else tep[p[1]][p[2]]=v;markFieldManual(k);}"
            "glavapuImport=payload;await applyGlavapu();"
            "console.log(JSON.stringify({inputs,tep,status:glavapuStatus.innerHTML}));})()")
    return page_blocks.run_json(
        f"const MANUAL={json.dumps(manual or {}, ensure_ascii=False)};\n" + prelude, tail)


def _parsed(when=datetime(2026, 10, 6)) -> dict:
    return core.parse_glavapu_xlsx(_dated(XLSX.read_bytes(), when), "nagatino.xlsx")


MOSCOW = {"vri_region": "msk", "_cadastral_analysis": {"recognized": ["77:05:0004001:1"]}}


def test_moscow_values_land_with_their_origin() -> None:
    got = _apply(_parsed(), dict(MOSCOW))
    inputs, origin = got["inputs"], got["inputs"]["_field_origin"]
    assert inputs["land_rights_cost_mln"] == pytest.approx(14985.285)
    assert origin["inputs.land_rights_cost_mln"]["text"] == \
        "ГлавАПУ, выгрузка от 06.10.2026, лист «ТЭП», строка 44"
    assert origin["inputs.site_area_ha"]["text"].endswith("строка 1")
    assert origin["tep.apartments.gns"]["row"] == "строка 7.1"
    assert got["tep"]["apartments"]["gns"] == pytest.approx(215721)
    assert "выгрузка от 06.10.2026" in got["status"]


def test_a_manual_value_stays_manual_on_a_new_export_of_the_same_site() -> None:
    """Новая версия выгрузки того же участка: вписанное руками не тронуто и
    названо; остальное подставлено с происхождением."""
    parsed = _parsed()
    got = _apply(parsed, dict(MOSCOW), before=parsed,
                 manual={"inputs.land_rights_cost_mln": 5000.0, "tep.apartments.saleable": 120000.0})
    inputs = got["inputs"]
    assert inputs["land_rights_cost_mln"] == 5000.0
    assert inputs["_field_origin"]["inputs.land_rights_cost_mln"]["source"] == "manual"
    assert got["tep"]["apartments"]["saleable"] == 120000.0
    assert inputs["social_compensation_mln"] == pytest.approx(0.0)
    assert inputs["_field_origin"]["inputs.social_compensation_mln"]["source"] == "glavapu"
    assert "Оставлено вписанное вручную" in got["status"] and "плата за смену ВРИ" in got["status"]


def test_a_new_site_clears_the_old_manual_values() -> None:
    """Контрпример: другой участок — ручное прежней площадки не переезжает."""
    parsed = _parsed()
    other = json.loads(json.dumps(parsed))
    other["normalized"]["cadastral_quarter"] = "77:01:0001001"
    got = _apply(parsed, dict(MOSCOW), before=other, manual={"inputs.land_rights_cost_mln": 5000.0})
    assert got["inputs"]["land_rights_cost_mln"] == pytest.approx(14985.285)
    assert got["inputs"]["_field_origin"]["inputs.land_rights_cost_mln"]["source"] == "glavapu"


@pytest.mark.parametrize("extra", [
    {"vri_region": "mo"},
    {"vri_region": "msk", "_cadastral_analysis": {"recognized": ["50:12:0100101:5"]}},
])
def test_outside_moscow_the_calculator_takes_no_part(extra) -> None:
    """Подмосковье: ни подстановки, ни справки — выгрузка не сохраняется."""
    got = _apply(_parsed(), dict(extra))
    inputs = got["inputs"]
    assert inputs.get("land_rights_cost_mln") == core.DEFAULT_INPUTS.get("land_rights_cost_mln")
    assert "_glavapu_import" not in inputs and not inputs.get("_field_origin")
    assert not any("glavapu" in key for key in inputs if key.startswith("_"))
    assert got["tep"]["apartments"]["gns"] == core.TEP_DEFAULT["apartments"]["gns"]
    assert "не участвует" in got["status"] and "не сохранена" in got["status"]


def test_the_region_is_ours_not_the_file_name() -> None:
    """Имя файла «Подмосковье» московскому проекту регион не меняет."""
    parsed = core.parse_glavapu_xlsx(_dated(XLSX.read_bytes(), datetime(2026, 10, 6)),
                                     "Подмосковье_50.xlsx")
    got = _apply(parsed, dict(MOSCOW))
    assert "_glavapu_import" in got["inputs"]
    assert got["inputs"]["land_rights_cost_mln"] == pytest.approx(14985.285)


def test_the_origin_is_shown_at_the_field() -> None:
    page = core.PAGE
    assert "fieldOriginNote('inputs.'+id)" in page
    note = page_blocks.run_json(
        "let inputs={_field_origin:{'inputs.x':{source:'glavapu',text:'ГлавАПУ, выгрузка от 06.10.2026, лист «ТЭП», строка 44'},"
        "'inputs.y':{source:'manual',text:'вписано вручную'}}};",
        "console.log(JSON.stringify([fieldOriginNote('inputs.x'),fieldOriginNote('inputs.y'),fieldOriginNote('inputs.z')]))")
    assert "строка 44" in note[0] and note[1] == "" and note[2] == ""


@pytest.mark.parametrize("inputs, numbers", [
    ({"vri_region": "mo"}, ["77:05:0004001:1"]),
    ({}, ["50:12:0100101:5"]),
])
def test_the_scenario_check_refuses_outside_moscow(inputs, numbers, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DEVELOPAID_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    called: list = []
    monkeypatch.setattr(core, "_glavapu_headless_run", lambda *a, **k: called.append(a))
    req = core.GlavapuScenarioRequest(
        inputs=dict(inputs, site_area_ha=10.0, _cadastral_analysis={"recognized": numbers}),
        tep={"apartments": {"gns": 10000.0, "saleable": 7000.0, "units": 100}})
    answer = core.glavapu_scenario_check(req)
    assert answer["state"] == "refused" and "не участвует" in answer["error"]
    assert "регион проекта" in answer["where"] and not called
