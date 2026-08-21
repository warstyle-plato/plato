from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from auction_search.adapters import LotOnlineAdapter, RoseltorgAdapter
from auction_search.developaid_mapper import build_developaid_seed
from auction_search.documents import DocumentExtractionError
from auction_search.krt_pipeline import enrich_krt_from_official_documents
from auction_search.models import LotKind


class AuctionIngestRequest(BaseModel):
    url: str = Field(min_length=12, max_length=2000)
    enrich_krt_documents: bool = True
    include_raw: bool = False


def _adapter_for(url: str):
    host = (urlparse(url).hostname or "").lower()
    if host == "roseltorg.ru" or host.endswith(".roseltorg.ru"):
        return RoseltorgAdapter()
    if host == "lot-online.ru" or host.endswith(".lot-online.ru"):
        return LotOnlineAdapter()
    raise ValueError("Поддерживаются только официальные URL Росэлторг и РАД/Lot-online")


def install(app: FastAPI) -> None:
    if getattr(app.state, "auction_search_installed", False):
        return
    app.state.auction_search_installed = True

    @app.get("/auctions/sources")
    async def auction_sources() -> dict[str, Any]:
        return {
            "source_policy": "official_etp_only",
            "sources": [
                {
                    "id": "lot_online",
                    "name": "Российский аукционный дом / Lot-online",
                    "direct_lot_ingest": True,
                    "moscow_discovery": False,
                },
                {
                    "id": "roseltorg",
                    "name": "Росэлторг",
                    "direct_lot_ingest": True,
                    "moscow_discovery": False,
                },
            ],
            "note": "Discovery включается отдельно после фиксации официальных публичных search-endpoint площадок.",
        }

    @app.post("/auctions/ingest")
    async def auction_ingest(req: AuctionIngestRequest) -> dict[str, Any]:
        try:
            adapter = _adapter_for(req.url)
            lot = await run_in_threadpool(adapter.fetch_lot, req.url)
            if lot.lot_kind == LotKind.KRT and req.enrich_krt_documents:
                lot = await run_in_threadpool(enrich_krt_from_official_documents, lot)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DocumentExtractionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            # Platform outages/layout changes are upstream failures, not model errors.
            raise HTTPException(status_code=502, detail=f"Не удалось прочитать официальный лот: {exc}") from exc

        normalized = lot.to_dict()
        if not req.include_raw:
            normalized.pop("raw", None)
        return {
            "lot": normalized,
            "developaid_seed": build_developaid_seed(lot),
            "screening": {
                "legal_structure": lot.lot_kind.value,
                "requires_krt_terms": lot.lot_kind == LotKind.KRT,
                "krt_documents_complete": (
                    bool(lot.raw.get("krt_extraction_complete")) if lot.lot_kind == LotKind.KRT else None
                ),
                "ready_for_financial_model": (
                    bool(lot.krt_program or lot.obligations) and not lot.raw.get("krt_document_warnings")
                    if lot.lot_kind == LotKind.KRT
                    else bool(lot.cadastral_numbers and lot.start_price_rub is not None)
                ),
            },
        }
