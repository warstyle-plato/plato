"""МО: плата за смену ВРИ уменьшается на сумму компенсации по соглашению (Ксу*).

Поправка № 1310-ПП вычитает Ксу* из платы в пп. 4.1 и 4.8: П = … − Ксу*.
Ксу* — денежная сумма, не множитель; плата не ниже 1 ₽ (п. 5.2). Берётся
сумма компенсации по соглашению целиком, банковская гарантия в сумме не
участвует (решение владельца 12.11.2026).

Сумма — вводная проекта: она едет в проект с расчётом, пересчёт ТЭП шлёт её
снова, а новый участок её сбрасывает. Стенды гоняют настоящие
`applyNormativeTep` и `resetTerritoryData`, ответ `/mo/calculate` берут у
самого сервера.

Запуск: python3 -m pytest tests/test_mo_vri_compensation.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from tests import page_blocks  # noqa: E402

PARCEL = [{"cadastral_number": "50:00:0000000:1", "area_sqm": 3000.0,
           "permitted_use": "Для индивидуального жилищного строительства",
           "cadastral_value_rub": 1_000_000.0}]


def _fee(**over):
    args = dict(upks_target=8000.0, upks_average_oks=100_000.0,
                apartments_sqm=9000.0, market_price_rub_per_sqm=200_000.0, kd=0.1)
    args.update(over)
    return core.mo_vri_payment(PARCEL, **args)


def test_the_compensation_is_subtracted_in_rubles_and_named():
    full = _fee()
    reduced = _fee(compensation_rub=50_000_000.0)
    gross = full["payment_used_rub"]
    assert reduced["payment_before_compensation_rub"] == pytest.approx(gross)
    assert reduced["payment_used_rub"] == pytest.approx(gross - 50_000_000.0)
    assert reduced["payment_used_mln"] == pytest.approx((gross - 50_000_000.0) / 1e6)
    assert reduced["compensation_rub"] == pytest.approx(50_000_000.0)
    assert reduced["compensation_applied_rub"] == pytest.approx(50_000_000.0)
    assert reduced["compensation_basis"], "у вычета нет происхождения"
    assert reduced["payment_basis"].endswith("за вычетом компенсации по соглашению")
    said = [w for w in reduced["warnings"] if "компенсации по соглашению" in w]
    assert len(said) == 1 and "1310-ПП" in said[0] and "вычтено 50,0 млн ₽" in said[0]
    assert "подтверждает только соглашение" in said[0]


def test_without_an_agreement_nothing_changes():
    for none in (None, 0.0, -5.0):
        vri = _fee(compensation_rub=none)
        assert vri["compensation_rub"] is None and vri["compensation_applied_rub"] is None
        assert vri["payment_used_rub"] == pytest.approx(_fee()["payment_used_rub"])
        assert vri["payment_used_mln"] == _fee()["payment_used_mln"]
        assert not any("компенсации по соглашению" in w for w in vri["warnings"])


def test_the_fee_does_not_go_below_one_ruble():
    gross = _fee()["payment_used_rub"]
    vri = _fee(compensation_rub=gross * 10)
    assert vri["payment_used_rub"] == pytest.approx(1.0)
    assert vri["compensation_applied_rub"] == pytest.approx(gross - 1.0)
    # Три знака дали бы 0,0 млн ₽, а ноль страница читает как «не рассчитана».
    assert vri["payment_used_mln"] > 0
    assert any("осталось 1 ₽" in w for w in vri["warnings"])


def test_a_compensation_without_a_fee_says_there_is_nothing_to_reduce():
    vri = _fee(kd=None, compensation_rub=50_000_000.0)
    assert vri["payment_used_rub"] is None and vri["compensation_applied_rub"] is None
    assert any("уменьшать нечего" in w for w in vri["warnings"])


@pytest.fixture(scope="module")
def server():
    from fastapi.testclient import TestClient
    import main_registry

    def ask(compensation_rub):
        answer = TestClient(main_registry.app).post("/mo/calculate", json={
            "query": "", "limit": 30, "site_area_ha": 6.6667, "density_sqm_per_ha": 30000,
            "district": "Мытищи", "market_price_rub_per_sqm": 0, "vri_kd": 0,
            "vri_compensation_rub": compensation_rub, "average_flat_sqm": 58.8,
        })
        assert answer.status_code == 200, answer.text
        return answer.json()
    return ask


def test_the_route_sends_the_reduced_fee_and_the_sum_into_the_project(server):
    full, reduced = server(0), server(50_000_000)
    assert reduced["inputs"]["land_rights_cost_mln"] == pytest.approx(
        full["inputs"]["land_rights_cost_mln"] - 50.0, abs=0.001)
    assert reduced["inputs"]["mo_vri_compensation_mln"] == pytest.approx(50.0)
    assert full["inputs"]["mo_vri_compensation_mln"] == 0


def _stand(server_answer, tail):
    prelude = "\n".join([
        "let inputs={site_area_ha:6.6667,vri_region:'mo',mo_vri_compensation_mln:50,"
        "land_rights_cost_mln:1,_mo_calc:{territory:{district:'Мытищи'}}};",
        "let tep=" + json.dumps(core.TEP_DEFAULT, ensure_ascii=False) + ";",
        "const SERVER=" + json.dumps(server_answer, ensure_ascii=False) + ";",
        "let cadastralAnalysis=null,moResult=null,glavapuImport=null;",
        "let bodies=[];",
        "async function fetch(url,opts){bodies.push(JSON.parse(opts.body));return {ok:true,json:async()=>SERVER}}",
        "const notes={};",
        "const document={getElementById(id){return notes[id]||(notes[id]={style:{},innerHTML:'',value:''})},"
        "activeElement:null};",
        "function renderTep(){}",
        "function renderInputs(){}",
        "function updateTepTotals(){}",
        "function renderPhasing(){}",
        "async function calculate(){}",
        "function syncTep(){}",
        "function escapeHtml(s){return String(s)}",
        "function num(v){return Number(v||0).toFixed(1)}",
        "function landNum(v,d){return Number(v||0).toFixed(d===undefined?1:d)}",
    ])
    out, taken = page_blocks.run(prelude, tail)
    return json.loads(out), taken


def test_the_tep_recalc_sends_the_sum_again_and_keeps_it(server):
    answer = server(50_000_000)
    shown, taken = _stand(answer, "\n".join([
        "(async()=>{",
        " await applyNormativeTep();",
        " console.log(JSON.stringify({sent:bodies.map(b=>b.vri_compensation_rub),",
        "  fee:inputs.land_rights_cost_mln,sum:inputs.mo_vri_compensation_mln}));",
        "})().catch(e=>{console.error(e);process.exit(1)});",
    ]))
    assert "applyNormativeTep" in taken
    assert shown["sent"] == [50_000_000], "пересчёт ТЭП потерял сумму компенсации"
    assert shown["fee"] == pytest.approx(answer["inputs"]["land_rights_cost_mln"])
    assert shown["sum"] == pytest.approx(50.0)


def test_the_calculation_sends_the_typed_sum(server):
    # Ошибку внутри своего try расчёт пишет в статус, а не бросает — стенд
    # такое имя сам не доберёт, поэтому константа берётся со страницы явно.
    shown, taken = _stand(server(50_000_000), "\n".join([
        page_blocks.page_const("AVERAGE_FLAT"),
        "notes.moArea={value:'6.6667'};notes.moCompensation={value:'50'};",
        "(async()=>{",
        " await calculateMo('');",
        " console.log(JSON.stringify({sent:bodies.map(b=>b.vri_compensation_rub),status:notes.cadastralStatus.innerHTML}));",
        "})().catch(e=>{console.error(e);process.exit(1)});",
    ]))
    assert "calculateMo" in taken
    assert shown["sent"] == [50_000_000], f"расчёт МО не отправил вписанную сумму: {shown}"


def test_a_zero_fee_does_not_become_one_ruble():
    vri = _fee(apartments_sqm=0.0, compensation_rub=5_000_000.0)
    assert vri["payment_used_rub"] == pytest.approx(0.0)
    assert vri["compensation_applied_rub"] is None
    assert not vri["payment_basis"].endswith("за вычетом компенсации по соглашению")
    assert any("уменьшать нечего" in w for w in vri["warnings"])
    assert not any("осталось 1 ₽" in w for w in vri["warnings"])


def test_a_fee_below_one_ruble_is_not_raised_to_it():
    vri = _fee(apartments_sqm=0.00004, compensation_rub=5_000_000.0)
    gross = vri["payment_before_compensation_rub"]
    assert 0 < gross < 1.0
    assert vri["payment_used_rub"] == pytest.approx(gross)
    assert vri["compensation_applied_rub"] is None


def test_the_block_shows_one_ruble_not_zero():
    shown, taken = page_blocks.run(
        "function landNum(v,d){return Number(v||0).toFixed(d===undefined?1:d)}",
        "console.log(JSON.stringify([moFeeText({payment_used_rub:1,payment_used_mln:0.000001}),"
        "moFeeText({payment_used_rub:12500000,payment_used_mln:12.5}),moFeeText({})]))")
    assert "moFeeText" in taken
    assert json.loads(shown) == ["1 ₽", "12.5 млн ₽", "—"]


def test_a_new_parcel_drops_the_agreement_and_says_so(server):
    shown, taken = _stand(server(0), "\n".join([
        "resetTerritoryData();",
        "console.log(JSON.stringify({sum:inputs.mo_vri_compensation_mln,cleared:territoryCleared,",
        " note:territoryClearedNote()}));",
    ]))
    assert "resetTerritoryData" in taken
    assert not shown["sum"], "соглашение прежнего участка перешло на новый"
    assert "mo_vri_compensation_mln" in shown["cleared"]
    assert "компенсация по соглашению" in shown["note"]


def test_the_page_field_reads_and_writes_the_project_value():
    shown, _ = page_blocks.run("\n".join([
        "let inputs={mo_vri_compensation_mln:12.5};",
        "const notes={moCompensation:{value:''}};",
        "const document={getElementById(id){return notes[id]||null}};",
    ]), "\n".join([
        "syncMoCompensation();",
        "const shownValue=notes.moCompensation.value;",
        "notes.moCompensation.value='';",
        "const empty=moCompensationRub();",
        "notes.moCompensation.value='7';",
        "console.log(JSON.stringify({shownValue,empty,typed:moCompensationRub()}));",
    ]))
    result = json.loads(shown)
    assert result == {"shownValue": "12.5", "empty": 0, "typed": 7_000_000}


@pytest.mark.parametrize("rubles", [1_234_567, 50_000_001, 1])
def test_a_server_result_keeps_the_exact_compensation_for_the_next_request(rubles):
    shown, taken = page_blocks.run(
        "let inputs={}; const fields={}; const document={getElementById(id){"
        "return fields[id]||(fields[id]={value:'',checked:false})}};",
        f"syncMoParams({{vri:{{compensation_rub:{rubles}}}}});"
        "console.log(JSON.stringify({next:moCompensationRub()}));")
    assert "syncMoParams" in taken and "moCompensationRub" in taken
    assert json.loads(shown)["next"] == pytest.approx(rubles, rel=0, abs=0.000001)


def _book_text(**over) -> str:
    import copy, html, io, re, zipfile
    x = dict(core.DEFAULT_INPUTS, vri_region="mo", land_rights_cost_mln=100.0, **over)
    content, _, _meta = core.build_project_workbook(
        x, copy.deepcopy(core.TEP_DEFAULT), [], None, project_name="Компенсация ВРИ")
    texts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as book:
        for name in book.namelist():
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                xml = book.read(name).decode("utf-8")
                texts.extend(html.unescape(a or b) for a, b in
                             re.findall(r"<x:t[^>]*>(.*?)</x:t>|<x:v>(.*?)</x:v>", xml, re.S))
    return " ".join(texts)


def test_the_book_names_the_deduction_only_when_there_is_one():
    named = "Плата уменьшена на сумму компенсации по соглашению с областью (1310-ПП, Ксу*)"
    calc = {"vri": {"compensation_applied_rub": 1_250_500_000.0, "payment_used_mln": 100.0}}
    with_sum = _book_text(mo_vri_compensation_mln=1300.0, _mo_calc=calc)
    assert named in with_sum and "вычтено 1 250,5 млн ₽, плата не ниже 1 ₽" in with_sum
    assert named not in _book_text()
    # Сумма вписана, но расчёт её не вычел (платы не было) — книга молчит.
    assert named not in _book_text(mo_vri_compensation_mln=1300.0,
                                   _mo_calc={"vri": {"compensation_applied_rub": None,
                                                     "payment_used_mln": 100.0}})
    # Плату в проекте переписали руками поверх расчёта — это уже не плата за вычетом.
    assert named not in _book_text(mo_vri_compensation_mln=1300.0,
                                   _mo_calc={"vri": dict(calc["vri"], payment_used_mln=40.0)})


# Решение владельца 13.11.2026 («А»): в Московской области компенсация по
# соглашению о Ксу* и зачёт переданных муниципалитету площадей вычитаются оба.
# Ксу* уже срезан в плате из расчёта по области (не ниже 1 ₽), зачёт метров
# вычитается после и может довести плату до нуля; если вписаны оба, расчёт
# предупреждает о двойном счёте одних и тех же метров.
MO_OFFSET = {"vri_region": "mo", "vri_transfer_offset_mln": 300.0}


def test_the_offset_still_counts_next_to_the_agreement():
    relief, net = core.vri_relief(dict(MO_OFFSET, mo_vri_compensation_mln=50.0), 1000e6)
    assert relief == pytest.approx(300e6) and net == pytest.approx(700e6), \
        "метры отданы, а зачёт за них пропал"
    # Зачёт больше оставшейся после Ксу* платы доводит её до нуля, а не ниже.
    relief, net = core.vri_relief(dict(MO_OFFSET, mo_vri_compensation_mln=50.0), 1.0)
    assert net == 0.0


def test_the_warning_needs_both_fields_in_the_region():
    assert core.vri_offset_with_compensation(dict(MO_OFFSET, mo_vri_compensation_mln=50.0))
    assert not core.vri_offset_with_compensation(MO_OFFSET)
    for empty in (0.0, None, ""):
        assert not core.vri_offset_with_compensation(dict(MO_OFFSET, mo_vri_compensation_mln=empty))
        assert not core.vri_offset_with_compensation(
            {"vri_region": "mo", "mo_vri_compensation_mln": 50.0, "vri_transfer_offset_mln": empty})
    assert not core.vri_offset_with_compensation(
        {"vri_region": "msk", "mo_vri_compensation_mln": 50.0, "vri_transfer_offset_mln": 300.0})


def _result(extra: dict, tep: dict | None = None) -> dict:
    import copy
    x = {**core.DEFAULT_INPUTS, "vri_required": True, "land_rights_cost_mln": 1000.0, **extra}
    return core.calculate(core.CalcRequest(inputs=x, tep=copy.deepcopy(tep or core.TEP_DEFAULT)))


def test_the_given_metres_leave_sales_and_keep_their_offset():
    import copy
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["apartments"]["transfer"] = 2000
    both = _result(dict(MO_OFFSET, mo_vri_compensation_mln=50.0), tep)
    offset = _result(MO_OFFSET, tep)
    none = _result({"vri_region": "mo"}, tep)
    assert both["summary"]["revenue"] == pytest.approx(none["summary"]["revenue"])
    assert both["vri"]["totals"]["relief"] == pytest.approx(300e6)
    assert both["summary"]["net_profit"] == pytest.approx(offset["summary"]["net_profit"])
    assert both["vri"]["totals"]["offset_with_compensation"] is True
    assert core.VRI_OFFSET_WITH_COMPENSATION in both["vri"]["warnings"]
    assert offset["vri"]["totals"]["offset_with_compensation"] is False
    assert core.VRI_OFFSET_WITH_COMPENSATION not in offset["vri"]["warnings"]


def test_the_offset_field_warns_about_counting_twice():
    shown, taken = page_blocks.run("\n".join([
        "let inputs={};",
        "let lastResult={vri:{totals:{offset_with_compensation:true}}};",
    ]), "\n".join([
        "const both=classFieldUnitText('vri_transfer_offset_mln','млн ₽');",
        "lastResult={vri:{totals:{offset_with_compensation:false}}};",
        "console.log(JSON.stringify({both,alone:classFieldUnitText('vri_transfer_offset_mln','млн ₽')}));",
    ]))
    result = json.loads(shown)
    assert "classFieldUnitText" in taken
    assert result["both"].startswith("млн ₽. Вычитается вместе с компенсацией") and "Ксу*" in result["both"]
    assert "не применяется" not in result["both"].lower()
    assert result["alone"] == "млн ₽"


def test_the_book_says_the_offset_is_counted_with_the_agreement():
    note = "Вычтен вместе с компенсацией по соглашению о Ксу*"
    assert note in _book_text(vri_transfer_offset_mln=300.0, mo_vri_compensation_mln=50.0)
    assert note not in _book_text(vri_transfer_offset_mln=300.0)


def test_the_phased_result_also_warns_once():
    import copy
    x = {**core.DEFAULT_INPUTS, "vri_required": True, "land_rights_cost_mln": 1000.0,
         **MO_OFFSET, "mo_vri_compensation_mln": 50.0}
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT),
        phasing={"enabled": True, "phase_count": 2,
                 "phases": [{"name": "О1", "start_offset_months": 0},
                            {"name": "О2", "start_offset_months": 12}]}))
    vri = bundle["consolidated"]["vri"]
    assert vri["totals"]["offset_with_compensation"] is True
    assert vri["warnings"].count(core.VRI_OFFSET_WITH_COMPENSATION) == 1
