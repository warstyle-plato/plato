from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, model_validator

from . import cabinet as cabinet_module
from .geocoder import GeocodingError
from .http import RemoteServiceError
from .service_v6 import MarketDiscoveryService
from .subject import SubjectNotFound


class MarketDiscoveryRequest(BaseModel):
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=3.0, ge=0.25, le=10.0)
    limit: int = Field(default=10, ge=1, le=20)
    # Пусто — класс выводится по ближайшим соседям: своего класса у площадки нет,
    # она ещё не построена.
    segment: str | None = None

    @model_validator(mode="after")
    def address_or_coordinates(self) -> "MarketDiscoveryRequest":
        have_coords = self.latitude is not None and self.longitude is not None
        if not have_coords and not str(self.address or "").strip():
            raise ValueError("Нужен адрес либо координаты")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Широта и долгота передаются вместе")
        return self


class PriceHintRequest(BaseModel):
    """Ориентир для поля «Цена квартир»: нужна только точка и, если известен, класс."""

    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    segment: str | None = None
    radius_km: float = Field(default=2.5, ge=0.5, le=5.0)

    @model_validator(mode="after")
    def address_or_coordinates(self) -> "PriceHintRequest":
        have_coords = self.latitude is not None and self.longitude is not None
        if not have_coords and not str(self.address or "").strip():
            raise ValueError("Нужен адрес, кадастровый номер или координаты")
        return self


class ReportRequest(BaseModel):
    """Конструктор отчёта: объект и набор разделов.

    Ввод один — тот же, что в поле «Участок» основного сервиса: кадастровый
    номер, координаты, название проекта или адрес. Второго разбора для рынка
    не заводим, иначе один и тот же ввод даст в двух местах разные точки.
    """

    query: str
    codes: list[str] | None = None
    radius_km: float = Field(default=3.0, ge=0.25, le=10.0)
    peers_limit: int = Field(default=12, ge=1, le=40)
    # Пусто — класс берётся у «Пульса». Ручной выбор не отменяет решения от
    # 18.08.2026, а называется в отчёте отдельным источником.
    segment: str | None = None

    @model_validator(mode="after")
    def query_is_not_blank(self) -> "ReportRequest":
        if not str(self.query or "").strip():
            raise ValueError("Нужен кадастровый номер, адрес, координаты или название проекта")
        return self


def install(app: FastAPI) -> MarketDiscoveryService:
    if getattr(app.state, "market_discovery_installed", False):
        return app.state.market_discovery_service

    data_dir = Path(os.getenv("DATA_DIR", "data")) / "market"
    service = MarketDiscoveryService(data_dir)
    app.state.market_discovery_installed = True
    app.state.market_discovery_service = service

    @app.post("/market/price-hint")
    async def market_price_hint(req: PriceHintRequest) -> dict[str, Any]:
        """Одно число для поля модели. Список проектов сюда не отдаётся."""
        try:
            return service.price_hint(
                address=req.address,
                latitude=req.latitude,
                longitude=req.longitude,
                segment=req.segment,
                radius_km=req.radius_km,
            )
        except GeocodingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RemoteServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/cabinet", response_class=HTMLResponse)
    async def cabinet_home(request: Request) -> HTMLResponse:
        """Кабинет. Без ключа — форма входа, а не отказ: сюда приходит человек."""
        problem = cabinet_module.key_problem()
        if problem:
            return HTMLResponse(cabinet_module.login_page(problem), status_code=503)
        if not cabinet_module.cabinet_key():
            return HTMLResponse(
                cabinet_module.login_page(
                    f"Кабинет выключен: не задан {cabinet_module.ENV_NAME}."
                ),
                status_code=503,
            )
        if not cabinet_module.authorised(request):
            return HTMLResponse(cabinet_module.login_page(), status_code=401)
        return HTMLResponse(cabinet_module.cabinet_page())

    @app.post("/cabinet/login")
    async def cabinet_login(request: Request) -> Any:
        # Тело разбираем руками: `Form(...)` в Starlette тянет python-multipart,
        # и ставить зависимость в образ ради одного поля не стоит.
        raw = (await request.body()).decode("utf-8", errors="replace")
        key = (parse_qs(raw).get("key") or [""])[0]
        if not cabinet_module.key_accepted(key):
            # Задержки и счётчиков здесь нет нарочно: ключ один, и подбор его
            # по сети упирается в длину, а не в скорость ответа. Что именно не
            # так — не уточняем.
            return HTMLResponse(cabinet_module.login_page("Ключ не подошёл."), status_code=401)
        response = RedirectResponse("/cabinet", status_code=303)
        cabinet_module.set_cookie(response, key)
        return response

    @app.get("/market/projects/suggest")
    async def market_projects_suggest(request: Request, q: str = "") -> dict[str, Any]:
        """Подсказки по названию ЖК. Закрыты ключом: это перечень чужой базы."""
        cabinet_module.require_cabinet(request)
        if not service.pulse.available:
            return {"items": [], "reason": "Источник выключен: не заданы PULSE_LOGIN и PULSE_PASSWORD"}
        return {"items": service.pulse.suggest(q)}

    @app.post("/market/report")
    async def market_report(request: Request, req: ReportRequest) -> dict[str, Any]:
        """Отчёт по объекту: соседи из «Пульса» и выбранные разделы.

        Ошибки разделены нарочно. Не опознан объект — 422, это ответ человеку,
        а не поломка. Неизвестный код раздела — тоже 422: опечатка в списке не
        должна выглядеть как «раздел ничего не показал». Источник недоступен —
        502, потому что чинить нечего, надо ждать или включить доступы.

        Маршрут закрыт ключом кабинета: он отдаёт список чужих проектов с
        ценами. Кнопка ориентира цены (`/market/price-hint`) остаётся открытой
        — она отдаёт одно число без источников, и это разные вещи.
        """
        cabinet_module.require_cabinet(request)
        try:
            return service.build_report(
                req.query,
                codes=req.codes,
                radius_km=req.radius_km,
                peers_limit=req.peers_limit,
                segment_override=req.segment,
            )
        except SubjectNotFound as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except GeocodingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RemoteServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/market/discovery")
    async def market_discovery(req: MarketDiscoveryRequest) -> dict[str, Any]:
        try:
            return service.discover(
                address=req.address,
                latitude=req.latitude,
                longitude=req.longitude,
                radius_km=req.radius_km,
                limit=req.limit,
                segment=req.segment,
            )
        except GeocodingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RemoteServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:  # preview: never return an opaque HTML 500 to the UI
            detail = f"Внутренняя ошибка market discovery: {type(exc).__name__}: {exc}"
            raise HTTPException(status_code=500, detail=detail) from exc

    return service
