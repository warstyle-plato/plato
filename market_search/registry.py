"""Справочник проектов: якорь вместо угадывания имён из прозы.

До сих пор конвейер шёл от поиска: найти документы, угадать в них название,
доказать, что это проект, доказать адрес. Каждый шаг воевал с шумом, и каждая
сборка приносила новый его вид — «Мичуринский проспект», «Донстрой»,
«2 квартал 2026 года», «Прямо напротив».

Здесь курс развёрнут. Есть внешний реестр проектов — помесячный отчёт о
продажах по ДДУ, где у каждого проекта названы девелопер, округ, район и объём
продаж. Всё, что в нём есть, — заведомо настоящий проект; всего, чего в нём нет,
конвейер не выдумывает. Поиску остаётся один узкий вопрос: сколько стоит метр в
известном проекте известного девелопера.

Чего реестр не даёт:

* цен — их в отчёте нет вовсе;
* сданных и распроданных домов — отчёт про ДДУ, а у готового дома их нет.
  Именно поэтому на Саввинской набережной он не знает ни Хамовники 12, ни
  Саввинскую 27: они сданы. Реестр дополняет поиск, а не заменяет его.

Зато он даёт то, что ТЗ считало недостижимым без отдельного провайдера: темп
продаж, штук в месяц.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .normalize import canonical_key, labels_match


OKRUGS = (
    "ЦАО", "САО", "СВАО", "ВАО", "ЮВАО", "ЮАО", "ЮЗАО", "ЗАО", "СЗАО",
    "ЗелАО", "ТАО", "НАО", "ТиНАО",
)


@dataclass(frozen=True)
class RegistryProject:
    name: str
    developer: str | None = None
    okrug: str | None = None
    district: str | None = None
    # {"2026-06": 4, "2026-07": 6} — штук ДДУ за месяц.
    sales: dict[str, int] = field(default_factory=dict)
    source: str | None = None

    @property
    def key(self) -> str:
        return canonical_key(self.name)

    def velocity(self) -> dict[str, Any]:
        """Темп продаж: последний месяц, предыдущий и изменение."""
        if not self.sales:
            return {"units_per_month": None, "quality": "unknown"}
        months = sorted(self.sales)
        last = months[-1]
        previous = months[-2] if len(months) > 1 else None
        current = self.sales[last]
        result: dict[str, Any] = {
            "units_per_month": current,
            "observed_at": last,
            "source": self.source,
            "quality": "registry",
        }
        if previous is not None:
            before = self.sales[previous]
            result["previous_units_per_month"] = before
            result["previous_observed_at"] = previous
            if before:
                result["change_pct"] = round((current - before) / before * 100, 1)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "developer": self.developer,
            "okrug": self.okrug,
            "district": self.district,
            "sales": dict(self.sales),
            "source": self.source,
        }


class ProjectRegistry:
    """Справочник в памяти. Пустой справочник — не ошибка, а прежнее поведение."""

    def __init__(self, projects: list[RegistryProject] | None = None):
        self.projects = list(projects or [])
        self._by_key = {item.key: item for item in self.projects if item.key}

    def __len__(self) -> int:
        return len(self.projects)

    @property
    def available(self) -> bool:
        return bool(self.projects)

    @classmethod
    def bundled_directory(cls) -> Path:
        """Выгрузки, уезжающие вместе с кодом.

        Каталог данных в контейнере перекрывается томом, поэтому справочник,
        положенный в `data/`, до рантайма не доезжает. Базовая выгрузка живёт
        рядом с кодом, а свежие — в каталоге данных, поверх неё.
        """
        return Path(__file__).resolve().parent / "registry_data"

    @classmethod
    def load(cls, *directories: Path) -> "ProjectRegistry":
        """Собрать справочник из всех выгрузок указанных каталогов.

        Отчёт помесячный, поэтому файлов может быть несколько; продажи по одному
        проекту сливаются, а не затирают друг друга. Более поздний файл уточняет
        более ранний, но не стирает его данные.
        """
        merged: dict[str, RegistryProject] = {}
        paths: list[Path] = []
        for directory in directories:
            try:
                paths.extend(sorted(Path(directory).glob("*.json")))
            except OSError:
                continue
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for row in payload.get("projects") or []:
                item = RegistryProject(
                    name=str(row.get("name") or "").strip(),
                    developer=(row.get("developer") or None),
                    okrug=(row.get("okrug") or None),
                    district=(row.get("district") or None),
                    sales={str(k): int(v) for k, v in (row.get("sales") or {}).items()},
                    source=str(row.get("source") or payload.get("source") or path.name),
                )
                if not item.name or not item.key:
                    continue
                existing = merged.get(item.key)
                if existing is None:
                    merged[item.key] = item
                    continue
                merged[item.key] = RegistryProject(
                    name=existing.name,
                    developer=existing.developer or item.developer,
                    okrug=existing.okrug or item.okrug,
                    district=existing.district or item.district,
                    sales={**existing.sales, **item.sales},
                    source=item.source or existing.source,
                )
        return cls(list(merged.values()))

    def by_district(self, district: str | None) -> list[RegistryProject]:
        if not district:
            return []
        target = _fold(district)
        return [item for item in self.projects if item.district and _fold(item.district) == target]

    def find(self, name: str) -> RegistryProject | None:
        """Проект справочника по названию, с учётом сокращений и алфавита."""
        key = canonical_key(name)
        if key and key in self._by_key:
            return self._by_key[key]
        for item in self.projects:
            if labels_match(name, [item.name]):
                return item
        return None


def _fold(value: str) -> str:
    return re.sub(r"[^а-яa-z0-9]+", "", str(value or "").lower().replace("ё", "е"))


# --- разбор помесячного отчёта о продажах -------------------------------------


def parse_sales_report(lines: list[str], *, months: list[str], source: str) -> list[dict[str, Any]]:
    """Собрать строки отчёта в записи справочника.

    Якорем служит округ: он из закрытого списка и в отчёте стоит между
    девелопером и районом. Опираться на номер строки нельзя — нумерация в отчёте
    прерывается, а колонки не выровнены.
    """
    clean = [" ".join(str(line).split()) for line in lines]
    clean = [line for line in clean if line]
    out: list[dict[str, Any]] = []
    for index, line in enumerate(clean):
        if line not in OKRUGS:
            continue
        if index < 2 or index + 1 >= len(clean):
            continue
        developer = clean[index - 1]
        name = clean[index - 2]
        district = clean[index + 1]
        if not name or _looks_numeric(name) or _looks_numeric(developer):
            continue
        sales: dict[str, int] = {}
        for offset, month in enumerate(months, start=2):
            position = index + offset
            if position >= len(clean):
                break
            value = _units(clean[position])
            if value is not None:
                sales[month] = value
        out.append(
            {
                "name": name,
                "developer": developer,
                "okrug": line,
                "district": district,
                "sales": sales,
                "source": source,
            }
        )
    return out


def _looks_numeric(value: str) -> bool:
    return bool(re.fullmatch(r"[\d\s,.%+-]+", str(value or "").strip()))


def _units(value: str) -> int | None:
    """Число ДДУ за месяц. «старт» и «н/д» — не ноль, а отсутствие данных."""
    text = str(value or "").strip().lower()
    if text in {"старт", "н/д", "нд", "-", "—"}:
        return None
    if re.fullmatch(r"\d{1,4}", text):
        return int(text)
    return None
