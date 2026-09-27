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
import statistics
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
    # Появились с выпуска отчёта за август: доля ипотеки по классу и цена
    # сделки по ДДУ. У прежних сводов их нет вовсе, поэтому оба с умолчанием —
    # «не знаем», а не ноль.
    mortgage_median_pct: float | None = None
    discount_projects: int | None = None
    discount_offering: int | None = None
    discount_median_offered_pct: float | None = None
    ddu_median: int | None = None
    ddu_projects: int | None = None

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


# Эталон поглощения — та же мера, что у числителя: СРЕДНИЙ месячный темп за
# окно, а не срез одного месяца. Числитель рейтинга — средний месячный темп
# аналогов Пульса за период, и знаменатель, взятый за один последний месяц,
# сравнивал разные величины. Замер владельца на 2026-08 (медиана «1 месяц» →
# медиана «среднее 12 мес.»): бизнес 708 (n 79) → 884 (n 102), комфорт 670 (50)
# → 1016 (66), премиум 304 (43) → 550 (52), элит 236 (4) → 292 (16). Перекос
# около 1,45× в одну сторону, и выборка при этом растёт: месяц без сделок
# выбрасывал из неё работающий проект целиком.
#
# Окно и порог объявлены здесь, рядом с расчётом, и берутся отсюда всеми.
ABSORPTION_WINDOW_MONTHS = 12
# Сколько месяцев с продажами обязан иметь проект, чтобы его средний темп стал
# наблюдением класса.
ABSORPTION_MIN_MONTHS = 3


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
        payload = dict(newest or {})
        # #485 требует медиану поглощения Москвы в м²/мес., а не ДДУ/мес.
        # Исходный импорт уже хранит помесячную площадь продаж каждого проекта
        # в moscow-dynamics-*.json; прежний маленький свод просто не переносил
        # эту медиану. Считаем её один раз при загрузке reference — без сети.
        wanted_month = str(payload.get("last_month") or "")
        dynamics = None
        for path in sorted(folder.glob("moscow-dynamics-*.json")):
            try:
                candidate = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not wanted_month or str(candidate.get("last_month") or "") == wanted_month:
                dynamics = candidate
        area_by_segment: dict[str, list[float]] = {}
        if isinstance(dynamics, dict):
            months = list(dynamics.get("months") or [])
            index = months.index(wanted_month) if wanted_month in months else len(months) - 1
            first = max(0, index + 1 - ABSORPTION_WINDOW_MONTHS)
            for project in (dynamics.get("projects") or {}).values():
                if not isinstance(project, dict):
                    continue
                segment = str(project.get("segment") or "").strip()
                series = project.get("area") or []
                if not segment or index < 0 or index >= len(series):
                    continue
                sold: list[float] = []
                for value in series[first:index + 1]:
                    if value is None:
                        continue
                    try:
                        area = float(value)
                    except (TypeError, ValueError):
                        continue
                    # В динамике 0 используется и как «продаж за месяц нет», и
                    # как пустой/неполный месячный срез. В СРЕДНЕЕ он не входит
                    # ни в одном из двух смыслов: месяц без продаж — не месяц
                    # темпа, а пустой срез вовсе не наблюдение.
                    if area > 0:
                        sold.append(area)
                # Проект с одним-двумя месяцами продаж за год — не темп, а
                # случай. Порог отсекает его целиком, а не даёт ему голос
                # наравне с работающим проектом.
                if len(sold) < ABSORPTION_MIN_MONTHS:
                    continue
                area_by_segment.setdefault(segment, []).append(
                    sum(sold) / len(sold))
        payload["_area_median_by_segment"] = {
            segment: round(float(statistics.median(values)), 1)
            for segment, values in area_by_segment.items() if values
        }
        payload["_area_median_window_months"] = ABSORPTION_WINDOW_MONTHS
        payload["_area_median_min_months"] = ABSORPTION_MIN_MONTHS
        payload["_area_median_projects"] = {
            segment: len(values) for segment, values in area_by_segment.items() if values
        }
        payload["_area_median_source"] = str(
            (dynamics or {}).get("source") or payload.get("source") or ""
        )
        return cls(payload)

    @property
    def available(self) -> bool:
        return bool(self.payload.get("current"))

    @property
    def observed_at(self) -> str | None:
        return self.payload.get("last_month")

    @property
    def source(self) -> str | None:
        return self.payload.get("source")

    COVERAGE_LABEL = "Москва старая"
    # Новая Москва в отчёт «Москва старая» не входит, хотя адрес там начинается
    # тем же словом. Признаки её округов перечислены явно, потому что «Москва»
    # в строке — не доказательство попадания в свод.
    _OUTSIDE = ("тао", "нао", "поселение", "новомосковск", "троицк", "зеленоград")

    def covers(self, address: str | None) -> bool:
        """Лежит ли объект внутри свода.

        Свод собран по одному отчёту — «Москва старая». Для Мытищ, Химок и
        Новой Москвы его медианы не значат ничего, а `snapshot()` смотрит
        только на класс и отдал бы их молча: отчёт по подмосковному проекту
        сравнивал бы его с московскими квартилями и выглядел бы исправным.
        """
        text = str(address or "").casefold()
        if not text:
            return False
        if "москва" not in text and "москв" not in text:
            return False
        return not any(mark in text for mark in self._OUTSIDE)

    def scope(self, address: str | None) -> dict[str, Any]:
        """Что сказать про сравнение с городом на этом адресе."""
        if not self.available:
            return {"covered": False, "label": self.COVERAGE_LABEL,
                    "reason": "Свод рынка не загружен"}
        if self.covers(address):
            return {"covered": True, "label": self.COVERAGE_LABEL, "reason": None}
        return {
            "covered": False,
            "label": self.COVERAGE_LABEL,
            "reason": (
                f"Свод собран по отчёту «{self.COVERAGE_LABEL}»; для этого адреса "
                "сравнение с городом не строится — соседи и класс считаются как обычно"
            ),
        }

    def segments(self) -> list[str]:
        return sorted(self.payload.get("current") or {})

    def area_median(self, segment: str | None) -> float | None:
        """Медиана продаж площади в м²/мес. по Москве для класса.

        Мера одна на всех читателей: медиана по проектам класса их СРЕДНЕГО
        месячного темпа за `ABSORPTION_WINDOW_MONTHS`. Второго эталона рядом не
        заводить — разойдясь, два знаменателя дали бы два достоверных на вид
        ответа об одном поглощении.
        """
        value = (self.payload.get("_area_median_by_segment") or {}).get(str(segment or ""))
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

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
            mortgage_median_pct=row.get("mortgage_median"),
            discount_projects=row.get("disc_projects"),
            discount_offering=row.get("disc_offering"),
            discount_median_offered_pct=row.get("disc_median_offered"),
            ddu_median=row.get("ddu_median"),
            ddu_projects=row.get("ddu_projects"),
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
