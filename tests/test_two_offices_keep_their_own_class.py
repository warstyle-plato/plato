"""Класс офиса — в блоке каждого офиса, а не в шапке; «Строительство» — вкладками.

Владелец, 10.11.2026 (разбор «два офисника и ТЦ»):

  — «класс должен в нежилье выбираться в блоке каждого конкретного объекта, а
    не наверху». Шапка нежилого проекта больше не выбирает класс офиса: она
    называет только профиль пары (машино-место, подземная ставка). Класс —
    поле офиса `{prefix}_office_class`, у каждого своё;
  — «Блок „Строительство“ должен быть с такими же вкладками, как блоки
    объектов, если их несколько». Ставка здания на карточке — выбранного
    вкладкой объекта (`{prefix}_cost_th_per_sqm`), и вкладки те же словами,
    что у блоков объектов.

Третье утверждение — главное для книги: в нежилой книге (`office_workbook`)
класс КАЖДОГО офиса — своя вводная-клетка, а числа идут за ней формулой
`IF(ручное; ручное; INDEX(шкала; MATCH(класс)))`. Значит два офиса с разными
классами и/или разной себестоимостью живут в книге без единого харда, и
«ПРОВЕРКИ» сходятся с движком.

Запуск: python3 -m pytest tests/test_two_offices_keep_their_own_class.py -q
"""

from __future__ import annotations

import copy
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import page_blocks  # noqa: E402
import developaid_nonres_strategy as ns  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18623


def _two_offices(**over) -> tuple[dict, dict]:
    """Два офисника и ТЦ: у офисов разные классы и разная себестоимость."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x.update(project_kind=core.PROJECT_KIND_NONRESIDENTIAL,
             offices_enabled=True, offices_gba_sqm=20000.0, offices_saleable_sqm=14000.0,
             offices_office_class="B", offices_cost_th_per_sqm=120.0,
             offices2_enabled=True, offices2_gba_sqm=12000.0, offices2_saleable_sqm=8000.0,
             offices2_office_class="A+", offices2_cost_th_per_sqm=240.0,
             retail_enabled=True, retail_gba_sqm=8000.0, retail_saleable_sqm=5000.0,
             retail_cost_th_per_sqm=90.0,
             object_instances=["offices2"])
    x.update(over)
    for obj in core.STANDALONE_OBJECTS:
        if not x.get(obj.enabled_key):
            continue
        gba = float(x.get(f"{obj.prefix}_gba_sqm") or 0)
        if gba <= 0:
            continue
        saleable = float(x.get(f"{obj.prefix}_saleable_sqm") or 0)
        t.setdefault(obj.key, {}).update(gns=gba, total_area=round(gba * 0.94, 2),
                                         useful=saleable, saleable=saleable)
    for key in core.MKD_PRODUCTS:
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            if key in t:
                t[key][col] = 0
    return x, t


# --- движок: один ответ на «какой класс у офиса» --------------------------------

def test_the_header_does_not_choose_the_office_class_in_a_nonres_project() -> None:
    """Шапка нежилого проекта не задаёт класс офиса: без поля офиса — ступень.

    Класс проекта `business` в нежилом прежде давал B+ всем офисам. Теперь офис
    без своего класса получает ступень по умолчанию, а `business` двигает
    только профиль пары (машино-место, подземная ставка).
    """
    choice = ns.office_class_choice(
        {"project_kind": core.PROJECT_KIND_NONRESIDENTIAL, "project_class": "business"}, "offices")
    assert choice["office_class"] == ns.DEFAULT_OFFICE_CLASS
    assert choice["source"] == ns.OFFICE_CLASS_DEFAULT_SOURCE


def test_each_office_answers_with_its_own_class() -> None:
    x, _ = _two_offices()
    assert ns.office_class_choice(x, "offices")["office_class"] == "B"
    assert ns.office_class_choice(x, "offices2")["office_class"] == "A+"
    assert ns.office_class_choice(x, "offices2")["source"] == ns.OFFICE_CLASS_CHOSEN


def test_the_class_of_an_office_goes_with_its_own_pair_profile() -> None:
    """A+ у второго офиса берёт профиль своей пары (элитный), а не профиль шапки.

    Своё число себестоимости человека сильнее класса: два офиса с разной
    себестоимостью считаются порознь, и второй офис не подхватывает число
    первого. Класс ставит цену, аренду и эксплуатацию, а себестоимость здания —
    своя вводная каждого офиса.
    """
    x, _ = _two_offices(project_class="comfort")
    core.apply_office_classes(x)
    assert x["offices_cost_th_per_sqm"] != x["offices2_cost_th_per_sqm"]
    # Класс у каждого свой — и его ступень видна в ставке капитализации.
    assert x["offices_exit_cap_pct"] != x["offices2_exit_cap_pct"]
    assert x["offices2_exit_cap_pct"] == pytest.approx(
        ns.OFFICE_CLASS_SCALE["A+"]["exit_cap_pct"])
    # Своё число ставки не сбивается классом: класса оба, а числа — свои.
    assert (x["offices_cost_th_per_sqm"], x["offices2_cost_th_per_sqm"]) == (120.0, 240.0)


def test_a_typed_cost_beats_the_class_and_is_kept() -> None:
    x, _ = _two_offices(offices2_cost_th_per_sqm=260.0)
    x["_class_manual"] = ["offices2_cost_th_per_sqm"]
    core.apply_office_classes(x)
    assert x["offices2_cost_th_per_sqm"] == 260.0


def test_a_legacy_project_class_moves_into_the_office_field() -> None:
    """Проект, сохранённый с `nonres_office_class`, открывается той же ступенью."""
    x, _ = _two_offices(offices_office_class="", offices2_office_class="", nonres_office_class="A")
    del x["offices_office_class"], x["offices2_office_class"]
    core.apply_office_classes(x)
    assert x["offices_office_class"] == "A" and x["offices2_office_class"] == "A"
    assert ns.office_class_choice(x, "offices2")["source"] == ns.OFFICE_CLASS_CHOSEN


# --- страница: шапка и вкладки «Строительства» -----------------------------------

PRELUDE = page_blocks.project_kind() + "\n" + page_blocks.object_roster() + "\n"
HEADER = r"""
const classDialogBox={textContent:''};
const document={getElementById:id=>id==='projectClassPreview'?classDialogBox:(id==='projectClassSelect'?null:null)};
const inputs=INPUT;
renderProjectClassPreview();
process.stdout.write(JSON.stringify({preview:classDialogBox.textContent,
  options:projectClassOptions(), value:projectClassSelectValue()}));
"""


def _header(state: dict) -> dict:
    prelude = PRELUDE + "const INPUT=" + json.dumps(state, ensure_ascii=False) + ";\n"
    # OFFICE_CLASS подставляет сборка страницы; стенду он нужен целиком.
    prelude += page_blocks.page_const("OFFICE_CLASS") + "\n"
    prelude += page_blocks.page_const("CLASS_REGION_BASES") + "\n"
    out, _ = page_blocks.run(prelude, HEADER)
    return json.loads(out)


def test_the_header_names_a_profile_not_an_office_class() -> None:
    got = _header({"project_kind": core.PROJECT_KIND_NONRESIDENTIAL, "project_class": "comfort",
                   "offices_enabled": True, "offices_gba_sqm": 10000})
    assert [v for v, _ in got["options"]] == ["profile:B", "profile:B+", "profile:A", "profile:A+", "custom"]
    assert got["value"] == "profile:B"
    # Подпись называет то, что класс проекта двигает в нежилом: м/м и подземную
    # ставку. «офисы класса …» стоит у офиса, в его блоке.
    assert "Офисы/ТЦ" in got["preview"] and "м/м" in got["preview"]
    assert "офисы класса" not in got["preview"]


# --- «Строительство» вкладками ----------------------------------------------------

STUB = r"""
const document={createElement:tag=>{const el={tagName:tag,dataset:{},children:[],style:{},
  appendChild(c){this.children.push(c)},querySelectorAll:()=>[]};return el},
  getElementById:()=>null};
const inputs=INPUT;
function renderInputs(){} function refreshGroupPeeks(){}
"""

BUILDING = STUB + r"""
const bar=nonresConstructionTabsBar();
const tabs=nonresConstructionTabs();
process.stdout.write(JSON.stringify({tabs:bar?Number(bar.dataset.buttons):0,
  objects:tabs?tabs.objects.map(o=>o.key):[], shown:(tabs||{}).shown||'',
  fields:nonresBuildingRateFields().map(f=>f[0])}));
"""


def _building(state: dict) -> dict:
    prelude = PRELUDE + "const INPUT=" + json.dumps(state, ensure_ascii=False) + ";\n"
    out, _ = page_blocks.run(prelude, BUILDING)
    return json.loads(out)


def test_construction_gets_tabs_when_objects_are_several() -> None:
    x, _ = _two_offices()
    got = _building(x)
    # Вкладка на каждый объект с СМР — словами и порядком реестра: ТЦ, офис,
    # второй офис. Строка ставит ставку выбранного объекта — по умолчанию
    # первой вкладки (ТЦ — первый объект реестра).
    assert got["tabs"] == 3, got
    assert got["objects"] == ["standalone_retail", "offices", "offices2"], got
    assert got["shown"] == "standalone_retail"
    assert got["fields"] == ["retail_cost_th_per_sqm"]


def test_the_second_office_rate_is_its_own_field() -> None:
    x, _ = _two_offices()
    prelude = PRELUDE + "const INPUT=" + json.dumps(x, ensure_ascii=False) + ";\n"
    # Объект вкладки «Строительства» — второй офис: его своё поле ставки.
    tail = STUB + ("CONSTRUCTION_TAB.construction='offices2';"
                   "process.stdout.write(JSON.stringify(nonresBuildingRateFields().map(f=>f[0])));")
    out, _ = page_blocks.run(prelude, tail)
    assert json.loads(out) == ["offices2_cost_th_per_sqm"]


def test_one_object_has_no_tabs() -> None:
    x, _ = _two_offices(object_instances=[], offices2_enabled=False, retail_enabled=False)
    got = _building(x)
    assert got["tabs"] == 0 and got["fields"] == ["offices_cost_th_per_sqm"]


# --- книга нежилого проекта: два офиса, своя себестоимость, своя формула ---------

openpyxl = pytest.importorskip("openpyxl")
import office_workbook as ow  # noqa: E402


def _book() -> tuple[bytes, dict]:
    x, t = _two_offices()
    content, filename, meta = core.build_project_workbook(x, t, [], {}, project_name="Два офиса")
    assert meta.get("nonres_book") is True, (filename, meta)
    return content, meta


@pytest.fixture(scope="module")
def book() -> tuple[bytes, dict]:
    return _book()


def _row(sheet, label: str) -> int:
    return next(r for r in range(1, sheet.max_row + 1)
                if str(sheet[f"A{r}"].value or "").startswith(label))


def test_the_book_has_a_class_cell_for_each_office(book) -> None:
    content, _meta = book
    sheet = openpyxl.load_workbook(io.BytesIO(content))[ow.INPUTS_SHEET]
    values = {str(sheet[f"{c}{_row(sheet, 'Класс офиса')}"].value)
               for c in ("B", "C", "D") if sheet[f"{c}{_row(sheet, 'Класс офиса')}"].value}
    assert values == {"B", "A+"}, values


def test_the_book_keeps_two_rates_of_construction(book) -> None:
    """Ставка стройки — своя клетка на каждый офис, и она читается формулой."""
    content, _meta = book
    sheet = openpyxl.load_workbook(io.BytesIO(content))[ow.INPUTS_SHEET]
    row = _row(sheet, "Стоимость стройки здания")
    rates = [sheet[f"{c}{row}"].value for c in ("B", "C", "D")]
    assert rates[0] != rates[1], rates


def test_the_book_agrees_with_the_engine_about_the_two_offices(book) -> None:
    content, meta = book
    assert meta["missing"] == [], meta["missing"]
    verdict, bad, _evaluator, _book = _evaluate(content)
    assert verdict == ow.PASSED and bad == [], bad
    # Смета по объектам: две строки здания — по одной на офис.
    capex = openpyxl.load_workbook(io.BytesIO(content))[ow.CAPEX_SHEET]
    labels = [str(capex[f"A{r}"].value or "") for r in range(1, capex.max_row + 1)]
    buildings = [label for label in labels if "здание" in label.lower()]
    assert len(buildings) >= 2, buildings


def _evaluate(content: bytes, tamper=None):
    book = openpyxl.load_workbook(io.BytesIO(content))
    if tamper:
        tamper(book)
    evaluator = ow.evaluate(book)
    verdict, bad = ow.verdict(evaluator)
    return verdict, bad, evaluator, book


def test_the_class_change_of_one_office_moves_only_that_office(book) -> None:
    """Смена класса второго офиса в книге меняет модель — иначе класс не читается."""
    content, _meta = book

    def other_class(workbook):
        ws = workbook[ow.INPUTS_SHEET]
        row = _row(ws, "Класс офиса")
        # Колонка D — третий объект; C — второй офис (порядок объектов книги).
        for column in ("C", "D", "E"):
            if ws[f"{column}{row}"].value == "A+":
                ws[f"{column}{row}"] = "B"
                return
        raise AssertionError("класса A+ нет в книге")

    verdict, bad, _evaluator, _book = _evaluate(content, other_class)
    assert verdict == ow.FAILED and bad, "смена класса не двигает модель"
