from __future__ import annotations

from auction_search import egrn_archive, egrn_extracts
from auction_search.documents import (
    DocumentAuthorizationRequired,
    DocumentExtractionError,
    download_document,
    extract_document_paragraphs,
)
from auction_search.krt import extract_krt_obligations, extract_krt_program
from auction_search.models import AuctionLot, LotKind


_PROGRAM_DOC_TYPES = {"krt_decision", "agreement", "notice", "annex", "other"}
_OBLIGATION_DOC_TYPES = {"agreement", "notice", "annex", "krt_decision", "other"}


def _read_egrn(document) -> dict:
    """Вложение с выписками → записи. Разбор выписки здесь не повторяется."""
    data, content_type, authenticated = download_document(document.url)
    document.access_status = "authenticated" if authenticated else "public"
    document.auth_required = False
    return egrn_archive.read(data, name=document.title or document.url)


def enrich_krt_from_official_documents(lot: AuctionLot) -> AuctionLot:
    """Programme, obligations and EGRN holders from official ETP attachments only.

    Extraction/auth failures are retained in `lot.raw['krt_document_warnings']`;
    the lot is never silently treated as having no obligations merely because a
    document is a scan or the ETP requires an authenticated service-account session.

    У вложений два разных вопроса, и вложение с выписками отвечает на свой:
    программа и обязательства живут в решении, договоре и извещении, а
    правообладатель участка — в выписке ЕГРН (`lot.raw['egrn']`, свод —
    `egrn_summary`). Прежде такие вложения пропускались одной строкой вместе с
    ГПЗУ, то есть собственники до лота не доезжали вовсе.
    """
    if lot.lot_kind != LotKind.KRT:
        return lot

    program = list(lot.krt_program)
    obligations = list(lot.obligations)
    warnings: list[dict[str, str]] = []

    parcels: list[dict] = []
    egrn_documents: list[dict] = []

    for document in lot.documents:
        # Выписки ЕГРН отвечают на свой вопрос — кто правообладатель участка и
        # чем он обременён, — и программу с обязательствами в них не ищут.
        # Прежде они пропускались одной строкой вместе с ГПЗУ, то есть
        # собственники до лота не доезжали вовсе, хотя разбор выписки у нас
        # есть с 18.08.2026 (владелец, 12.09.2026: «собственники участков и
        # зданий это важно и оно есть в документации на росэлторг»).
        if document.document_type == "egrn":
            # Отказ по вложению ЕГРН ложится и в общие предупреждения, и в сам
            # блок: без второй записи `lot.raw["egrn"]` не появляется вовсе, и
            # свод отвечает «не спрашивали» там, где площадка отказала. На лоте
            # 21000005000000033023 Росэлторг ответил 503 по трём вложениям —
            # ответ площадки, выданный за отсутствие вопроса.
            try:
                found = _read_egrn(document)
            except DocumentAuthorizationRequired as exc:
                document.access_status = "auth_required"
                document.auth_required = True
                warnings.append({"document": document.title, "url": document.url,
                                 "error": str(exc), "kind": "auth_required"})
                egrn_documents.append({
                    "document": document.title, "url": document.url,
                    "entries": 0, "read": 0, "unread": [], "companions": [],
                    "duplicates": [], "error": str(exc), "kind": "auth_required",
                })
                continue
            except DocumentExtractionError as exc:
                warnings.append({"document": document.title, "url": document.url,
                                 "error": str(exc), "kind": "extraction_error"})
                egrn_documents.append({
                    "document": document.title, "url": document.url,
                    "entries": 0, "read": 0, "unread": [], "companions": [],
                    "duplicates": [], "error": str(exc), "kind": "extraction_error",
                })
                continue
            parcels.extend(found["records"])
            egrn_documents.append({
                "document": document.title,
                "url": document.url,
                "entries": found["entries"],
                "read": found["read"],
                "unread": found["unread"],
                "companions": found["companions"],
                "duplicates": found["duplicates"],
            })
            # Запись, которую не прочитали, — наш пробел, и он назван: молча
            # выброшенная выписка читается как отсутствие собственника.
            if found["unread"]:
                warnings.append({
                    "document": document.title,
                    "url": document.url,
                    "error": "не прочитано: " + "; ".join(
                        f"{item['name']} — {item['reason']}" for item in found["unread"][:20]),
                    "kind": "egrn_unread",
                })
            continue
        if document.document_type == "gpzu":
            continue
        try:
            paragraphs = extract_document_paragraphs(document)
        except DocumentAuthorizationRequired as exc:
            document.access_status = "auth_required"
            document.auth_required = True
            warnings.append({
                "document": document.title,
                "url": document.url,
                "error": str(exc),
                "kind": "auth_required",
            })
            continue
        except DocumentExtractionError as exc:
            warnings.append({
                "document": document.title,
                "url": document.url,
                "error": str(exc),
                "kind": "extraction_error",
            })
            continue

        if document.document_type in _PROGRAM_DOC_TYPES:
            program.extend(
                extract_krt_program(
                    paragraphs,
                    source_url=document.url,
                    source_document=document.title,
                    fetched_at=document.fetched_at or lot.source.fetched_at,
                )
            )
        if document.document_type in _OBLIGATION_DOC_TYPES:
            obligations.extend(
                extract_krt_obligations(
                    paragraphs,
                    source_url=document.url,
                    source_document=document.title,
                    fetched_at=document.fetched_at or lot.source.fetched_at,
                )
            )

    lot.krt_program = _dedupe_program(program)
    lot.obligations = _dedupe_obligations(obligations)
    if egrn_documents:
        lot.raw["egrn"] = {
            "records": parcels,
            "lands": sum(1 for item in parcels if item.get("kind") == "land"),
            "builds": sum(1 for item in parcels if item.get("kind") == "build"),
            "documents": egrn_documents,
        }
    if warnings:
        lot.raw["krt_document_warnings"] = warnings
    lot.raw["krt_auth_required"] = any(w.get("kind") == "auth_required" for w in warnings)
    lot.raw["krt_extraction_complete"] = bool(lot.documents) and not warnings
    return lot


def egrn_summary(lot: AuctionLot) -> dict | None:
    """Кто правообладатель по выпискам лота. Второго ответа об этом нет.

    Личность сводится тем же `holder_key`, которым её сводит страница Нагатино:
    одна компания приходит и капсом, и обычным письмом, а субъект РФ то
    «Москва», то «город Москва» — сложенные по имени, они дают двух владельцев
    вместо одного. Право оперативного управления собственностью не считается:
    девять строений квартала записаны за городом, а держит их ГБУ.

    Незарегистрированное право — ответ документа, а не наш пробел, поэтому оно
    стоит своим числом, а не подмешивается к владельцам.

    Состояний три, и слить их нельзя. Вложений с выписками у лота нет — свода
    нет вовсе (`None`), это «не спрашивали». Вложения есть, а площадка
    отказала — свод есть, владельцев в нём нет, и отказ назван поимённо с
    причиной: 503 Росэлторга это ответ площадки, а не отсутствие вопроса.
    Прочитали — владельцы по ИНН.

    И у пустого ответа причина стоит рядом с числами (`reason`): машинной
    выписки в лоте может не быть вовсе — у Росэлторга выписки лотовой
    документации приходят печатными PDF (13.09.2026: пять живых КРТ-лотов, 32
    PDF и ни одного XML). «Владельцев нет» и «читать было нечего» на экране
    неразличимы, пока причина не написана.
    """
    egrn = lot.raw.get("egrn")
    if not egrn:
        return None
    records = egrn.get("records") or []
    owners: dict[str, dict] = {}
    without = 0
    for record in records:
        owner = egrn_extracts.owner_of(record)
        if not owner or not owner.get("name"):
            without += 1
            continue
        row = owners.setdefault(owner["key"], {
            "name": owner.get("name") or "", "inn": owner.get("inn") or "",
            "ogrn": owner.get("ogrn") or "", "kind": owner.get("kind") or "",
            "objects": 0, "area_sqm": 0.0,
        })
        row["objects"] += 1
        row["area_sqm"] += float(record.get("area_sqm") or 0)
    documents = egrn.get("documents") or []
    refused = [{"document": item.get("document") or "",
                "url": item.get("url") or "",
                "reason": item.get("error") or "",
                "kind": item.get("kind") or ""}
               for item in documents if item.get("error")]
    answered = [item for item in documents if not item.get("error")]
    companions = [companion for item in answered
                  for companion in (item.get("companions") or [])]
    print_forms = sum(1 for companion in companions
                      if companion.get("kind") == "print_form")
    unread = sum(len(item.get("unread") or []) for item in answered)
    rows = sorted(owners.values(), key=lambda row: (-row["objects"], row["name"]))
    return {
        "documents": len(documents),
        "answered": len(answered),
        "refused": refused,
        "records": len(records),
        "lands": egrn.get("lands", 0),
        "builds": egrn.get("builds", 0),
        "owners": rows,
        "without_registered_owner": without,
        "unread": unread,
        "companions": len(companions),
        "print_forms": print_forms,
        "reason": _egrn_reason(len(documents), len(answered), len(records),
                               len(rows), without, unread, print_forms),
    }


def _egrn_reason(documents: int, answered: int, records: int, owners: int,
                 without: int, unread: int, print_forms: int) -> str:
    """Почему владельцев не видно. Пустая строка — видно, объяснять нечего."""
    if owners:
        return ""
    if answered == 0:
        return (f"площадка не отдала ни одного вложения с выписками "
                f"(спросили {documents})")
    if records == 0 and print_forms and unread == 0:
        return (f"машинной выписки в лоте нет — приехала только печатная форма "
                f"({print_forms} файл(ов)), а разбор написан по XML")
    if records == 0 and unread:
        return f"выписки не прочитаны: {unread}"
    if records == 0:
        return "во вложении нет выписок"
    if without == records:
        return "право не зарегистрировано ни у одного объекта — так сказано в выписках"
    return ""


def _norm(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _dedupe_program(items):
    out = []
    seen: set[tuple] = set()
    for item in items:
        key = (item.category, item.area_sqm, item.quantity, _norm(item.source_text))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _dedupe_obligations(items):
    out = []
    seen: set[tuple] = set()
    for item in items:
        key = (item.category, item.quantity, item.unit, _norm(item.source_text))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
