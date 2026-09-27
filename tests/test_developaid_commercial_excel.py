"""Commercial beta Excel books are independent from residential workbook."""

from __future__ import annotations

import io
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

import developaid_commercial as commercial
from developaid_commercial_excel import build_commercial_workbook


def _req(asset: str, strategy: str = "income", financing: str = "equity_debt"):
    return commercial.CommercialRequest(
        asset_type=asset,
        strategy=strategy,
        financing_mode=financing,
        inputs={},
    )


def _xml(content: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return archive.read(name).decode("utf-8")


def test_each_asset_gets_its_own_filename_and_no_escrow_model():
    expected = {
        "office": "DevelopAid_Office_Model_Beta_v2.xlsx",
        "retail": "DevelopAid_Retail_Model_Beta_v2.xlsx",
        "hotel": "DevelopAid_Hotel_Model_Beta_v2.xlsx",
    }
    for asset, filename in expected.items():
        content, actual, meta = build_commercial_workbook(_req(asset))
        assert actual == filename
        assert content.startswith(b"PK")
        assert meta["uses_escrow"] is False


def test_workbook_has_separate_inputs_operating_cashflow_and_summary_sheets():
    content, _, _ = build_commercial_workbook(_req("office"))
    workbook_xml = _xml(content, "xl/workbook.xml")
    for sheet in ("Summary", "Inputs", "Development", "Operating", "Sales", "Cash_Flow", "Financing", "Sensitivity", "Checks"):
        assert f'name="{sheet}"' in workbook_xml


def test_workbook_contains_live_formulas_not_just_engine_values():
    content, _, _ = build_commercial_workbook(_req("hotel"))
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        worksheets = "\n".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
    assert "IRR(" in worksheets
    assert "inp_adr_rub" in worksheets
    assert "op_noi_annual" in worksheets
    assert "model_financing" in worksheets


def test_equity_only_excel_still_contains_zero_debt_logic():
    content, _, _ = build_commercial_workbook(_req("retail", financing="equity"))
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        text = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if name.endswith(".xml")
        )
    assert 'model_financing="equity_debt"' in text
    assert "escrow" not in text.lower()


def test_web_endpoint_returns_xlsx_download():
    app = FastAPI()
    commercial.install(app)
    client = TestClient(app)
    response = client.post("/api/v2/commercial/export/xlsx", json={
        "asset_type": "office",
        "strategy": "income",
        "financing_mode": "equity_debt",
        "inputs": {"debt_share_pct": 50},
    })
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"PK")
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "DevelopAid_Office_Model_Beta_v2.xlsx" in response.headers["content-disposition"]


def test_development_sheet_has_formula_driven_s_curve():
    content, _, _ = build_commercial_workbook(_req("office"))
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        worksheets = "\n".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
    assert "inp_construction_months" in worksheets
    assert "Development" in _xml(content, "xl/workbook.xml")


def test_hotel_model_carries_management_fee_and_preopening():
    content, _, _ = build_commercial_workbook(_req("hotel"))
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        text = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if name.endswith(".xml")
        )
    assert "inp_management_fee_pct" in text
    assert "inp_preopening_cost_rub" in text
