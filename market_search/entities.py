"""Разрешение сущности ЖК: много кандидатов из разных источников — один проект.

Дедупликация в v5 шла по одному ключу — нормализованной строке названия. Ключ
считался от «сырого» заголовка, поэтому «Savvin River Residence», «Саввин Ривер
Резиденс» и «Savvin River Residence - купить квартиру» были тремя проектами.

Здесь тождество опирается на три независимых признака, в порядке надёжности:

1. внешний идентификатор карточки агрегатора — жёсткий якорь;
2. совпадение канонического ключа названия (алфавит и очередь уже свёрнуты);
3. близость названий выше порога — только вместе с географией, поэтому это
   слияние выполняется после геокодирования.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .candidates_v6 import Candidate
from .normalize import canonical_key, name_similarity, same_project


_MERGE_SIMILARITY = 0.88
_MERGE_DISTANCE_KM = 0.25


@dataclass
class ProjectEntity:
    key: str
    canonical_name: str
    aliases: set[str] = field(default_factory=set)
    external_ids: set[str] = field(default_factory=set)
    developers: set[str] = field(default_factory=set)
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def search_rank(self) -> int:
        return min((item.search_rank for item in self.candidates), default=10_000)

    @property
    def extraction_confidence(self) -> float:
        return max((item.extraction_confidence for item in self.candidates), default=0.0)

    @property
    def source_domains(self) -> set[str]:
        return {item.source_domain for item in self.candidates if item.source_domain}

    @property
    def project_pages(self) -> list[Candidate]:
        return [item for item in self.candidates if item.source_kind == "project_page"]

    @property
    def primary_candidate(self) -> Candidate:
        return sorted(
            self.candidates,
            key=lambda item: (-item.extraction_confidence, item.search_rank),
        )[0]

    def absorb(self, other: "ProjectEntity") -> None:
        self.aliases.update(other.aliases)
        self.aliases.add(other.canonical_name)
        self.external_ids.update(other.external_ids)
        self.developers.update(other.developers)
        self.candidates.extend(other.candidates)
        self.canonical_name = _best_label(self.canonical_name, other.canonical_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.canonical_name,
            "aliases": sorted(alias for alias in self.aliases if alias != self.canonical_name),
            "external_ids": sorted(self.external_ids),
            "developer": sorted(self.developers)[0] if self.developers else None,
            "extraction_confidence": round(self.extraction_confidence, 2),
            "discovery_sources": sorted(self.source_domains),
            "discovery_source_count": len(self.source_domains),
            "has_project_page": bool(self.project_pages),
        }


def _best_label(left: str, right: str) -> str:
    """Полная брендовая вывеска предпочтительнее её сокращения.

    «Клубный квартал Фрунзенский» и «Фрунзенский» сходятся в одну сущность;
    показывать надо ту форму, под которой проект продаётся.

    Номер очереди — исключение из правила «длиннее значит полнее»: «Хамовники XII»
    длиннее «Хамовники 12», но проект продаётся под арабской записью, и именно её
    ждёт golden acceptance.
    """
    if canonical_key(left) != canonical_key(right):
        return left
    left_roman, right_roman = _ends_with_roman(left), _ends_with_roman(right)
    if left_roman != right_roman:
        return right if left_roman else left
    if len(right) > len(left):
        return right
    return left


def _ends_with_roman(value: str) -> bool:
    tokens = str(value or "").split()
    if len(tokens) < 2:
        return False
    return bool(re.fullmatch(r"[IVXivx]+", tokens[-1].strip(".,")))


def resolve_entities(candidates: list[Candidate]) -> list[ProjectEntity]:
    """Слияние по идентификатору агрегатора и по каноническому ключу названия."""
    entities: list[ProjectEntity] = []
    by_key: dict[str, ProjectEntity] = {}
    by_external: dict[str, ProjectEntity] = {}

    for candidate in candidates:
        target = by_key.get(candidate.key)
        if target is None and candidate.external_id:
            target = by_external.get(candidate.external_id)

        if target is None:
            target = ProjectEntity(
                key=candidate.key,
                canonical_name=candidate.canonical_name,
                aliases={candidate.canonical_name},
            )
            entities.append(target)
        else:
            target.aliases.add(candidate.canonical_name)
            target.canonical_name = _best_label(target.canonical_name, candidate.canonical_name)

        target.candidates.append(candidate)
        if candidate.external_id:
            target.external_ids.add(candidate.external_id)
            by_external[candidate.external_id] = target
        if candidate.developer:
            target.developers.add(candidate.developer)
        by_key[candidate.key] = target
        by_key.setdefault(target.key, target)

    # Второй проход: один внешний идентификатор мог склеить две группы ключей.
    merged: list[ProjectEntity] = []
    owner: dict[str, ProjectEntity] = {}
    for entity in entities:
        target = None
        for external in entity.external_ids:
            if external in owner:
                target = owner[external]
                break
        if target is None:
            merged.append(entity)
            target = entity
        elif target is not entity:
            target.absorb(entity)
        for external in target.external_ids:
            owner[external] = target

    merged = _merge_similar_labels(merged)
    return sorted(merged, key=lambda item: (item.search_rank, item.canonical_name.lower()))


def _same_site_conflict(left: ProjectEntity, right: ProjectEntity) -> bool:
    """Две разные карточки одного агрегатора — это два разных проекта."""
    def by_site(entity: ProjectEntity) -> dict[str, set[str]]:
        table: dict[str, set[str]] = {}
        for external in entity.external_ids:
            site = external.split(":", 1)[0]
            table.setdefault(site, set()).add(external)
        return table

    left_ids, right_ids = by_site(left), by_site(right)
    for site, ids in left_ids.items():
        other = right_ids.get(site)
        if other and not (ids & other):
            return True
    return False


def _merge_similar_labels(entities: list[ProjectEntity]) -> list[ProjectEntity]:
    """Свести вывески, разошедшиеся на транслитерации.

    Порог высокий и подпёрт номером очереди: «Savvin River Residence» и «Саввин
    Ривер Резиденс» — один проект, «Петровский парк» и «Петровский парк II» — нет,
    хотя по буквам они ближе.
    """
    result: list[ProjectEntity] = []
    for entity in entities:
        target = None
        for existing in result:
            if _same_site_conflict(existing, entity):
                continue
            if not same_project(existing.canonical_name, entity.canonical_name):
                continue
            target = existing
            break
        if target is None:
            result.append(entity)
        else:
            target.absorb(entity)
    return result


def merge_geographic_duplicates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Схлопнуть проекты, оказавшиеся одним объектом на карте.

    Разные вывески одной стройки («Savvin River Residence» и «Саввин Ривер
    Резиденс») переживают ключевое слияние, если транслит разошёлся. Совпадение
    координат в пределах 250 м вместе с похожим названием — это один проект, а
    не два аналога, и в рекомендацию он должен входить один раз.
    """
    from .service import haversine_km

    result: list[dict[str, Any]] = []
    for row in rows:
        point = row.get("coordinates") or {}
        latitude, longitude = point.get("latitude"), point.get("longitude")
        target = None
        if latitude is not None and longitude is not None:
            for existing in result:
                other = existing.get("coordinates") or {}
                if other.get("latitude") is None or other.get("longitude") is None:
                    continue
                distance = haversine_km(
                    float(latitude), float(longitude), float(other["latitude"]), float(other["longitude"])
                )
                if distance > _MERGE_DISTANCE_KM:
                    continue
                if name_similarity(str(row.get("name") or ""), str(existing.get("name") or "")) < _MERGE_SIMILARITY:
                    continue
                target = existing
                break
        if target is None:
            result.append(row)
            continue
        aliases = set(target.get("aliases") or []) | set(row.get("aliases") or [])
        aliases.add(str(row.get("name") or ""))
        aliases.discard(str(target.get("name") or ""))
        target["aliases"] = sorted(alias for alias in aliases if alias)
        target["name"] = _best_label(str(target.get("name") or ""), str(row.get("name") or ""))
        target["merged_from"] = sorted(set(target.get("merged_from") or []) | {str(row.get("name") or "")})
        # Слитая вывеска приносит свои карточки: без этого источники поглощённого
        # проекта пропадали, и цена искалась по половине доказательств.
        absorbed, keeper = row.get("_entity"), target.get("_entity")
        if absorbed is not None and keeper is not None and absorbed is not keeper:
            keeper.absorb(absorbed)
            target["external_ids"] = sorted(keeper.external_ids)
            target["discovery_sources"] = sorted(keeper.source_domains)
            target["discovery_source_count"] = len(keeper.source_domains)
            target["market_source_count"] = max(len(keeper.source_domains), 1)
    return result
