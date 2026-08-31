"""Все поверхности показывают одну и ту же экономику.

Карточка Telegram, PDF и Excel-модель делались из разных источников: PDF брал
результат, посчитанный в мини-приложении и присланный вместе с запросом, а
модель пересчитывалась на сервере из тех же вводных. Пока обе стороны на одной
версии, разницы не видно. Стоит браузеру остаться на прежней странице — и
отчёт показывает одну экономику, детализация другую, причём обе выглядят
достоверно, и понять, какая верна, по ним нельзя.

Здесь закреплено: считаем один раз на сервере, расхождение с присланным
расчётом ищем явно и доносим в чат.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402
from xlsx_eval import Evaluator  # noqa: E402

core = wrapper.core
openpyxl = pytest.importorskip("openpyxl")


def project():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(purchase_price_mln=700, land_rights_cost_mln=1276.304,
                  project_start="2027-01-01", ird_months=18)
    return inputs, core.TEP_DEFAULT


def server_result():
    inputs, tep = project()
    return core._run_authoritative_model(inputs, tep, [], {})["consolidated"], inputs


# --- сверка ------------------------------------------------------------------

def test_a_result_agrees_with_itself():
    result, inputs = server_result()
    payload = {**result, "inputs": inputs}

    assert core._parity_mismatch(payload, payload) == []


@pytest.mark.parametrize("path,factor,label", [
    ("llcr", 0.9, "LLCR"),
    ("financing_cost", 0.6, "проценты и комиссии"),
    ("revenue", 1.05, "выручка"),
    ("net_profit", 0.8, "чистая прибыль"),
])
def test_a_stale_client_result_is_caught(path, factor, label):
    result, inputs = server_result()
    stale = copy.deepcopy(result)
    stale["summary"][path] = stale["summary"][path] * factor

    problems = core._parity_mismatch({**result, "inputs": inputs},
                                     {**stale, "inputs": inputs})

    assert any(label in text for text in problems), problems


def test_rounding_noise_is_not_a_mismatch():
    """Сверка не должна срабатывать на разнице представления чисел."""
    result, inputs = server_result()
    noisy = copy.deepcopy(result)
    noisy["summary"]["revenue"] = round(noisy["summary"]["revenue"], 2)
    noisy["summary"]["llcr"] = round(noisy["summary"]["llcr"], 4)

    assert core._parity_mismatch({**result, "inputs": inputs},
                                 {**noisy, "inputs": inputs}) == []


def test_every_agreed_metric_is_checked():
    """Список сверяемых величин — из постановки задачи, а не на глаз."""
    labels = {label for _, label, _ in core._PARITY_FIELDS}

    assert {"LLCR", "выручка", "расходы", "EBITDA", "чистая прибыль",
            "пик БРИДЖа", "выборка ПФ", "проценты и комиссии", "ВРИ",
            "социальная нагрузка"} <= labels


def test_a_missing_value_is_not_reported_as_a_mismatch():
    result, inputs = server_result()
    partial = {"summary": {"llcr": result["summary"]["llcr"]}}

    assert core._parity_mismatch({**result, "inputs": inputs}, partial) == []


# --- один расчёт на все поверхности -----------------------------------------

def test_the_workbook_matches_the_engine():
    """Книга считается из тех же вводных и обязана сойтись.

    Сторож паритета сверял лист из архива очередей — выгрузки, которой не было
    ни кнопки на сайте, ни отправки ботом. Книгу, которую скачивают на самом
    деле, он не смотрел: проверка стояла не у той двери. Архив снят
    (владелец, 30.08.2026), и сверка переехала на книгу v4.
    """
    inputs, tep = project()
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    content, _, meta = core.build_project_workbook(
        inputs, tep, [], {}, project_name="Паритет")
    assert meta["missing"] == [], meta["missing"]
    # Книга вся из формул, а openpyxl их не считает: сверять надо посчитанное,
    # иначе проверка выродится в сравнение адресов ячеек.
    sys.setrecursionlimit(400000)
    book = Evaluator(openpyxl.load_workbook(io.BytesIO(content)))
    assert book.cell("ОТЧЕТ", "B19") == pytest.approx(
        result["summary"]["llcr"], rel=0.005)
    assert book.cell("ОТЧЕТ", "B5") == pytest.approx(
        result["summary"]["revenue"] / 1e6, rel=0.005)
    assert book.cell("ОТЧЕТ", "B12") == pytest.approx(
        result["summary"]["net_profit"] / 1e6, rel=0.005)


def test_the_attachments_use_the_server_calculation(monkeypatch):
    """PDF больше не строится по присланному результату."""
    inputs, tep = project()
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    stale = copy.deepcopy(result)
    stale["summary"]["llcr"] = 0.42

    seen = {}
    monkeypatch.setattr(core, "_build_developaid_pdf",
                        lambda payload: seen.setdefault("llcr", payload["result"]["summary"]["llcr"]) and b"")
    monkeypatch.setattr(core, "_telegram_send_document_bytes", lambda *a, **kw: None)
    monkeypatch.setattr(core, "_telegram_send_message", lambda *a, **kw: None)
    monkeypatch.setattr(core, "build_project_workbook",
                        lambda *a, **kw: (b"", "model.xlsx", {}))
    monkeypatch.setattr(core, "run_sensitivity", lambda *a, **kw: {})

    core._telegram_send_attachments(1, {
        "result": stale, "inputs": inputs, "tep": tep, "rates": [], "phasing": {},
    }, "Паритет", [])

    assert seen["llcr"] == pytest.approx(result["summary"]["llcr"], rel=1e-6)
    assert seen["llcr"] != 0.42


def test_the_discrepancy_reaches_the_chat(monkeypatch):
    """Молча подменить числа нельзя: в PDF будет не то, что было на экране."""
    inputs, tep = project()
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    stale = copy.deepcopy(result)
    stale["summary"]["llcr"] = 0.42

    messages = []
    monkeypatch.setattr(core, "_build_developaid_pdf", lambda payload: b"")
    monkeypatch.setattr(core, "_telegram_send_document_bytes", lambda *a, **kw: None)
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kw: messages.append(text))
    monkeypatch.setattr(core, "build_project_workbook",
                        lambda *a, **kw: (b"", "model.xlsx", {}))
    monkeypatch.setattr(core, "run_sensitivity", lambda *a, **kw: {})

    core._telegram_send_attachments(1, {
        "result": stale, "inputs": inputs, "tep": tep, "rates": [], "phasing": {},
    }, "Паритет", [])

    assert any("разошёлся" in text for text in messages), messages
    assert any("LLCR" in text for text in messages)
