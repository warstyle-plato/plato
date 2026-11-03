"""Ответы анкеты доходят до владельца, хотя сайт и бот на разных машинах.

Журнал пишется там, где обслужен запрос: сайт живёт на ядре, бот — на Render.
`/survey` в боте показывал только свою половину, и анкеты, заполненные на
сайте, не видел никто (18.08.2026). Здесь закреплено:

- ядро отдаёт свой свод по подписи общим токеном бота и только по ней;
- бот показывает его отдельным блоком, а не подмешивает в свои средние:
  смешать две выборки в одно число значит выдумать третье;
- если ядро не ответило, бот честно говорит, что показана половина.

Запуск: python3 -m pytest tests/test_survey_reaches_the_owner.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402

core = wrapper.core


def test_the_core_hands_the_summary_only_against_a_signature(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:survey-test-token")
    request = core.InternalSummaryRequest(days=7, sign="не та подпись")
    with pytest.raises(core.HTTPException) as exc:
        core.internal_usage_summary(request)
    assert exc.value.status_code == 403

    good = core.InternalSummaryRequest(days=7, sign=core._web_login_sign("usage-summary", 7))
    answer = core.internal_usage_summary(good)
    assert "survey" in answer and "usage" in answer


def test_the_signature_covers_the_window(monkeypatch):
    """Подпись считается вместе с числом дней: иначе одна подпись открывает
    любой отрезок, включая всё хранение."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:survey-test-token")
    sign_for_seven = core._web_login_sign("usage-summary", 7)
    with pytest.raises(core.HTTPException):
        core.internal_usage_summary(core.InternalSummaryRequest(days=30, sign=sign_for_seven))


def test_the_bot_asks_the_core_and_shows_it_separately(monkeypatch):
    # Подпись считается токеном бота — без него ходить незачем и нечем.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:survey-test-token")
    monkeypatch.setattr(core, "_projects_remote_url", lambda path: "https://core.test" + path)
    monkeypatch.setattr(core, "_core_post", lambda url, payload, timeout: {
        "survey": {"answers": 3, "groups": [{"label": "Участок", "avg": 4.5, "count": 3}],
                   "notes": [{"group": "Участок", "role": "Брокер", "text": "карта мелкая"}]},
        "usage": {"enabled": True},
    })
    got = wrapper._remote_summaries(30)
    assert got["survey"]["answers"] == 3

    block = "\n".join(wrapper._survey_block(got["survey"], "Анкеты с сайта (ядро)"))
    assert "Анкеты с сайта (ядро)" in block
    assert "3" in block and "карта мелкая" in block
    assert "Брокер" in block


def test_a_silent_core_is_said_out_loud():
    """«Свод не получен» — это ответ; молчание выглядело бы как «анкет нет»."""
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    body = source[source.index("def _survey_message("):]
    body = body[:body.index("def _stats_message(")]
    assert "_remote_summaries(days)" in body
    assert "показана только половина" in body
    assert "Анкеты с сайта (ядро)" in body


def test_the_remote_failure_never_breaks_the_summary(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:survey-test-token")
    monkeypatch.setattr(core, "_projects_remote_url", lambda path: "https://core.test" + path)
    def boom(*a, **k):
        raise RuntimeError("ядро недоступно")
    monkeypatch.setattr(core, "_core_post", boom)
    assert wrapper._remote_summaries(30) is None


def test_a_single_host_asks_nobody(monkeypatch):
    """Когда сайт и бот на одной машине, ходить не к кому — и не ходим."""
    monkeypatch.setattr(core, "_projects_remote_url", lambda path: "")
    assert wrapper._remote_summaries(30) is None
