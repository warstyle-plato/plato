"""РСС, утверждённый бюджет, дефицит общий и структурный — раздельно.

«Непонятно, почему ДДС-остаток 1,6 при дефиците потока 3,6… Нет структуры
интуитивно понятно — РСС такой, утверждённый бюджет такой-то. Остаток лимитов на
завершение по РСС такой-то, по утверждённому бюджету — такой-то. Дефицит такой-то
общий и такой-то структурный… потребность в доп финансировании нужно выделить по
сумме и сроку» (владелец, 29.08.2026).

Структурный дефицит — это когда общей суммы по РСС хватает, а лежит она на
статьях, куда потребность не относится: свободный лимит одной статьи не
закрывает дефицит другой. Движок это уже считал (`additional_financing`), но на
экране два разных числа из двух разных контуров стояли порознь без подписей и
читались как одно.

И гарантийные удержания: «в РСС банка сумма по договору берётся общая, но ГУ до
момента погашения ПФ не заплатятся — по сути это скрытый резерв».

Запуск: python3 -m pytest tests/test_the_monitor_shows_the_money_structure.py -q
"""

from __future__ import annotations

import datetime
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import developaid_monitor_retention as retention  # noqa: E402

PAGE = (ROOT / "developaid_monitor_page.py").read_text(encoding="utf-8")
DASH = (ROOT / "developaid_monitor_dashboard.py").read_text(encoding="utf-8")


def test_the_structure_names_both_contours_and_both_deficits() -> None:
    body = PAGE[PAGE.index("function fundingStructure("):]
    body = body[: body.index("\n}\n")]
    for line in ("Лимит РСС", "Остаток лимитов на завершение",
                 "Утверждённый бюджет глав 2–3",
                 "Остаток потребности по утверждённому бюджету",
                 "Дефицит общий", "Дефицит структурный",
                 "Потребность в дофинансировании"):
        assert line in body, f"в структуре нет строки «{line}»"
    # Срок — половина ответа: «нужно 3,6 млрд» и «нужно с марта» — разные новости.
    assert "additional_financing_from" in body
    # Структурный дефицит объяснён там же, где показан.
    assert "не покрывается по статьям" in body
    assert "это потребность, а не деньги" in body


def test_the_need_carries_the_month_it_starts() -> None:
    assert '"additional_financing_from": unfunded_from' in DASH
    assert '"additional_financing_from": waterfall["additional_financing_from"]' in DASH


def test_a_bigger_structural_deficit_is_explained_not_just_shown() -> None:
    """Денег хватает, а лежат не там — это повод к перераспределению."""
    body = PAGE[PAGE.index("function fundingStructure("):]
    assert "Структурный дефицит больше общего" in body


def _register(rows: list[dict]) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Незачтенный аванс "
    head = ["№ п/п", "Заказчик", "Контрагент", "Реквизиты договора",
            "Стоимость Договора ", "Размер ГУ, %", "Сумма ГУ",
            "Выплачено ГУ по состточнию на", "Остаток к выплате",
            "Дата выплаты ГУ", "Примечание", "Дата окончания работ"]
    for column, title in enumerate(head, start=1):
        sheet.cell(row=3, column=column, value=title)
    for index, row in enumerate(rows, start=4):
        for column, key in enumerate(
                ["n", "customer", "counterparty", "contract", "contract_amount",
                 "share", "amount", "paid", "left", "due", "note", "works_end"], start=1):
            sheet.cell(row=index, column=column, value=row.get(key))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_the_total_row_of_the_register_is_not_added_to_its_own_rows() -> None:
    """Итог, посчитанный вместе со строками, удваивает резерв."""
    data = _register([
        {"contract_amount": 100.0, "amount": 5.0, "paid": 0.0, "left": 5.0},
        {"counterparty": "Базис ООО", "contract": "382-ГРД", "contract_amount": 60.0,
         "share": 5, "amount": 3.0, "paid": 3.0, "left": 0.0, "due": "16.02.2026"},
        {"counterparty": "НУР ООО", "contract": "386-ГРД", "contract_amount": 40.0,
         "share": 5, "amount": 2.0, "paid": 0.0, "left": 2.0, "due": "30.09.2032"},
    ])
    got = retention.read_retention(data)
    assert len(got["rows"]) == 2, "итоговая строка попала в реестр"
    assert got["file_total"]["amount"] == 5.0

    summary = retention.summary(got, horizon="2027-12-31")
    assert summary["amount"] == 5.0 and summary["left"] == 2.0
    assert summary["contract_amount"] == 100.0
    # За горизонтом стройки — тот самый скрытый резерв.
    assert summary["deferred_after_horizon"] == 2.0


def test_a_second_payout_stage_does_not_double_the_contract() -> None:
    """Строка без контрагента, но со своим сроком, — продолжение договора."""
    data = _register([
        {"counterparty": "КЛОДО ООО", "contract": "412-ГРД", "contract_amount": 48.0,
         "share": 3, "amount": 0.7, "paid": 0.0, "left": 0.7, "due": "30.09.2027"},
        {"contract_amount": 48.0, "amount": 0.7, "paid": 0.0, "left": 0.7,
         "due": "30.09.2032"},
    ])
    got = retention.read_retention(data)
    assert len(got["rows"]) == 2
    assert got["rows"][1]["continued"] is True
    summary = retention.summary(got, horizon="2027-12-31")
    assert summary["contract_amount"] == 48.0, "стоимость договора сложена дважды"
    assert round(summary["left"], 2) == 1.4


def test_without_a_horizon_the_deferred_part_is_not_invented() -> None:
    """Без горизонта вопрос «что за ним» ответа не имеет — и это не ноль."""
    data = _register([
        {"counterparty": "НУР ООО", "contract": "386", "contract_amount": 40.0,
         "share": 5, "amount": 2.0, "paid": 0.0, "left": 2.0, "due": "30.09.2032"},
    ])
    summary = retention.summary(retention.read_retention(data))
    assert summary["deferred_after_horizon"] is None


def test_a_register_without_its_head_is_refused_by_name() -> None:
    from openpyxl import Workbook

    book = Workbook()
    book.active["A1"] = "просто таблица"
    buffer = io.BytesIO()
    book.save(buffer)
    with pytest.raises(retention.RetentionUnreadable) as failed:
        retention.read_retention(buffer.getvalue())
    assert "Сумма ГУ" in str(failed.value)


def test_our_sum_is_checked_against_the_file_total() -> None:
    """Строка, выпавшая из формулы реестра, иначе не видна никому."""
    # Числа настоящего порядка: допуск расхождения — рубль, и на копейках
    # проверять его бессмысленно.
    data = _register([
        {"contract_amount": 90_000_000.0, "amount": 4_000_000.0,
         "paid": 0.0, "left": 4_000_000.0},
        {"counterparty": "А", "contract": "1", "contract_amount": 50_000_000.0,
         "share": 5, "amount": 2_500_000.0, "paid": 0.0, "left": 2_500_000.0,
         "due": "30.09.2032"},
        {"counterparty": "Б", "contract": "2", "contract_amount": 40_000_000.0,
         "share": 5, "amount": 2_000_000.0, "paid": 0.0, "left": 2_000_000.0,
         "due": "30.09.2032"},
    ])
    summary = retention.summary(retention.read_retention(data), horizon="2027-12-31")
    bad = summary["file_total_mismatch"]
    assert "amount" in bad and round(bad["amount"]["delta"], 2) == 500_000.0
    assert "contract_amount" not in bad, "стоимость договоров сошлась — молчим"


def test_the_hidden_reserve_reaches_the_screen_and_the_store() -> None:
    import developaid_monitor as monitor

    assert hasattr(monitor, "store_retention") and hasattr(monitor, "latest_retention")
    assert '"retention": _retention(project, rnv)' in DASH
    body = PAGE[PAGE.index("function fundingStructure("):]
    assert "скрытый резерв РСС" in body
    assert "Из них после ввода" in body
    assert "в стройке эти деньги не будут потрачены" in body
    # Реестра нет — строки нет вовсе: «не загружали» и «удержаний нет» разное.
    assert "const gu=f.retention;" in body
    # И маршрут, которым он приезжает.
    import main_legacy

    assert "/monitor/retention" in {getattr(route, "path", "") for route in main_legacy.app.routes}


def test_a_stored_register_is_read_back(tmp_path, monkeypatch) -> None:
    import developaid_monitor as monitor

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(monitor, "_DATA", None, raising=False)
    data = _register([
        {"counterparty": "НУР ООО", "contract": "386", "contract_amount": 40.0,
         "share": 5, "amount": 2.0, "paid": 0.0, "left": 2.0, "due": "30.09.2032"},
    ])
    stored = monitor.store_retention("Проверочный", data, "2026-08-29", "гу.xlsx")
    assert stored["contracts"] == 1
    back = monitor.latest_retention("Проверочный")
    assert back and back["taken_at"] == "2026-08-29"
    assert retention.summary(back, horizon=datetime.date(2027, 12, 31))["left"] == 2.0
