"""Словарь терминов — единственный владелец подписей величин.

Подпись величины живёт здесь, а страница, PDF, тизер, книга Excel, Telegram и
Платон её читают. Одна величина в пяти местах называлась «строительным
объёмом», хотя это сумма площадей в м²; строительный объём в отрасли — объём
здания в м³ по наружному обмеру (надземная и подземная части). Переименование
одной строкой здесь — и ни одна поверхность не отстаёт.

Ключи API (`construction_volume_sqm`, `core_total_gns`, `gns`) НЕ меняются:
словарь владеет словами, а не схемой. Полная таблица «наша подпись → что
считается → отраслевой термин» — `docs/glossary.md`.
"""
from __future__ import annotations

from typing import NamedTuple


class Term(NamedTuple):
    key: str
    name: str            # именительный, с заглавной: подпись строки/колонки
    full: str            # полная подпись с составом и единицей
    genitive: str        # родительный, строчный: «тыс. ₽/м² …»
    prepositional: str   # предложный, строчный: «в …»
    unit: str
    formula: str         # что на самом деле считается
    # Подписи, которые этой величине давать нельзя: тест ищет их на
    # отрисованной странице, в PDF и в книге.
    forbidden: tuple[str, ...] = ()

    def lower(self) -> str:
        return self.name[:1].lower() + self.name[1:]

    def with_unit(self) -> str:
        return f"{self.name}, {self.unit}"


# Наземная ГНС + подземная часть (паркинг, кладовые, гаражи объектов).
# На ней считаются общепроектные статьи и удельные «на м²» этой базы.
TOTAL_AREA = Term(
    key="total_area",
    name="Суммарная площадь",
    full="Суммарная площадь (наземная ГНС + подземная), м²",
    genitive="суммарной площади",
    prepositional="суммарной площади",
    unit="м²",
    formula="наземная ГНС + подземная часть (паркинг, кладовые, гаражи объектов)",
    forbidden=("Строительный объём", "строительный объём", "строительного объёма",
               "строительном объёме", "Строит. объём", "строит. объём",
               "строит. объёма"),
)

TERMS: dict[str, Term] = {term.key: term for term in (TOTAL_AREA,)}


def page_terms() -> dict[str, dict[str, str]]:
    """Словарь для страницы: те же слова, что у PDF и книги."""
    return {key: {"name": t.name, "lower": t.lower(), "full": t.full,
                  "genitive": t.genitive, "prepositional": t.prepositional,
                  "unit": t.unit, "with_unit": t.with_unit()}
            for key, t in TERMS.items()}


def forbidden_labels() -> tuple[str, ...]:
    return tuple(label for t in TERMS.values() for label in t.forbidden)
