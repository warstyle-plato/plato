"""Район участка и ТТК — один владелец на паркинг и льготу за МПТ.

Прежде было два читателя. Норма приобъектной парковки читала
`_glavapu_import.territory`, которую страница не сохраняет, и подпись К2
«пусто — по району из разбора кадастра» в живом проекте не сбывалась.
Льготы ВРИ читали разбор, ставили вписанное ниже документа и принимали
молчание ГлавАПУ о кольце за «за ТТК». Решение владельца (10.10.2026):
вписанное главнее, противоречие с разбором видно красным.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "DEVELOPAID_WORKBOOK_CACHE",
             "NORMATIVES_WATCH", "NAGATINO_EGRN_READ"):
    os.environ.setdefault(_key, "0")

import site_position as sp  # noqa: E402
import vri_benefits as vb  # noqa: E402

INSIDE = {"recognized": ["77:01:0001001:1"],
          "territory": {"district": "Хамовники", "inside_ttc": True,
                        "inside_ttc_known": True, "cadastral_quarter": "77:01:0001001"}}


@pytest.fixture(scope="module")
def core():
    import main as wrapper
    return wrapper.core


def _offices(core) -> tuple[dict, dict]:
    x = dict(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True)
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=10000, total_area=9400, saleable=6000)
    return x, t


# --------------------------------------------------------------- владелец --

def test_the_hand_wins_and_the_contradiction_is_named() -> None:
    got = sp.site_position({"_cadastral_analysis": copy.deepcopy(INSIDE),
                            "parking_inside_ttk": "outside"})
    assert got["inside_ttc"] is False and got["ttk_source"] == sp.MANUAL_SOURCE
    [conflict] = got["conflicts"]
    assert conflict["field"] == "parking_inside_ttk"
    assert conflict["manual"] == "за ТТК" and conflict["document"] == "внутри ТТК"
    assert "разбор кадастра" in conflict["text"] and "по вписанному" in conflict["text"]


def test_agreeing_hand_is_not_a_contradiction() -> None:
    got = sp.site_position({"_cadastral_analysis": copy.deepcopy(INSIDE),
                            "parking_inside_ttk": "inside", "parking_district": "район Хамовники"})
    assert got["inside_ttc"] is True and got["conflicts"] == []


def test_an_empty_field_reads_the_analysis() -> None:
    got = sp.site_position({"_cadastral_analysis": copy.deepcopy(INSIDE),
                            "parking_inside_ttk": ""})
    assert got["inside_ttc"] is True and got["ttk_source"] == sp.ANALYSIS_SOURCE
    assert got["district"] == "Хамовники" and got["district_source"] == "разбор кадастра"


def test_silence_about_the_ring_is_not_outside() -> None:
    """ГлавАПУ не ответил про кольцо: ключ `inside_ttc` стоит (False), но
    `inside_ttc_known` = False. Прежде льгота читала это как «за ТТК»."""
    analysis = copy.deepcopy(INSIDE)
    analysis["territory"].update(inside_ttc=False, inside_ttc_known=False)
    got = sp.site_position({"_cadastral_analysis": analysis})
    assert got["inside_ttc"] is None and got["ttk_source"] == ""
    place = vb.territory_of({"_cadastral_analysis": analysis})
    assert place["inside_ttc"] is None


def test_a_district_typed_by_hand_against_the_analysis_is_named() -> None:
    got = sp.site_position({"_cadastral_analysis": copy.deepcopy(INSIDE),
                            "parking_district": "Академический"})
    assert got["district"] == "Академический"
    assert [c["field"] for c in got["conflicts"]] == ["parking_district"]


# -------------------------------------------- оба читателя — один ответ --

def test_parking_takes_the_district_from_the_cadastral_analysis(core) -> None:
    """Подпись К2: «пусто — берётся по району участка из разбора кадастра».
    Прежде паркинг читал `_glavapu_import.territory`, которой страница не
    пишет, и брал верхний край."""
    x, t = _offices(core)
    blind = core.parking_demand(x, t)
    x["_cadastral_analysis"] = copy.deepcopy(INSIDE)
    got = core.parking_demand(x, t)
    assert got["k_basis"]["district"] == "Хамовники"
    assert got["k_basis"]["ttk_source"] == sp.ANALYSIS_SOURCE
    assert got["k_origin"]["k2"] == "table"
    assert got["required_total"] < blind["required_total"]


def test_parking_and_the_mpt_relief_read_the_same_site(core) -> None:
    x, t = _offices(core)
    x["_cadastral_analysis"] = copy.deepcopy(INSIDE)
    x["parking_inside_ttk"] = "outside"
    parking = core.parking_demand(x, t)["k_basis"]
    benefits = vb.compute(x, t, [{"key": "offices", "product": "offices", "label": "Офисы",
                                  "enabled": True}], today=date(2026, 10, 6))
    assert parking["inside_ttk"] is benefits["territory"]["inside_ttc"] is False
    assert parking["district"] == benefits["territory"]["district"] == "Хамовники"
    # Противоречие видно у обоих: под полем участка и над таблицей льгот.
    assert [c["field"] for c in parking["conflicts"]] == ["parking_inside_ttk"]
    assert benefits["conflicts"] == [parking["conflicts"][0]["text"]]


# ---------------------------------------------------------------- страница --

def test_the_page_draws_the_contradiction_in_red(core) -> None:
    import page_blocks

    x, t = _offices(core)
    x["_cadastral_analysis"] = copy.deepcopy(INSIDE)
    x["parking_inside_ttk"] = "outside"
    parking = core.parking_demand(x, t)
    benefits = vb.compute(x, t, [{"key": "offices", "product": "offices", "label": "Офисы",
                                  "enabled": True}], today=date(2026, 10, 6))
    prelude = ("let inputs={};let parking=%s;function projectParking(){return parking}"
               % json.dumps(parking, ensure_ascii=False))
    tail = ("console.log(JSON.stringify({"
            "conflicts:siteParkingConflicts('parking_inside_ttk'),"
            "other:siteParkingConflicts('parking_k2'),"
            "basis:siteParkingBasis('parking_inside_ttk'),"
            "card:vriBenefitsHtml(%s)}));" % json.dumps(benefits, ensure_ascii=False))
    out, _ = page_blocks.run(prelude, tail)
    got = json.loads(out)
    assert len(got["conflicts"]) == 1 and "«за ТТК»" in got["conflicts"][0]
    assert got["other"] == []
    assert "Сейчас в расчёте: за ТТК, источник — вписано в проекте" in got["basis"]
    card = got["card"]
    assert 'class="note vri-benefits-conflict"' in card and "#b3261e" in card
    assert card.index("vri-benefits-conflict") < card.index("<table")


def test_the_site_panel_offers_the_ttk_field(core) -> None:
    assert "parking_inside_ttk" in core.SITE_ONLY_INPUTS
    fields = {f[0]: f for _, group in core.FIELD_GROUPS for f in group}
    field = fields["parking_inside_ttk"]
    assert field[3] == "select"
    assert [value for value, _ in field[4]] == ["", "inside", "outside"]
