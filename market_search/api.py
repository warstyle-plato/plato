from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

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

    @app.post("/market/report")
    async def market_report(req: ReportRequest) -> dict[str, Any]:
        """Отчёт по объекту: соседи из «Пульса» и выбранные разделы.

        Ошибки разделены нарочно. Не опознан объект — 422, это ответ человеку,
        а не поломка. Неизвестный код раздела — тоже 422: опечатка в списке не
        должна выглядеть как «раздел ничего не показал». Источник недоступен —
        502, потому что чинить нечего, надо ждать или включить доступы.
        """
        try:
            return service.build_report(
                req.query,
                codes=req.codes,
                radius_km=req.radius_km,
                peers_limit=req.peers_limit,
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
