"""Модель должна быть доступна из чата, а её отказ — понятен.

Сборка Excel-модели идёт следом за карточкой, и её отказ оставлял человека
вовсе без модели: мини-приложение закрывается сразу после расчёта, и до кнопки
«Скачать модель (ZIP)» внутри уже не добраться. Сообщение при этом называло
кнопку, которой нет, а текст ошибки — «'NoneType' object has no attribute
'get'» — без места в коде не значит ничего.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

CONTEXT = {
    "session": "s-1", "chat_id": 42,
    "inputs": {"purchase_price_mln": 6500}, "tep": {},
    "rates": [], "phasing": {}, "selected_view": "all",
}


@pytest.fixture
def chat(monkeypatch, tmp_path):
    sent: list[str] = []
    documents: list[tuple[str, int]] = []
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "_send_message",
                        lambda chat_id, text, **kw: sent.append(text))
    monkeypatch.setattr(core, "_telegram_send_document_bytes",
                        lambda cid, data, name, **kw: documents.append((name, len(data))))
    return sent, documents


def test_the_model_is_sent_on_demand(chat, monkeypatch):
    sent, documents = chat
    monkeypatch.setattr(wrapper, "_PLATON_CONTEXT_BY_SESSION", {"s-1": CONTEXT})
    monkeypatch.setattr(wrapper, "_PLATON_LAST_SESSION", {42: "s-1"})
    monkeypatch.setattr(core, "build_project_workbook",
                        lambda *a, **k: (b"PK\x03\x04xlsx", "DevelopAid_модель.xlsx", {}))

    wrapper._send_model_archive(42)

    assert documents == [("DevelopAid_модель.xlsx", len(b"PK\x03\x04xlsx"))]
    assert any("Собираю" in text for text in sent), "человеку не сказали, что идёт сборка"


def test_without_a_project_it_says_so(chat, monkeypatch):
    sent, documents = chat
    monkeypatch.setattr(wrapper, "_PLATON_CONTEXT_BY_SESSION", {})
    monkeypatch.setattr(wrapper, "_PLATON_LAST_SESSION", {})
    monkeypatch.setattr(wrapper, "_PLATON_TEP_CONTEXT", {})

    wrapper._send_model_archive(42)

    assert not documents
    assert any("Собирать пока нечего" in text for text in sent)


def test_a_failure_names_the_place_in_the_code(chat, monkeypatch):
    """«'NoneType' object has no attribute 'get'» без строки кода бесполезно."""
    sent, documents = chat
    monkeypatch.setattr(wrapper, "_PLATON_CONTEXT_BY_SESSION", {"s-1": CONTEXT})
    monkeypatch.setattr(wrapper, "_PLATON_LAST_SESSION", {42: "s-1"})

    def refuse(*a, **k):
        None.get("x")  # noqa: B018
    monkeypatch.setattr(core, "build_project_workbook", refuse)

    wrapper._send_model_archive(42)

    assert not documents
    failure = next(text for text in sent if "не собралась" in text)
    assert "NoneType" in failure
    assert "test_model_on_demand.py:" in failure, "место ошибки не названо"


def test_the_error_location_helper_points_at_the_last_frame():
    def inner():
        return {}.get("a").get("b")

    try:
        inner()
    except AttributeError as exc:
        text = core._error_location(exc)
    assert "NoneType" in text
    assert "test_model_on_demand.py" in text and "inner" in text


def test_a_hole_in_the_social_objects_list_no_longer_breaks_phasing():
    """JSON.stringify превращает пропуск в массиве в null."""
    allocation = core._phase_social_allocation(
        [None, {"type": "kindergarten", "capacity": 250, "name": "ДОУ"}], 3)

    assert len(allocation) == 1
    assert allocation[0]["name"] == "ДОУ"


def test_the_whole_archive_survives_a_hole_in_the_list():
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    phasing = {
        "enabled": True, "phase_count": 3, "phase_gap_months": 12,
        "phases": [{"name": f"О{i+1}", "start_offset_months": i * 12,
                    "construction_months": 24} for i in range(3)],
        "social_objects": [None],
    }
    data, name, meta = core.build_project_workbook(
        inputs, tep, [], phasing, project_name="Тест")

    assert data[:2] == b"PK" and name.endswith(".xlsx")
    assert meta["missing"] == [], meta["missing"]
