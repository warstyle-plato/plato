"""Погашение кредитов считается из уже загруженного — без ручных файлов.

Владелец, 27.10.2026: «Откуда я возьму эти файлы и данные? Они все есть или в
НКЛ, или в РСС, или в модели». Здесь закреплено:

- проект «Кутузов Сити» в Мониторе сам находит условия своих НКЛ;
- выдачи и долг — из реестра платежей РСС (платежи из заёмных средств),
  выдача ложится на первую НКЛ в пределах её лимита на дату, остаток — дальше;
- проценты и плата за лимит до даты РСС досчитаны от первой выдачи;
- эскроу — поступило по графикам договоров отчёта о продажах, дальше — тот же
  прогноз, что «Эскроу по кварталам» сводки: раскрытие одно (дата ввода и сумма
  «к вводу» совпадают с таблицей эскроу);
- прогнозные выдачи — план остатка ПФ финмодели сверх выбранного;
- ручной набор — поправка поверх найденного, с подписью;
- чего нет — названо: что и где не нашлось; «загрузите данные» не пишется.

Данные вымышленные. Запуск:
python3 -m pytest tests/test_credit_repayment_from_loaded_data.py -q
"""
from __future__ import annotations

import datetime
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_credit_repayment as credit  # noqa: E402
import developaid_credit_sources as sources  # noqa: E402
import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
from market_search import sales_store  # noqa: E402
from test_management_report_model import _contract, _rss_book  # noqa: E402

M = credit.M
PROJECT = "Кутузов Сити"
SALES = "ЖК Кутузов"
RSS_DAY = "2026-10-18"
# Выдачи: в 2025 лимит НКЛ 2025 — 2 600, в 2026 — 5 000; НКЛ 2026 открыта с 26.06.2026.
DRAWS = [(datetime.date(2025, 5, 10), 1000 * M), (datetime.date(2025, 12, 10), 1500 * M),
         (datetime.date(2026, 3, 10), 1000 * M), (datetime.date(2026, 8, 10), 1800 * M)]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _months(first: str, last: str) -> list[str]:
    out, year, month = [], int(first[:4]), int(first[5:7])
    while f"{year}-{month:02d}" <= last:
        out.append(f"{year}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def _rss() -> bytes:
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(_rss_book(DRAWS + [(datetime.date(2026, 9, 1), 7 * M,
                                                         "3.1")])))
    paid = book["Реестр платежей"]
    for r in range(10, paid.max_row + 1):
        if paid.cell(row=r, column=10).value is not None:
            own = paid.cell(row=r, column=7).value == "3.1"
            paid.cell(row=r, column=11, value="Собственные средства" if own
                      else "Заемные средства")
    blob = io.BytesIO()
    book.save(blob)
    return blob.getvalue()


# Поступило по договорам — по месяц выгрузки; остаток цены — рассрочка до ввода.
SCHEDULE = {m: 40 * M for m in _months("2025-06", "2026-10")}


def _sales(credit_plan: bool = True) -> None:
    row = _contract("2025-06-10", "Квартира", 1000.0, 2500 * M)
    row["contract"] = "ДДУ-1"
    row["escrow_schedule"] = [{"month": m, "amount": v} for m, v in SCHEDULE.items()]
    parts = {"contracting": {"project": SALES, "missing": [], "rows": [row]}}
    if credit_plan:
        months = _months("2025-05", "2029-12")
        pf = {m: min(6400 * M, 1000 * M + 200 * M * i) for i, m in enumerate(months)}
        escrow = {m: 60 * M * (i + 1) for i, m in enumerate(months)}
        parts["credit"] = {"sheet": "КРЕДИТЫ", "queues": [{
            "queue": "Кутузов", "escrow": escrow, "pf": pf, "coverage": {},
            "rate": {m: 0.2 for m in months}, "drawn_from": "2025-05", "repay_from": "2027-09"}]}
    sales_store.save(sales_store.default_dir(), SALES, parts, "test.xlsx")


def _project(credit_plan: bool = True) -> None:
    monitor.store_estimate(PROJECT, _rss(), RSS_DAY)
    _sales(credit_plan)
    report.link_sales(PROJECT, SALES, "проверка")


def _run(**extra):
    return credit.for_project(PROJECT, SALES, end="2026-10-20", commissioning={
        "date": "2027-09-15", "source": "прогноз Монитора"}, **extra)


def test_the_project_finds_its_loan_terms_by_explicit_binding():
    assert sources.preset_for(PROJECT) == "kutuzov_city"
    assert sources.preset_for("Другой проект") is None
    got = credit.for_project("Другой проект")
    assert got["state"] == "missing"
    assert got["reason"].startswith("Условия кредитов проекта «Другой проект» в системе не "
                                    "заведены")


def test_debt_draws_and_interest_come_from_the_rss_and_the_terms():
    _project()
    got = _run()
    assert got["state"] == "ok"
    base = got["base"]
    loans = {loan["id"]: loan for loan in base["loans"]}
    # 1000 + 1500 + 1000 на НКЛ 2025, август: 1500 до лимита 5 000, остаток 300 — на НКЛ 2026.
    assert loans["nkl2025"]["debt_now"] == pytest.approx(5000 * M)
    assert loans["nkl2026"]["debt_now"] == pytest.approx(300 * M)
    assert base["top"]["debt_now"]["value"] == pytest.approx(5300 * M)
    assert "реестр платежей РСС от 18.10.2026" in base["top"]["debt_now"]["inputs"][0]
    # Отложенные проценты за полтора года — досчитаны, а не ноль и не «нет данных».
    data = {d["name"]: d for d in base["datasets"]}
    assert data["deferred.nkl2025"]["source"] == "досчитано от первой выдачи по условиям договора"
    assert any("РСС не называет, с какого кредита шла выдача" in note
               for note in base["assumptions"])
    # Прогнозные выдачи: сроки — план ПФ финмодели сверх выбранного (до 6 400 в
    # сумме), недостающее до лимита — в конец доступности (владелец, 27.10.2026:
    # «будущие выборки до РНВ = лимит»): всего 6 610,689 − 5 300 выбранных.
    plan = credit.inputs_for(PROJECT, SALES, end="2026-10-20")["datasets"]
    drawn = sum(d["amount"] for name in ("plan.nkl2025", "plan.nkl2026")
                for d in plan[name]["data"]["draws"])
    assert drawn == pytest.approx((5485.689 + 1125 - 5300) * M)
    assert plan["plan.nkl2026"]["data"]["draws"][-1] == {
        "date": "2027-09-30", "amount": pytest.approx(210.689 * M)}
    assert any("доводят долг до лимита" in note and "НКЛ 2026 — 210,7 млн ₽ на 30.09.2027"
               in note for note in base["assumptions"])


def test_escrow_comes_from_contract_schedules_and_one_forecast_with_the_report():
    _project()
    base = _run()["base"]
    on_rss = sum(v for m, v in SCHEDULE.items() if m <= RSS_DAY[:7])
    assert base["top"]["escrow_now"]["value"] == pytest.approx(on_rss)
    # Раскрытие одно на сводку: та же дата, что утверждённый ввод, и та же сумма,
    # что прогноз «к вводу» в «Эскроу по кварталам» (рассрочка + темп продаж).
    approved = {"date": "2027-09-15", "source": "утверждённый срок"}
    escrow = report._escrow(SALES, None, approved, None)
    told = escrow["queues"][0]["at_commissioning"]["keeping_escrow"]
    disclosed = [e for e in base["escrow"]["events"] if e["kind"] == "disclosure"]
    assert [e["date"] for e in disclosed] == ["2027-09-15"]
    assert disclosed[0]["amount"] == pytest.approx(told)
    first = base["rows"][0]
    assert first["date"] == "2027-09-15"
    # В строке раскрытия доступна вся сумма раскрытия (до неё погашений нет).
    assert first["disclosed_available"] == pytest.approx(told)
    # Рассрочка подписанных договоров не теряется: без новых продаж (только
    # подтверждённое) на эскроу к вводу — накоплено плюс остаток по договорам.
    pace = escrow["queues"][0]
    assert pace["owed"] > 0
    assert told == pytest.approx(pace["paid_now"] + pace["owed"]
                                 + pace["sales_pace"] * 11)


def test_a_manual_set_is_a_correction_over_what_was_found():
    _project()
    credit.save(PROJECT, [{"name": "key_rate", "as_of": "2026-10-20", "source": "письмо банка",
                           "data": {"path": [{"from": "2025-01-01", "rate": 21.0}]}}],
                "проверка")
    base = _run()["base"]
    shown = {d["name"]: d for d in base["datasets"]}
    assert shown["key_rate"]["source"] == "поправка вручную: письмо банка"


def test_what_is_not_in_the_system_is_named_with_its_place():
    _project(credit_plan=False)
    got = _run()
    text = " ".join(got["base"]["gaps"])
    assert "нет финмодели (лист «КРЕДИТЫ»)" in text
    assert "загрузите" not in text.lower() and "не загружены" not in text
    # Без связи с отчётом о продажах — названо, где выбрать отчёт.
    bare = credit.for_project(PROJECT, "", end="2026-10-20")
    assert any("проект не связан с отчётом о продажах" in g for g in bare["base"]["gaps"])


def test_the_report_block_reads_the_loaded_data():
    _project()
    built = report.build(PROJECT, "week", "2026-10-18")
    block = built["credit"]
    assert block["state"] == "ok"
    page = report.render_html(built)
    assert "Данные по кредитам не загружены" not in page
    assert "Текущий совокупный долг" in page


def test_the_model_rate_kind_is_decided_by_the_escrow_coverage():
    months = _months("2026-01", "2026-12")
    flat = {m: 21.0 for m in months}
    cover = {m: 0.1 * i for i, m in enumerate(months)}
    assert sources.rate_kind(flat, cover) == "base"
    # Ставка падает вслед за покрытием — это уже льготная (итоговая) ставка.
    falling = {m: 21.0 - 1.5 * i for i, m in enumerate(months)}
    assert sources.rate_kind(falling, cover) == "effective"
    # Ставка движется вслед за ключевой, а не за покрытием, — базовая.
    path = {m: 21.0 + (1 if i % 2 else -1) for i, m in enumerate(months)}
    assert sources.rate_kind(path, cover) == "base"


def test_every_missing_value_is_a_visible_assumption_with_its_effect():
    _project()
    got = _run()
    page = credit.render_html(got)
    block = page[page.index("credit-assumptions"):]
    block = block[:block.index("</div>")]
    assert "принята базовой" in block and "проценты здесь занижены" in block
    assert "при отсутствии дофинансирования и свободных денег" in block
    assert "Аккредитивы не учтены" in block and "оценены сверху" in block
    assert "сначала по НКЛ 2025 в пределах её лимита" in block
    assert "Раскрытие эскроу принято в дату ввода 15.09.2027" in block
    # Это допущения, а не пробелы: в «Не нашлось» их нет.
    assert not any("аккредитив" in g for g in got["base"]["gaps"])


def test_an_effective_model_rate_is_used_as_is():
    _project()
    kept = sales_store.load(sales_store.default_dir(), SALES)
    parts = {k: v["data"] for k, v in kept["sources"].items()}
    queue = parts["credit"]["queues"][0]
    months = sorted(queue["pf"])
    queue["coverage"] = {m: 0.05 * i for i, m in enumerate(months)}
    queue["rate"] = {m: max(0.02, 0.2 - 0.004 * i) for i, m in enumerate(months)}
    sales_store.save(sales_store.default_dir(), SALES, parts, "test.xlsx")
    base = _run()["base"]
    assert {loan["terms"]["rate"]["value"] for loan in base["loans"]} == {"model"}
    page = credit.render_html({**_run(), "base": base})
    assert "это уже итоговая ставка со скидкой" in page


def test_the_report_discloses_at_the_approved_date_as_the_escrow_table(monkeypatch):
    """Сводка: раскрытие в разделе кредитов — утверждённый ввод, как у таблицы эскроу;
    прогноз Монитора позже — строкой допущений, а не датой раскрытия."""
    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {
        "funding": {"known": False, "reason": "нет"},
        "schedule": {"approved_finish": "2027-09-15", "forecast_finish": "2028-12-15"}}})
    built = report.build(PROJECT, "week", "2026-10-18")
    at = built["funding"]["escrow"]["queues"][0]["at_commissioning"]
    assert (at["date"], at["source"]) == ("2027-09-15", "утверждённый срок")
    base = built["credit"]["base"]
    disclosed = [e for e in base["escrow"]["events"] if e["kind"] == "disclosure"]
    assert [(e["date"], round(e["amount"])) for e in disclosed] == [
        ("2027-09-15", round(at["keeping_escrow"]))]
    assert any("ввод может сдвинуться на 15.12.2028" in note for note in base["assumptions"])
