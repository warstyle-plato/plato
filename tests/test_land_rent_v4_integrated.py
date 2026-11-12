"""Actual v4 export consumes one global lease schedule, not one per queue."""
import copy
import io
import re
import sys

import openpyxl
import pytest

import main_legacy as core
import v4_land_rent
from xlsx_eval import Evaluator


@pytest.fixture(scope="module")
def phased_lease():
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(project_start="2027-01-01",ird_months=12,land_right="lease",
        land_rent_mode="manual",land_rent_cadastral_mln=100,
        land_rent_regime_start="2027-01-01",land_rent_tail_rule="repeat_last",
        land_rent_rates=[{"year":1,"rate_pct":1.5},{"year":2,"rate_pct":3}],
        land_rent_vat_treatment="public_exempt",offices_enabled=True,
        offices_gba_sqm=20000,offices_saleable_sqm=14000,
        offices_start="2030-01-01",offices_months=36)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    phasing = {"enabled":True,"phase_count":2,"phase_gap_months":12,"cost_inflation_pct":20,
        "phases":[{"name":"Поздняя","start_offset_months":12,"construction_months":24},
                  {"name":"Ранняя","start_offset_months":0,"construction_months":24}],
        "products":{key:[50,50] for key in ("apartments","ground_commercial","underground_parking","storage")}}
    bundle = core._run_authoritative_model(inputs,tep,[],phasing)
    hints = core._v4_finance_hints(bundle)
    content, _, meta = core.build_project_workbook(inputs,tep,[],phasing,
        project_name="Synthetic phased lease",finance_hints=hints,cache_values=False)
    assert not meta["missing"], meta["missing"]
    workbook = openpyxl.load_workbook(io.BytesIO(content),data_only=False)
    sys.setrecursionlimit(400000)
    return bundle, hints, workbook, Evaluator(workbook), meta


def test_actual_export_splits_common_lease_among_leased_queues_once(phased_lease):
    bundle,hints,workbook,ev,meta = phased_lease
    canonical = bundle["consolidated"]["land_rent"]
    own = [p["cash_total"] for p in canonical["phase_land"]]
    assert hints["land_rent_phase_shares"] == pytest.approx([v/sum(own) for v in own])
    for k,phase in enumerate(bundle["phases"]):
        assert ev.cell("CAPEX",f"B{145+k}")*1e6 == pytest.approx(own[k],abs=0.01)
        assert own[k] == pytest.approx(phase["result"]["capex"]["land_rent"])
    assert sum(own) == pytest.approx(canonical["known_total"])
    assert ev.cell(v4_land_rent.SHEET,"B19")*1e6 == pytest.approx(canonical["known_total"],abs=0.01)
    assert meta["land_rent"]["complete"] == canonical["complete"]
    assert meta["land_rent"]["cash_total"] == canonical["cash_total"]
    assert meta["land_rent"]["financial_missing_codes"] == canonical["financial_missing_codes"]
    assert meta["land_rent"]["workbook_supported"]
    # The old bridge-limit reference row must never be repurposed as rent.
    assert "база лимита БРИДЖа" in workbook["CAPEX"]["A39"].value
    import v4_dashboard
    labels = [label for label,_ in v4_dashboard.STRUCTURE_ITEMS]
    rent_row = v4_dashboard.STRUCTURE_FIRST_ROW + labels.index("Аренда земельного участка")
    assert ev.cell(v4_dashboard.DATA_SHEET,f"B{rent_row}")*1e6 == pytest.approx(canonical["known_total"],abs=0.01)


def test_export_preserves_dates_and_excludes_public_rent_from_vat(phased_lease):
    bundle,_,workbook,ev,_ = phased_lease
    canonical = bundle["consolidated"]["land_rent"]
    for month in ("2027-01-01","2029-01-01","2030-06-01"):
        year,number = (int(p) for p in month.split("-")[:2])
        offset = (year-2027)*12+number-1
        col = openpyxl.utils.get_column_letter(4+offset)
        for k,own in enumerate(canonical["phase_monthly"]):
            assert ev.cell("CAPEX",f"{col}{145+k}")*1e6 == pytest.approx(own.get(month,0),abs=0.01)
    assert "SUM('CAPEX'!$B$146)" in workbook["CF_2"]["D21"].value
    assert ev.cell("ПРОВЕРКИ","B86") == pytest.approx(bundle["consolidated"]["finance"]["vat"]/1e6,abs=0.05)


def test_land_relations_heading_groups_separate_vri_and_rent_without_another_expense(phased_lease):
    import v4_dashboard
    _,_,workbook,ev,_ = phased_lease
    dashboard = workbook[v4_dashboard.DASHBOARD_SHEET]
    headings = {cell.value:cell.row for row in dashboard for cell in row
                if cell.data_type != "f" and isinstance(cell.value,str)}
    assert v4_land_rent.BLOCK_TITLE in headings
    assert headings[v4_land_rent.BLOCK_TITLE] < headings["Прочие расходы проекта"]
    assert [label for label,_ in v4_dashboard.LAND_STRUCTURE_ITEMS] == [
        "Смена ВРИ / земельные права", "Проценты по рассрочке ВРИ", "Аренда земельного участка"]
    labels = [label for label,_ in v4_dashboard.STRUCTURE_ITEMS]
    assert v4_land_rent.BLOCK_TITLE not in labels  # heading is never another monetary row
    assert workbook[v4_land_rent.SHEET]["A1"].value == v4_land_rent.BLOCK_TITLE
    assert "годовой расчёт" in workbook[v4_land_rent.SHEET]["A2"].value
    for label,formula in v4_dashboard.LAND_STRUCTURE_ITEMS:
        row = v4_dashboard.STRUCTURE_FIRST_ROW + labels.index(label)
        assert workbook[v4_dashboard.DATA_SHEET][f"B{row}"].value == "="+formula
    first,last = v4_dashboard.STRUCTURE_FIRST_ROW,v4_dashboard.STRUCTURE_TOTAL_ROW-1
    assert ev.cell(v4_dashboard.DATA_SHEET,f"B{last+1}") == pytest.approx(sum(
        ev.cell(v4_dashboard.DATA_SHEET,f"B{row}") for row in range(first,last+1)))


def test_editing_only_object_months_changes_rent_without_moving_housing_rve(phased_lease):
    _,_,source,initial,_ = phased_lease
    workbook = copy.deepcopy(source)
    def editable(technical):
        formula = workbook["Параметры модели"][technical].value
        match = re.fullmatch(r"='Вводные'!(\$?[A-Z]+\$?\d+)",formula)
        assert match, (technical,formula)
        return workbook["Вводные"][match.group(1).replace("$","")]
    before = initial.cell(v4_land_rent.SHEET,"B19")
    housing_rve = initial.cell("CF_2","B8")
    editable("K28").value = 48
    changed = Evaluator(workbook)
    # Only the queue commissioned last holds its land until the objects finish.
    late = max(_queue_rows(workbook), key=lambda r: initial.cell(v4_land_rent.SHEET,f"C{r}"))
    last = initial.cell(v4_land_rent.SHEET,f"B{late}")
    assert changed.cell(v4_land_rent.SHEET,"B19")-before == pytest.approx(3.0*last,abs=0.000001)
    assert changed.cell("CF_2","B8") == housing_rve
    editable("K20").value = "Нет"
    disabled = Evaluator(workbook)
    assert disabled.cell(v4_land_rent.SHEET,"B19") < before


def _queue_rows(workbook):
    sheet = workbook[v4_land_rent.SHEET]
    return [r for r in range(1,sheet.max_row+1) if str(sheet[f"A{r}"].value or "").startswith("Очередь ")
            and ":" not in str(sheet[f"A{r}"].value)]


def test_queue_commissioning_and_share_stay_editable_in_the_book(phased_lease):
    _,_,source,initial,_ = phased_lease
    workbook = copy.deepcopy(source)
    sheet = workbook[v4_land_rent.SHEET]
    rows = _queue_rows(workbook)
    assert len(rows) == 2
    before = [initial.cell("CAPEX",f"B{145+k}") for k in range(2)]
    # A larger share of the early queue moves rent from the late one to it.
    sheet[f"B{rows[0]}"], sheet[f"B{rows[1]}"] = 0.25, 0.75
    moved = Evaluator(workbook)
    assert moved.cell("CAPEX","B145") < before[0] and moved.cell("CAPEX","B146") > before[1]
    sheet[f"B{rows[1]}"] = 0.5  # shares no longer sum to one: not a silent result
    assert Evaluator(workbook).cell(v4_land_rent.SHEET,"I20") == "Не полны"


def test_unsupported_historical_export_preserves_canonical_status_and_reports_limit():
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(land_right="lease",land_rent_mode="manual",land_rent_cadastral_mln=100,
                  land_rent_regime_start="2027-01-01",land_rent_rates=[{"year":1,"rate_pct":3}],
                  land_rent_tail_rule="repeat_last")
    bundle = core._run_authoritative_model(inputs,copy.deepcopy(core.TEP_DEFAULT),[],{})
    modified = core._v4_finance_hints(bundle)
    modified["land_rent"]["historical"] = {"mode":"aggregate_unclassified","cut":"2028-01-01"}
    modified["land_rent"]["financial_complete"] = True
    _,_,meta = core.build_project_workbook(inputs,copy.deepcopy(core.TEP_DEFAULT),[],{},
        project_name="Synthetic unsupported historical scope",finance_hints=modified,cache_values=False)
    assert meta["preliminary"]
    assert not meta["land_rent"]["workbook_supported"]
    assert meta["land_rent"]["financial_complete"]  # canonical observation retained, not rewritten
    assert "исторический импорт не поддержан" in meta["land_rent"]["workbook_error"]
    assert any("Аренда ЗУ" in str(message) for message in meta["missing"])


@pytest.mark.parametrize("supported",[False,True])
def test_http_export_rejects_unsupported_writer_but_allows_supported_preliminary_model(monkeypatch,supported):
    monkeypatch.setattr(core,"require_calc_access",lambda *args,**kwargs:None)
    monkeypatch.setattr(core,"build_project_workbook",lambda *args,**kwargs:(b"synthetic","book.xlsx",{
        "missing":[],"preliminary":True,"land_rent":{"workbook_supported":supported,
        "workbook_reason":"исторический импорт аренды вне календаря книги",
        "workbook_error":"исторический импорт аренды вне календаря книги"}}))
    request = core.WorkbookExportRequest(inputs={},tep={})
    if not supported:
        with pytest.raises(core.HTTPException) as raised:
            core.report_workbook(request)
        assert raised.value.status_code == 422
        assert "вне календаря" in raised.value.detail
    else:
        response = core.report_workbook(request)
        assert response.status_code == 200
        assert response.body == b"synthetic"


def test_book_queue_share_follows_its_metres_and_rent_only_exit_date(phased_lease):
    bundle,_,workbook,ev,_ = phased_lease
    canonical = bundle["consolidated"]["land_rent"]
    ws = workbook[v4_land_rent.SHEET]
    head = next(r for r in range(1, ws.max_row+1)
                if ws[f"A{r}"].value == "Очередь" and ws[f"B{r}"].value == "Доля участка")
    first = head + 1
    assert canonical["phase_share_basis"] == "total_area"
    assert ws[f"H{head}"].value == "Общая площадь объектов очереди, м²"
    for k, p in enumerate(canonical["phase_land"]):
        assert ws[f"H{first+k}"].value == pytest.approx(p["total_area"])
        assert ev.cell(v4_land_rent.SHEET, f"B{first+k}") == pytest.approx(p["share"])
        assert ev.cell(v4_land_rent.SHEET, f"D{first+k}") == pytest.approx(v4_land_rent._serial(p["rve"]))
    assert ev.cell(v4_land_rent.SHEET, "B15") == pytest.approx(v4_land_rent._serial(canonical["rve"]))
    saved = [ws[f"H{first}"].value, ws[f"I{first}"].value]
    try:
        # Равные метры — равные доли; ручная дата выхода — только у этой очереди.
        ws[f"H{first}"] = ws[f"H{first+1}"].value
        ws[f"I{first}"] = v4_land_rent._serial("2027-06-01")
        fresh = Evaluator(workbook)
        assert fresh.cell(v4_land_rent.SHEET, f"B{first}") == pytest.approx(0.5)
        assert fresh.cell(v4_land_rent.SHEET, f"D{first}") == pytest.approx(v4_land_rent._serial("2027-06-01"))
        assert fresh.cell(v4_land_rent.SHEET, f"C{first}") == pytest.approx(ev.cell(v4_land_rent.SHEET, f"C{first}"))
        assert fresh.cell(v4_land_rent.SHEET, f"D{first+1}") == pytest.approx(ev.cell(v4_land_rent.SHEET, f"D{first+1}"))
    finally:
        ws[f"H{first}"], ws[f"I{first}"] = saved
    # Ручная дата последней очереди раньше общей границы: «Расчёт до» (B15)
    # идёт за фактическими датами выхода, как rve движка, а не за границей.
    n = len(canonical["phase_land"])
    exits = [ev.cell(v4_land_rent.SHEET, f"D{first+k}") for k in range(n)]
    last = max(range(n), key=lambda k: exits[k])
    early = exits[last] - 100
    saved = ws[f"I{first+last}"].value
    try:
        ws[f"I{first+last}"] = early
        fresh = Evaluator(workbook)
        expected = max([early] + [exits[k] for k in range(n) if k != last])
        assert fresh.cell(v4_land_rent.SHEET, "B15") == pytest.approx(expected)
        assert expected < exits[last]
    finally:
        ws[f"I{first+last}"] = saved
