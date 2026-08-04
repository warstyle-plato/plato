"""ProjectResult — единственный сериализуемый результат живого движка.

Здесь нет ни одной формулы: модуль вызывает действующую точку входа расчёта
(`main_legacy._run_authoritative_model`) ровно один раз и раскладывает её
результат по стабильной схеме. Ни одно число не пересчитывается, не
округляется и не переводится в другие единицы — деньги отдаются в рублях
ровно так, как их посчитал движок, доли (маржа, ставки) остаются долями.

Правило проверяется тестом: в модуле не должно быть ни одной арифметической
операции (`tests/test_developaid_v2_live_result.py::
test_the_adapter_contains_no_arithmetic`). Пересчёт единиц — это уже вторая
реализация экономики, и первая же разошедшаяся версия страницы делает две
достоверные цифры на одни вводные. Форматирование — дело интерфейса.

ProjectResult — общий контракт для PWA `/v2`, PDF, Telegram и Платона:
одни вводные → один расчёт → один результат. Идентификатор расчёта берётся
у движка (`_calculation_fingerprint`) — тот же, что печатают PDF и книга,
чтобы вопрос «один ли это расчёт» решался сравнением строки.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

# Точка входа движка. Та же, которой пользуются Telegram-карточка, PDF и
# сверка Excel-книги: `_telegram_send_attachments` зовёт именно её.
ENGINE_ENTRY_POINT = "main_legacy._run_authoritative_model"

# Версия схемы ProjectResult. Поднимается при несовместимом изменении полей.
SCHEMA_VERSION = "1"

# Единицы, в которых движок отдаёт числа. Объявлены в самом результате,
# чтобы интерфейсу не приходилось их угадывать.
UNITS = {
    "money": "rub",
    "ratio": "fraction",
    "area": "sqm",
    "rate": "fraction_per_year",
    "price": "th_rub_per_unit",
}

# Остаток долга ПФ ниже этого порога — хвост округления, а не дефолт.
# Порог тот же, что в Telegram-карточке: 0,5 млн ₽, выраженные в рублях.
_ENDING_PF_NOISE_RUB = 500_000.0

# Показатели, которые интерфейс называет KPI. Список ключей, а не вычислений:
# значения берутся из summary движка как есть.
_KPI_KEYS = (
    "revenue",
    "capex",
    "commercial_costs",
    "total_expenses",
    "ebitda",
    "financing_cost",
    "profit_before_tax",
    "profit_tax",
    "net_profit",
    "margin",
    "llcr",
    "npv",
    "irr_equity",
    "full_project_cost",
    "ending_pf",
    "monetizable_saleable_sqm",
    "apartment_saleable_sqm",
    "project_gns_sqm",
    "average_apartment_price_th",
    "full_cost_per_saleable_th",
    "construction_cost_per_gns_th",
    "ebitda_per_saleable_th",
    "net_profit_per_saleable_th",
)

# Помесячные ряды финансирования: ключ строки движка → имя ряда наружу.
_MONTHLY_FINANCE_SERIES = (
    "bridge_draw",
    "bridge_repayment",
    "bridge_balance",
    "bridge_interest",
    "bridge_capitalization",
    "pf_draw",
    "pf_repayment",
    "pf_balance",
    "pf_interest",
    "pf_interest_capitalization",
    "escrow",
    "limit_fee",
    "interest_payment",
    "coverage",
    "key_rate",
    "bridge_rate",
    "pf_rate",
)


def canonical_payload(
    inputs: dict[str, Any],
    tep: dict[str, Any],
    rates: list[dict[str, Any]],
    phasing: dict[str, Any],
) -> str:
    """Канонический JSON вводных: одинаковые вводные — одинаковая строка."""
    return json.dumps(
        {
            "inputs": inputs or {},
            "tep": tep or {},
            "rates": rates or [],
            "phasing": phasing or {},
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def input_hash(
    inputs: dict[str, Any],
    tep: dict[str, Any],
    rates: list[dict[str, Any]],
    phasing: dict[str, Any],
) -> str:
    """Отпечаток вводных. По нему видно, из чего посчитан результат."""
    digest = hashlib.sha256(
        canonical_payload(inputs, tep, rates, phasing).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _series(rows: Iterable[dict[str, Any]], key: str) -> list[Any]:
    """Помесячный ряд из строк движка. Значения берутся как есть."""
    return [row.get(key) for row in rows or []]


def _picked(source: dict[str, Any] | None, keys: Iterable[str]) -> dict[str, Any]:
    """Выборка ключей без изменения значений."""
    data = source or {}
    return {key: data.get(key) for key in keys}


def _monthly_block(result: dict[str, Any]) -> dict[str, Any]:
    """Помесячный cash flow, эскроу и остатки долга — рядами движка.

    Месяцы берутся из cashflow, ряды финансирования — из строк финмодели;
    и то и другое построено движком на одной временнОй оси.
    """
    cashflow = result.get("cashflow") or {}
    rows = (result.get("finance") or {}).get("rows") or []
    months = list(cashflow.get("months") or [])
    block: dict[str, Any] = {
        "months": months,
        "cashflow_project": list(cashflow.get("project") or []),
        "cashflow_equity": list(cashflow.get("equity") or []),
        "profit_tax": list(cashflow.get("profit_tax") or []),
        "finance_months": _series(rows, "month"),
    }
    for key in _MONTHLY_FINANCE_SERIES:
        block[key] = _series(rows, key)
    # Детализация статей и продуктов по месяцам есть у одноочередного расчёта
    # и у каждой очереди; у консолидации многоочередного проекта её нет —
    # движок её там не строит, и придумывать её здесь нельзя.
    block["detail"] = result.get("monthly")
    return block


def _social_block(summary: dict[str, Any]) -> dict[str, Any]:
    """Социальная нагрузка так, как её отдаёт движок."""
    return {
        "payment": summary.get("social_payment"),
        "payment_mode": summary.get("social_payment_mode"),
        "program": summary.get("social_program"),
        "breakdown": summary.get("social_payment_breakdown"),
        "in_capex_check": summary.get("social_in_capex_check"),
    }


def _queue_block(item: dict[str, Any], comparison: dict[str, Any] | None) -> dict[str, Any]:
    """Очередь: её собственный результат движка, без пересчёта."""
    result = item.get("result") or {}
    report = result.get("report") or {}
    return {
        "name": item.get("name"),
        "index": item.get("index"),
        "start_offset_months": item.get("start_offset_months"),
        "cost_inflation_pct": item.get("cost_inflation_pct"),
        "sales_price_inflation_pct": item.get("sales_price_inflation_pct"),
        "cash_shared_cost": item.get("cash_shared_cost"),
        "allocated_shared_cost": item.get("allocated_shared_cost"),
        "allocated_net_profit": item.get("allocated_net_profit"),
        "summary": result.get("summary"),
        "kpi": _picked(result.get("summary"), _KPI_KEYS),
        "tep": result.get("tep"),
        "vri": result.get("vri"),
        "revenue": result.get("revenue"),
        "capex": result.get("capex"),
        "products": report.get("products"),
        "expense_structure": report.get("expense_structure"),
        "financing": report.get("financing"),
        "calendar": report.get("calendar"),
        "monthly": _monthly_block(result),
        "comparison": comparison,
    }


def _queues(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    phases = bundle.get("phases") or []
    comparison = bundle.get("comparison") or []
    rows: list[dict[str, Any]] = []
    for item, row in zip(phases, comparison):
        rows.append(_queue_block(item, row))
    # Сравнение короче списка очередей быть не должно, но если движок отдал
    # его пустым, очереди всё равно обязаны доехать.
    for item in phases[len(rows):]:
        rows.append(_queue_block(item, None))
    return rows


def _warnings(
    core: Any,
    result: dict[str, Any],
    tep: dict[str, Any],
    broken_products: list[str],
) -> list[str]:
    """Предупреждения движка плюс то, что он обязан донести до экрана.

    Ни одно из них здесь не выводится расчётом: это либо собственные
    предупреждения движка, либо констатация его же чисел.
    """
    messages: list[str] = []
    for text in ((result.get("vri") or {}).get("warnings") or []):
        messages.append(str(text))
    summary = result.get("summary") or {}
    ending_pf = summary.get("ending_pf")
    try:
        ending_pf_value = float(ending_pf or 0.0)
    except (TypeError, ValueError):
        ending_pf_value = 0.0
    if ending_pf_value > _ENDING_PF_NOISE_RUB:
        amount = f"{ending_pf_value:,.0f}".replace(",", " ")
        messages.append(
            f"Долг ПФ не погашается к концу проекта: остаток {amount} ₽. "
            "Выручки через эскроу не хватает на полное погашение проектного "
            "финансирования."
        )
    if broken_products:
        names = ", ".join(broken_products)
        messages.append(
            f"Есть ГНС без продаваемой площади: {names}. Себестоимость этих "
            "продуктов учтена полностью, выручки по ним нет — проверьте ТЭП."
        )
    if summary.get("social_in_capex_check") is False:
        messages.append(
            "Социальная нагрузка в CAPEX расходится с выбранным режимом её "
            "оплаты — проверьте режим социалки и импорт ГлавАПУ."
        )
    return messages


def _verdict(core: Any, inputs: dict[str, Any], result: dict[str, Any],
             broken_products: list[str]) -> dict[str, Any]:
    """Инвестиционный вывод — функцией движка, а не своей копией правил.

    `_purchase_feasibility` сравнивает чистую прибыль и долг с нулём, а LLCR
    с целевым 1,20x: масштаб денег для неё безразличен, поэтому рубли движка
    уходят туда без перевода в миллионы. Цена покупки во вводных и так задана
    в миллионах — это её собственная единица.
    """
    summary = result.get("summary") or {}
    financing = (result.get("report") or {}).get("financing") or {}
    if broken_products:
        names = ", ".join(broken_products)
        return {
            "status": "not_available",
            "title": "Вывод не сформирован — ТЭП неполный",
            "text": (
                f"Нет продаваемой площади: {names}. Себестоимость считается от "
                "ГНС и учтена полностью, выручки по этим продуктам нет — расчёт "
                "показывает убыток по этой причине, а не из-за экономики проекта."
            ),
        }
    return core._purchase_feasibility(
        inputs.get("purchase_price_mln"),
        summary.get("net_profit"),
        summary.get("llcr"),
        max(
            float(financing.get("calculated_bridge") or 0.0),
            float(financing.get("pf_uncovered_peak") or 0.0),
        ),
    )


def build_project_result(
    core: Any,
    *,
    inputs: dict[str, Any],
    tep: dict[str, Any],
    rates: list[dict[str, Any]] | None = None,
    phasing: dict[str, Any] | None = None,
    project_name: str = "",
    region: str = "",
    cadastral_numbers: Sequence[str] = (),
    source_label: str = "",
    scenario: str = "base",
    sensitivity: bool = True,
    sensitivity_metric: str = "llcr",
    calculation_id: str | None = None,
    calculated_at: str | None = None,
) -> dict[str, Any]:
    """Один вызов движка — один ProjectResult.

    `core` — модуль движка (`main.core`). Передаётся аргументом, чтобы модуль
    не поднимал второй экземпляр движка своим импортом.
    """
    rates = list(rates or [])
    phasing = dict(phasing or {})

    # Единственный расчёт. Всё остальное ниже — раскладка его результата.
    bundle = core._run_authoritative_model(inputs, tep, rates, phasing)
    result = bundle.get("consolidated") or {}
    summary = result.get("summary") or {}
    report = result.get("report") or {}

    tornado: dict[str, Any] | None = None
    tornado_error: str | None = None
    if sensitivity:
        # Tornado — отдельный анализ: он сам гоняет движок по одному параметру
        # за расчёт. Без него ProjectResult остаётся полным, поэтому отказ
        # анализа не должен ронять расчёт — он доносится полем.
        try:
            tornado = core.run_sensitivity(
                inputs, tep, rates, phasing, metric=sensitivity_metric,
            )
        except Exception as exc:  # анализ не обязателен, расчёт обязателен
            tornado_error = core._error_location(exc)

    broken_products = list(core._tep_cost_without_revenue(tep) or [])

    return {
        "schema_version": SCHEMA_VERSION,
        # Идентификатор расчёта общий с PDF и книгой: сверка пары начинается
        # с вопроса, один ли это расчёт, и свой идентификатор у каждой
        # поверхности отвечать на него не помогает.
        "calculation_id": calculation_id or core._calculation_fingerprint(
            inputs, tep, phasing),
        "engine_version": core.VERSION,
        "engine_entry_point": ENGINE_ENTRY_POINT,
        "calculated_at": calculated_at or datetime.now(timezone.utc).isoformat(),
        "input_hash": input_hash(inputs, tep, rates, phasing),
        # Явный признак: числа посчитаны движком, а не взяты из fixtures.
        "source": "engine",
        "prototype": False,
        "units": dict(UNITS),
        "mode": bundle.get("mode"),
        "project": {
            "name": str(project_name or ""),
            "region": str(region or ""),
            "cadastral_numbers": [str(item) for item in cadastral_numbers or []],
            "source_label": str(source_label or ""),
            "scenario": str(scenario or "base"),
            "class": inputs.get("project_class"),
        },
        # Исходные вводные едут с результатом: по ним воспроизводится расчёт.
        "request": {
            "inputs": inputs,
            "tep": tep,
            "rates": rates,
            # Движок достраивает конфигурацию очередей — наружу уходит она.
            "phasing": bundle.get("phasing") or phasing,
        },
        "dates": result.get("dates"),
        "tep": result.get("tep"),
        "vri": result.get("vri"),
        "social": _social_block(summary),
        "revenue": {
            "total": (result.get("revenue") or {}).get("total"),
            "by_product": result.get("revenue"),
            "products": report.get("products"),
            "phase_products": report.get("phase_products"),
        },
        "capex": {
            "total": (result.get("capex") or {}).get("total"),
            "by_article": result.get("capex"),
            "structure": report.get("expense_structure"),
            "construction": report.get("construction_costs"),
            "commercial_costs": result.get("commercial_costs"),
        },
        "summary": summary,
        "kpi": _picked(summary, _KPI_KEYS),
        "unit_economics": report.get("unit_economics"),
        "financing": report.get("financing"),
        "calendar": report.get("calendar"),
        "monthly": _monthly_block(result),
        "queues": _queues(bundle),
        "comparison": bundle.get("comparison") or [],
        "sensitivity": tornado,
        "sensitivity_error": tornado_error,
        "warnings": _warnings(core, result, tep, broken_products),
        "verdict": _verdict(core, inputs, result, broken_products),
        "notes": result.get("notes"),
    }
