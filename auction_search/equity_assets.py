"""Что стоит за долей: участок и здания общества — из документов лота.

Лот 178fz30102600019 (продажа 100% доли ООО «Фонвизина 8», 02.11.2026) — это
продажа общества-«обёртки», которому принадлежит земельный участок. В карточке
площадки участка нет вовсе: ни кадастра, ни площади; он назван только в
документах лота — в выписке ЕГРН и в лотовой документации. Чтобы посчитать
такой лот, нужен участок, цена доли как цена входа и срок приёма заявок.

Три правила, ради которых модуль написан отдельно.

**Адрес общества — не участок.** Юридический адрес «обёртки» (у этого лота —
другая улица, чем участок) ничего не говорит о её активе. Участок берётся
только по кадастровому номеру из документов лота; адреса общества модуль не
читает вовсе.

**Правообладатель решает, чей это объект.** Выписка, где правообладатель —
само общество (по имени в кавычках из названия лота или по ОГРН), — участок
общества. Выписка, где правообладатель не раскрыт, приложена продавцом к лоту
и берётся с пометкой. Выписка, где правообладатель — кто-то другой (сосед,
город), не берётся, и это названо, а не проглочено.

**Непрочитанное — «не знаем», а не «активов нет».** Отказ площадки, скан без
текста, пустой архив — каждый назван в `raw["equity_assets"]["refused"]`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from auction_search import archives, egrn_archive
from auction_search.documents import DocumentExtractionError, extract_document_paragraphs
from auction_search.krt_pipeline import _bytes_of, store_key
from auction_search.models import AuctionLot, LotKind, Provenance, utc_now_iso
from auction_search.parsing import cadastral_numbers

# Имя общества — в кавычках после его организационно-правовой формы.
_COMPANY = re.compile(
    r"(?iu)(?:\bООО\b|\bАО\b|\bПАО\b|\bЗАО\b|обществ\w*\s+с\s+ограниченн\w*\s+"
    r"ответственност\w*|акционерн\w*\s+обществ\w*)\s*[«\"“]+([^»\"”]{2,80})[»\"”]")
_OGRN = re.compile(r"(?iu)ОГРН\s*:?\s*(\d{13})")
# Предложение документации, где кадастровый номер назван активом общества:
# «Обществу на праве собственности принадлежит земельный участок с
# кадастровым номером …». Голый номер в тексте (соседний участок в описании
# окружения, номер квартала) активом не считается.
_OWNED = re.compile(
    r"(?iu)обществ\w*.{0,200}(?:принадлеж|собственност|аренд|актив|баланс)"
    r"|(?:принадлеж|собственност|аренд|актив|баланс).{0,200}обществ")
_SENTENCES = re.compile(r"(?<=[.;!?])\s+|\n+")


def _norm(value: str) -> str:
    return re.sub(r"[\s«»\"“”'`]+", " ", str(value or "").lower()).strip()


def company_of(lot: AuctionLot) -> dict[str, str]:
    """Имя и ОГРН общества, доля которого продаётся, — из названия лота."""
    title = str(lot.title or "")
    name = _COMPANY.search(title)
    ogrn = _OGRN.search(title)
    return {"name": name.group(1).strip() if name else "",
            "ogrn": ogrn.group(1) if ogrn else ""}


def _holders(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [holder for right in record.get("rights") or []
            for holder in right.get("holders") or []]


def _owner_verdict(record: dict[str, Any], company: dict[str, str]) -> str:
    """«company» — объект общества, «undisclosed» — правообладатель не раскрыт,
    «other» — правообладатель кто-то другой."""
    holders = [holder for holder in _holders(record) if holder.get("name") or holder.get("ogrn")]
    if not holders:
        return "undisclosed"
    for holder in holders:
        if company["ogrn"] and holder.get("ogrn") == company["ogrn"]:
            return "company"
        if company["name"] and _norm(company["name"]) in _norm(holder.get("name", "")):
            return "company"
    return "other"


def _from_text(paragraphs: list[str]) -> list[str]:
    numbers: list[str] = []
    for paragraph in paragraphs:
        for sentence in _SENTENCES.split(paragraph):
            if not _OWNED.search(sentence):
                continue
            for number in cadastral_numbers(sentence):
                if number not in numbers:
                    numbers.append(number)
    return numbers


def enrich_equity_from_documents(
        lot: AuctionLot, *, store_dir: Path | str | None = None,
        deadline: float | None = None) -> AuctionLot:
    """Участок и здания общества из выписок ЕГРН и текста документации лота.

    Найденный кадастр становится кадастром лота с происхождением; площадь и
    адрес участка — из выписки, а не из адреса общества. Дальше их берёт
    обычная передача в расчёт (`/auctions/ingest`: НСПД отделяет участок от
    здания), а цена доли остаётся ценой входа.
    """
    if lot.lot_kind is not LotKind.EQUITY_STAKE:
        return lot
    company = company_of(lot)
    store = Path(store_dir) if store_dir else None
    key = store_key(lot)
    taken: list[dict[str, Any]] = []
    not_taken: list[dict[str, Any]] = []
    refused: list[dict[str, str]] = []
    read = 0
    for document in lot.documents:
        if document.document_type == "gpzu":
            continue
        try:
            data, content_type, _came_from = _bytes_of(
                document, store=store, key=key, deadline=deadline)
        except DocumentExtractionError as exc:
            refused.append({"document": document.title, "url": document.url, "why": str(exc)})
            continue
        name = document.title or document.url
        # Выписки — по их разбору; печатную форму с распознаванием запускаем
        # только у вложения, которое площадка назвала выпиской: распознавать
        # всю лотовую документацию как выписку — трата срока без ответа.
        looks_like_extracts = (document.document_type == "egrn"
                               or (archives.looks_like_zip(data)
                                   and not archives.is_office_package(data))
                               or egrn_archive.looks_like_xml(data))
        records = egrn_archive.read(data, name=name)["records"] if looks_like_extracts else []
        for record in records:
            number = str(record.get("cadastral_number") or "")
            if not number:
                continue
            verdict = _owner_verdict(record, company)
            row = {
                "cadastral_number": number,
                "kind": record.get("kind") or "",
                "area_sqm": record.get("area_sqm"),
                "address": record.get("address") or "",
                "document": name,
                "evidence": {
                    "company": "выписка ЕГРН: правообладатель — само общество",
                    "undisclosed": ("выписка ЕГРН приложена к лоту; правообладатель "
                                    "в ней не раскрыт"),
                    "other": "выписка ЕГРН: правообладатель — не это общество",
                }[verdict],
            }
            (not_taken if verdict == "other" else taken).append(row)
        if document.document_type == "egrn":
            read += 1 if records else 0
            continue
        try:
            paragraphs = extract_document_paragraphs(document, data, content_type)
        except DocumentExtractionError as exc:
            if not records:
                refused.append({"document": document.title, "url": document.url,
                                "why": str(exc)})
            else:
                read += 1
            continue
        read += 1
        for number in _from_text(paragraphs):
            taken.append({"cadastral_number": number, "kind": "", "area_sqm": None,
                          "address": "", "document": name,
                          "evidence": "текст документации: объект назван имуществом общества"})

    # Один объект из двух документов — одна строка; выписка сильнее текста.
    by_number: dict[str, dict[str, Any]] = {}
    for row in taken:
        current = by_number.get(row["cadastral_number"])
        if current is None or (not current["kind"] and row["kind"]):
            by_number[row["cadastral_number"]] = row
    objects = list(by_number.values())
    lot.raw["equity_assets"] = {
        "company": company,
        "objects": objects,
        "not_taken": not_taken,
        "documents_read": read,
        "documents_asked": len([d for d in lot.documents if d.document_type != "gpzu"]),
        "refused": refused,
    }
    if not objects:
        return lot
    numbers = [row["cadastral_number"] for row in objects]
    lot.cadastral_numbers = sorted(set(lot.cadastral_numbers) | set(numbers))
    fetched_at = utc_now_iso()
    lot.provenance["cadastral_numbers"] = Provenance(
        source_url=lot.source.lot_url, fetched_at=fetched_at,
        source_section="документы лота: объекты общества",
        raw_value=", ".join(f"{row['cadastral_number']} ({row['evidence']}; {row['document']})"
                            for row in objects))
    land = [row for row in objects if row["kind"] == "land" and row["area_sqm"]]
    if land and lot.land_area_sqm is None:
        lot.land_area_sqm = float(sum(row["area_sqm"] for row in land))
        lot.provenance["land_area_sqm"] = Provenance(
            source_url=lot.source.lot_url, fetched_at=fetched_at,
            source_section="выписка ЕГРН участка общества",
            raw_value=", ".join(f"{row['cadastral_number']}: {row['area_sqm']} м²" for row in land))
    if land and not lot.address and land[0]["address"]:
        # Адрес УЧАСТКА из его выписки, а не адрес общества.
        lot.address = land[0]["address"]
        lot.provenance["address"] = Provenance(
            source_url=lot.source.lot_url, fetched_at=fetched_at,
            source_section="выписка ЕГРН участка общества", raw_value=land[0]["address"])
    return lot
