"""Перечень участков решения доезжает до модели.

«Блок КРТ ничего толком не передаёт в движок, ни кадастровые номера, ни соц
нагрузку, ни офисники» (владелец, 04.09.2026). Про номера это было верно
буквально: решение по Варшавскому ш., вл. 37 называет 60 кадастровых номеров
(`cadastral_numbers_source: appendix`), карточка собирает по ним контур — и до
модели не доезжал ни один. Проверено не на одной площадке: у шести
планируемых подряд перечень есть всегда (43, 8, 40, 14, 30, 23 номера), в
модели — ноль.

Ловушка та же, что уже ловилась на лотах: из 60 номеров 39 — здания, их
сносят и перечисляют поимённо. Отданные калькулятору, они превращают площадь
дома в площадь территории. Разделяет их ЕГРН, и разделяет ОДИН раз — в
контуре карточки; второго опроса здесь нет.

Запуск: python3 -m pytest tests/test_the_decision_parcels_reach_the_model.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.krt_screening import _requirements_for_model  # noqa: E402

API = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
CARD = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")
BRIDGE = (ROOT / "auction_search" / "bridge.py").read_text(encoding="utf-8")

DECISION = {
    "available": True,
    "decision_available": True,
    "cadastral_numbers": ["77:05:0004001:2046", "77:05:0004001:1052"],
    "cadastral_numbers_source": "appendix",
    "object_actions": [], "construction": [], "resettlement": [],
    "permitted_uses": [], "deadlines": [],
}


def test_the_screening_carries_the_list_the_decision_named() -> None:
    duties = _requirements_for_model(DECISION)
    assert duties["cadastral_numbers"] == DECISION["cadastral_numbers"]
    assert duties["cadastral_numbers_source"] == "appendix"


def test_an_unread_decision_is_an_empty_list_not_a_guess() -> None:
    """«Не прочитали» — не «участков нет»: обе половины отвечают пустым
    списком, но источник называет, которая это."""
    duties = _requirements_for_model({})
    assert duties["cadastral_numbers"] == []
    assert duties["cadastral_numbers_source"] == "none"


def test_the_handoff_takes_land_parcels_not_the_whole_list() -> None:
    """Здания в поле участка — это площадь дома, принятая за площадь земли."""
    handoff = API[API.index('@app.get("/auctions/krt/{slug}/handoff")'):]
    handoff = handoff[: handoff.index('@app.post("/auctions/krt/{slug}/plato")')]
    assert "_decision_outline(slug)" in handoff, \
        "перечень берётся не из контура — значит вторым опросом ЕГРН"
    assert 'outline.get("parcels")' in handoff, "в handoff уехали бы и здания"
    assert '"cadastral_numbers": parcels' in handoff


def test_the_handoff_says_what_it_left_out() -> None:
    """Молча выброшенный номер читается как его отсутствие в документе."""
    handoff = API[API.index('@app.get("/auctions/krt/{slug}/handoff")'):]
    handoff = handoff[: handoff.index('@app.post("/auctions/krt/{slug}/plato")')]
    for key in ('"land"', '"listed"', '"buildings"', '"missing"', '"problem"'):
        assert key in handoff, f"счёт прочитанного неполон: нет {key}"


def test_the_card_puts_the_parcels_into_the_load() -> None:
    assert "krt_cadastres:d.cadastral_numbers" in CARD
    assert "krt_cadastre_note:d.cadastral" in CARD


def test_the_bridge_stopped_saying_they_do_not_exist() -> None:
    """Оговорка «мы этого не читаем» устаревает молча.

    Фраза была верна до того, как контур стал собираться по перечню решения,
    и осталась стоять — человек читал её как ответ документа.

    Запрещать надо МЕСТО, а не слово: объяснить в комментарии, почему прежний
    текст снят, можно и нужно — на этом уже спотыкался сторож пробы
    Росэлторга. Проверяется то, что видит человек, — вопрос в окне.
    """
    start = BRIDGE.index("if(!confirm('Открыть площадку КРТ")
    question = BRIDGE[start: BRIDGE.index("))return;", start)]
    assert "в каталоге города нет" not in question, "фраза пережила свою правду"
    assert "перечня проекта решения" in BRIDGE
