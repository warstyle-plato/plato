"""Карточки проектов из отчёта «Пульса»: что за дом и из чего он состоит.

Файл `moscow-cards-*.json` собирает импорт отчёта (`pulse_report_import`), и до
08.09.2026 его не читал НИКТО: 685 карточек с составом лежали на диске, пока
отчёт о рынке сравнивал апартаменты с квартирами, не называя этого.

Что здесь нужно отчёту — вид жилья. Разница измерена на самой выгрузке за
2026-08: в 25 парах «тот же район, тот же класс», где есть и квартиры, и
апартаменты, апартаменты дешевле в 21 паре, медиана разницы −21,0 %. Но правило
это НЕ универсально: в премиуме апартаменты дороже (Хамовники +12,8 %,
Басманный +31,1 %) — то есть ответ у каждого проекта свой, и отчёт обязан его
считать, а не применять поправку.

Состав назван не у всех: у 117 карточек из 685 нет ни квартир, ни апартаментов,
и это «не назван», а не «квартиры».
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FLATS = "квартиры"
APARTMENTS = "апартаменты"
MIXED = "смешанный"


class ProjectCards:
    """Карточки в памяти. Пустой файл — не ошибка, а прежнее поведение."""

    BUNDLED_GLOB = "moscow-cards-*.json"

    def __init__(self, payload: dict[str, Any] | None = None):
        self.payload = payload or {}
        self._cards: dict[str, Any] = self.payload.get("cards") or {}

    @classmethod
    def bundled(cls, directory: Path | None = None) -> "ProjectCards":
        folder = Path(directory) if directory else Path(__file__).with_name("registry_data")
        newest: dict[str, Any] = {}
        try:
            paths = sorted(folder.glob(cls.BUNDLED_GLOB))
        except OSError:
            paths = []
        for path in paths:
            try:
                newest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Битый файл не отменяет прежний: отчёт живёт и без состава.
                continue
        return cls(newest)

    @property
    def available(self) -> bool:
        return bool(self._cards)

    @property
    def source(self) -> str:
        return str(self.payload.get("source") or "")

    @property
    def last_month(self) -> str:
        return str(self.payload.get("last_month") or "")

    def card(self, complex_id: int | str | None) -> dict[str, Any]:
        return dict(self._cards.get(str(complex_id or "")) or {})

    def facts(self, complex_id: int | str | None) -> dict[str, Any]:
        """Вид жилья и его состав — то, что кладётся в строку проекта.

        Ключи те же у объекта и у соседа: правило одно, и разойтись им негде.
        Ничего не знаем — не кладём ничего: пустой ключ читался бы как ответ.
        """
        card = self.card(complex_id)
        if not card:
            return {}
        flats = int(card.get("flats") or 0)
        apartments = int(card.get("apartments") or 0)
        kind = housing_kind(flats, apartments)
        if not kind:
            return {}
        return {"housing_kind": kind, "flats_units": flats, "apartment_units": apartments}


def housing_kind(flats: int | None, apartments: int | None) -> str | None:
    """Вид жилья по составу. Ни того ни другого — «не назван», а не «квартиры»."""
    flats = int(flats or 0)
    apartments = int(apartments or 0)
    if flats and apartments:
        return MIXED
    if apartments:
        return APARTMENTS
    if flats:
        return FLATS
    return None


def housing_kind_from_flag(value: Any) -> str | None:
    """Тот же словарь для источника, который отдаёт признак, а не состав.

    У bnMAP это флаг «апартаменты» на карточке, у «Пульса» — два числа. Слова
    при этом одни и те же, и объявлены они здесь: две копии словаря однажды
    напишут «апарт.» в одной таблице и «апартаменты» в другой, а сравнить их
    станет нечем. Пустое значение — «не назван», а не «квартиры».
    """
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().casefold() in {"0", "false", "нет"}:
        return FLATS
    return APARTMENTS if value else FLATS
