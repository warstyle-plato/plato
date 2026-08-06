"""Пилот рынка локации и рекомендации цены продаж.

Первый релиз намеренно отделяет методику от источников данных. Контрольный
срез Мишина, 46 позволяет проверить весь пользовательский путь на сайте и в
Telegram, не выдавая неподтверждённый парсинг публичных страниц за production-
интеграцию. Следующий адаптер заменит reference dataset данными НАШ.ДОМ.РФ и
Домклик, не меняя API и интерфейсы.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parent
_FRONTEND = _ROOT / "frontend_v2"
_REFERENCE_DATE = date(2026, 8, 6)


class MarketAnalysisRequest(BaseModel):
    address: str
    sale_start_date: str | None = None
    saleable_area_sqm: float | None = Field(default=None, ge=0)
    annual_price_growth: float = Field(default=0.06, ge=-0.30, le=0.50)
    sales_duration_months: int = Field(default=42, ge=1, le=120)


_REFERENCE_MARKETS: dict[str, dict[str, Any]] = {
    "мишина 46": {
        "canonical_address": "Москва, ул. Мишина, 46",
        "radius_km": 3,
        "source_date": "2026-08-06",
        "source_label": "Контрольный срез НАШ.ДОМ.РФ + Домклик",
        "comparables": [
            {
                "name": "Петровский парк II",
                "distance_km": 0.4,
                "status": "сдан, продажи продолжаются",
                "total_area_sqm": 108000,
                "units": 1128,
                "active_listings": 158,
                "price_sqm": 601000,
                "weight": 0.65,
                "role": "прямой аналог",
            },
            {
                "name": "Symphony 34",
                "distance_km": 1.1,
                "status": "сдан",
                "total_area_sqm": 102000,
                "units": None,
                "active_listings": 139,
                "price_sqm": 664000,
                "weight": 0.35,
                "role": "верхняя граница",
            },
        ],
        "launch_discount": 0.045,
        "confidence": 64,
        "notes": [
            "Цена основана на текущей экспозиции, а не на зарегистрированных сделках.",
            "Темп продаж появится после накопления ежемесячных срезов НАШ.ДОМ.РФ.",
            "Контрольный кейс нужен для проверки интерфейса и формулы до live-сбора.",
        ],
    },
}


def _normalise_address(value: str) -> str:
    text = str(value or "").lower().replace("ё", "е")
    text = re.sub(r"\b(россия|г\.?\s*москва|москва|улица|ул\.?|дом|д\.?)\b", " ", text)
    text = re.sub(r"[^0-9a-zа-я]+", " ", text)
    return " ".join(text.split())


def _reference_for(address: str) -> dict[str, Any]:
    key = _normalise_address(address)
    for marker, dataset in _REFERENCE_MARKETS.items():
        if marker in key or key in marker:
            return dataset
    raise HTTPException(
        status_code=422,
        detail=(
            "Пилотный live-контур пока включён только для адреса «Москва, ул. Мишина, 46». "
            "Другие адреса не рассчитываются по вымышленным данным."
        ),
    )


def _parse_date(raw: str | None) -> date:
    if not raw:
        return _REFERENCE_DATE
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Дата старта продаж должна быть в формате ГГГГ-ММ-ДД") from exc


def _round_price(value: float) -> int:
    return int(round(value / 5000.0) * 5000)


def analyse_market(req: MarketAnalysisRequest) -> dict[str, Any]:
    dataset = _reference_for(req.address)
    comparables = [dict(item) for item in dataset["comparables"]]
    weight_sum = sum(float(item["weight"]) for item in comparables) or 1.0
    current_price = sum(float(item["price_sqm"]) * float(item["weight"]) for item in comparables) / weight_sum

    launch_date = _parse_date(req.sale_start_date)
    months_to_launch = max(0.0, (launch_date - _REFERENCE_DATE).days / 30.4375)
    time_factor = (1.0 + req.annual_price_growth) ** (months_to_launch / 12.0)
    launch_price = current_price * time_factor * (1.0 - float(dataset["launch_discount"]))
    # При равномерной реализации средний проданный метр приходится примерно на
    # середину периода. Это не заменяет помесячную модель, а задаёт честный
    # ориентир для первого переноса в экономику проекта.
    average_factor = (1.0 + req.annual_price_growth) ** (req.sales_duration_months / 24.0)
    average_price = launch_price * average_factor

    total_area = sum(float(item.get("total_area_sqm") or 0) for item in comparables)
    active_listings = sum(int(item.get("active_listings") or 0) for item in comparables)
    project_share = None
    if req.saleable_area_sqm and total_area > 0:
        project_share = req.saleable_area_sqm / total_area

    recommended = _round_price(launch_price)
    result = {
        "mode": "pilot_reference",
        "address": dataset["canonical_address"],
        "radius_km": dataset["radius_km"],
        "source_date": dataset["source_date"],
        "source_label": dataset["source_label"],
        "market_price_today": _round_price(current_price),
        "recommended_launch_price": recommended,
        "recommended_price_range": {
            "low": _round_price(launch_price * 0.95),
            "high": _round_price(launch_price * 1.05),
        },
        "weighted_average_project_price": _round_price(average_price),
        "annual_price_growth": req.annual_price_growth,
        "sales_duration_months": req.sales_duration_months,
        "months_to_launch": round(months_to_launch, 1),
        "confidence_score": int(dataset["confidence"]),
        "market": {
            "projects": len(comparables),
            "total_area_sqm": int(total_area),
            "active_listings": active_listings,
            "sold_sqm": None,
            "residual_sqm": None,
            "monthly_absorption_sqm": None,
            "supply_months": None,
            "project_share_of_nearby_area": round(project_share, 4) if project_share is not None else None,
        },
        "comparables": comparables,
        "notes": list(dataset["notes"]),
        "formula": {
            "weighted_current_price": round(current_price, 2),
            "time_factor": round(time_factor, 6),
            "launch_discount": dataset["launch_discount"],
            "average_factor": round(average_factor, 6),
        },
    }
    return result


def _telegram_result(payload: dict[str, Any]) -> str:
    price = lambda value: f"{int(value):,}".replace(",", " ") + " ₽/м²"
    market = payload["market"]
    low = payload["recommended_price_range"]["low"]
    high = payload["recommended_price_range"]["high"]
    lines = [
        "<b>Рынок и рекомендация цены</b>",
        html.escape(payload["address"]),
        "",
        f"Ориентир рынка сегодня: <b>{price(payload['market_price_today'])}</b>",
        f"Рекомендуемая цена старта: <b>{price(payload['recommended_launch_price'])}</b>",
        f"Рабочий диапазон: {price(low)} — {price(high)}",
        f"Средняя цена реализации: <b>{price(payload['weighted_average_project_price'])}</b>",
        "",
        f"В радиусе {payload['radius_km']} км: {market['projects']} проекта, "
        f"{market['total_area_sqm']:,} м² и {market['active_listings']} активных предложений".replace(",", " "),
        f"Достоверность пилота: {payload['confidence_score']}%",
        "",
        "<i>Пока это контрольный срез экспозиции. Продажи по месяцам будут рассчитаны "
        "после подключения и накопления снимков НАШ.ДОМ.РФ.</i>",
    ]
    return "\n".join(lines)


def _install_bot(app: FastAPI) -> None:
    @app.on_event("startup")
    def patch_market_bot() -> None:
        import main as wrapper

        core = wrapper.core
        if getattr(core, "_market_pilot_installed", False):
            return
        core._market_pilot_installed = True

        commands = list(core.TELEGRAM_BOT_COMMANDS)
        if not any(item.get("command") == "market" for item in commands):
            commands.append({"command": "market", "description": "Рынок и рекомендация цены"})
            core.TELEGRAM_BOT_COMMANDS = commands

        old_help_markup = wrapper._help_markup

        def help_markup(chat_id: int) -> dict[str, Any]:
            markup = old_help_markup(chat_id)
            rows = markup.setdefault("inline_keyboard", [])
            if not any(button.get("callback_data") == "market_mishina"
                       for row in rows for button in row if isinstance(button, dict)):
                rows.insert(3, [{"text": "Рынок и цена продаж", "callback_data": "market_mishina"}])
            return markup

        wrapper._help_markup = help_markup
        original_message = core._telegram_handle_message
        original_update = core._telegram_handle_update

        def send_market(chat_id: int, address: str) -> None:
            try:
                payload = analyse_market(MarketAnalysisRequest(address=address or "Москва, ул. Мишина, 46"))
                wrapper._send_message(chat_id, _telegram_result(payload))
            except Exception as exc:
                detail = getattr(exc, "detail", None) or str(exc)
                wrapper._send_message(chat_id, "<b>Рынок не рассчитан.</b>\n" + html.escape(str(detail)[:300]))

        def handle_message(message: dict[str, Any]) -> None:
            chat_id, _, text = wrapper._extract_message(message)
            command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.startswith("/") else ""
            if command in {"/market", "/price", "/рынок"}:
                argument = text.split(maxsplit=1)[1].strip() if " " in text else ""
                if not argument:
                    wrapper._send_message(
                        chat_id,
                        "<b>Рынок и рекомендация цены</b>\n"
                        "Пилот сейчас проверяется на контрольном адресе Мишина, 46. "
                        "Нажмите кнопку или отправьте <code>/market Москва, ул. Мишина, 46</code>.",
                        reply_markup={"inline_keyboard": [[
                            {"text": "Рассчитать Мишина, 46", "callback_data": "market_mishina"}
                        ]]},
                    )
                else:
                    send_market(chat_id, argument)
                return
            original_message(message)

        def handle_update(update: dict[str, Any]) -> None:
            query = update.get("callback_query") if isinstance(update, dict) else None
            if isinstance(query, dict) and str(query.get("data") or "") == "market_mishina":
                wrapper._answer_callback(query)
                message = query.get("message") or {}
                sender = query.get("from") or {}
                chat_id = int(((message.get("chat") or {}).get("id")) or sender.get("id") or 0)
                send_market(chat_id, "Москва, ул. Мишина, 46")
                return
            original_update(update)

        core._telegram_handle_message = handle_message
        core._telegram_handle_update = handle_update


def install(app: FastAPI) -> None:
    @app.get("/v2/assets/market.css", include_in_schema=False)
    async def market_styles() -> FileResponse:
        return FileResponse(_FRONTEND / "market.css", media_type="text/css")

    @app.get("/v2/assets/market.js", include_in_schema=False)
    async def market_script() -> FileResponse:
        return FileResponse(_FRONTEND / "market.js", media_type="application/javascript")

    @app.post("/api/v2/market-analysis")
    async def market_analysis(req: MarketAnalysisRequest) -> dict[str, Any]:
        return analyse_market(req)

    _install_bot(app)
