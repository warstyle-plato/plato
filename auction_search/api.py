from __future__ import annotations

import os
import sys
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from auction_search.adapters import LotOnlineAdapter, RoseltorgAdapter
from auction_search.bridge import auction_page_with_handoff, install_page_bridge
from auction_search.developaid_mapper import build_developaid_seed
from auction_search.documents import DocumentExtractionError
from auction_search.krt_pipeline import enrich_krt_from_official_documents
from auction_search.models import LotKind
from auction_search.preset_mapper import build_project_preset
from auction_search.service import AuctionSearchService
from auction_search.ui import auctions_page


class AuctionIngestRequest(BaseModel):
    url: str = Field(min_length=12, max_length=2000)
    enrich_krt_documents: bool = True
    include_raw: bool = False


_LOTONLINE_PROJECT_SHARES_FLAG = "AUCTION_LOTONLINE_PROJECT_SHARES_DISCOVERY"


def _feature_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _lot_online_discovery_adapter() -> LotOnlineAdapter:
    return LotOnlineAdapter(
        include_project_shares=_feature_enabled(_LOTONLINE_PROJECT_SHARES_FLAG),
    )


def _adapter_for(url: str):
    host = (urlparse(url).hostname or "").lower()
    if host == "roseltorg.ru" or host.endswith(".roseltorg.ru"):
        return RoseltorgAdapter()
    if host == "lot-online.ru" or host.endswith(".lot-online.ru"):
        return LotOnlineAdapter()
    raise ValueError("Поддерживаются только официальные URL Росэлторг и РАД/Lot-online")


def _discovery_adapters(source: str):
    value = (source or "all").strip().lower()
    if value in {"lot_online", "rad", "lot-online"}:
        return [_lot_online_discovery_adapter()]
    if value in {"roseltorg", "ros"}:
        return [RoseltorgAdapter()]
    if value == "all":
        return [_lot_online_discovery_adapter(), RoseltorgAdapter()]
    raise ValueError("source: all, lot_online или roseltorg")


def _public_lot_dict(lot) -> dict[str, Any]:
    data = lot.to_dict()
    data.pop("raw", None)
    return data


def install(app: FastAPI) -> None:
    if getattr(app.state, "auction_search_installed", False):
        return
    app.state.auction_search_installed = True

    # main.py loads the canonical legacy core as `developaid_core`. Inject only the
    # same-origin handoff bootstrap; no calculation or project UI is duplicated.
    core = sys.modules.get("developaid_core")
    if core is not None:
        install_page_bridge(core)

    @app.get("/auctions", response_class=HTMLResponse)
    async def auctions_home() -> HTMLResponse:
        return HTMLResponse(
            auction_page_with_handoff(auctions_page()),
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    @app.get("/auctions/sources")
    async def auction_sources() -> dict[str, Any]:
        return {
            "source_policy": "official_etp_only",
            "sources": [
                {
                    "id": "lot_online",
                    "name": "Российский аукционный дом / Lot-online",
                    "direct_lot_ingest": True,
                    "moscow_discovery": True,
                    "discovery_access": "public_catalogue",
                    "project_company_shares_discovery": {
                        "enabled": _feature_enabled(_LOTONLINE_PROJECT_SHARES_FLAG),
                        "rollout": "explicit_runtime_flag",
                    },
                },
                {
                    "id": "roseltorg",
                    "name": "Росэлторг",
                    "direct_lot_ingest": True,
                    "moscow_discovery": True,
                    "discovery_access": "public_tags_search",
                },
            ],
            "document_access": "public_first_optional_service_account_session",
        }

    @app.get("/auctions/discover")
    async def auction_discover(
        source: str = Query(default="all"),
        include_noise: bool = Query(default=False),
    ) -> dict[str, Any]:
        """Discover current Moscow opportunities from official public ETP catalogues.

        This endpoint does not download/parse every attachment. Full KRT document
        extraction happens only through `/auctions/ingest` for a selected lot.
        """
        try:
            adapters = _discovery_adapters(source)
            service = AuctionSearchService(adapters)
            lots = await run_in_threadpool(lambda: service.discover_moscow(include_noise=include_noise))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Не удалось получить публичный каталог ЭТП: {exc}") from exc

        return {
            "source_policy": "official_etp_only",
            "source": source,
            "count": len(lots),
            "lots": [
                {
                    **_public_lot_dict(lot),
                    "screening": {
                        "development_relevant": AuctionSearchService.is_development_relevant(lot),
                        "documents_count": len(lot.documents),
                        "full_document_parse_deferred": True,
                    },
                }
                for lot in lots
            ],
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
        project_preset = build_project_preset(lot)
        return {
            "lot": normalized,
            "developaid_seed": build_developaid_seed(lot),
            "project_preset": project_preset,
            "project_preset_import": {
                "endpoint": "/api/project-presets/import",
                "mode": "preview_then_apply",
                "filled_inputs": project_preset.get("auction_import", {}).get("filled_inputs", {}),
            },
            "screening": {
                "legal_structure": lot.lot_kind.value,
                "requires_krt_terms": lot.lot_kind == LotKind.KRT,
                "krt_documents_complete": (
                    bool(lot.raw.get("krt_extraction_complete")) if lot.lot_kind == LotKind.KRT else None
                ),
                "krt_auth_required": (
                    bool(lot.raw.get("krt_auth_required")) if lot.lot_kind == LotKind.KRT else None
                ),
                "ready_for_financial_model": (
                    bool(lot.krt_program or lot.obligations) and not lot.raw.get("krt_document_warnings")
                    if lot.lot_kind == LotKind.KRT
                    else bool(lot.cadastral_numbers and (lot.current_price_rub is not None or lot.start_price_rub is not None))
                ),
            },
        }
