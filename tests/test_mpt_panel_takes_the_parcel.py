"""Блок «Льгота МПТ» берёт кадастр, район и ТТК из участка проекта.

Замечание владельца 07.10.2026: кадастр в блоке приходилось вбивать руками,
хотя участок в проекте уже введён («как у ГлавАПУ»). Ручной ввод нужен только
когда ТЭП собран без адреса.

Проверяется настоящий код: `projectParcelFacts` — со страницы (`PAGE`),
`parcelPlan` — из вставки блока МПТ (`_MPT_FRAGMENT`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import page_blocks  # noqa: E402
from mpt_extension import _MPT_FRAGMENT  # noqa: E402

DISTRICTS = ["Раменки", "Нагатино-Садовники", "Басманный"]


def _analysis(district: str = "Нагатино-Садовники", inside: bool = False,
              known: bool | None = True, number: str = "77:05:0002004:12") -> dict:
    territory = {"district": district, "cadastral_quarter": number.rsplit(":", 1)[0],
                 "inside_ttc": inside, "inside_moscow": True}
    if known is not None:
        territory["inside_ttc_known"] = known
    return {"requested": [number], "recognized": [number], "territory": territory}


def plan(steps: list[dict]) -> list[dict]:
    """Прогоняет шаги: участок проекта, правки человека, повторная подстановка.

    Каждый шаг: {"analysis": … | None, "edit": {key: value}}.
    """
    prelude = (
        "let inputs={}; let cadastralAnalysis=null;\n"
        + page_blocks.function("projectParcelFacts") + "\n"
    )
    tail = (
        f"const steps={json.dumps(steps, ensure_ascii=False)};\n"
        f"const districts={json.dumps(DISTRICTS, ensure_ascii=False)};\n"
        "let current={cadastral:'',district:'',ttk:''}, origin={cadastral:'',district:'',ttk:''};\n"
        "const out=[];\n"
        "for(const step of steps){\n"
        "  if('analysis' in step) inputs={_cadastral_analysis:step.analysis};\n"
        "  for(const [key,value] of Object.entries(step.edit||{})){current[key]=value;origin[key]=value?'manual':'';}\n"
        "  const got=parcelPlan(projectParcelFacts(),current,origin,districts);\n"
        "  out.push(JSON.parse(JSON.stringify(got))); current={...got.values}; origin={...got.origin};\n"
        "}\n"
        "console.log(JSON.stringify(out));"
    )
    out, _taken = page_blocks.run(prelude, tail, page=_MPT_FRAGMENT)
    return json.loads(out)


def test_the_parcel_in_the_project_fills_the_block() -> None:
    got = plan([{"analysis": _analysis()}])[0]
    assert got["values"] == {"cadastral": "77:05:0002004:12",
                             "district": "Нагатино-Садовники", "ttk": "outside"}
    assert got["origin"] == {"cadastral": "parcel", "district": "parcel", "ttk": "parcel"}
    assert "77:05:0002004:12" in got["note"]


def test_a_manual_edit_survives_the_next_fill_and_the_rest_follows_the_parcel() -> None:
    first, second = plan([
        {"analysis": _analysis()},
        {"analysis": _analysis(district="Раменки", inside=True, number="77:07:0012002:1"),
         "edit": {"district": "Басманный"}},
    ])
    assert first["values"]["district"] == "Нагатино-Садовники"
    # Ручной район остаётся ручным, неручные поля переходят на новый участок.
    assert second["values"]["district"] == "Басманный"
    assert second["origin"]["district"] == "manual"
    assert second["values"]["cadastral"] == "77:07:0012002:1"
    assert second["values"]["ttk"] == "inside"


def test_without_a_parcel_the_fields_stay_empty_and_say_why() -> None:
    got = plan([{"analysis": None}])[0]
    assert got["values"] == {"cadastral": "", "district": "", "ttk": ""}
    assert "не введён" in got["note"] and "вручную" in got["note"]


def test_a_missing_ttk_sign_is_not_read_as_outside() -> None:
    """Сохранённый анализ без признака ГлавАПУ: inside_ttc=false — это молчание.

    Прочитай поле как «вне ТТК», и блок присвоил бы статус участку, о котором
    ничего не известно.
    """
    got = plan([{"analysis": _analysis(known=None)}])[0]
    assert got["values"]["ttk"] == ""
    assert "ТТК" in got["note"]


def test_an_unknown_district_name_is_named_not_guessed() -> None:
    got = plan([{"analysis": _analysis(district="поселение Неизвестное")}])[0]
    assert got["values"]["district"] == ""
    assert "Неизвестное" in got["note"]


def test_a_district_with_the_word_rayon_is_matched() -> None:
    got = plan([{"analysis": _analysis(district="район Раменки")}])[0]
    assert got["values"]["district"] == "Раменки"


def test_the_panel_marks_where_each_value_came_from() -> None:
    for marker in ('id="mpt-cadastral-origin"', 'id="mpt-district-origin"',
                   'id="mpt-ttk-origin"', 'id="mpt-parcel-note"',
                   "'из участка '", "'введено вручную'"):
        assert marker in _MPT_FRAGMENT, marker
