"""Оценка рынка конкурентов: один расчёт на все поверхности.

Панель «Рынок», Платон Сергеевич и бот спрашивают одно и то же — что рядом
строят и почём. Считать это каждый раз по-своему нельзя: правило модуля
«поверхности считают один раз» уже стоило нам двух достоверных на вид отчётов с
разными числами. Здесь конвейер v6 запускается ровно один раз, а результат
приводится к виду, который читается человеком и моделью одинаково.

Своей арифметики тут нет — по той же причине, по которой её нет в адаптере
результата v2: первое «просто поделить на миллион» превращает представление во
вторую реализацию экономики. Цену считает ``recommendation.py``, здесь она
только пересчитывается в единицы поля «Цена квартир» (тыс. ₽/м²) и называется
своим основанием.
"""

from __future__ import annotations

from typing import Any

from .http import RemoteServiceError

# Основание цены. Официальная средняя ЕИСЖС — среднее по зарегистрированным
# сделкам: она отстаёт от рынка и подписью «цена предложения» быть не может.
# Разница между ними — не подробность, а то, можно ли применять число в модель
# не глядя.
ASKING = "asking"
OFFICIAL = "official_eisgs"

_QUARANTINE_LABELS = {
    "geo_unresolved": "адрес проекта не подтверждён",
    "outside_radius": "вне радиуса",
    "over_limit": "не вошёл в лимит выдачи",
    "not_evaluated": "бюджет разбора исчерпан",
    "district_mismatch": "другой район",
    "class_mismatch": "другой класс",
    "class_unknown": "класс не определён",
    "subject_itself": "это сам объект оценки",
    "developer_not_project": "застройщик, а не проект",
}

# Ключи вводных, где может лежать адрес участка. Спрашивать адрес у человека,
# когда он уже ввёл кадастровый номер и получил ТЭП, — лишний шаг; а угадывать
# адрес по названию проекта нельзя, названия к географии отношения не имеют.
ADDRESS_PATHS = (
    ("_cadastral_analysis", "territory", "address"),
    ("_cadastral_analysis", "address"),
    ("_mo_calc", "territory", "address"),
    ("_glavapu_import", "source", "address"),
)


def quarantine_label(status: str | None) -> str:
    return _QUARANTINE_LABELS.get(str(status or ""), str(status or "отсеян"))


def address_from_inputs(inputs: dict[str, Any] | None) -> str:
    """Адрес участка из вводных модели, если он там уже есть."""
    if not isinstance(inputs, dict):
        return ""
    for path in ADDRESS_PATHS:
        node: Any = inputs
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, str) and node.strip():
            return " ".join(node.split())
    lookup = inputs.get("_land_lookup")
    if isinstance(lookup, dict):
        for parcel in lookup.get("parcels") or lookup.get("items") or []:
            if isinstance(parcel, dict) and str(parcel.get("address") or "").strip():
                return " ".join(str(parcel["address"]).split())
    return ""


def _analogue(row: dict[str, Any]) -> dict[str, Any]:
    price = row.get("market_price") or {}
    inventory = row.get("inventory") or {}
    sales = row.get("sales") or {}
    source = row.get("market_source") or {}
    official = str(price.get("basis") or "") == "official_domrf_fallback"
    return {
        "name": row.get("name"),
        "developer": row.get("developer") or None,
        "distance_km": row.get("distance_km"),
        "segment": row.get("segment") or None,
        "district": row.get("district") or None,
        "address": row.get("address") or None,
        "price_per_sqm": price.get("price_per_sqm") if price.get("available") else None,
        "price_basis": OFFICIAL if official else (ASKING if price.get("available") else None),
        "price_verified": bool(row.get("price_verified")) and not official,
        "price_quality": price.get("quality"),
        "price_reason": price.get("reason") if not price.get("available") else None,
        "sample_count": price.get("sample_count"),
        "price_sources": list(price.get("sources") or []),
        "observed_at": price.get("observed_at") or price.get("retrieved_at"),
        "inventory_units": inventory.get("units"),
        "inventory_quality": inventory.get("quality") or "unknown",
        "sales_per_month": sales.get("units_per_month"),
        "eligible_analogue": bool(row.get("eligible_analogue")),
        "confirmed_eisgs": bool(row.get("confirmed")),
        "url": source.get("url") or None,
    }


def _quarantine_summary(payload: dict[str, Any]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in payload.get("quarantine") or []:
        key = str(item.get("status") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return [
        {"status": status, "label": quarantine_label(status), "count": count}
        for status, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def assess(
    service: Any,
    *,
    address: str,
    radius_km: float = 3.0,
    limit: int = 10,
    segment: str | None = None,
) -> dict[str, Any]:
    """Оценка рынка конкурентов по адресу площадки.

    Возвращает то же самое для всех, кто спросит. Недоступность поиска —
    такой же ответ, а не исключение: «оценка не выполнена и вот почему»
    полезнее пустого экрана. Ошибка, ушедшая только в лог, — это ошибка,
    которой нет.
    """
    address = " ".join(str(address or "").split())
    if not address:
        return _unavailable(address, "Не указан адрес площадки")
    if not getattr(service.search, "configured", False):
        return _unavailable(
            address,
            "Поиск аналогов не настроен: нужны YANDEX_SEARCH_API_KEY и YANDEX_SEARCH_FOLDER_ID",
        )
    try:
        payload = service.discover(
            address=address,
            latitude=None,
            longitude=None,
            radius_km=float(radius_km),
            limit=int(limit),
            segment=segment,
        )
    except RemoteServiceError as exc:
        return _unavailable(address, f"Источник данных недоступен: {exc}")
    except Exception as exc:  # noqa: BLE001 — причина доносится в чат, а не в лог
        return _unavailable(address, f"{type(exc).__name__}: {exc}")
    return from_payload(payload, address=address)


def from_payload(payload: dict[str, Any], *, address: str = "") -> dict[str, Any]:
    """Привести готовый ответ конвейера к общему виду.

    Отдельно от ``assess``, чтобы панель и приёмка читали ровно ту же сборку,
    что бот и Платон, не запуская поиск второй раз.
    """
    query = payload.get("query") or {}
    address = " ".join(str(address or query.get("address") or "").split())

    summary = payload.get("price_summary")
    basis = ASKING
    if not summary:
        summary = payload.get("official_price_summary")
        basis = OFFICIAL
    summary = summary or {}
    price_per_sqm = summary.get("price_per_sqm")

    rows = payload.get("projects") or []
    return {
        "available": True,
        "address": address,
        "radius_km": query.get("radius_km"),
        "segment": query.get("segment"),
        "segment_source": query.get("segment_source"),
        "district": query.get("subject_district") or query.get("district"),
        "price_basis": basis if price_per_sqm else None,
        "price_per_sqm": price_per_sqm,
        # Поле «Цена квартир» в модели — в тыс. ₽/м². Пересчёт единиц, а не
        # вторая экономика: сама цена посчитана рекомендацией.
        "price_th_per_sqm": round(float(price_per_sqm) / 1000.0, 3) if price_per_sqm else None,
        "corridor_low_per_sqm": summary.get("corridor_low_price_per_sqm"),
        "corridor_high_per_sqm": summary.get("corridor_high_price_per_sqm"),
        "median_per_sqm": summary.get("market_median_price_per_sqm"),
        "confidence": summary.get("confidence"),
        "method": summary.get("method"),
        "note": summary.get("note"),
        "analogue_count": summary.get("analogue_count") or 0,
        "found_count": payload.get("count") or 0,
        "priced_count": payload.get("priced_count") or 0,
        "confirmed_count": payload.get("confirmed_count") or 0,
        "quarantine_count": payload.get("quarantine_count") or 0,
        "quarantine_summary": _quarantine_summary(payload),
        "warning": payload.get("warning") or None,
        "analogues": [_analogue(row) for row in rows],
        "source": payload.get("source") or {},
        "raw": payload,
    }


def _unavailable(address: str, reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "address": address,
        "reason": reason,
        "price_per_sqm": None,
        "price_th_per_sqm": None,
        "price_basis": None,
        "analogues": [],
        "analogue_count": 0,
        "found_count": 0,
        "quarantine_count": 0,
        "quarantine_summary": [],
    }


def for_agent(assessment: dict[str, Any], *, analogues: int = 8) -> dict[str, Any]:
    """Сжатый вид для модели: без сырого ответа конвейера и без карантинных строк.

    Платону нужны числа и их основание, а не диагностика поиска: карантин
    приезжает счётчиком и сводкой причин. Полный ответ остаётся у панели.
    """
    if not assessment.get("available"):
        return {
            "available": False,
            "address": assessment.get("address"),
            "reason": assessment.get("reason"),
        }
    return {
        "available": True,
        "address": assessment.get("address"),
        "radius_km": assessment.get("radius_km"),
        "district": assessment.get("district"),
        "segment": assessment.get("segment"),
        "segment_source": assessment.get("segment_source"),
        "recommended_price_per_sqm": assessment.get("price_per_sqm"),
        "recommended_price_th_per_sqm": assessment.get("price_th_per_sqm"),
        "price_basis": assessment.get("price_basis"),
        "price_basis_meaning": _basis_meaning(assessment.get("price_basis")),
        "corridor_per_sqm": [
            assessment.get("corridor_low_per_sqm"),
            assessment.get("corridor_high_per_sqm"),
        ],
        "median_per_sqm": assessment.get("median_per_sqm"),
        "confidence": assessment.get("confidence"),
        "method": assessment.get("method"),
        "note": assessment.get("note"),
        "analogue_count": assessment.get("analogue_count"),
        "found_count": assessment.get("found_count"),
        "quarantine_count": assessment.get("quarantine_count"),
        "quarantine_summary": assessment.get("quarantine_summary"),
        "warning": assessment.get("warning"),
        "analogues": [
            {
                key: value
                for key, value in item.items()
                if key
                in {
                    "name", "developer", "distance_km", "segment", "district",
                    "price_per_sqm", "price_basis", "price_verified", "sample_count",
                    "price_sources", "observed_at", "inventory_units", "inventory_quality",
                    "sales_per_month", "eligible_analogue",
                }
            }
            for item in (assessment.get("analogues") or [])[:analogues]
        ],
        "model_field": {
            "input": "apartment_price_th",
            "label": "Цена квартир",
            "units": "тыс. ₽/м²",
            "value": assessment.get("price_th_per_sqm"),
        },
    }


def _basis_meaning(basis: str | None) -> str | None:
    if basis == ASKING:
        return (
            "Цены предложения с карточек проектов: текущий рынок, "
            "применимо как ориентир цены квартир."
        )
    if basis == OFFICIAL:
        return (
            "Среднее по зарегистрированным сделкам ЕИСЖС: цен предложения не нашлось. "
            "Показатель отстаёт от рынка — применять только после проверки."
        )
    return None
