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
        "office": "DevelopAid_Office_Model_Beta.xlsx",
        "retail": "DevelopAid_Retail_Model_Beta.xlsx",
        "hotel": "DevelopAid_Hotel_Model_Beta.xlsx",
    }
    for asset, filename in expected.items():
        content, actual, meta = build_commercial_workbook(_req(asset))
        assert actual == filename
        assert content.startswith(b"PK")
        assert meta["uses_escrow"] is False


def test_workbook_has_separate_inputs_operating_cashflow_and_summary_sheets():
    content, _, _ = build_commercial_workbook(_req("office"))
    workbook_xml = _xml(content, "xl/workbook.xml")
    for sheet in ("Summary", "Inputs", "Operating", "Cash_Flow"):
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
    assert "DevelopAid_Office_Model_Beta.xlsx" in response.headers["content-disposition"]
