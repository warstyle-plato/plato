"""Свод рынка Москвы: вторая база сравнения, кроме соседей по радиусу.

Соседи отвечают на вопрос «как мы против тех, кто рядом». Есть и второй,
не менее нужный: «как мы против города». Проект может быть самым дорогим в
своём километре и при этом обычным для Москвы — или наоборот.

Свод сворачивается из помесячного отчёта «Пульс Продаж Новостроек» один раз
и уезжает вместе с кодом: в книге 17 тысяч записей проект-месяц и 168 мегабайт,
в своде — тринадцать килобайт. Тянуть книгу в рантайм ради пяти медиан нельзя,
а держать медианы в коде нельзя тем более: они верны только на свой месяц.
Поэтому у свода есть дата, и она печатается рядом с числами.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ClassSnapshot:
    """Срез по классу на последний месяц свода."""

    segment: str
    projects: int
    price_median: int | None
    price_p25: int | None
    price_p75: int | None
    sold_median: float | None
    sold_total: int | None
    remainder_total: int | None
    discount_median_pct: float | None

    def position(self, price: int | None) -> dict[str, Any] | None:
        """Где цена проекта стоит относительно города.

        Квартили честнее медианы: «выше медианы» звучит одинаково и для плюс
        пяти процентов, и для плюс восьмидесяти, а «выше верхнего квартиля»
        сразу говорит, что проект вне основной массы.
        """
        if not price or not self.price_median:
            return None
        out: dict[str, Any] = {
            "price_per_sqm": price,
            "median": self.price_median,
            "vs_median_pct": round((price / self.price_median - 1) * 100, 1),
        }
        if self.price_p25 and self.price_p75:
            out["p25"] = self.price_p25
            out["p75"] = self.price_p75
            if price > self.price_p75:
                out["band"] = "above_p75"
            elif price < self.price_p25:
                out["band"] = "below_p25"
            else:
                out["band"] = "interquartile"
        return out


class MoscowMarket:
    """Городские своды по классам и округам. Нет файла — источник выключен."""

    def __init__(self, payload: dict[str, Any] | None = None):
        self.payload = payload or {}

    @classmethod
    def bundled(cls, directory: Path | None = None) -> "MoscowMarket":
        folder = Path(directory) if directory else Path(__file__).resolve().parent / "registry_data"
        newest = None
        for path in sorted(folder.glob("moscow-market-*.json")):
            try:
                newest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
        return cls(newest)

    @property
    def available(self) -> bool:
        return bool(self.payload.get("current"))

    @property
    def observed_at(self) -> str | None:
        return self.payload.get("last_month")

    @property
    def source(self) -> str | None:
        return self.payload.get("source")

    def segments(self) -> list[str]:
        return sorted(self.payload.get("current") or {})

    def snapshot(self, segment: str | None) -> ClassSnapshot | None:
        row = (self.payload.get("current") or {}).get(str(segment or ""))
        if not row:
            return None
        return ClassSnapshot(
            segment=str(segment),
            projects=int(row.get("projects") or 0),
            price_median=row.get("price_median"),
            price_p25=row.get("price_p25"),
            price_p75=row.get("price_p75"),
            sold_median=row.get("sold_median"),
            sold_total=row.get("sold_total"),
            remainder_total=row.get("rem_total"),
            discount_median_pct=row.get("disc_median"),
        )

    def okrug(self, okrug: str | None, segment: str | None) -> dict[str, Any] | None:
        """Округ — средняя ступень между соседями и городом."""
        table = (self.payload.get("by_okrug") or {}).get(str(okrug or ""))
        if not table:
            return None
        return table.get(str(segment or "")) or None

    def history(self, segment: str | None, months: int = 12) -> list[dict[str, Any]]:
        """Помесячный ряд по классу: медиана цены и продажи по городу."""
        series = (self.payload.get("by_class") or {}).get(str(segment or "")) or []
        return list(series[-months:])
