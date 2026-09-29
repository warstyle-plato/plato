"""Срок в карточке КРТ — срок, а не обрывок первой фразы решения.

У многих карточек в строке «Срок» стояло «Предельный срок реализации решения о
КРТ «ул.»: фраза резалась по точке после «ул.» в названии КРТ. Образец —
живой проект решения «ул. Тверская» (`tests/fixtures/krt_decision_tverskaya_*`):
в нём «7. Предельный срок реализации решения о КРТ «ул. Тверская» составляет
6 лет со дня заключения договора о КРТ …», а рядом, в п. 8, — «12 месяцев»
подготовки ДПТ, и это не срок реализации.
"""

from __future__ import annotations

import json
from pathlib import Path

import page_blocks  # noqa: E402 — стенд страницы, лежит рядом с тестами
from auction_search.krt_investment_card import krt_investment_card_page
from auction_search.ui import auctions_page
from market_search import krt_requirements

FIXTURE = (Path(__file__).resolve().parent / "fixtures"
           / "krt_decision_tverskaya_2026-09-29.txt")


def _decision() -> dict:
    text = FIXTURE.read_text(encoding="utf-8")
    return krt_requirements.parse_decision_requirements(text, title="ул. Тверская")


def test_the_term_is_read_as_a_number_with_its_point() -> None:
    facts = _decision()
    term = facts["term"]
    assert term["value"] == 6 and term["unit"] == "years"
    assert term["label"] == "6 лет со дня заключения договора о КРТ"
    assert term["point"] == "7" and term["origin"] == "проект решения, п. 7"
    assert "«ул. Тверская»" in term["quote"]
    # Абзац больше не режется на «ул.».
    assert all(not item.rstrip().endswith("«ул.") for item in facts["deadlines"])


def test_abbreviations_and_quotes_do_not_end_a_sentence() -> None:
    sentences = krt_requirements._decision_sentences(
        "Решение о КРТ «ул. Тверская, д. 5, стр. 1». Второе предложение.")
    assert sentences == ["Решение о КРТ «ул. Тверская, д. 5, стр. 1».",
                         "Второе предложение."]


def test_the_planning_term_is_not_the_realisation_term() -> None:
    assert krt_requirements.decision_term(
        "8. Предельный срок подготовки документации составляет 12 месяцев.") is None


def _card(prelude: str, tail: str):
    return page_blocks.run_json(
        "let html={};const document={getElementById:id=>({set innerHTML(v){html[id]=v},"
        "style:{}})};" + prelude, tail, page=krt_investment_card_page("x"))


def test_the_rendered_card_shows_the_term_and_names_missing_data() -> None:
    req = {"source_level": "official_project_decision", "decision_available": True,
           **{k: v for k, v in _decision().items() if k != "intent"}}
    legacy = {"source_level": "official_project_decision",
              "deadlines": ["Предельный срок реализации решения о КРТ «ул."]}
    unread = {"decision_available": False, "deadlines": []}
    out = _card(
        "const p={total_gfa_sqm:16450,housing_gfa_sqm:16450};",
        "const r=[];for(const q of " + json.dumps([req, legacy, unread], ensure_ascii=False)
        + "){html={};renderProgramme(p,q);r.push([html.programme||'',html.burden||''])}"
        "console.log(JSON.stringify(r))")
    (fresh, fresh_burden), (old, _), (none, none_burden) = out
    assert "6 лет со дня заключения договора о КРТ (проект решения, п. 7)" in fresh
    assert "«ул.</b>" not in old and "срок в решении не найден (проект решения на mos.ru)" in old
    assert "срок в решении не найден (проект решения не найден на mos.ru)" in none
    # Прочитанное решение: счётчики числами; непрочитанное — причина, не нули.
    assert "<b>0</b>" in fresh_burden or "<b>5</b>" in fresh_burden
    assert "<b>0</b>" not in none_burden
    assert "нет данных: проект решения не найден на mos.ru" in none_burden


def test_card_and_catalogue_share_one_rule() -> None:
    card = page_blocks.function("krtTermText", krt_investment_card_page("x"))
    catalogue = page_blocks.function("krtTermText", auctions_page())
    assert card == catalogue


def test_a_dash_and_a_torn_word_still_give_the_term() -> None:
    """Живые варианты каталога: «…» – 6 лет» вместо «составляет» и «реше ния»."""
    dash = krt_requirements.decision_term(
        "4. Предельный срок реализации решения о КРТ «Фестивальная ул.. влд. 53А» – "
        "6 лет со дня заключения договора о КРТ « Фестивальная ул. » или договора.")
    assert dash["label"] == "6 лет со дня заключения договора о КРТ" and dash["point"] == "4"
    torn = krt_requirements.decision_term(
        "Предельный срок реализации реше ния о КРТ « вдоль Синельниковской ул.; "
        "1-я Горловская улица, вл д. 4 » составляет 7 лет со дня заключения договора.")
    assert torn["value"] == 7 and torn["unit"] == "years"
