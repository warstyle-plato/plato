from __future__ import annotations

from datetime import date

import pytest

import main_legacy as core
import normatives_registry as registry


def test_scheme2_contract_split_uses_f_plus_half_f2_for_step_coverage() -> None:
    parts = core.pf_escrow_rate_components(100.0, 80.0, 50.0)
    assert parts["f"] == pytest.approx(40.0)
    assert parts["f2"] == pytest.approx(40.0)
    assert parts["coverage"] == pytest.approx(0.60)
    assert parts["iv2_principal"] == pytest.approx(40.0)
    assert parts["iv_principal"] == pytest.approx(40.0)
    assert parts["base_principal"] == pytest.approx(20.0)


def test_scheme2_zero_share_is_exact_old_method() -> None:
    parts = core.pf_escrow_rate_components(100.0, 80.0, 0.0)
    assert parts["coverage"] == pytest.approx(0.80)
    assert parts["iv2_principal"] == 0
    assert parts["iv_principal"] == pytest.approx(80.0)
    assert parts["base_principal"] == pytest.approx(20.0)


def test_ncl_interest_payment_is_deferred_then_quarterly() -> None:
    rve = date(2029, 6, 1)
    mode = "defer_then_quarterly"
    stop = "2028-12-31"

    assert not core.pf_interest_payment_due(
        date(2028, 11, 1), rve, mode, stop, 100, 10)
    assert core.pf_interest_payment_due(
        date(2028, 12, 1), rve, mode, stop, 100, 10)
    assert not core.pf_interest_payment_due(
        date(2029, 1, 1), rve, mode, stop, 100, 10)
    assert core.pf_interest_payment_due(
        date(2029, 3, 1), rve, mode, stop, 100, 10)


def test_earlier_escrow_close_beats_contract_stop_date() -> None:
    rve = date(2028, 9, 1)
    assert core.pf_interest_payment_due(
        date(2028, 9, 1), rve, "defer_then_quarterly", "2028-12-31", 100, 10)


def test_945_registry_source_is_the_2118_amendment_not_2025_pdf() -> None:
    rows = {row["id"]: row for row in registry._load_registry()}
    item = rows["moscow-945-pp"]
    assert "414735575" in item["source_url"]
    assert "2118-ПП" in item["source_label"]
    assert "945-ppS1092025.pdf" not in item["source_url"]
