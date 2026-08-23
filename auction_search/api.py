from __future__ import annotations

import logging
import os
import sys
import threading
import time
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
from auction_search.krt_ranking import HEARTBEAT_SECONDS, KrtRanking, score_row
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


class KrtRankingRequest(BaseModel):
    """Что считать: слаги отобранных площадок. Пусто — весь каталог."""

    slugs: list[str] = Field(default_factory=list, max_length=400)


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


def _plato_number(value: Any, digits: int = 0) -> str:
    try:
        return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")
    except (TypeError, ValueError):
        return "—"


_MARKET_DIGEST_KEYS = ("peers", "price_hint", "comparison", "analysis", "subject", "segment")


def _market_digest(report: dict[str, Any]) -> dict[str, Any]:
    """Что из отчёта рынка нужно карточке. Остальное на диске не хранится.

    Полный отчёт несёт и разбор источников, и сырые выдачи поиска. Карточке они
    не нужны, а диск у нас уже кончался — молча и до отказа выкатки.
    """
    digest = {key: report.get(key) for key in _MARKET_DIGEST_KEYS if report.get(key) is not None}
    peers = digest.get("peers")
    if isinstance(peers, list):
        digest["peers"] = peers[:12]
    analysis = digest.get("analysis")
    if isinstance(analysis, dict):
        digest["analysis"] = {key: value for key, value in analysis.items()
                              if key in {"site", "overall"}}
    verdict = report.get("verdict")
    if isinstance(verdict, dict):
        digest["verdict"] = {key: verdict.get(key) for key in
                             ("units_per_month", "sold_lot_avg", "price_per_sqm", "headline")
                             if verdict.get(key) is not None}
    return digest


def _plato_krt_prompt(stored: dict[str, Any]) -> str:
    """Что спросить у Платона про площадку.

    Числа собираются здесь и подаются готовыми: модель их не пересчитывает и
    пересчитывать не должна — экономику считает движок, а Платон читает
    посчитанное. Спрашиваем и по маркетингу, и по модели одним вопросом:
    рекомендация, разведённая по двум ответам, не сходится сама с собой.
    """
    project = stored.get("project") or {}
    screening = stored.get("screening") or {}
    report = stored.get("market") or {}
    metrics = screening.get("metrics") or {}
    market_block = screening.get("market") or {}
    phasing = screening.get("phasing") or {}
    capacity = screening.get("entry_capacity") or {}
    verdict = report.get("verdict") or {}
    peers = report.get("peers") or []

    lines = [
        "Ты оцениваешь площадку КРТ в Москве для решения об участии в торгах.",
        "Все числа ниже посчитаны движком DevelopAid и маркетинговым модулем; "
        "пересчитывать их не надо, надо прочитать.",
        "",
        f"ПЛОЩАДКА: {project.get('name') or stored.get('slug')}",
        f"Округ и район: {' · '.join(str(v) for v in (project.get('okrug'), project.get('district')) if v) or '—'}",
        f"Статус: {project.get('status') or '—'}; площадь {project.get('area_ha') or '—'} га; "
        f"жилой объём {_plato_number(project.get('housing_gfa_sqm'))} м².",
        "",
        "МАРКЕТИНГ",
        f"Рекомендованный класс: {market_block.get('recommended_segment') or '—'}; "
        f"стартовая цена в модели {_plato_number(market_block.get('start_price_rub_sqm'))} ₽/м² "
        f"({market_block.get('price_basis') or 'основание не указано'}).",
        f"Ориентир рынка: {_plato_number(market_block.get('market_price_rub_sqm'))} ₽/м²; "
        f"сопоставимых проектов рядом: {len(peers)}.",
    ]
    if verdict.get("units_per_month"):
        lines.append(
            f"Темп рынка: {verdict.get('units_per_month')} ДДУ/мес.; "
            f"средний проданный лот {verdict.get('sold_lot_avg') or '—'} м².")
    lines += [
        "",
        "МОДЕЛЬ DEVELOPAID (предварительная, цена входа принята нулём)",
        f"Выручка {_plato_number(metrics.get('revenue_mln'))} млн ₽, "
        f"CAPEX {_plato_number(metrics.get('capex_mln'))} млн ₽, "
        f"чистая прибыль {_plato_number(metrics.get('net_profit_mln'))} млн ₽, "
        f"маржа {_plato_number(metrics.get('margin_pct'), 1)}%.",
        f"LLCR проекта {_plato_number(metrics.get('project_llcr_x'), 2)}x, "
        f"слабейшая очередь {_plato_number(metrics.get('weakest_phase_llcr_x'), 2)}x "
        f"при целевом ориентире банка 1,20x.",
        f"Очередей: {phasing.get('count') or '—'}; продаваемая площадь "
        f"{_plato_number(phasing.get('saleable_sqm'))} м².",
        f"Пик БРИДЖа {_plato_number(metrics.get('peak_bridge_mln'))} млн ₽, "
        f"пик ПФ {_plato_number(metrics.get('peak_pf_mln'))} млн ₽.",
    ]
    if capacity.get("available"):
        lines.append(
            f"Потолок цены входа при LLCR 1,20x: {_plato_number(capacity.get('amount_mln'), 1)} млн ₽.")
    else:
        lines.append(f"Потолок цены входа не подобран: {capacity.get('reason') or 'причина не названа'}.")
    for item in (screening.get("exclusions") or [])[:6]:
        lines.append(f"НЕ УЧТЕНО: {item}")
    lines += [
        "",
        "Ответь по-русски, коротко и по делу, без списка формул:",
        "1. Идти ли смотреть эту площадку дальше — да, нет или «при условии», и почему.",
        "2. Что в маркетинге и в модели противоречит друг другу, если противоречит.",
        "3. Три вопроса, которые надо снять до подачи заявки, по убыванию цены вопроса.",
        "Не выдумывай чисел, которых нет выше. Про неучтённое скажи прямо, что оно неучтено.",
    ]
    return "\n".join(lines)


def install(app: FastAPI) -> None:
    if getattr(app.state, "auction_search_installed", False):
        return
    app.state.auction_search_installed = True
    market = getattr(app.state, "market_discovery_service", None)
    krt_registry = getattr(market, "krt", None) or KrtRegistry(
        os.path.join(os.getenv("DATA_DIR", "data"), "market")
    )
    krt_ranking = KrtRanking(os.path.join(os.getenv("DATA_DIR", "data"), "market"))

    def _weekly_ranking() -> None:
        """Раз в неделю каталог обновляется и считается сам.

        Ждать прогон каждый раз, когда открываешь торги, — это минуты на пустом
        месте (владелец, 23.08.2026). Здесь считается ВЕСЬ каталог, а не срез
        фильтра: никто не ждёт, а к утру должно быть посчитано всё.

        Срок — ночь с субботы на воскресенье, 3 часа по Москве: к утру
        воскресенья каталог свежий, а рабочая неделя начинается с посчитанного.
        Считается календарная точка, а не «неделя от прошлого раза», иначе
        расписание уползает на часы с каждой выкаткой.

        Воркеров два, память у них раздельная, поэтому работу берёт один — по
        файловому замку. Проигравший просто спит дальше. Отключается
        переменной `AUCTION_KRT_WEEKLY=0`.
        """
        while True:
            try:
                if market is not None and core is not None and krt_ranking.due():
                    if krt_ranking.claim():
                        try:
                            projects = krt_registry.projects(refresh=True)
                            rows = [row.to_dict() if hasattr(row, "to_dict") else row
                                    for row in projects]
                            if rows and not krt_ranking.start(rows, _screen_one, scheduled=True):
                                krt_ranking.release()
                        except Exception:
                            logger.exception("weekly KRT ranking failed")
                            krt_ranking.release()
            except Exception:
                logger.exception("weekly KRT ranking loop")
            time.sleep(HEARTBEAT_SECONDS)


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
        screening = build_krt_model_screening(project, report, core)
        # Маркетинг едет вместе со скринингом и оседает в отчёте площадки.
        # Считать его второй раз при открытии карточки незачем: прогон уже
        # сходил к рынку, к соседям и к движку — минуты чужого ожидания на
        # готовом ответе. Кладётся выжимка, а не отчёт целиком: сто двадцать
        # площадок × полный отчёт — это десятки мегабайт на диске, который у
        # нас уже кончался, а карточка рисует ровно эти блоки.
        screening["market_report"] = _market_digest(report)
        return screening

    @app.get("/auctions/krt/{slug}/point")
    async def auction_krt_point(slug: str) -> dict[str, Any]:
        """Геокодированная точка территории — чтобы показать её на карте.

        Полный отчёт рынка ради одной картинки гонять незачем: он считает
        соседей, цены и модель. Здесь только адрес → координата, через тот же
        геокодер движка и тот же кэш; своего второго geocode не заводим.
        Точность возвращается вместе с точкой: центр района выглядит на карте
        так же уверенно, как настоящий адрес.
        """
        if market is None:
            raise HTTPException(status_code=503, detail="Маркетинговый движок не подключён")
        finder = getattr(krt_registry, "find", None)
        project = finder(f"krt:{slug}") if callable(finder) else None
        if project is None:
            project = next(
                (item for item in krt_registry.catalogue() if item.get("slug") == slug), None)
        if not project:
            raise HTTPException(status_code=404, detail="Территория КРТ не найдена")
        query = str(project.get("geocode_query") or project.get("name") or "").strip()
        geocoder = getattr(market, "geocoder", None)
        if geocoder is None or not query:
            raise HTTPException(status_code=503, detail="Геокодер недоступен")
        try:
            point = await run_in_threadpool(geocoder.geocode, query)
        except (GeocodingError, RemoteServiceError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        data = point.to_dict() if hasattr(point, "to_dict") else {}
        return {
            "slug": slug,
            "query": query,
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "precision": data.get("precision"),
            "area_ha": project.get("area_ha"),
        }

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
    async def auction_krt_ranking_refresh(
        request: Request, body: KrtRankingRequest | None = None
    ) -> dict[str, Any]:
        """Запустить фоновый прогон. На ходу — не запускает второй.

        Считаются те площадки, которые остались после фильтра на экране, а не
        весь каталог: смотрят перспективные округа и нужный статус, а прогон по
        всем ста двадцати четырём — это минуты чужой работы и чужой нагрузки на
        рынок (владелец, 23.08.2026). Список слагов приходит со страницы; пустой
        список значит «весь каталог» — так ведёт себя вызов без тела.
        """
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
        wanted = [str(slug) for slug in ((body.slugs if body else None) or []) if str(slug).strip()]
        if wanted:
            order = {slug: index for index, slug in enumerate(wanted)}
            projects = [row for row in projects if str(row.get("slug")) in order]
            projects.sort(key=lambda row: order.get(str(row.get("slug")), 0))
            if not projects:
                raise HTTPException(
                    status_code=422,
                    detail="Ни одна из выбранных площадок не найдена в каталоге",
                )
        started = krt_ranking.start(projects, _screen_one)
        return {
            "started": started,
            "reason": "" if started else "Прогон уже идёт",
            "progress": krt_ranking.progress(),
        }

    def _stored_report(slug: str) -> dict[str, Any]:
        stored = krt_ranking.report(slug)
        if not stored:
            raise HTTPException(
                status_code=404,
                detail="Эта площадка ещё не считалась. Запустите прогон — или дождитесь "
                       "еженедельного: он идёт в ночь с субботы на воскресенье.",
            )
        return stored

    @app.get("/auctions/krt/{slug}/report")
    async def auction_krt_report(slug: str, request: Request) -> dict[str, Any]:
        """Готовый отчёт площадки: маркетинг, модель и рекомендация Платона.

        Ничего не считает. Прогон уже сходил и к рынку, и к движку — карточка
        показывает посчитанное, а не запускает то же самое заново.
        """
        market_cabinet.require_cabinet(request)
        return await run_in_threadpool(_stored_report, slug)

    @app.get("/auctions/krt/{slug}/handoff")
    async def auction_krt_handoff(slug: str, request: Request) -> dict[str, Any]:
        """Вводные площадки для калькулятора DevelopAid.

        Это те же самые вводные, которыми посчитан отчёт, — не собранные
        заново. Второй сборщик модели однажды разошёлся бы с первым, и карточка
        с калькулятором показывали бы про одну площадку разное.
        """
        market_cabinet.require_cabinet(request)
        stored = await run_in_threadpool(_stored_report, slug)
        screening = stored.get("screening") or {}
        model = screening.get("model_inputs")
        if not model:
            raise HTTPException(
                status_code=409,
                detail=str(screening.get("reason")
                          or "Модель по этой площадке не собрана — передавать нечего"),
            )
        project = stored.get("project") or {}
        return {
            "slug": slug,
            "name": project.get("name") or slug,
            "computed_at": stored.get("computed_at"),
            "inputs": model.get("inputs") or {},
            "tep": model.get("tep") or {},
            "phasing": model.get("phasing") or {},
            "assumptions": screening.get("assumptions") or [],
            "exclusions": screening.get("exclusions") or [],
        }

    @app.post("/auctions/krt/{slug}/plato")
    async def auction_krt_plato(slug: str, request: Request) -> dict[str, Any]:
        """Рекомендация Платона по этой площадке — по маркетингу и по модели.

        Спрашивается по требованию и запоминается в том же отчёте: гонять
        модель по всему каталогу в еженедельном прогоне значит платить за сто
        двадцать ответов, из которых прочитают три. Готовый ответ возвращается
        сразу; `refresh=1` спрашивает заново.
        """
        market_cabinet.require_cabinet(request)
        stored = await run_in_threadpool(_stored_report, slug)
        refresh = str(request.query_params.get("refresh") or "").strip() in {"1", "true", "yes"}
        cached = stored.get("plato")
        if cached and not refresh:
            return {"slug": slug, "cached": True, **cached}
        ask = getattr(market, "plato_ask", None) if market is not None else None
        if ask is None:
            raise HTTPException(
                status_code=503,
                detail="Платон недоступен: модуль рынка запущен без движка DevelopAid",
            )
        prompt = _plato_krt_prompt(stored)
        try:
            answer = await run_in_threadpool(ask, prompt, request)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"Платон не ответил: {type(exc).__name__}: {exc}"
            ) from exc
        text = str((answer or {}).get("reply") or (answer or {}).get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=502, detail="Платон вернул пустой ответ")
        payload = {"text": text, "asked_at": int(time.time())}
        stored["plato"] = payload
        rest = {key: value for key, value in stored.items()
                if key not in {"schema_version", "slug", "computed_at"}}
        await run_in_threadpool(
            lambda: krt_ranking.save_report(
                slug, rest, computed_at=stored.get("computed_at")),
        )
        return {"slug": slug, "cached": False, **payload}

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
                # Пересчёт из карточки — тот же прогон, что и еженедельный,
                # поэтому и оседает он там же. Иначе «пересчитать сейчас»
                # обновляло бы только экран: на диске остался бы прошлый отчёт,
                # в таблице — прошлый балл, и оба выглядели бы верными.
                if project is not None and screening.get("available") is not None:
                    stored = dict(screening)
                    krt_ranking.save_report(slug, {
                        "project": project,
                        "market": _market_digest(report),
                        "screening": {key: value for key, value in stored.items()
                                      if key != "market_report"},
                    })
                    krt_ranking.upsert_row(score_row(project, dict(stored)))
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

    # Поток поднимается последним: он зовёт `_screen_one`, а замыкание
    # разрешается в момент вызова — стартуй он выше, первая же итерация
    # получила бы NameError.
    if os.getenv("AUCTION_KRT_WEEKLY", "1").strip() not in {"0", "false", "no"}:
        threading.Thread(target=_weekly_ranking, name="krt-weekly", daemon=True).start()
