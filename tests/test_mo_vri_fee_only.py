"""Настоящие денежные функции и DTO/маршрут без запуска приложения и провайдеров."""
from __future__ import annotations

import ast
import copy
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import time
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
import pytest

import project_regions

ROOT = Path(__file__).resolve().parent.parent


class Routes:
    def __init__(self):
        self.registered = {}

    def post(self, path):
        def register(function):
            self.registered[path] = function
            return function
        return register


def put(namespace, path, names):
    tree = ast.parse((ROOT / path).read_text())
    found = {node.name: node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for name in names:
        assert name in found, (path, name)
        exec(compile(ast.Module([found[name]], type_ignores=[]), str(ROOT / path), "exec"), namespace)


def money_namespace():
    ns = {"__name__": __name__, "Any": Any, "re": re, "BaseModel": BaseModel,
          "HTTPException": HTTPException, "project_regions": project_regions, "app": Routes(),
          "copy": copy, "math": math}
    put(ns, "engine/nspd.py", ["_land_float"])
    put(ns, "engine/inputs.py", ["project_region"])
    put(ns, "engine/norms.py", ["n"])
    put(ns, "engine/vri_payment.py", ["vri_relief_basis", "vri_relief"])
    put(ns, "engine/mo_calc.py", ["mo_vri_compensation", "mo_vri_applied_details", "mo_vri_payment", "normalize_mo_vri_region",
                                 "MoVriCompensationRequest", "mo_vri_compensation_preview"])
    ns["require_calc_access"] = lambda *args, **kwargs: None
    return ns


@pytest.fixture
def money():
    return money_namespace()


def request(money, gross=100_000_000, compensation=10_000_000, **inputs):
    return money["MoVriCompensationRequest"](
        payment_before_compensation_rub=gross, compensation_rub=compensation,
        inputs={"vri_region": "mo", "land_rights_cost_mln": 777, **inputs},
        tep={"apartments": {"saleable": 8000, "transfer": 2000}},
        session="fictional-session", access_key="fictional-owner-key")


@pytest.mark.parametrize("gross,compensation,expected", [
    (100_000_000, 10_000_000, 90_000_000), (100, 100, 1), (100, 1000, 1),
    (0, 100, 0), (0.5, 100, 0.5), (1, 100, 1), (1234567.89, None, 1234567.89),
])
def test_fee_only_route_has_the_same_deduction_and_preserves_exact_manual_money(money, gross, compensation, expected):
    req = request(money, gross, compensation)
    before = req.model_dump()
    vri = money["mo_vri_compensation_preview"](req)["vri"]
    assert vri["payment_before_compensation_rub"] == gross
    assert vri["payment_used_rub"] == expected
    assert vri["payment_used_mln"] * 1e6 == pytest.approx(expected, abs=0.000001)
    assert req.model_dump() == before, "предпросмотр не сохраняет проект и не меняет ТЭП"
    assert money["app"].registered["/mo/vri-compensation"] is money["mo_vri_compensation_preview"]


def test_compensation_and_transfer_offset_are_separate_and_the_engine_consumer_matches(money):
    req = request(money, vri_transfer_offset_mln=30)
    vri = money["mo_vri_compensation_preview"](req)["vri"]
    assert vri["payment_used_rub"] == 90_000_000
    assert vri["transfer_offset_requested_rub"] == vri["transfer_offset_applied_rub"] == 30_000_000
    assert vri["payment_after_reliefs_rub"] == 60_000_000
    applied = dict(req.inputs, land_rights_cost_mln=vri["payment_used_mln"])
    _, real_payable = money["vri_relief"](applied, applied["land_rights_cost_mln"] * 1e6, req.tep)
    assert real_payable == vri["payment_after_reliefs_rub"], "зачёт не вшивается второй раз в исходную плату"
    assert req.tep["apartments"] == {"saleable": 8000, "transfer": 2000}


def test_existing_mo_territory_calculation_uses_the_same_monetary_helper(money):
    calls = []
    actual = money["mo_vri_compensation"]
    def record(gross, compensation):
        calls.append((gross, compensation))
        return actual(gross, compensation)
    money["mo_vri_compensation"] = record
    result = money["mo_vri_payment"]([], upks_target=8000, upks_average_oks=100000,
                                     apartments_sqm=9000, market_price_rub_per_sqm=200000,
                                     kd=0.1, compensation_rub=50_000_000)
    assert calls == [(180_000_000, 50_000_000)]
    assert result["payment_used_rub"] == 130_000_000
    for key, value in actual(180_000_000, 50_000_000).items():
        if key != "warnings":
            assert result[key] == value


def test_offset_can_reduce_the_one_ruble_compensation_floor_to_zero(money):
    vri = money["mo_vri_compensation_preview"](request(money, 100, 100, vri_transfer_offset_mln=30))["vri"]
    assert vri["payment_used_rub"] == vri["transfer_offset_applied_rub"] == 1
    assert vri["payment_after_reliefs_rub"] == 0


def test_other_existing_manual_relief_is_visible_in_the_same_final_consumer(money):
    vri = money["mo_vri_compensation_preview"](request(
        money, vri_relief_mode="amount", vri_relief_mln=20, vri_transfer_offset_mln=30))["vri"]
    assert vri["other_relief_rub"] == 20_000_000
    assert vri["transfer_offset_applied_rub"] == 30_000_000
    assert vri["payment_after_reliefs_rub"] == 40_000_000


def test_access_guard_receives_the_real_session_key_and_project_before_any_math(money):
    calls = []
    def refuse(session, key, action, **kwargs):
        calls.append((session, key, kwargs))
        raise HTTPException(401, "fictional access refusal")
    money["require_calc_access"] = refuse
    money["mo_vri_compensation"] = lambda *args: pytest.fail("денежная функция вызвана после отказа")
    req = request(money)
    with pytest.raises(HTTPException) as failed:
        money["mo_vri_compensation_preview"](req)
    assert failed.value.status_code == 401
    assert calls == [("fictional-session", "fictional-owner-key", {"inputs": req.inputs})]


@pytest.mark.parametrize("gross,compensation", [(None, 10), (-1, 10), (float("nan"), 10),
                                              (float("inf"), 10), (10, -1), (10, float("nan"))])
def test_unknown_or_nonfinite_or_negative_inputs_do_not_become_zero(money, gross, compensation):
    with pytest.raises(HTTPException) as failed:
        money["mo_vri_compensation_preview"](request(money, gross, compensation))
    assert failed.value.status_code == 422


def test_other_region_and_boolean_money_are_rejected(money):
    with pytest.raises(HTTPException) as failed:
        money["mo_vri_compensation_preview"](request(money, vri_region="msk"))
    assert failed.value.status_code == 400
    with pytest.raises(ValidationError):
        request(money, True, 10)


def test_reopened_proof_keeps_gross_and_is_ignored_after_an_independent_money_change(money):
    vri = money["mo_vri_compensation_preview"](request(money))["vri"]
    saved = {"vri_region": "mo", "land_rights_cost_mln": 90, "mo_vri_compensation_mln": 10,
             "_mo_vri_relief": {"schema": 1, "vri": deepcopy(vri), "source": {"kind": "manual"}}}
    assert money["mo_vri_applied_details"](saved)["payment_before_compensation_rub"] == 100_000_000
    assert money["mo_vri_applied_details"](dict(saved, land_rights_cost_mln=80)) == {}
    assert money["mo_vri_applied_details"](dict(saved, mo_vri_compensation_mln=20)) == {}
    assert money["mo_vri_applied_details"](dict(saved, land_rights_cost_mln=float("nan"))) == {}
    fresh = money["mo_vri_compensation_preview"](request(money, 100_000_000, 10_000_000))["vri"]
    assert fresh["payment_used_rub"] == 90_000_000


def test_legacy_mo_applied_source_stays_available_for_the_workbook(money):
    legacy = {"vri_region": "mo", "land_rights_cost_mln": 100,
              "_mo_calc": {"vri": {"compensation_applied_rub": 1_250_500_000, "payment_used_mln": 100}}}
    assert money["mo_vri_applied_details"](legacy)["compensation_applied_rub"] == 1_250_500_000
    assert money["mo_vri_applied_details"](dict(legacy, land_rights_cost_mln=40)) == {}


def test_actual_project_save_and_open_preserve_the_original_base_and_applied_proof(money, tmp_path):
    # Файловый корень и карточка списка заменены; сам writer/reader проекта настоящий.
    money.update({"json": json, "datetime": datetime, "timezone": timezone, "time": time,
                  "hashlib": hashlib, "VERSION": "fictional", "_PROJECT_PAYLOAD_LIMIT": 4 * 1024 * 1024,
                  "_PROJECTS_LIMIT": 200, "_project_dir": lambda owner: tmp_path,
                  "_project_path": lambda owner, identity: tmp_path / (identity + ".json"),
                  "_project_card": lambda record: {"id": record["id"]}})
    put(money, "engine/bot_users.py", ["project_save", "project_open"])
    req = request(money, vri_transfer_offset_mln=30)
    vri = money["mo_vri_compensation_preview"](req)["vri"]
    inputs = dict(req.inputs, land_rights_cost_mln=vri["payment_used_mln"], mo_vri_compensation_mln=10,
                  _mo_vri_relief={"schema": 1, "vri": vri, "source": {"kind": "manual"}})
    payload = {"inputs": inputs, "tep": req.tep,
               "phasing": {"enabled": True, "phases": [{"id": "first", "share": 0.4}, {"id": "second", "share": 0.6}]}}
    money["project_save"](42, "Fictional МО", payload, project_id="f1c2d3e4a5b6")
    reopened = money["project_open"](42, "f1c2d3e4a5b6")["payload"]
    assert reopened == payload
    proof = money["mo_vri_applied_details"](reopened["inputs"])
    assert proof["payment_before_compensation_rub"] == 100_000_000
    assert proof["payment_used_rub"] == 90_000_000
    repeated = money["mo_vri_compensation_preview"](request(money, proof["payment_before_compensation_rub"], 10_000_000))["vri"]
    assert repeated["payment_used_rub"] == 90_000_000
