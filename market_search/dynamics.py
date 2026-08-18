"""Помесячная история продаж: сколько продано, сколько осталось, почём.

Живой источник отдаёт историю только по цене (`/api/compare/price-dynamic-chart/`).
Продажи, остаток и скидку он держит в помесячном отчёте — той самой книге на
176 МБ, из которой уже собран справочник проектов. Возить книгу в рантайме
незачем: нужные ряды вынуты один раз и едут с кодом отдельным файлом на 169 КБ.

Ключ — идентификатор ЖК из колонки «ID ЖК», тот же, которым проекты зовутся в
«Пульсе». Это важнее, чем кажется: сопоставление по названию здесь не нужно
вовсе, а значит невозможна и его любимая ошибка — «Мнёвники от Гранель» против
«Мнвников», латиница против кириллицы, вторая очередь против первой.

Покрытие честное и неполное: 339 проектов «Москвы старой» против трёх с
половиной тысяч в карте «Пульса». У соседа из области или из Новой Москвы ряда
не будет, и график должен сказать это словами, а не нарисовать пустоту.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BUNDLED_NAME = "moscow-dynamics-2026-07.json"


class SalesDynamics:
    """Ряды по месяцам, вынутые из помесячного отчёта."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload or {}
        self._projects: dict[str, Any] = self.payload.get("projects") or {}

    @classmethod
    def bundled(cls) -> "SalesDynamics":
        path = Path(__file__).with_name("registry_data") / BUNDLED_NAME
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            # Файла нет — модуль работает без истории продаж, а не падает.
            return cls({})

    @property
    def available(self) -> bool:
        return bool(self._projects)

    @property
    def months(self) -> list[str]:
        return list(self.payload.get("months") or [])

    @property
    def source(self) -> str | None:
        return self.payload.get("source")

    @property
    def last_month(self) -> str | None:
        return self.payload.get("last_month")

    def series(self, complex_id: int | str | None, keys: tuple[str, ...] = ("sold", "rem")) -> list[dict[str, Any]]:
        """Помесячный ряд по проекту. Пусто — значит проекта нет в отчёте.

        Точки без чисел выбрасываются: у проекта, вышедшего в продажу год назад,
        первые месяцы пустые, и рисовать их нулями значило бы показать провал
        продаж там, где продаж ещё не было.
        """
        row = self._projects.get(str(complex_id or ""))
        if not row:
            return []
        months = self.months
        out: list[dict[str, Any]] = []
        for index, month in enumerate(months):
            point: dict[str, Any] = {"month": month}
            has_value = False
            for key in keys:
                values = row.get(key) or []
                value = values[index] if index < len(values) else None
                point[key] = value
                has_value = has_value or value is not None
            if has_value:
                out.append(point)
        return out

    def coverage(self, complex_id: int | str | None) -> bool:
        return str(complex_id or "") in self._projects
