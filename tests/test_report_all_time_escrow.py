"""One presentation of the existing financing pair; no new cash calculation."""
from __future__ import annotations

import copy

import pytest

import developaid_management_report as report

LABEL = "Оплачено на эскроу всего"
END = "2026-11-26"


def _dto(paid=20_000_000, owed=30_000_000):
    return {"end": END, "kind": "week",
            "funding": {"state": "ok", "escrow_track": {
                "state": "ok", "paid_now": paid, "owed": owed, "data_month": "2026-11"}},
            "sales": {"uploaded": "2026-11-23T14:00:00+00:00"}}


def _built():
    value = report.build("Синтетический проект", "week", END)
    sums = {"period": 0, "month": 0, "total": 0, "by_month": {}}
    track = dict(_dto()["funding"]["escrow_track"], rows=[], bank_known=False, fm_known=False)
    value["funding"] = {"state": "ok", "rss": "2026-11-20",
        "draws": dict(sums), "draws_previous": 0, "interest": dict(sums),
        "limit": {"known": False, "reason": "Синтетический источник"},
        "escrow": {"state": "missing", "reason": "Синтетический источник"},
        "escrow_bank": {"state": "missing", "reason": "Синтетический источник"},
        "escrow_track": track}
    value["sales"]["uploaded"] = _dto()["sales"]["uploaded"]
    return value


def test_tile_reuses_one_pair_without_reading_sources_or_recalculating_sales(monkeypatch):
    value = _dto()
    value["funding"].update(escrow={"inflow_total": 999},
        escrow_bank={"current": {"actual": 888}})
    value["funding"]["escrow_track"].update(forecast=777, disclosure={"released": 666})
    value["sales"].update(all_time_escrow={"paid": 555, "expected": 444},
                         quarter={"fact": {"escrow": 333}})
    frozen = copy.deepcopy(value)
    monkeypatch.setattr(report.sales_store, "load", lambda *a, **k: pytest.fail("No source read"))
    monkeypatch.setattr(report.contracting, "owed_by_contracts", lambda *a, **k: pytest.fail("No cash recalculation"))
    tile = report._escrow_total_tile(value)
    assert tile["label"] == LABEL and tile["value"] == "20,0 млн ₽"
    assert "Ещё ожидается 30,0 млн ₽" in tile["note"]
    assert value == frozen


@pytest.mark.parametrize("key", ["paid_now", "owed"])
@pytest.mark.parametrize("invalid", [None, True, False, -1, float("nan"), float("inf"), "20"])
def test_unknown_or_invalid_amounts_do_not_become_zero_or_hide_the_other_amount(key, invalid):
    value = _dto()
    value["funding"]["escrow_track"][key] = invalid
    tile = report._escrow_total_tile(value)
    if key == "paid_now":
        assert tile["value"] == "нет данных" and "Ещё ожидается 30,0 млн ₽" in tile["note"]
    else:
        assert tile["value"] == "20,0 млн ₽" and "Сколько ещё ожидается" in tile["note"]


def test_explicit_zero_is_displayed_and_missing_values_are_not_inferred():
    tile = report._escrow_total_tile(_dto(0, 0))
    assert tile["value"] == "0 ₽" and "Ещё ожидается 0 ₽" in tile["note"]
    value = _dto()
    value["funding"]["escrow_track"].pop("paid_now")
    assert report._escrow_total_tile(value)["value"] == "нет данных"


@pytest.mark.parametrize("month", [None, "", "0000-01", "2026-13", "2027-01"])
def test_unknown_or_future_month_does_not_mix_latest_owed_with_earlier_inflow(month):
    value = _dto()
    value["funding"]["escrow_track"]["data_month"] = month
    value["funding"]["escrow"] = {"state": "ok", "inflow_total": 7_000_000}
    tile = report._escrow_total_tile(value)
    assert tile["value"] == "нет данных" and "Сколько ещё ожидается" in tile["note"]
    assert "7,0 млн ₽" not in tile["note"]


@pytest.mark.parametrize("block", ["funding", "escrow_track"])
def test_missing_source_state_cannot_bless_stale_cached_numbers(block):
    value = _dto()
    target = value["funding"] if block == "funding" else value["funding"][block]
    target.update(state="missing", reason="Нет сохранённого расчёта")
    tile = report._escrow_total_tile(value)
    assert tile["value"] == "нет данных" and "Нет сохранённого расчёта" in tile["note"]


def test_source_month_and_upload_date_do_not_become_a_bank_business_date():
    tile = report._escrow_total_tile(_dto())
    assert "ноябрь 2026" in tile["note"]
    assert "Источник загружен 23.11.2026" in tile["note"]
    assert "Дата загрузки не является датой состояния банковских счетов" in tile["hint"]
    assert "не остаток банка после раскрытий" in tile["note"]
    assert "с учётом отражённых возвратов" in tile["note"]
    assert "Срез на 23.11.2026" not in tile["note"]


def test_later_upload_does_not_claim_a_historical_daily_snapshot():
    value = _dto()
    value["end"] = "2026-11-20"
    tile = report._escrow_total_tile(value)
    assert tile["value"] == "нет данных" and "исторический срез не подтверждён" in tile["note"]


def test_old_receipt_month_does_not_invent_missing_later_receipts():
    value = _dto()
    value["funding"]["escrow_track"]["data_month"] = "2026-10"
    tile = report._escrow_total_tile(value)
    assert tile["value"] == "20,0 млн ₽" and "октябрь 2026" in tile["note"]
    assert "не учтены" not in tile["note"]


def test_upload_date_uses_moscow_calendar_and_missing_date_does_not_invent_one():
    value = _dto()
    value["sales"]["uploaded"] = "2026-11-23T22:30:00Z"
    assert "Источник загружен 24.11.2026" in report._escrow_total_tile(value)["note"]
    value["sales"].pop("uploaded")
    tile = report._escrow_total_tile(value)
    assert tile["value"] == "20,0 млн ₽" and "Дата загрузки источника не указана" in tile["note"]


def test_week_month_and_all_consumers_share_the_same_ready_pair():
    value = _built()
    before = copy.deepcopy(value)
    tile = report._escrow_total_tile(value)
    shown = next(t for t in report.tiles(value) if t["label"] == LABEL)
    assert shown == tile
    for consumer in (report.render_html(value), report.render_text(value)):
        assert LABEL in consumer and tile["value"] in consumer
        assert "Ещё ожидается 30,0 млн ₽" in consumer
        assert "Источник загружен 23.11.2026" in consumer
    value["kind"] = "month"
    assert report._escrow_total_tile(value) == tile
    value["kind"] = "week"
    assert value == before
