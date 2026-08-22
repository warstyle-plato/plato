from __future__ import annotations

import logging
import os
import sys
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from auction_search.adapters import InvestMoscowDiscoveryAdapter, LotOnlineAdapter, RoseltorgAdapter
from auction_search.bridge import auction_page_with_handoff, install_page_bridge
from auction_search.developaid_mapper import build_developaid_seed
from auction_search.documents import DocumentExtractionError
from auction_search.krt_pipeline import enrich_krt_from_official_documents
from auction_search.krt_ranking import KrtRanking
from auction_search.krt_screening import build_krt_model_screening
from auction_search.models import LotKind
from auction_search.preset_mapper import build_project_preset
from auction_search.service import AuctionSearchService
from auction_search.ui import auctions_page
from market_search.krt_registry import CATALOGUE_URL, KrtRegistry
from market_search import cabinet as market_cabinet
from market_search.geocoder import GeocodingError
from market_search.http import RemoteServiceError
from market_search.subject import SubjectNotFound


logger = logging.getLogger(__name__)


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
    if value in {"investmoscow", "moscow", "city"}:
        return [InvestMoscowDiscoveryAdapter()]
    if value == "all":
        return [_lot_online_discovery_adapter(), RoseltorgAdapter(), InvestMoscowDiscoveryAdapter()]
    raise ValueError("source: all, lot_online, roseltorg или investmoscow")


def _public_lot_dict(lot) -> dict[str, Any]:
    data = lot.to_dict()
    data.pop("raw", None)
    return data


def install(app: FastAPI) -> None:
    if getattr(app.state, "auction_search_installed", False):
        return
    app.state.auction_search_installed = True
    market = getattr(app.state, "market_discovery_service", None)
    krt_registry = getattr(market, "krt", None) or KrtRegistry(
        os.path.join(os.getenv("DATA_DIR", "data"), "market")
    )
    krt_ranking = KrtRanking(os.path.join(os.getenv("DATA_DIR", "data"), "market"))

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
                {
                    "id": "investmoscow",
                    "name": "Официальный портал «Торги Москвы» → фактическая ЭТП",
                    "direct_lot_ingest": False,
                    "moscow_discovery": True,
                    "discovery_access": "public_city_catalogue_then_official_etp",
                    "facts_source": "conducting_etp_only",
                },
            ],
            "document_access": "public_first_optional_service_account_session",
        }

    @app.get("/auctions/krt")
    async def auction_krt_catalogue() -> dict[str, Any]:
        projects = await run_in_threadpool(krt_registry.catalogue)
        status = krt_registry.status()
        return {
            "source": CATALOGUE_URL,
            "geometry_status": "not_published_in_catalogue",
            **status,
            "count": len(projects),
            "projects": projects,
        }

    def _screen_one(project: dict[str, Any]) -> dict[str, Any]:
        """Один прогон для рейтинга — тем же путём, что и открытая карточка.

        Второго скрининга не заводим: разойдись они, список и карточка
        показали бы про одну площадку разное, и оба достоверно.
        """
        if core is None or market is None:
            return {"available": False, "reason": "Финансовый движок DevelopAid не подключён"}
        report = market.build_report(
            f"krt:{project.get('slug')}", radius_km=3.0, peers_limit=12,
            city_reference=False, include_project_totals=True,
        )
        return build_krt_model_screening(project, report, core)

    @app.get("/auctions/krt/ranking")
    async def auction_krt_ranking() -> dict[str, Any]:
        """Балл по всем КРТ: потолок цены входа на метр продаваемой.

        Отдаёт посчитанное сразу — даже на ходу прогона: половина рейтинга с
        честным ходом полезнее пустого экрана, который ничего не объясняет.
        """
        return {
            "measure": "entry_capacity_rub_per_sqm",
            "measure_label": "Потолок цены входа, ₽/м² продаваемой",
            "target_llcr": 1.20,
            "price_note": (
                "Цена аукциона в балл не входит: у проекта каталога krt.mos.ru "
                "ценового поля нет. Балл отвечает «сколько площадка выдерживает "
                "за вход», а не «проходит ли она по объявленной цене»."
            ),
            "progress": krt_ranking.progress(),
            "rows": krt_ranking.rows(),
        }

    @app.post("/auctions/krt/ranking/refresh")
    async def auction_krt_ranking_refresh(request: Request) -> dict[str, Any]:
        """Запустить фоновый прогон по каталогу. На ходу — не запускает второй."""
        market_cabinet.require_cabinet(request)
        if market is None or core is None:
            raise HTTPException(
                status_code=503,
                detail="Прогон требует и маркетингового движка, и движка DevelopAid",
            )
        projects = await run_in_threadpool(krt_registry.catalogue)
        if not projects:
            raise HTTPException(
                status_code=503,
                detail="Каталог КРТ ещё не получен — обновите каталог и повторите",
            )
        started = krt_ranking.start(projects, _screen_one)
        return {
            "started": started,
            "reason": "" if started else "Прогон уже идёт",
            "progress": krt_ranking.progress(),
        }

    @app.get("/auctions/krt/{slug}/market")
    async def auction_krt_market(
        slug: str,
        request: Request,
        radius_km: float = Query(default=3.0, ge=0.25, le=10.0),
        peers_limit: int = Query(default=12, ge=1, le=20),
    ) -> dict[str, Any]:
        """Existing market engine, embedded in the KRT opportunity card."""
        market_cabinet.require_cabinet(request)
        if market is None:
            raise HTTPException(status_code=503, detail="Маркетинговый движок не подключён")
        try:
            def build_report_with_model() -> dict[str, Any]:
                report = market.build_report(
                    f"krt:{slug}", radius_km=radius_km, peers_limit=peers_limit,
                    city_reference=False, include_project_totals=True,
                )
                finder = getattr(krt_registry, "find", None)
                project = finder(f"krt:{slug}") if callable(finder) else None
                if project is None:
                    project = next(
                        (item for item in krt_registry.catalogue() if item.get("slug") == slug),
                        None,
                    )
                if core is None:
                    screening = {
                        "available": False,
                        "reason": "Финансовый движок DevelopAid не подключён",
                    }
                else:
                    try:
                        screening = build_krt_model_screening(project, report, core)
                    except Exception:
                        # Marketing remains useful if a preliminary model cannot
                        # be assembled.  Do not turn an optional screen into a
                        # failure of the existing market report.
                        logger.exception("KRT model screening failed slug=%s", slug)
                        screening = {
                            "available": False,
                            "reason": "Предварительный прогон модели временно недоступен",
                        }
                return {**report, "model_screening": screening}

            return await run_in_threadpool(build_report_with_model)
        except (SubjectNotFound, GeocodingError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RemoteServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

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
            "coverage": [
                report
                for adapter in adapters
                if (report := getattr(adapter, "last_report", None)) is not None
            ],
            "lots": [
                {
                    **_public_lot_dict(lot),
                    "screening": {
                        **AuctionSearchService.screen_lot(lot),
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

        screening = AuctionSearchService.screen_lot(lot)
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
                **screening,
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
