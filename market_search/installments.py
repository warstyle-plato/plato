"""Рассрочка соседей: чем проект торгует помимо цены.

Файл `moscow-installments-*.json` собирает импорт свода TrendAgent
(`installments_import`). Отвечает он на вопрос, которого нет ни у «Пульса», ни у
bnMAP: сравнение цен у нас витрина против витрины, а витрину двигает рассрочка —
сосед с тем же прайсом, нулевым взносом и годом рассрочки продаёт мягче, чем
выглядит в таблице цен.

Охват назван числом и не прячется: свод накрывает 175 наших проектов из 685.
У соседа вне свода условий НЕТ — это «не знаем», а не «рассрочки не даёт»;
разница между этими двумя ответами здесь и хранится (`has_installment` умеет
быть `False`, а отсутствие проекта в своде даёт пустой ответ).

Ключ — идентификатор проекта, а где его нет (у bnMAP свои строки), имя
разрешается тем же `canonical_key`, что и везде: второго правила «это один
проект» в модуле не бывает.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .normalize import canonical_key


class Installments:
    """Свод в памяти. Пустой файл — не ошибка, а прежнее поведение отчёта."""

    BUNDLED_GLOB = "moscow-installments-*.json"

    def __init__(self, payload: dict[str, Any] | None = None):
        self.payload = payload or {}
        self._projects: dict[str, Any] = self.payload.get("projects") or {}
        self._by_name: dict[str, str] = {}
        for identifier, project in self._projects.items():
            key = canonical_key(str(project.get("name") or ""))
            if key:
                self._by_name.setdefault(key, str(identifier))

    @classmethod
    def bundled(cls, directory: Path | None = None) -> "Installments":
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
                # Битый файл не отменяет прежний: отчёт живёт и без рассрочек.
                continue
        return cls(newest)

    @property
    def available(self) -> bool:
        return bool(self._projects)

    @property
    def source(self) -> str:
        return str(self.payload.get("source") or "")

    @property
    def saved_at(self) -> str:
        return str(self.payload.get("saved_at") or "")

    @property
    def covered(self) -> int:
        return len(self._projects)

    @property
    def registry_projects(self) -> int:
        return int(self.payload.get("registry_projects") or 0)

    def facts(
        self, complex_id: int | str | None = None, name: str | None = None
    ) -> dict[str, Any]:
        """Условия рассрочки в строку проекта.

        Ключи одни у объекта и у соседа. Проекта нет в своде — не кладём ничего:
        пустой ключ читался бы как ответ источника.
        """
        found = self._projects.get(str(complex_id or ""))
        if found is None and name:
            identifier = self._by_name.get(canonical_key(name))
            if identifier is not None:
                found = self._projects.get(identifier)
        if not found:
            return {}
        out: dict[str, Any] = {"installment": bool(found.get("has_installment"))}
        for key in ("down_payment_pct", "term_months", "keys_before_payment", "price_terms"):
            if found.get(key) is not None:
                out["installment_" + key] = found[key]
        if found.get("programs"):
            out["installment_programs"] = int(found["programs"])
        return out
