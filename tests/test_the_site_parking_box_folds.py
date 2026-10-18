"""«Паркинг и нормативы» свёрнуты под таблицей ТЭП, а заголовок говорит, что в расчёте.

Владелец (16.10.2026), к карточке «Участок и плотность»: «Может это свернуть?
Торчит как-то неуместно и не понятно почему именно тут». Блок свёрнут по
умолчанию; в заголовке — зачем он (число машино-мест нежилья) и что принял
расчёт: К1, К2, район — те же числа, что «авто:» в полях. Противоречие
вписанного с разбором кадастра видно в заголовке без раскрытия и раскрывает
блок само; закрытое человеком при том же противоречии остаётся закрытым.

Запуск: python3 -m pytest tests/test_the_site_parking_box_folds.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import page_blocks  # noqa: E402
import main_legacy as core  # noqa: E402


def test_the_box_is_folded_and_holds_the_fields() -> None:
    match = re.search(r'<details[^>]*id="siteParkingBox"[^>]*>(.*?)</details>', core.PAGE, re.S)
    assert match, "блока-складки у коэффициентов парковки нет"
    opening = match.group(0)[:match.group(0).index(">") + 1]
    assert " open" not in opening, "складка раскрыта по умолчанию"
    assert 'id="siteParkingFields"' in match.group(1), "поля стоят вне складки"
    assert 'id="siteParkingSummary"' in match.group(1)


PRELUDE = """
function mk(tag){return {tag,children:[],style:{},dataset:{},innerHTML:'',textContent:'',value:'',
 placeholder:'',open:false,appendChild(c){this.children.push(c);return c},contains(){return false}};}
const box=mk('div'),sum=mk('summary'),det=mk('details');
const document={activeElement:null,createElement:mk,
 getElementById:id=>({siteParkingFields:box,siteParkingSummary:sum,siteParkingBox:det})[id]||null};
let phaseBundle=null;
let inputs={parking_k1:'',parking_rail_distance_m:'',parking_k2:'',parking_design_mode:'maximum'};
let lastResult={parking:{k1:1,k2:0.5,k_origin:{k1:'table',k2:'table'},
 k_basis:{district:'Нагатино-Садовники',district_source:'разбор кадастра'}}};
"""


def test_the_title_carries_what_the_calculation_took() -> None:
    tail = """
renderSiteParkingFields();
process.stdout.write(JSON.stringify({sum:sum.innerHTML,open:det.open,
 k2:box.children[2].children[0].placeholder}));
"""
    out = page_blocks.run_json(PRELUDE, tail)
    assert out["open"] is False, "без противоречия блок раскрылся сам"
    title = out["sum"]
    assert "Паркинг и нормативы" in title
    assert "машино-мест нежилья" in title
    assert "К1 1" in title and "К2 0,5" in title and "Нагатино-Садовники" in title
    # То же число, что «авто:» в поле, — один источник.
    assert "авто: 0,5" in out["k2"]
    assert "⚠" not in title


def test_a_conflict_is_seen_without_opening() -> None:
    tail = """
lastResult.parking.k_basis.conflicts=[{field:'parking_inside_ttk',text:'Вписано «внутри ТТК», кадастр — за ТТК'}];
renderSiteParkingFields();
const first={sum:sum.innerHTML,open:det.open};
det.open=false;                       // человек закрыл
renderSiteParkingFields();
const closed=det.open;
lastResult.parking.k_basis.conflicts.push({field:'parking_district',text:'Район вписан другой'});
renderSiteParkingFields();
process.stdout.write(JSON.stringify({first,closed,reopened:det.open,sum:sum.innerHTML}));
"""
    out = page_blocks.run_json(PRELUDE, tail)
    assert out["first"]["open"] is True, "противоречие спрятано в свёрнутом блоке"
    assert "⚠" in out["first"]["sum"] and "кадастр" in out["first"]["sum"]
    assert out["closed"] is False, "перерисовка отменила решение человека закрыть"
    assert out["reopened"] is True, "новое противоречие не раскрыло блок"
    assert "2 противоречия" in out["sum"]
