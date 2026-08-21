from __future__ import annotations

from auction_search.documents import (
    DocumentAuthorizationRequired,
    DocumentExtractionError,
    extract_document_paragraphs,
)
from auction_search.krt import extract_krt_obligations, extract_krt_program
from auction_search.models import AuctionLot, LotKind


_PROGRAM_DOC_TYPES = {"krt_decision", "agreement", "notice", "annex", "other"}
_OBLIGATION_DOC_TYPES = {"agreement", "notice", "annex", "krt_decision", "other"}


def enrich_krt_from_official_documents(lot: AuctionLot) -> AuctionLot:
    """Populate KRT program and obligations using only official ETP attachments.

    Extraction/auth failures are retained in `lot.raw['krt_document_warnings']`;
    the lot is never silently treated as having no obligations merely because a
    document is a scan or the ETP requires an authenticated service-account session.
    """
    if lot.lot_kind != LotKind.KRT:
        return lot

    program = list(lot.krt_program)
    obligations = list(lot.obligations)
    warnings: list[dict[str, str]] = []

    for document in lot.documents:
        if document.document_type in {"egrn", "gpzu"}:
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
    if warnings:
        lot.raw["krt_document_warnings"] = warnings
    lot.raw["krt_auth_required"] = any(w.get("kind") == "auth_required" for w in warnings)
    lot.raw["krt_extraction_complete"] = bool(lot.documents) and not warnings
    return lot


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
