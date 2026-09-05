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


# Имя файла зашивать нельзя: отчёт месячный, и следующий выпуск лёг бы рядом
# с прежним, а читался бы всё равно старый — правку негде было бы заметить.
# Берётся самый поздний по имени, как городской свод.
BUNDLED_GLOB = "moscow-dynamics-*.json"


class SalesDynamics:
    """Ряды по месяцам, вынутые из помесячного отчёта."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload or {}
        self._projects: dict[str, Any] = self.payload.get("projects") or {}

    @classmethod
    def bundled(cls, directory: Path | None = None) -> "SalesDynamics":
        folder = Path(directory) if directory else Path(__file__).with_name("registry_data")
        newest: dict[str, Any] = {}
        try:
            paths = sorted(folder.glob(BUNDLED_GLOB))
        except OSError:
            paths = []
        for path in paths:
            try:
                newest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Битый файл не отменяет прежний: модуль работает без истории
                # продаж, а не падает.
                continue
        return cls(newest)

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

    def latest(self, complex_id: int | str | None, keys: tuple[str, ...]) -> dict[str, Any]:
        """Последнее известное значение по каждому ключу, со своим месяцем.

        У ключей разная заполненность: доля ипотеки есть только в месяцах, где
        были продажи, а прайс стоит каждый месяц. Один общий «последний месяц»
        на всех выдал бы пустоту там, где значение есть, — поэтому месяц свой у
        каждого числа и он называется рядом.
        """
        row = self._projects.get(str(complex_id or ""))
        if not row:
            return {}
        months = self.months
        out: dict[str, Any] = {}
        for key in keys:
            values = row.get(key) or []
            for index in range(min(len(values), len(months)) - 1, -1, -1):
                if values[index] is not None:
                    out[key] = values[index]
                    out[f"{key}_at"] = months[index]
                    break
        if row.get("room_mix"):
            out["room_mix"] = row["room_mix"]
        return out


class DealsSummary:
    """Свод выписок: полосы площади и банки ипотеки по проекту.

    Отдельно от рядов, потому что отвечает на другой вопрос и приезжает из
    другого листа отчёта. Комнатности и доли ипотеки здесь нет намеренно — их
    считает сам отчёт, и второй счёт тех же величин однажды разошёлся бы с
    первым, а обе цифры выглядели бы верными.
    """

    BUNDLED_GLOB = "moscow-deals-*.json"

    def __init__(self, payload: dict[str, Any] | None = None):
        self.payload = payload or {}
        self._projects: dict[str, Any] = self.payload.get("projects") or {}

    @classmethod
    def bundled(cls, directory: Path | None = None) -> "DealsSummary":
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
                continue
        return cls(newest)

    @property
    def available(self) -> bool:
        return bool(self._projects)

    @property
    def months(self) -> list[str]:
        return list(self.payload.get("months") or [])

    def project(self, complex_id: int | str | None) -> dict[str, Any]:
        return dict(self._projects.get(str(complex_id or "")) or {})

    def bands(self, complex_id: int | str | None) -> dict[str, int]:
        """Доли полос площади в проданном. Пусто — значит сделок в окне нет."""
        row = self.project(complex_id)
        return dict(row.get("bands") or {})

    def banks(self, complex_id: int | str | None) -> dict[str, int]:
        row = self.project(complex_id)
        return dict(row.get("banks") or {})
