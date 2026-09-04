"""Public Moscow KRT catalogue (krt.mos.ru) with a disk-backed snapshot.

The catalogue is discovery evidence, not a source of parcel geometry.  A
project is therefore resolved to an explicitly approximate geocoded point;
official decision geometry can be attached later without changing callers.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from .http import RemoteServiceError, fresh, load_json, request_bytes, save_json
from .krt_requirements import (
    decision_search_urls,
    document_attachments_url,
    document_detail_url,
    is_planned_project,
    merge_decision_requirements,
    parse_decision_requirements,
    parse_project_requirements,
    pdf_text,
    select_pdf_attachment,
    select_project_decision,
)


BASE_URL = "https://api.krt.mos.ru"
CATALOGUE_URL = BASE_URL + "/projects/"
JINA_PREFIX = "https://r.jina.ai/"
CACHE_SCHEMA_VERSION = 3
REQUIREMENTS_CACHE_SCHEMA_VERSION = 3
# Разбор карточки версионируется отдельно: он меняется чаще требований.
CARD_FACTS_SCHEMA_VERSION = 1
DECISIONS_CACHE_SCHEMA_VERSION = 2
TENDERS_CACHE_SCHEMA_VERSION = 1
MAP_CACHE_SCHEMA_VERSION = 1
# Поля записи решения — по ним кэш поднимается обратно в объект.
_DECISION_FIELDS = ("id", "title", "url", "address", "okrug", "kind",
                    "published_at", "department")
_SPACE = re.compile(r"\s+")
_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _map_name_key(value: Any) -> str:
    """Имя площадки как ключ: регистр, «ё» и знаки препинания не различают."""
    text = str(value or "").casefold().replace("ё", "е")
    return _SPACE.sub(" ", re.sub(r"[^0-9a-zа-я]+", " ", text)).strip()


# Сокращения адреса: список и карта портала пишут одно владение по-разному
# («Варшавское шоссе, вл. 37» и «Варшавское ш., влд. 37»), и точный ключ не
# совпадал — площадка уходила на геокодер, а на карте стояла чужая точка.
_ADDRESS_ABBREVIATIONS = (
    (r"\bшоссе\b", "ш"), (r"\bулица\b", "ул"), (r"\bпроспект\b", "пр"),
    (r"\bпр\s*кт\b", "пр"), (r"\bпереулок\b", "пер"), (r"\bнабережная\b", "наб"),
    (r"\bпроезд\b", "пр д"), (r"\bбульвар\b", "б р"), (r"\bплощадь\b", "пл"),
    (r"\bвладение\b", "вл"), (r"\bвлд\b", "вл"), (r"\bдом\b", "д"),
    (r"\bкорпус\b", "к"), (r"\bкорп\b", "к"), (r"\bстроение\b", "стр"),
)


def _address_key(value: Any) -> str:
    """Ключ адреса без разницы в сокращениях."""
    key = _map_name_key(value)
    for pattern, short in _ADDRESS_ABBREVIATIONS:
        key = re.sub(pattern, short, key)
    return _SPACE.sub(" ", key).strip()


def _address_parts(value: Any) -> list[str]:
    """Составное имя «адрес, вл. N, адрес, вл. M» — по одному адресу.

    Портал склеивает несколько владений в одно имя площадки; часть разделяет
    запятой, а внутри одного адреса запятая стоит перед номером владения.
    Поэтому режем по запятым и склеиваем «улица + номер» обратно.
    """
    pieces = [piece.strip() for piece in str(value or "").split(",") if piece.strip()]
    parts: list[str] = []
    for piece in pieces:
        if parts and re.match(r"^(вл\.?|влд\.?|владение|д\.?|дом|стр\.?|к\.?|корп\.?)\s*\S", piece, re.I):
            parts[-1] = parts[-1] + ", " + piece
        else:
            parts.append(piece)
    return [_address_key(part) for part in parts if _address_key(part)]


def _map_match(sites: list[dict[str, Any]], clean: str, name: str = "",
               project: dict[str, Any] | None = None) -> dict[str, Any]:
    """Найти площадку в записях файла карты — слагом, именем, адресом, паспортом.

    Правило совпадения одно на обе поверхности: карточка спрашивает про одну
    площадку, обзорная карта — про все 268 сразу, и второе правило разошлось
    бы с первым молча: одна площадка была бы «в файле» на карточке и «нет в
    файле» на карте, обе поверхности выглядели бы верными.
    """
    for site in sites:
        if str(site.get("slug") or "") == clean:
            return {"site": dict(site), "problem": "", "matched": "slug"}
    wanted = _map_name_key(name)
    if wanted:
        for site in sites:
            if _map_name_key(site.get("name")) == wanted:
                return {"site": dict(site), "problem": "", "matched": "name"}
    # Имя одно, записано по-разному: сокращения адреса и составные имена
    # из нескольких владений. У Варшавского ш., вл. 37 имя списка — два
    # адреса через запятую, и точный ключ не совпадал ни с чем (владелец,
    # 03.09.2026: «почему у него единственного нет верного контура»).
    wanted_key = _address_key(name)
    wanted_parts = set(_address_parts(name))
    if wanted_key:
        for site in sites:
            site_key = _address_key(site.get("name"))
            site_parts = set(_address_parts(site.get("name")))
            if site_key == wanted_key or (wanted_parts and site_parts & wanted_parts):
                return {"site": dict(site), "problem": "", "matched": "address"}
    # Последний ключ — паспорт: район, площадь и жилой объём в обоих
    # источниках из одного реестра.
    if project:
        twins = [site for site in sites if _same_territory(site, project)]
        if len(twins) == 1:
            return {"site": dict(twins[0]), "problem": "", "matched": "passport"}
    return {"site": None,
            "problem": f"площадки нет в файле карты реестра ({len(sites)} площадок)"}


def _same_territory(site: dict[str, Any], project: dict[str, Any]) -> bool:
    """Одна площадка по паспорту: район, площадь и жилой объём совпали.

    Имя у списка и у карты может расходиться, а ТЭП в обоих источниках один и
    тот же реестр: совпадение трёх паспортных чисел — не совпадение по
    случайности.
    """
    def num(item: dict[str, Any], key: str) -> float | None:
        try:
            value = float(item.get(key) or 0.0)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    district = _map_name_key(site.get("district"))
    if district and _map_name_key(project.get("district")) and \
            district != _map_name_key(project.get("district")):
        return False
    area, area_p = num(site, "area_ha"), num(project, "area_ha")
    housing, housing_p = num(site, "housing_gfa_sqm"), num(project, "housing_gfa_sqm")
    if not (area and area_p and housing and housing_p):
        return False
    return abs(area - area_p) <= 0.02 * max(area, area_p) and \
        abs(housing - housing_p) <= 0.01 * max(housing, housing_p)


@dataclass(frozen=True)
class KrtTerritory:
    slug: str
    name: str
    url: str
    area_ha: float | None = None
    okrug: str | None = None
    district: str | None = None
    status: str | None = None
    total_gfa_sqm: float | None = None
    housing_gfa_sqm: float | None = None
    nonresidential_gfa_sqm: float | None = None
    business_gfa_sqm: float | None = None
    jobs: float | None = None
    source: str = "krt.mos.ru"
    # Чем карточка не разобралась. Пустая строка — разобралась.
    parse_problem: str = ""

    @property
    def query(self) -> str:
        return "krt:" + self.slug

    @property
    def geocode_query(self) -> str:
        return ", ".join(filter(None, ("Москва", self.district, self.name)))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "query": self.query, "geocode_query": self.geocode_query,
                "geometry_status": "not_published_in_catalogue"}


class _CatalogueParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str, list[str]]] = []
        self._slug: str | None = None
        self._name = ""
        self._parts: list[str] = []
        self._capture_link = False
        self.next_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        href = values.get("href") or ""
        classes = values.get("class") or ""
        if tag == "a" and re.fullmatch(r"/projects/[^/?#]+/?", href):
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            if self._slug and slug != self._slug:
                self._flush()
            self._slug = slug
            self._capture_link = True
        if "show_more" in classes and values.get("data-url"):
            self.next_url = urljoin(BASE_URL, values["data-url"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._capture_link = False

    def handle_data(self, data: str) -> None:
        text = _SPACE.sub(" ", data).strip()
        if not text or not self._slug:
            return
        if self._capture_link and text.lower() != "подробнее" and not self._name:
            self._name = text
        elif ":" in text:
            self._parts.append(text)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        if self._slug and self._name:
            self.rows.append((self._slug, self._name, list(dict.fromkeys(self._parts))))
        self._slug, self._name, self._parts = None, "", []


def _number(text: str) -> float | None:
    found = _NUMBER.search(text.replace(" ", ""))
    return float(found.group(0).replace(",", ".")) if found else None


# Округа Москвы так, как их пишет сам каталог: ТАО и НАО там раздельно.
_OKRUGS = frozenset((
    "ЦАО", "САО", "СВАО", "ВАО", "ЮВАО", "ЮАО", "ЮЗАО", "ЗАО", "СЗАО",
    "ЗелАО", "ТАО", "НАО", "ТиНАО",
))


def parse_problem(row: KrtTerritory) -> str:
    """Чем разбор карточки не сошёлся сам с собой.

    Значения карточек иногда съезжают на поле: у «2-й Звенигородской» округом
    стал «Планируемый», статусом — хвост адреса «влд. 13», а общий объём вышел
    350 м² при жилье 27 580 (снимок прода, 31.08.2026). Такая строка молча
    доезжала до каталога, до балла и до экрана — и там пропадала, потому что
    её «округ» не проходит ни один флажок.

    Разбор проверяется тем, что известно о нём самом: округ из набора, статус
    из двух, общий объём не меньше жилого. Проверка не чинит съезд — она не
    даёт выдать неразобранное за разобранное.
    """
    problems: list[str] = []
    okrug = (row.okrug or "").strip()
    if okrug and okrug not in _OKRUGS:
        problems.append(f"округ «{okrug}» не из московских")
    status = (row.status or "").strip().casefold()
    if status and "планируем" not in status and "реализац" not in status:
        problems.append(f"статус «{row.status}» не опознан")
    total, housing = row.total_gfa_sqm, row.housing_gfa_sqm
    if total is not None and housing is not None and total < housing:
        problems.append("общий объём меньше жилого")
    return "; ".join(problems)


def _checked(row: KrtTerritory) -> KrtTerritory:
    """Строка каталога несёт свой диагноз с собой, а не теряет его по дороге."""
    problem = parse_problem(row)
    return replace(row, parse_problem=problem) if problem else row


def parse_catalogue(html: str) -> tuple[list[KrtTerritory], str | None]:
    parser = _CatalogueParser()
    parser.feed(html)
    parser.close()
    rows: list[KrtTerritory] = []
    for slug, name, parts in parser.rows:
        fields = {p.split(":", 1)[0].strip().lower(): p.split(":", 1)[1].strip() for p in parts}
        rows.append(_checked(KrtTerritory(
            slug=slug, name=name, url=f"{BASE_URL}/projects/{slug}",
            area_ha=_number(fields.get("площадь", "")),
            okrug=fields.get("округ"), district=fields.get("район"), status=fields.get("статус"),
            total_gfa_sqm=_number(fields.get("общий объем застройки", "")),
            housing_gfa_sqm=_number(fields.get("жилое назначение", "")),
            nonresidential_gfa_sqm=_number(fields.get("нежилое назначение", "")),
            business_gfa_sqm=_number(fields.get("общественно-деловое назначение", "")),
            jobs=_number(fields.get("прирост рабочих мест", "")),
        )))
    return rows, parser.next_url


_MARKDOWN_CARD = re.compile(
    r"\[([^\]\n]+?)\s*Подробнее\]\(https?://(?:api\.)?krt\.mos\.ru/projects/([^/?#)]+)\)"
)


def parse_catalogue_markdown(markdown: str) -> list[KrtTerritory]:
    """Parse the official page as rendered by the read-only transport fallback."""
    matches = list(_MARKDOWN_CARD.finditer(markdown))
    rows: list[KrtTerritory] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        block = markdown[match.end():end]
        fields: dict[str, str] = {}
        for line in block.splitlines():
            text = _SPACE.sub(" ", line).strip().strip("*")
            if ":" in text:
                key, value = text.split(":", 1)
                fields[key.strip().lower()] = value.strip()
        slug, name = match.group(2), match.group(1).strip()
        rows.append(_checked(KrtTerritory(
            slug=slug, name=name, url=f"{BASE_URL}/projects/{slug}",
            area_ha=_number(fields.get("площадь", "")),
            okrug=fields.get("округ"), district=fields.get("район"), status=fields.get("статус"),
            total_gfa_sqm=_number(fields.get("общий объем застройки", "")),
            housing_gfa_sqm=_number(fields.get("жилое назначение", "")),
            nonresidential_gfa_sqm=_number(fields.get("нежилое назначение", "")),
            business_gfa_sqm=_number(fields.get("общественно-деловое назначение", "")),
            jobs=_number(fields.get("прирост рабочих мест", "")),
        )))
    return rows


class KrtRegistry:
    def __init__(self, data_dir: Path, *, fetch: Callable[[str], bytes] | None = None) -> None:
        self.path = Path(data_dir) / "krt" / "catalogue.json"
        self.requirements_dir = Path(data_dir) / "krt" / "requirements"
        # Решения о КРТ на mos.ru — вход со стороны документа. Каталог отвечает
        # на «какие площадки город показывает», решения — на «о каких он принял
        # решение», и это разные множества.
        self.decisions_path = Path(data_dir) / "krt" / "decisions.json"
        self.tenders_path = Path(data_dir) / "krt" / "tender_orders.json"
        self.map_path = Path(data_dir) / "krt" / "map_dataset.json"
        # Разобранная карточка каталога: застройщик и реновация. Лежит рядом с
        # требованиями и по тому же правилу — хранится разобранное, не страница.
        self.card_facts_dir = Path(data_dir) / "krt" / "cards"
        # Контур площадки, собранный из участков ЕГРН по перечню проекта
        # решения, — для тех, кого нет в файле карты реестра. Участки ЕГРН не
        # двигаются, поэтому срок неделя; неответ ЕГРН помнится полчаса.
        self.outline_dir = Path(data_dir) / "krt" / "outlines"
        self.outline_ttl_seconds = 7 * 24 * 60 * 60
        # Отказ помнится полчаса: см. `card_facts`.
        self.card_facts_failure_ttl_seconds = 30 * 60
        self.tender_links_path = Path(data_dir) / "krt" / "tender_links.json"
        self.fetch = fetch or (lambda url: request_bytes(url, timeout=15, retries=1))
        self.ttl_seconds = 24 * 60 * 60
        self._refreshing = False
        self._refresh_lock = threading.Lock()
        self._decisions_refreshing = False
        self._decisions_lock = threading.Lock()
        self._cards_filling = False
        self._cards_lock = threading.Lock()
        self._outlines_filling = False
        self._outlines_lock = threading.Lock()

    def projects(self, *, refresh: bool = False, max_pages: int = 100) -> list[KrtTerritory]:
        cached = load_json(self.path)
        if (self._cache_current(cached) and not refresh and fresh(self.path, self.ttl_seconds)
                and cached.get("complete", True)):
            return self._decode(cached)
        rows: list[KrtTerritory] = []
        seen_urls: set[str] = set()
        seen_slugs: set[str] = set()

        def persist(*, complete: bool) -> None:
            if not rows:
                return
            save_json(self.path, {
                "schema_version": CACHE_SCHEMA_VERSION,
                "source": CATALOGUE_URL, "retrieved_at": int(time.time()),
                "complete": complete, "projects": [row.to_dict() for row in rows],
            })

        # The official host is primary. It occasionally drops all TCP traffic;
        # failure then switches the public catalogue only to a read-only page
        # renderer. User requests never wait for either path (see catalogue()).
        direct_complete = False
        try:
            url = CATALOGUE_URL
            for _ in range(max_pages):
                if not url or url in seen_urls:
                    direct_complete = True
                    break
                seen_urls.add(url)
                page, url = parse_catalogue(self.fetch(url).decode("utf-8", errors="replace"))
                if not page:
                    # Неразобранная страница — не конец каталога. Конец
                    # объявляет сам сайт отсутствием ссылки «показать ещё»;
                    # пустой разбор посреди обхода значит, что страница не
                    # прочиталась, и помечать усечённый список полным нельзя.
                    break
                new_rows = [row for row in page if row.slug not in seen_slugs]
                rows.extend(new_rows)
                seen_slugs.update(row.slug for row in new_rows)
                persist(complete=False)
        except (RemoteServiceError, OSError, UnicodeError):
            pass
        if rows and direct_complete:
            persist(complete=True)
            return rows

        # The renderer preserves the official page text and links. Pagination
        # has no reliable final-page marker, so a repeated page is the stop.
        try:
            previous: list[str] | None = None
            for page_number in range(1, max_pages + 1):
                suffix = "" if page_number == 1 else f"?PAGEN_1={page_number}"
                document = self.fetch(JINA_PREFIX + CATALOGUE_URL + suffix).decode(
                    "utf-8", errors="replace"
                )
                page = parse_catalogue_markdown(document)
                slugs = [row.slug for row in page]
                # Конец — повтор предыдущей страницы, а не «нет новых
                # площадок». Прямой путь мог оборваться на середине, и тогда
                # первая же страница запасного состоит из уже прочитанных:
                # обход останавливался на ней и объявлял усечённый список
                # полным. Пустая первая страница — отказ рендерера, а не конец.
                if slugs and previous is not None and slugs == previous:
                    persist(complete=True)
                    return rows
                if not page:
                    if previous is None:
                        break
                    persist(complete=True)
                    return rows
                previous = slugs
                new_rows = [row for row in page if row.slug not in seen_slugs]
                rows.extend(new_rows)
                seen_slugs.update(row.slug for row in new_rows)
                persist(complete=False)
        except (RemoteServiceError, OSError, UnicodeError):
            pass
        persist(complete=False)
        return rows or (self._decode(cached) if cached else [])

    @staticmethod
    def _decode(payload: Any) -> list[KrtTerritory]:
        out = []
        for raw in (payload or {}).get("projects", []):
            clean = {key: raw.get(key) for key in KrtTerritory.__dataclass_fields__}
            try:
                out.append(KrtTerritory(**clean))
            except (TypeError, ValueError):
                continue
        return out

    @staticmethod
    def _cache_current(payload: Any) -> bool:
        return bool(
            isinstance(payload, dict)
            and payload.get("schema_version") == CACHE_SCHEMA_VERSION
        )

    def find(self, query: str) -> dict[str, Any] | None:
        text = _SPACE.sub(" ", str(query or "")).strip()
        slug = text[4:] if text.lower().startswith("krt:") else None
        low = text.casefold()
        cached = load_json(self.path)
        rows = self._decode(cached) if cached else []
        if (not self._cache_current(cached) or not fresh(self.path, self.ttl_seconds)
                or not cached.get("complete", True)):
            self.refresh_in_background()
        for item in rows:
            if (slug and item.slug == slug) or (not slug and item.name.casefold() == low):
                return item.to_dict()
        return None

    def suggest(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        needle = _SPACE.sub(" ", str(query or "")).strip().casefold()
        if len(needle) < 2:
            return []
        cached = load_json(self.path)
        rows = self._decode(cached) if cached else []
        if (not self._cache_current(cached) or not fresh(self.path, self.ttl_seconds)
                or not cached.get("complete", True)):
            self.refresh_in_background()
        ranked = [row for row in rows if needle in row.name.casefold()
                  or needle in (row.district or "").casefold()]
        ranked.sort(key=lambda row: (not row.name.casefold().startswith(needle), row.name))
        return [row.to_dict() for row in ranked[:limit]]

    def catalogue(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        """Return the snapshot immediately; all network work stays off-thread.

        `refresh` — это нажатая человеком кнопка, и она обязана значить обход
        источника. Прежде обход начинался только у ПРОСРОЧЕННОГО снимка, и
        «Обновить каталог» на суточном сроке не читал ничего: страница
        перерисовывала тот же файл, а новая площадка ждала своего часа
        («Так я жал обновить, значит вручную не обновляется каталог?» —
        владелец, 04.09.2026). Кнопка, которая ничего не делает, хуже
        отсутствующей: по ней судят, что источник пуст.
        """
        cached = load_json(self.path)
        rows = self._decode(cached) if cached else []
        if (refresh or not self._cache_current(cached)
                or not fresh(self.path, self.ttl_seconds)
                or not cached.get("complete", True)):
            self.refresh_in_background()
        return [row.to_dict() for row in rows]

    def card_facts(self, slug: str, *, refresh: bool = False) -> dict[str, Any]:
        """Что говорит сама карточка: застройщик и реновация.

        Официальный источник и бесплатный — ни поиска, ни его квоты. Поэтому он
        идёт первым, а публикации остаются вторым слоем: у планируемой площадки
        застройщика ещё нет, и карточка о нём честно молчит.

        Читается для ЛЮБОГО статуса, в отличие от требований: решение читают
        только у планируемых, а имя застройщика ценно как раз у тех, кто уже в
        реализации — оно отвечает «войти нельзя и вот кто вошёл».
        """
        from . import krt_card_facts

        clean = str(slug or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{2,180}", clean):
            return {"available": False, "reason": "Неверный идентификатор площадки"}
        path = self.card_facts_dir / f"{clean}.json"
        cached = load_json(path)
        if (not refresh and isinstance(cached, dict)
                and cached.get("schema_version") == CARD_FACTS_SCHEMA_VERSION):
            # У отказа свой, короткий срок: он про минуту, когда источник не
            # ответил, а не про сутки. Держать его сутками значило бы выдать
            # разовый сбой за свойство площадки; не держать вовсе — стучаться
            # в город при каждом открытии каталога.
            ttl = (self.ttl_seconds if cached.get("available")
                   else self.card_facts_failure_ttl_seconds)
            if fresh(path, ttl):
                return cached
        url = f"{BASE_URL}/projects/{clean}"
        try:
            page = self.fetch(url).decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            # Не ответила карточка — это «не спросили», а не «застройщика нет».
            # Отказ ЗАПИСЫВАЕТСЯ, и это важнее, чем кажется: прежде он не
            # сохранялся вовсе, поэтому неотвечающая карточка не становилась
            # «известной» никогда — фоновой добор перечитывал её при каждом
            # открытии каталога, а посчитать, что не отвечает НИ ОДНА, было
            # нечем. Общая причина (просроченный корень, смена адреса) выглядела
            # на экране ровно как «реновации тут нет».
            failure = {"available": False, "slug": clean, "source_url": url,
                       "schema_version": CARD_FACTS_SCHEMA_VERSION,
                       "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "reason": f"{type(exc).__name__}: {exc}"}
            save_json(path, failure)
            return failure
        out = krt_card_facts.parse(page)
        out.update({"schema_version": CARD_FACTS_SCHEMA_VERSION, "available": True,
                    "slug": clean, "source_url": url})
        save_json(path, out)
        return out

    def card_facts_known(self, slugs: list[str] | tuple[str, ...]) -> dict[str, dict[str, Any]]:
        """Что о карточках УЖЕ прочитано — с диска, без единого запроса.

        Карточка называет застройщика бесплатно, а читалась она только в
        платном прогоне каталога: пока прогона не было, колонка занятости
        пустовала у всех подряд, и «мы не спрашивали» читалось как «оператора
        нет» (владелец, 01.09.2026: «где очевидно что КРТ уже с оператором —
        ничего не стоит»). Бесплатный официальный источник не должен зависеть
        от платного.

        Здесь именно ЗНАЕМ, а не спрашиваем: маршрут каталога не имеет права
        ходить в сеть 263 раза, пока человек ждёт ответа.
        """
        out: dict[str, dict[str, Any]] = {}
        for slug in slugs:
            clean = str(slug or "").strip()
            if not re.fullmatch(r"[a-zA-Z0-9_-]{2,180}", clean):
                continue
            cached = load_json(self.card_facts_dir / f"{clean}.json")
            if (isinstance(cached, dict)
                    and cached.get("schema_version") == CARD_FACTS_SCHEMA_VERSION):
                out[clean] = cached
        return out

    def card_facts_coverage(self, slugs: list[str] | tuple[str, ...]) -> dict[str, Any]:
        """Сколько карточек города прочитано, сколько не ответило и почему.

        Молчащая проверка неотличима от отсутствующей: фоновой добор ловит
        отказ каждой карточки по отдельности и читает дальше — «не ответила
        одна, остальные читаем», — и когда не отвечает НИ ОДНА, на экране это
        выглядит как «реновации и застройщика тут нет». Общая причина (корень
        сертификата, смена адреса) обязана быть названа один раз и вслух.
        """
        read = failed = unknown = 0
        reasons: dict[str, int] = {}
        for slug in slugs:
            clean = str(slug or "").strip()
            if not re.fullmatch(r"[a-zA-Z0-9_-]{2,180}", clean):
                continue
            cached = load_json(self.card_facts_dir / f"{clean}.json")
            if not (isinstance(cached, dict)
                    and cached.get("schema_version") == CARD_FACTS_SCHEMA_VERSION):
                unknown += 1
                continue
            if cached.get("available"):
                read += 1
                continue
            failed += 1
            # Причина сворачивается до вида ошибки: двести строк с разными
            # адресами внутри — это одна причина, а не двести.
            reason = str(cached.get("reason") or "источник не ответил")
            short = reason.split(":")[0].strip() or reason
            reasons[short] = reasons.get(short, 0) + 1
        return {
            "read": read, "failed": failed, "unknown": unknown,
            "reasons": dict(sorted(reasons.items(), key=lambda pair: -pair[1])),
        }

    def fill_card_facts_in_background(self, slugs: list[str] | tuple[str, ...],
                                      *, limit: int = 40) -> bool:
        """Дочитать карточки, которых ещё нет, — фоном и порциями.

        Порция намеренно ограничена: каталог из 263 площадок за один заход —
        это 263 запроса подряд к сайту города, и он вправе счесть это налётом.
        Следующее чтение каталога дочитает следующую порцию; через несколько
        открытий колонка заполнена целиком.

        Работу берёт один: воркеров два, память у них раздельная, и без замка
        оба пошли бы читать одно и то же.
        """
        clean = [str(slug or "").strip() for slug in slugs]
        missing = [slug for slug in clean
                   if re.fullmatch(r"[a-zA-Z0-9_-]{2,180}", slug or "")
                   and not fresh(self.card_facts_dir / f"{slug}.json", self.ttl_seconds)]
        if not missing:
            return False
        with self._cards_lock:
            if self._cards_filling:
                return False
            self._cards_filling = True

        def run() -> None:
            try:
                for slug in missing[:max(1, int(limit))]:
                    try:
                        self.card_facts(slug)
                    except Exception:  # noqa: BLE001
                        # Не ответила одна карточка — остальные читаем дальше:
                        # один отказ не должен оставлять колонку пустой у всех.
                        continue
            finally:
                with self._cards_lock:
                    self._cards_filling = False

        threading.Thread(target=run, name="krt-card-facts", daemon=True).start()
        return True

    def requirements(self, slug: str, *, refresh: bool = False) -> dict[str, Any] | None:
        """Read one planned KRT card and its official project-decision PDF."""
        clean_slug = str(slug or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{2,180}", clean_slug):
            return None
        project = next(
            (item for item in self.catalogue() if item.get("slug") == clean_slug), None)
        if not project:
            return None
        if not is_planned_project(project):
            return {
                "schema_version": REQUIREMENTS_CACHE_SCHEMA_VERSION,
                "slug": clean_slug,
                "name": project.get("name"),
                "status": project.get("status"),
                "available": False,
                "skipped": True,
                "warning": "Документы читаются только для планируемых КРТ.",
            }
        cache_path = self.requirements_dir / f"{clean_slug}.json"
        cached = load_json(cache_path)
        if (not refresh and fresh(cache_path, self.ttl_seconds)
                and isinstance(cached, dict)
                and cached.get("schema_version") == REQUIREMENTS_CACHE_SCHEMA_VERSION):
            return cached

        source_url = str(project.get("url") or f"{BASE_URL}/projects/{clean_slug}")
        document = ""
        transport = "official_host"
        errors: list[str] = []
        # The KRT host currently presents a certificate chain that standard
        # server trust stores reject.  The renderer transports the same public
        # page and returns in seconds; the official host remains a fallback.
        # The legally relevant PDF below is always downloaded directly from
        # mos.ru and never through the renderer.
        for url, label in ((JINA_PREFIX + source_url, "read_only_renderer"),
                           (source_url, "official_host")):
            try:
                document = self.fetch(url).decode("utf-8", errors="replace")
            except (RemoteServiceError, OSError, UnicodeError) as exc:
                errors.append(f"{label}: {type(exc).__name__}: {exc}")
                continue
            if document.strip():
                transport = label
                break
        result = parse_project_requirements(document, project)
        result["status"] = project.get("status")

        def remote_json(url: str, label: str) -> Any | None:
            try:
                return json.loads(self.fetch(url).decode("utf-8"))
            except (RemoteServiceError, OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(f"{label}: {type(exc).__name__}: {exc}")
                return None

        decision = None
        for index, search_url in enumerate(decision_search_urls(project), start=1):
            payload = remote_json(search_url, f"mos_search_{index}")
            decision = select_project_decision(payload, project)
            if decision:
                break

        decision_meta: dict[str, Any] | None = None
        if decision:
            document_id = str(decision.get("id") or "").strip()
            detail = remote_json(document_detail_url(document_id), "mos_document_detail")
            institution_id = (detail or {}).get("institution_id")
            if institution_id is not None:
                attachments = remote_json(
                    document_attachments_url(document_id, institution_id),
                    "mos_document_attachments",
                )
                pdf_url = select_pdf_attachment(attachments)
                if pdf_url:
                    try:
                        pdf_data = self.fetch(pdf_url)
                        if len(pdf_data) > 35 * 1024 * 1024:
                            raise RuntimeError("PDF проекта решения превышает 35 МБ")
                        facts = parse_decision_requirements(
                            pdf_text(pdf_data), str(decision.get("title") or ""))
                        decision_meta = {
                            "id": document_id,
                            "title": decision.get("title"),
                            "page_url": decision.get("url"),
                            "pdf_url": pdf_url,
                            "published_at": (detail or {}).get("date_published"),
                        }
                        result = merge_decision_requirements(result, facts, decision_meta)
                    except (RemoteServiceError, OSError, RuntimeError) as exc:
                        errors.append(f"mos_decision_pdf: {type(exc).__name__}: {exc}")
                else:
                    errors.append("mos_document_attachments: PDF не опубликован")
            else:
                errors.append("mos_document_detail: не указан орган публикации")

        if decision_meta is None:
            result["decision_available"] = False
            result["warning"] = (
                "В официальном поиске mos.ru не найден читаемый проект решения для этой "
                "карточки. Показаны только ТЭП и текст krt.mos.ru; отсутствие сведений "
                "о сносе или расселении не означает, что их нет."
            )
        else:
            result["decision_available"] = True
        result.update({
            "schema_version": REQUIREMENTS_CACHE_SCHEMA_VERSION,
            "available": True,
            "retrieved_at": int(time.time()),
            "transport": transport,
            "errors": errors[:3],
        })
        save_json(cache_path, result)
        return result

    def decisions(self, *, refresh: bool = False, max_pages: int = 60) -> dict[str, Any]:
        """Решения о КРТ и разложение их на «карточка есть» и «карточки нет».

        Кэш держит САМИ решения, а разложение считается на каждом чтении. Иначе
        площадка, у которой карточка появилась час назад, до суток стоит в
        списке дважды: строкой каталога и строкой «без карточки» из вчерашнего
        разложения («когда карточка появится, она обновится в списке?» —
        владелец, 31.08.2026). Кэшировать надо ответ источника, а не соединение
        двух списков: второй меняется чаще первого.

        Недособранный список, выданный за полный, читается как «таких решений
        больше нет», поэтому `complete` едет вместе с числами, а не вместо них.
        """
        from . import krt_decisions

        cached = load_json(self.decisions_path)
        payload: dict[str, Any] | None = None
        if (not refresh and isinstance(cached, dict)
                and cached.get("schema_version") == DECISIONS_CACHE_SCHEMA_VERSION
                and fresh(self.decisions_path, self.ttl_seconds)):
            payload = dict(cached)
        if payload is None:
            found, complete = krt_decisions.collect(self.fetch, max_pages=max_pages)
            if not found and isinstance(cached, dict) and cached.get("all"):
                # Источник не ответил — прежний ответ честнее пустого списка, и
                # он назван прежним.
                payload = dict(cached)
                payload["stale"] = True
            else:
                payload = {
                    "schema_version": DECISIONS_CACHE_SCHEMA_VERSION,
                    "retrieved_at": int(time.time()),
                    "complete": complete,
                    "stale": False,
                    "all": [one.to_dict() for one in found],
                    "query": krt_decisions.MOS_KRT_QUERY,
                }
                save_json(self.decisions_path, payload)
        rows = [krt_decisions.KrtDecision(**{key: value for key, value in one.items()
                                             if key in _DECISION_FIELDS})
                for one in (payload.get("all") or [])]
        split = krt_decisions.match_catalogue(rows, self.catalogue())
        out = dict(payload)
        # Когда снят снимок решений — часть ответа: без даты «577 решений»
        # читается как ответ источника сию секунду.
        out["ttl_seconds"] = int(self.ttl_seconds)
        out["total"] = split["total"]
        out["matched"] = len(split["matched"])
        out["decisions"] = [one.to_dict() for one in split["unmatched"]]
        # Сопоставленные — не только счёт: у площадки каталога появляется дата
        # её проекта решения и ссылка на документ. Прежде дата была только у
        # тех, у кого карточки нет, и колонка «Проект решения» у остальных
        # стояла пустой, будто документа не существует.
        out["matched_rows"] = [
            {"slug": one.matched_slug, "published_at": one.published_at,
             "url": one.url, "title": one.title}
            for one in split["matched"] if one.matched_slug]
        return out

    def map_dataset(self, *, refresh: bool = False, step_m: float = 40.0) -> dict[str, Any]:
        """Реестр КРТ картой: 263 площадки с полигонами официальных границ.

        Постраничный список отдаёт 136, наш прежний снимок держал 124 — то есть
        половина каталога до нас не доезжала. Здесь весь реестр одним файлом, и
        у каждой записи есть контур: карточка перестаёт говорить «официальный
        полигон границ пока не получен».
        """
        from . import krt_map_data

        cached = load_json(self.map_path)
        if (not refresh and isinstance(cached, dict)
                and cached.get("schema_version") == MAP_CACHE_SCHEMA_VERSION
                and cached.get("step_m") == step_m
                and fresh(self.map_path, self.ttl_seconds)):
            return cached
        try:
            sites = krt_map_data.read(self.fetch, step_m)
        except Exception as exc:  # noqa: BLE001
            if isinstance(cached, dict) and cached.get("sites"):
                stale = dict(cached)
                stale["stale"] = True
                stale["error"] = f"{type(exc).__name__}: {exc}"
                return stale
            raise
        payload = {
            "schema_version": MAP_CACHE_SCHEMA_VERSION,
            "retrieved_at": int(time.time()),
            "source": krt_map_data.DATASET_URL,
            "step_m": step_m,
            "stale": False,
            "count": len(sites),
            "bbox_merc": krt_map_data.bbox(sites),
            "sites": sites,
        }
        save_json(self.map_path, payload)
        return payload

    def map_lookup(self, slug: str, name: str = "",
                   project: dict[str, Any] | None = None) -> dict[str, Any]:
        """Площадка из файла карты и ПРИЧИНА, если её там не нашлось.

        Прежде отказ был один на два разных случая: файл карты не прочитан
        (сеть, сертификат) и площадки в файле нет. Оба возвращали `None`, и
        карточка писала одно и то же — «площадки нет в файле карты», — а на
        экране это выглядело как чужая точка без объяснения (владелец,
        02.09.2026: «там не то на карте место указано»). Молчание источника
        нельзя показывать как его отрицательный ответ.

        Слаг сверяется первым: он приходит из ссылки портала и в обоих
        источниках один. Не совпал — пробуем имя: у списка и у карты оно
        одинаковой строкой, а слаг портал пишет по-разному
        («varshavskoe-shosse-…» против «varshavskoe-sh-…»), и одна такая
        разница молча уводила карточку на геокодер.
        """
        clean = str(slug or "").strip()
        if not clean:
            return {"site": None, "problem": "слаг площадки не задан"}
        try:
            payload = self.map_dataset()
        except Exception as exc:  # noqa: BLE001 — это не «нет контура», а «нет ответа»
            return {"site": None,
                    "problem": f"файл карты реестра не прочитан: {type(exc).__name__}"}
        return _map_match((payload or {}).get("sites") or [], clean, name, project)

    def map_site(self, slug: str, name: str = "",
                 project: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Площадка из файла карты: официальный контур и центр."""
        return self.map_lookup(slug, name, project).get("site")

    def decision_outline(self, slug: str, *, lookup: Callable[[list[str]], list[dict[str, Any]]],
                         refresh: bool = False, max_numbers: int = 60) -> dict[str, Any]:
        """Контур площадки из участков ЕГРН по перечню проекта решения.

        Файл карты реестра — не весь реестр: у 35 строк каталога из 268 в нём
        нет записи, и у Варшавского ш., вл. 37 контур не приезжал никаким
        сопоставлением имён (владелец, 04.09.2026: «и что с контуром КРТ
        Нагатино? почему его до сих пор нет»). Проект решения о КРТ при этом
        перечисляет состав территории — участки и здания с кадастровыми
        номерами, — а ЕГРН отдаёт контур каждого участка (`lookup` — путь
        движка `_land_lookup_by_numbers`, второго клиента НСПД здесь нет).

        Ответ подписан своим именем: это состав территории ПО ДОКУМЕНТУ, а не
        официальный полигон границ. Здания контур не задают (их пятна лежат
        внутри участков), ненайденные номера названы числом: молча выброшенный
        участок читается как «его нет в территории».
        """
        clean = str(slug or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{2,180}", clean):
            return {"rings_merc": [], "centre_merc": None, "problem": "слаг площадки не задан"}
        cache_path = self.outline_dir / f"{clean}.json"
        cached = load_json(cache_path)
        if not refresh and isinstance(cached, dict) and cached.get("schema_version") == 1:
            ttl = (self.outline_ttl_seconds if cached.get("rings_merc")
                   else self.card_facts_failure_ttl_seconds)
            if fresh(cache_path, ttl):
                return dict(cached)
        requirements = self.requirements(clean)
        numbers = list((requirements or {}).get("cadastral_numbers") or [])
        decision = dict((requirements or {}).get("decision") or {})
        if requirements and requirements.get("skipped"):
            problem = "перечень участков читается из проекта решения, а он есть только у планируемых площадок"
        elif not requirements or not requirements.get("available"):
            problem = "требования по площадке не читаются"
        elif not decision:
            problem = "проект решения о КРТ на mos.ru не найден — перечня участков нет"
        elif not numbers:
            problem = "в проекте решения нет кадастровых номеров участков"
        else:
            problem = ""
        result: dict[str, Any] = {
            "schema_version": 1,
            "slug": clean,
            "decision": {key: decision.get(key) for key in ("title", "page_url", "pdf_url")},
            "numbers_source": str((requirements or {}).get("cadastral_numbers_source") or "none"),
            "counts": {"numbers": len(numbers), "asked": 0, "land": 0, "buildings": 0,
                       "missing": 0},
            "parcels": [],
            "rings_merc": [],
            "centre_merc": None,
            "area_ha": None,
            "problem": problem,
            "retrieved_at": int(time.time()),
        }
        if problem:
            save_json(cache_path, result)
            return result
        asked = numbers[:max_numbers]
        result["counts"]["asked"] = len(asked)
        if len(numbers) > max_numbers:
            result["problem"] = (f"в перечне {len(numbers)} номеров, опрошены первые "
                                 f"{max_numbers}: контур неполный")
        try:
            found = list(lookup(asked) or [])
        except Exception as exc:  # noqa: BLE001 — неответ ЕГРН называется, а не молчит
            result["problem"] = f"ЕГРН не ответил: {type(exc).__name__}"
            save_json(cache_path, result)
            return result
        rings: list[list[list[float]]] = []
        area_sqm = 0.0
        for item in found:
            if not isinstance(item, dict) or not item.get("found"):
                result["counts"]["missing"] += 1
                continue
            if str(item.get("kind") or "") != "land":
                result["counts"]["buildings"] += 1
                continue
            contour = [ring for ring in (item.get("contour_merc") or [])
                       if isinstance(ring, list) and len(ring) >= 3]
            if not contour:
                result["counts"]["missing"] += 1
                continue
            result["counts"]["land"] += 1
            rings.extend(contour)
            area = item.get("area_sqm")
            if isinstance(area, (int, float)):
                area_sqm += float(area)
            result["parcels"].append({
                "cadastral_number": str(item.get("cadastral_number") or ""),
                "area_sqm": area if isinstance(area, (int, float)) else None,
            })
        result["rings_merc"] = rings
        if rings:
            points = [point for ring in rings for point in ring]
            xs = [float(p[0]) for p in points]
            ys = [float(p[1]) for p in points]
            result["centre_merc"] = [(min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0]
            result["area_ha"] = round(area_sqm / 10000.0, 2) if area_sqm else None
        elif not result["problem"]:
            result["problem"] = "ни один номер перечня не найден в ЕГРН как участок с контуром"
        save_json(cache_path, result)
        return result

    def outline_cached(self, slug: str) -> dict[str, Any] | None:
        """Контур из решения, если он УЖЕ посчитан. Сеть здесь не трогается.

        Обзорная карта рисует весь каталог сразу, и спрашивать ЕГРН по перечню
        каждой недостающей площадки внутри запроса нельзя — это десятки
        обходов на одно открытие. Поэтому карта показывает прочитанное, а
        дочитывает фон (`fill_outlines_in_background`).

        Просроченный ответ здесь годится: контур участка меняется реже, чем
        живёт кэш, а не нарисовать вовсе — это показать площадку как
        отсутствующую в реестре.
        """
        clean = str(slug or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{2,180}", clean):
            return None
        cached = load_json(self.outline_dir / f"{clean}.json")
        if isinstance(cached, dict) and cached.get("schema_version") == 1:
            return dict(cached)
        return None

    def map_supplement(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Площадки каталога, которых нет в файле карты города, — и что с ними.

        Файл карты реестра несёт 263 записи, каталог — 268, и совпадают не все:
        у части строк нет соответствия ни слагом, ни именем, ни паспортом. На
        обзорной карте их не было вовсе, и про Нагатино владелец спросил трижды
        (04.09.2026: «На карте крт Нагатино так и нет. Хотя контур в карточке
        верный»). Контур им собирает тот же путь, что уже у карточки, — участки
        ЕГРН по перечню проекта решения; здесь он только читается из кэша.

        Ответ разделяет три состояния, и это главное: **нарисовано по решению**,
        **перечень не спрашивали** (наш пробел, дочитает фон) и **спросили, а
        контура нет** — с причиной документа. Слитые в одно «не нарисовано»,
        они читались бы как отсутствие площадки в реестре.
        """
        try:
            data = payload if isinstance(payload, dict) else self.map_dataset()
        except Exception as exc:  # noqa: BLE001 — неответ файла карты не «нет площадок»
            return {"sites": [], "gaps": [],
                    "counts": {"catalogue": 0, "in_map": 0, "drawn": 0,
                               "unread": 0, "no_outline": 0},
                    "problem": f"файл карты реестра не прочитан: {type(exc).__name__}"}
        sites = list((data or {}).get("sites") or [])
        try:
            rows = list(self.catalogue())
        except Exception as exc:  # noqa: BLE001
            return {"sites": [], "gaps": [],
                    "counts": {"catalogue": 0, "in_map": len(sites), "drawn": 0,
                               "unread": 0, "no_outline": 0},
                    "problem": f"каталог не прочитан: {type(exc).__name__}"}
        extra: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        in_map = unread = no_outline = 0
        for row in rows:
            slug = str(row.get("slug") or "").strip()
            if not slug:
                continue
            name = str(row.get("name") or "")
            if _map_match(sites, slug, name, dict(row)).get("site"):
                in_map += 1
                continue
            outline = self.outline_cached(slug)
            if outline is None:
                unread += 1
                gaps.append({"slug": slug, "name": name, "kind": "unread",
                             "reason": "перечень участков решения ещё не читали"})
                continue
            rings = list(outline.get("rings_merc") or [])
            if not rings:
                no_outline += 1
                gaps.append({"slug": slug, "name": name, "kind": "no_outline",
                             "reason": str(outline.get("problem")
                                           or "в решении нет участков с контуром")})
                continue
            centre = outline.get("centre_merc")
            extra.append({
                "slug": slug,
                "url": str(row.get("url") or ""),
                "name": name,
                "status": str(row.get("status") or ""),
                "okrug": str(row.get("okrug") or ""),
                "district": str(row.get("district") or ""),
                "area_ha": row.get("area_ha"),
                "housing_gfa_sqm": row.get("housing_gfa_sqm"),
                "rings_merc": rings,
                "centre_merc": centre,
                # Контур подписан своим происхождением: это состав территории
                # ПО ДОКУМЕНТУ, а не официальный полигон границ, и рисуется он
                # иначе. Одинаково нарисованные, два источника выглядели бы
                # одним, и приближение читалось бы как граница города.
                "outline_source": "decision",
                "outline_area_ha": outline.get("area_ha"),
                "outline_note": str(outline.get("problem") or ""),
            })
        return {
            "sites": extra,
            "gaps": gaps,
            "counts": {"catalogue": len(rows), "in_map": in_map, "drawn": len(extra),
                       "unread": unread, "no_outline": no_outline},
            "problem": "",
        }

    def fill_outlines_in_background(
            self, slugs: list[str] | tuple[str, ...],
            *, lookup: Callable[[list[str]], list[dict[str, Any]]],
            limit: int = 8) -> bool:
        """Дочитать перечни решений тех площадок, которых нет в файле карты.

        Порция мала намеренно: за одним слагом стоит проект решения на mos.ru,
        распознавание скана и до шестидесяти запросов в ЕГРН — десяток таких
        подряд город вправе счесть налётом. Следующее открытие карты дочитает
        следующую порцию.

        Работу берёт один: воркеров два, память у них раздельная, и без замка
        оба пошли бы читать одно и то же.
        """
        clean = [str(slug or "").strip() for slug in slugs]
        missing = [slug for slug in clean
                   if re.fullmatch(r"[a-zA-Z0-9_-]{2,180}", slug or "")
                   and self.outline_cached(slug) is None]
        if not missing:
            return False
        with self._outlines_lock:
            if self._outlines_filling:
                return False
            self._outlines_filling = True

        def run() -> None:
            try:
                for slug in missing[:max(1, int(limit))]:
                    try:
                        self.decision_outline(slug, lookup=lookup)
                    except Exception:  # noqa: BLE001
                        # Не ответила одна площадка — читаем остальные: один
                        # отказ не должен оставлять карту без всех контуров.
                        continue
            finally:
                with self._outlines_lock:
                    self._outlines_filling = False

        threading.Thread(target=run, name="krt-decision-outlines", daemon=True).start()
        return True
    def _read_order_details(self, order: dict[str, Any]) -> dict[str, Any]:
        """Распознать скан одного распоряжения. Отказ называется, а не молчит."""
        from . import krt_requirements as requirements
        from . import krt_tender_orders as orders

        blank = {"ocr_done": False, "ocr_notes": []}
        if not orders.ocr_available():
            return {**blank, "ocr_notes": ["в образе нет tesseract — скан не распознать"]}
        try:
            page = json.loads(self.fetch(
                requirements.document_detail_url(str(order.get("id") or ""))).decode("utf-8"))
            files = json.loads(self.fetch(requirements.document_attachments_url(
                str(order.get("id") or ""), page.get("institution_id"))).decode("utf-8"))
            pdf_url = requirements.select_pdf_attachment(files)
            if not pdf_url:
                return {**blank, "ocr_notes": ["у распоряжения нет PDF"]}
            text = orders.ocr(self.fetch(pdf_url))
        except Exception as exc:  # noqa: BLE001
            return {**blank, "ocr_notes": [f"{type(exc).__name__}: {exc}"[:200]]}
        parsed = orders.parse_order(text)
        return {
            "address": parsed.get("address", ""),
            "krt_name": parsed.get("krt_name", ""),
            "start_price_rub": parsed.get("start_price_rub"),
            "step_rub": parsed.get("step_rub"),
            "deposit_rub": parsed.get("deposit_rub"),
            "ocr_notes": parsed.get("notes") or [],
            "ocr_done": True,
        }

    def tender_link(self, slug: str = "") -> dict[str, Any]:
        """Привязки «распоряжение — площадка», проставленные человеком.

        Машине привязать нечем: адреса в распоряжении нет ни в заголовке, ни в
        карточке документа, а PDF — скан (семь страниц, 199 картинок на первой,
        текста только регистрационный штамп). Разложить 53 распоряжения по
        площадкам может только тот, кто их открыл, поэтому отметка ставится
        руками и хранится с датой: это утверждение человека, а не наш вывод, и
        подписано оно так же.
        """
        marks = load_json(self.tender_links_path)
        marks = marks if isinstance(marks, dict) else {}
        return marks.get(str(slug)) or {} if slug else marks

    def mark_tender(self, slug: str, order: dict[str, Any], who: str = "") -> dict[str, Any]:
        """Отметить, что по этой площадке объявлены торги — по такому-то документу."""
        marks = load_json(self.tender_links_path)
        marks = marks if isinstance(marks, dict) else {}
        clean = str(slug or "").strip()
        if not clean:
            raise ValueError("площадка не названа")
        if not order:
            marks.pop(clean, None)
            save_json(self.tender_links_path, marks)
            return {}
        entry = {
            "order_id": str(order.get("id") or "").strip(),
            "number": str(order.get("number") or "").strip(),
            "url": str(order.get("url") or "").strip(),
            "published_at": int(order.get("published_at") or 0),
            "kind": str(order.get("kind") or "").strip(),
            "marked_at": int(time.time()),
            "marked_by": str(who or "").strip(),
        }
        marks[clean] = entry
        save_json(self.tender_links_path, marks)
        return entry

    def tender_orders(self, *, refresh: bool = False, max_pages: int = 12) -> dict[str, Any]:
        """Распоряжения ДГП о проведении торгов по КРТ.

        Адреса в них нет — ни в заголовке, ни в карточке документа, а PDF скан.
        Поэтому это факт со ссылкой и датой, а не привязка к площадке.
        """
        from . import krt_decisions

        cached = load_json(self.tenders_path)
        if (not refresh and isinstance(cached, dict)
                and cached.get("schema_version") == TENDERS_CACHE_SCHEMA_VERSION
                and fresh(self.tenders_path, self.ttl_seconds)):
            return cached
        found, complete = krt_decisions.collect_tender_orders(
            self.fetch, max_pages=max_pages)
        if not found and isinstance(cached, dict) and cached.get("orders"):
            stale = dict(cached)
            stale["stale"] = True
            return stale
        found.sort(key=lambda one: one.get("published_at") or 0, reverse=True)
        # Адрес площадки лежит в СКАНЕ распоряжения, и другого места у него нет.
        # Распознаётся один раз и кладётся рядом с записью: без этого привязку
        # пришлось бы ставить руками, то есть возвращать работу человеку.
        previous = {str(one.get("id")): one for one in
                    ((cached or {}).get("orders") or []) if isinstance(one, dict)}
        for one in found:
            was = previous.get(str(one.get("id"))) or {}
            if was.get("ocr_done"):
                one.update({key: was[key] for key in
                            ("address", "krt_name", "start_price_rub", "step_rub",
                             "deposit_rub", "ocr_notes", "ocr_done") if key in was})
                continue
            one.update(self._read_order_details(one))
        payload = {
            "schema_version": TENDERS_CACHE_SCHEMA_VERSION,
            "retrieved_at": int(time.time()),
            "complete": complete,
            "stale": False,
            "orders": found,
            "query": krt_decisions.MOS_TENDER_QUERY,
            # Сказать это обязан сам свод: молча непривязанные распоряжения
            # читаются как «торгов по нашим площадкам нет».
            "note": ("Адреса в распоряжении нет: ни в заголовке, ни в карточке "
                     "документа, а PDF — скан. Привязать распоряжение к площадке "
                     "нечем; лот на площадке ищется отдельно, по торгам."),
        }
        save_json(self.tenders_path, payload)
        return payload

    def status(self) -> dict[str, Any]:
        """Полнота снимка, ход обхода и КОГДА снимок снят.

        Даты не было, и на экране «577 решений» выглядело как ответ источника
        сию секунду, хотя снимок мог быть суточной давности: новую площадку
        города не видно, а понять это можно только измерением со стороны
        (владелец, 04.09.2026). Возраст снимка — часть ответа, как метод опроса
        у НСПД.
        """
        cached = load_json(self.path)
        stamp = 0
        try:
            stamp = int(self.path.stat().st_mtime)
        except OSError:
            stamp = 0
        return {
            "complete": bool(
                self._cache_current(cached) and cached.get("complete", True)
            ),
            "refreshing": self._refreshing,
            "decisions_refreshing": self._decisions_refreshing,
            "retrieved_at": stamp,
            "ttl_seconds": int(self.ttl_seconds),
        }

    def refresh_in_background(self) -> bool:
        with self._refresh_lock:
            if self._refreshing:
                return False
            self._refreshing = True

        def run() -> None:
            try:
                self.projects(refresh=True)
            finally:
                with self._refresh_lock:
                    self._refreshing = False

        threading.Thread(target=run, name="krt-catalogue-refresh", daemon=True).start()
        return True

    def refresh_decisions_in_background(self) -> bool:
        """Перечитать решения mos.ru, не держа соединение с человеком.

        Обход шестидесяти страниц поиска в срок ответа не укладывается, а
        кнопка обязана ответить сразу: работу принимают, а не держат
        соединением. Ход виден полем `decisions_refreshing` — страница
        доспрашивает, пока обход идёт.
        """
        with self._decisions_lock:
            if self._decisions_refreshing:
                return False
            self._decisions_refreshing = True

        def run() -> None:
            try:
                self.decisions(refresh=True)
            except Exception:  # noqa: BLE001 — отказ источника не роняет процесс
                pass
            finally:
                with self._decisions_lock:
                    self._decisions_refreshing = False

        threading.Thread(target=run, name="krt-decisions-refresh", daemon=True).start()
        return True
