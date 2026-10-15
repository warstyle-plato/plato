"""Платон находит выводы разбора «торги или SPV» в КРТ Москвы.

Разбор лежал только в `docs/krt_spv_research.md`, а поиск Платона по
нормативам читает `docs/normative/*.md` — выводы он не видел (замечание
сессии 331-ПП, 15.10.2026). Выжимка с теми же статусами лежит в
`docs/normative/moscow_krt_spv_option_511pp.md`; здесь проверяется, что
вопрос словами владельца приводит к нужному разделу и что раздел несёт сам
вывод, а не только заголовок.

Запуск: python3 -m pytest tests/test_platon_finds_krt_spv_findings.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import project_knowledge as knowledge  # noqa: E402

STEM = "moscow_krt_spv_option_511pp"


def _top(question: str, source: str | None = "normative") -> list[dict[str, str]]:
    found = knowledge.search(question, source=source)
    assert found.get("available", True), found
    return found["entries"][:2]


@pytest.mark.parametrize("question, heading, facts", [
    ("Что такое стоимость SPV в КРТ и откуда формула",
     "Стоимость SPV — плата за опцион, 511-ПП п. 7.9",
     ["511-ПП", "п. 7.9", "ФАКТ", "Попц = (Пври − Пи × 1,1 × Кн) × 1/Ки − Оц"]),
    ("Платится ли плата за ВРИ при торгах КРТ отдельно от цены торгов",
     "Плата за ВРИ при торгах КРТ — сверх цены торгов",
     ["сверх цены торгов", "владелец", "ФАКТ"]),
    ("Как инвестор входит в SPV вместе с городом",
     "Кто создаёт SPV и как входит инвестор",
     ["51%", "ст. 71", "4.7(1)"]),
])
def test_owner_words_lead_to_the_finding(question: str, heading: str,
                                         facts: list[str]) -> None:
    top = _top(question)
    hit = next((e for e in top if e["title"] == f"{STEM}: {heading}"), None)
    assert hit, [e["title"] for e in top]
    for fact in facts:
        assert fact in hit["text"], (fact, hit["text"][:300])


def test_general_search_reaches_the_findings_too() -> None:
    """Без указания источника выжимка тоже первая, а не тонет в правилах."""
    top = _top("стоимость SPV опцион 511-ПП", source=None)
    assert top[0]["title"].startswith(f"{STEM}: Стоимость SPV"), [e["title"] for e in top]


def test_open_question_keeps_its_status() -> None:
    """ВРИ при SPV не выдаётся за установленное: статус назван явно."""
    top = _top("Платится ли плата за ВРИ при SPV отдельно от опциона")
    hit = next(e for e in top if e["title"] == f"{STEM}: Плата за ВРИ при SPV")
    assert "Пври" in hit["text"] and "511-ПП п. 7.9" in hit["text"]
    assert any(status in hit["text"] for status in ("НЕ УСТАНОВЛЕНО", "ФАКТ", "ВЫВОД"))


def test_the_excerpt_points_to_the_full_review() -> None:
    text = (ROOT / "docs" / "normative" / f"{STEM}.md").read_text(encoding="utf-8")
    assert "docs/krt_spv_research.md" in text
    assert (ROOT / "docs" / "krt_spv_research.md").exists()
