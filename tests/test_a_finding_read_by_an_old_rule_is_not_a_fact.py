"""Находка, посчитанная прежним правилом привязки, признаком не считается.

Занятость спрашивается один раз: «отданная площадка свободной не становится»
(владелец, 01.09.2026) — прогон платит за площадку однажды и больше её не
перечитывает. У этого правила есть обратная сторона: НЕВЕРНАЯ находка живёт
вечно. «Бореалис 53А не строит» (владелец, 02.09.2026) — оператор соседней
площадки стоял у Фестивальной, 53А, и перечитывать было незачем: площадка же
«занята».

Хранимый ответ посчитан ПРАВИЛОМ, и когда правило меняется, прежний ответ
перестаёт быть ответом. Версия правила лежит рядом с находкой, как схема рядом
с кэшем: ответ старой версии — «не знаем», а не «занята».

Запуск: python3 -m pytest tests/test_a_finding_read_by_an_old_rule_is_not_a_fact.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_open_sources as sources  # noqa: E402

API = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")


def test_the_findings_carry_the_rules_version() -> None:
    got = sources.read_findings([], "Фестивальная ул., вл. 53А")
    assert got["rules_version"] == sources.ANCHOR_RULES_VERSION
    assert sources.ANCHOR_RULES_VERSION >= 2, "версия правила не поднята вместе с правилом"


def test_a_stored_answer_of_an_older_rule_is_asked_again() -> None:
    """Гейт «спрашивали один раз» пропускает только ответ нынешнего правила."""
    assert "_facts_by_current_rules(stored)" in API
    body = API[API.index("def _open_sources_for_run"):]
    body = body[: body.index("def ", body.index("\n") + 1)]
    assert 'stored.get("taken") and _facts_by_current_rules(stored)' in body, (
        "занятость прежнего правила по-прежнему отменяет повторный вопрос")


def test_the_list_does_not_show_a_stale_finding_as_a_fact() -> None:
    body = API[API.index("def _row_without_stale_facts"):]
    body = body[: body.index("\n    def ", 1)]
    assert '"available": False' in body and '"stale_rules": True' in body
    assert "прежним правилом" in body
    # Причина названа, а не выброшена молча: пустой блок читается как
    # «в источниках ничего нет».
    assert '"reason"' in body
    assert "_row_without_stale_facts(row) for row in krt_ranking.rows()" in API


def test_the_weekly_run_reasks_the_sites_read_by_the_old_rule() -> None:
    body = API[API.index("planned = []"):]
    body = body[: body.index("if not planned")]
    assert "_facts_by_current_rules(stored)" in body
