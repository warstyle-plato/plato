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


def test_the_auction_section_names_the_2024_rewrite() -> None:
    """Практика «ВРИ сверху» и буква 273-ПП после 2652-ПП расходятся — это сказано."""
    top = _top("Платится ли плата за ВРИ при торгах КРТ отдельно от цены торгов")
    hit = next(e for e in top if "при торгах КРТ" in e["title"])
    assert "2652-ПП" in hit["text"] and "расходится с практикой" in hit["text"]


def test_general_search_reaches_the_findings_too() -> None:
    """Без указания источника выжимка тоже первая, а не тонет в правилах."""
    top = _top("стоимость SPV опцион 511-ПП", source=None)
    assert top[0]["title"].startswith(f"{STEM}: Стоимость SPV"), [e["title"] for e in top]


def test_vri_under_spv_is_answered_with_its_basis_and_status() -> None:
    """ВРИ при SPV: ответ — вывод из 273-ПП (п. 2.5 одинаково касается
    победителя торгов и оператора), с названным статусом, а не «уже в цене
    опциона» без нормы."""
    top = _top("Платится ли плата за ВРИ при SPV отдельно от опциона")
    hit = next(e for e in top if e["title"] == f"{STEM}: Плата за ВРИ при SPV")
    assert "ВЫВОД" in hit["text"] and "сверх опциона" in hit["text"]
    assert "П. 2.5 273-ПП" in hit["text"] and "2652-ПП" in hit["text"]
    assert "уже в цене опциона" not in hit["text"]


def test_auction_price_is_80_percent_of_the_same_formula() -> None:
    top = _top("Начальная цена торгов КРТ 80 процентов от SPV")
    hit = next(e for e in top if e["title"].startswith(f"{STEM}: НЦА торгов"))
    assert "1465-ПП, п. 3 приложения" in hit["text"]
    assert "ЦПТ = 0,8 x [(Ппл − Пи x 1,1 x Кн) x 1 / Ки]" in hit["text"]


def test_every_section_fits_the_answer_budget() -> None:
    """Раздел длиннее бюджета Платон увидит обрезанным — вывод может отрезаться."""
    sections = [e for e in knowledge.entries("normative") if e["title"].startswith(STEM)]
    assert len(sections) >= 6
    assert all(len(e["text"]) <= knowledge.ENTRY_BUDGET for e in sections), [
        (e["title"], len(e["text"])) for e in sections]


def test_the_excerpt_points_to_the_full_review() -> None:
    text = (ROOT / "docs" / "normative" / f"{STEM}.md").read_text(encoding="utf-8")
    assert "docs/krt_spv_research.md" in text
    assert (ROOT / "docs" / "krt_spv_research.md").exists()


def test_no_verdict_while_the_owner_checks_the_discrepancy() -> None:
    """Решение владельца 16.10.2026: сначала нормы, вывода «торги выгоднее» нет,
    пока расхождение акта и практики — на сверке у владельца."""
    text = (ROOT / "docs" / "normative" / f"{STEM}.md").read_text(encoding="utf-8")
    assert "на сверке у владельца" in text
    assert "торги выгоднее" not in text
    norms = ROOT / "docs" / "krt_spv_land_payment_norms.md"
    assert norms.exists() and "2652-ПП" in norms.read_text(encoding="utf-8")
