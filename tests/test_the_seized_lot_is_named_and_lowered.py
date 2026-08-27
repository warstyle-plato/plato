"""Арест и исполнительное производство — не «прочее», а известное нам.

В реестре владельца из пятнадцати таких лотов, чьи торги уже прошли, до сделки
дошёл один. Это единственное, что реестр показывает уверенно: остальные доли
посчитаны на знаменателе, где «нет цены победителя» значит и «не продалось», и
«ещё идёт» — колонка «Состояние торгов» у всех ста тридцати лотов одна и та
же, «Прием заявок», и различить их в файле нечем.

Поэтому одно названное снижение, а не веса по всем происхождениям: тонкая
доля, превращённая в вес, выглядит на экране ровно так же уверенно, как
измеренная.
"""
from __future__ import annotations

from pathlib import Path

from auction_search.classifier import origin_from_evidence
from auction_search.models import LotOrigin

UI = Path(__file__).resolve().parent.parent / "auction_search" / "ui.py"


def test_seized_is_recognised_by_evidence_not_by_platform() -> None:
    assert origin_from_evidence(
        seller="Территориальное управление Росимущества",
        text="реализация арестованного имущества") is LotOrigin.SEIZED
    assert origin_from_evidence(
        text="передано судебным приставом-исполнителем") is LotOrigin.SEIZED


def test_bankruptcy_still_wins_over_seized() -> None:
    """Имущество банкрота продаёт и государственный орган."""
    assert origin_from_evidence(
        seller="Росимущество", text="конкурсный управляющий Иванов") is LotOrigin.BANKRUPTCY


def test_an_unknown_seller_stays_other() -> None:
    """«Мы не знаем» — не «арест» и не «городское»."""
    assert origin_from_evidence(seller="ООО Ромашка") is LotOrigin.OTHER


def test_the_lowering_is_named_with_its_count() -> None:
    """Снижение без объяснения — это просто другое число."""
    page = UI.read_text()
    block = page[page.index("function lotScore("):page.index("function lotScoreNote(")]
    assert "l.origin==='seized'" in block
    assert "1 лот из 15" in block, "цифра, на которой стоит снижение, названа"


def test_the_registry_cannot_calibrate_more_than_this() -> None:
    """Почему остальные доли в балл не превратились — записано рядом."""
    page = UI.read_text()
    block = page[page.index("function lotScore("):page.index("function lotScoreNote(")]
    assert "не продалось" in block, "почему знаменатель ненадёжен — сказано"


def test_the_new_origin_is_visible_and_filterable() -> None:
    page = UI.read_text()
    assert "seized:'Арест и ИП'" in page, "у происхождения есть имя на экране"
    assert '<option value="seized">' in page, "по нему можно отобрать"
