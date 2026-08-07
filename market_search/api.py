from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from .geocoder import GeocodingError
from .http import RemoteServiceError
from .service import MarketDiscoveryService


class MarketDiscoveryRequest(BaseModel):
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=3.0, ge=0.25, le=10.0)
    limit: int = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def address_or_coordinates(self) -> "MarketDiscoveryRequest":
        have_coords = self.latitude is not None and self.longitude is not None
        if not have_coords and not str(self.address or "").strip():
            raise ValueError("Нужен адрес либо координаты")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Широта и долгота передаются вместе")
        return self


def install(app: FastAPI) -> MarketDiscoveryService:
    if getattr(app.state, "market_discovery_installed", False):
        return app.state.market_discovery_service

    data_dir = Path(os.getenv("DATA_DIR", "data")) / "market"
    service = MarketDiscoveryService(data_dir)
    app.state.market_discovery_installed = True
    app.state.market_discovery_service = service

    @app.post("/market/discovery")
    async def market_discovery(req: MarketDiscoveryRequest) -> dict[str, Any]:
        try:
            return service.discover(
                address=req.address,
                latitude=req.latitude,
                longitude=req.longitude,
                radius_km=req.radius_km,
                limit=req.limit,
            )
        except GeocodingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RemoteServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:  # preview: never return an opaque HTML 500 to the UI
            detail = f"Внутренняя ошибка market discovery: {type(exc).__name__}: {exc}"
            raise HTTPException(status_code=500, detail=detail) from exc

    return service
