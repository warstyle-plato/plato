"""Бот называет ту книгу, которую прислал.

Подпись вложения и метка расхождений в журнале были жилыми у любой книги:
нежилая книга с очередями обещала «очереди на листе «Вводные»», хотя считает
проект одной очередью (`_nonres_project_workbook`), а её расхождения
подписывались «Книга v4». Теперь обе читают метаданные книги
(`workbook_label`, `workbook_caption`).

Запуск: python3 -m pytest tests/test_the_bot_names_the_book_it_sends.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402

core = wrapper.core

NONRES = {"missing": ["Очереди: книга моделирует проект одной очередью"], "phased": True,
          "class_deviations": [], "nonres_book": True}
V4 = {"missing": ["что-то"], "phased": True, "class_deviations": []}


def _send(monkeypatch, meta: dict) -> tuple[str, str]:
    sent: dict = {}
    monkeypatch.setattr(wrapper, "_resolve_context",
                        lambda chat_id: (None, {"inputs": {}, "tep": {}, "project_name": "П"}))
    monkeypatch.setattr(wrapper, "_send_message", lambda *a, **k: None)
    monkeypatch.setattr(core, "build_project_workbook",
                        lambda *a, **k: (b"xlsx", "book.xlsx", dict(meta)))
    monkeypatch.setattr(core, "_telegram_send_document_bytes",
                        lambda chat_id, data, name, caption="", **k: sent.update(caption=caption))
    monkeypatch.setitem(core._TELEGRAM_RUNTIME, "last_error", "")
    wrapper._send_model_archive(42)
    return sent["caption"], core._TELEGRAM_RUNTIME["last_error"]


def test_a_nonresidential_book_is_not_promised_queues(monkeypatch) -> None:
    caption, error = _send(monkeypatch, NONRES)
    assert "Вводные" not in caption
    assert "одной очередью" in caption
    assert error.startswith("Книга нежилого проекта")


def test_the_v4_book_keeps_its_caption(monkeypatch) -> None:
    caption, error = _send(monkeypatch, V4)
    assert "очереди на листе «Вводные»" in caption
    assert error.startswith("Книга v4")


@pytest.mark.parametrize("meta,label", [({"hotel_book": True}, "Книга гостиницы"),
                                        ({"nonres_book": True}, "Книга нежилого проекта"),
                                        ({}, "Книга v4")])
def test_each_book_has_its_name(meta, label) -> None:
    assert core.workbook_label(meta) == label
