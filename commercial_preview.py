"""Staging copy of the current DevelopAid.ru with commercial beta added.

Runs the normal current site from main.py and injects only one extra tab.
Main branch and production are not changed.
"""

from __future__ import annotations

from html import escape
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse

import main as site
import developaid_commercial as commercial

app = site.app
core = site.core

commercial.install(app)

COMMON = [
    "land_cost_rub", "gross_area_sqm", "construction_cost_rub_sqm",
    "soft_cost_pct", "contingency_pct", "construction_months",
]
INCOME_COMMON = [
    "opening_occupancy_pct", "occupancy_pct", "stabilization_months",
    "hold_years", "exit_cap_rate_pct", "exit_cost_pct",
    "project_discount_rate_pct", "equity_hurdle_rate_pct",
]
SALE_COMMON = [
    "sale_start_month", "sale_months", "sales_curve",
    "sale_price_growth_pct", "selling_cost_pct",
    "project_discount_rate_pct", "equity_hurdle_rate_pct",
]
FINANCE = [
    "debt_share_pct", "debt_rate_pct", "loan_fee_pct",
    "sales_cash_sweep_pct",
]


def field_keys(asset: str, strategy: str, financing: str) -> list[str]:
    keys = list(COMMON)
    if strategy == "income":
        keys.extend(INCOME_COMMON)
        if asset == "office":
            keys.extend([
                "income_area_sqm", "rent_rub_sqm_month", "rent_growth_pct",
                "other_income_pct", "opex_pct", "leasing_cost_pct",
            ])
        elif asset == "retail":
            keys.extend([
                "income_area_sqm", "rent_rub_sqm_month",
                "sales_rub_sqm_month", "turnover_rent_pct",
                "rent_growth_pct", "opex_pct", "marketing_pct",
            ])
        else:
            keys.extend([
                "keys", "adr_rub", "adr_growth_pct", "other_revenue_pct",
                "opex_pct", "management_fee_pct", "ffe_reserve_pct",
                "preopening_cost_rub",
            ])
    else:
        keys.extend(SALE_COMMON)
        if asset == "hotel":
            keys.extend(["saleable_keys", "sale_price_rub_key", "preopening_cost_rub"])
        else:
            keys.extend(["saleable_area_sqm", "sale_price_rub_sqm"])
    if financing == "equity_debt":
        keys.extend(FINANCE)
    return list(dict.fromkeys(keys))


def money(value: Any) -> str:
    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "—"


def multiple(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}x"
    except (TypeError, ValueError):
        return "—"


def options(rows: list[tuple[str, str]], current: str) -> str:
    return "".join(
        '<option value="' + escape(key) + '"' +
        (" selected" if key == current else "") + ">" +
        escape(label) + "</option>"
        for key, label in rows
    )


def render_commercial(
    asset: str,
    strategy: str,
    financing: str,
    values: dict[str, Any],
    result: dict[str, Any],
) -> str:
    fields = []
    for key in field_keys(asset, strategy, financing):
        label, unit = commercial.FIELD_LABELS.get(key, (key, ""))
        value = values.get(key, "")
        if key == "sales_curve":
            control = (
                '<select name="i_sales_curve">'
                + options([
                    ("bell", "Колокол"),
                    ("flat", "Равномерно"),
                    ("front_loaded", "В начале"),
                    ("back_loaded", "В конце"),
                ], str(value or "bell"))
                + "</select>"
            )
        else:
            control = (
                '<input name="i_' + escape(key) +
                '" type="number" step="any" value="' +
                escape(str(value)) + '">'
            )
        fields.append(
            "<label><span>" + escape(label) +
            (" <small>" + escape(unit) + "</small>" if unit else "") +
            "</span>" + control + "</label>"
        )

    k = result.get("kpi") or {}
    cards = [
        ("Development cost", money(k.get("development_cost"))),
        ("Total revenue", money(k.get("total_revenue"))),
        ("Прибыль до налога", money(k.get("profit_before_tax"))),
        ("Маржа", pct(k.get("margin"))),
        ("Project IRR", pct(k.get("project_irr"))),
        ("Project NPV", money(k.get("project_npv"))),
        ("Equity required", money(k.get("equity_required"))),
        ("Equity IRR", pct(k.get("equity_irr"))),
        ("Equity multiple", multiple(k.get("equity_multiple"))),
        ("Peak debt", money(k.get("peak_debt"))),
        ("LTC", pct(k.get("ltc"))),
        ("Exit LTV", pct(k.get("exit_ltv"))),
        ("Interest cover", multiple(k.get("interest_cover"))),
        ("Debt yield", pct(k.get("debt_yield"))),
        ("NOI / год", money(k.get("stabilized_noi_annual"))),
        ("Yield on cost", pct(k.get("yield_on_cost"))),
        ("Exit value", money(k.get("exit_value"))),
        ("Net exit proceeds", money(k.get("net_exit_proceeds"))),
    ]
    kpi_html = "".join(
        '<div class="k"><span>' + escape(label) + '</span><b>' +
        escape(value) + '</b></div>'
        for label, value in cards
    )

    annual_html = "".join(
        "<tr>"
        f"<td>{int(row.get('year') or 0)}</td>"
        f"<td>{money(row.get('development_spend'))}</td>"
        f"<td>{money(row.get('operating_revenue'))}</td>"
        f"<td>{money(row.get('sale_revenue'))}</td>"
        f"<td>{money(row.get('terminal_value'))}</td>"
        f"<td>{money(row.get('project_cashflow'))}</td>"
        f"<td>{money(row.get('debt_draw'))}</td>"
        f"<td>{money(row.get('interest'))}</td>"
        f"<td>{money(row.get('debt_repayment'))}</td>"
        f"<td>{money(row.get('ending_debt'))}</td>"
        f"<td>{money(row.get('equity_cashflow'))}</td>"
        "</tr>"
        for row in (result.get("annual") or [])
    )
    check_html = "".join(
        "<tr><td>" + escape(str(key)) + "</td><td><b>" +
        escape(str(value)) + "</b></td></tr>"
        for key, value in (result.get("checks") or {}).items()
    )
    warnings = "<br>".join(
        "• " + escape(str(item)) for item in (result.get("warnings") or [])
    )

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#fff;color:#171717;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}}
.card,form{{border:1px solid #dedede;padding:18px;margin:0 0 16px;background:#fff}}
.selectors{{display:grid;grid-template-columns:repeat(3,minmax(180px,1fr));gap:12px}}
.fields{{display:grid;grid-template-columns:repeat(2,minmax(180px,1fr));gap:10px 14px;margin-top:16px}}
label span{{display:block;font-size:12px;color:#555;margin-bottom:4px}}small{{color:#999;font-size:10px}}
input,select{{width:100%;border:1px solid #cfcfcf;background:#fff;padding:9px 10px;font-size:14px}}
button{{border:1px solid #111;background:#111;color:#fff;padding:10px 15px;font-weight:700;cursor:pointer}}
.kpis{{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));border-top:1px solid #111;border-left:1px solid #dedede}}
.k{{padding:14px;border-right:1px solid #dedede;border-bottom:1px solid #dedede;min-height:82px}}
.k span{{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#777}}.k b{{display:block;font-size:18px;margin-top:8px;font-weight:620}}
table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:8px;border-bottom:1px solid #e2e2e2;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}th{{font-size:10px;text-transform:uppercase;color:#777;background:#fafafa}}.scroll{{overflow:auto}}
.note{{padding:12px 14px;background:#fff8e6;border-left:3px solid #9a6700;font-size:12px;line-height:1.5}}
h3{{margin:0 0 12px}}@media(max-width:800px){{.selectors,.fields{{grid-template-columns:1fr}}.kpis{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<form method="get" action="/commercial-beta">
  <div class="selectors">
    <label><span>Тип объекта</span><select name="asset" onchange="this.form.submit()">{options([("office","Офис"),("retail","Торговый объект"),("hotel","Гостиница")],asset)}</select></label>
    <label><span>Модель реализации</span><select name="strategy" onchange="this.form.submit()">{options([("income","Доходная / hold"),("sale","Продажа")],strategy)}</select></label>
    <label><span>Финансирование</span><select name="financing" onchange="this.form.submit()">{options([("equity_debt","Equity + обычный кредит"),("equity","100% equity")],financing)}</select></label>
  </div>
  <div class="fields">{''.join(fields)}</div>
  <div style="margin-top:14px"><button type="submit">Рассчитать</button></div>
</form>
<div class="card"><h3>Ключевые показатели</h3><div class="kpis">{kpi_html}</div></div>
<div class="card"><h3>Годовой cash flow</h3><div class="scroll"><table>
<thead><tr><th>Год</th><th>Development</th><th>Operating rev.</th><th>Sale rev.</th><th>Exit</th><th>Project CF</th><th>Debt draw</th><th>Interest</th><th>Repayment</th><th>Debt balance</th><th>Equity CF</th></tr></thead>
<tbody>{annual_html}</tbody></table></div></div>
<div class="card"><h3>Проверки движка</h3><table><tbody>{check_html}</tbody></table></div>
<div class="note">{warnings}</div>
</body></html>"""


@app.get("/commercial-beta", response_class=HTMLResponse, include_in_schema=False)
async def commercial_beta(request: Request) -> HTMLResponse:
    qp = request.query_params
    asset = str(qp.get("asset") or "office")
    strategy = str(qp.get("strategy") or "income")
    financing = str(qp.get("financing") or "equity_debt")
    if asset not in commercial.ASSET_DEFAULTS:
        asset = "office"
    if strategy not in {"income", "sale"}:
        strategy = "income"
    if financing not in {"equity", "equity_debt"}:
        financing = "equity_debt"

    values = commercial.default_inputs(asset)
    for key in field_keys(asset, strategy, financing):
        raw = qp.get("i_" + key)
        if raw is None:
            continue
        if key == "sales_curve":
            values[key] = str(raw)
        else:
            try:
                values[key] = float(raw)
            except (TypeError, ValueError):
                pass

    result = commercial.calculate(commercial.CommercialRequest(
        asset_type=asset,
        strategy=strategy,
        financing_mode=financing,
        inputs=values,
    ))
    return HTMLResponse(
        render_commercial(asset, strategy, financing, values, result),
        headers={"Cache-Control": "no-store"},
    )


page = str(core.PAGE)
tab_anchor = (
    '<button class="tab" data-tab="finance" '
    'onclick="openTab(\'finance\',this)">Финансирование</button>'
)
tab = (
    '<button class="tab" data-tab="commercial" '
    'onclick="openTab(\'commercial\',this)">Нежилая экономика β</button>'
)
if 'data-tab="commercial"' not in page:
    if tab_anchor not in page:
        raise RuntimeError("Commercial staging: finance tab anchor not found")
    page = page.replace(tab_anchor, tab_anchor + tab, 1)

panel = """
<div id="commercial" class="panel">
  <div class="card">
    <div class="section-title">Отдельный контур нежилой экономики · beta</div>
    <h2>Офис · торговля · гостиница</h2>
    <div class="note">Тестовый контур этой ветки. Жилая экономика, эскроу и льготная ставка проектного финансирования сюда не переносятся.</div>
  </div>
  <iframe src="/commercial-beta" title="Нежилая экономика" style="width:100%;height:1650px;border:0;background:#fff"></iframe>
</div>
"""
if 'id="commercial" class="panel"' not in page:
    report_anchor = '<div id="report" class="panel">'
    if report_anchor not in page:
        raise RuntimeError("Commercial staging: report panel anchor not found")
    page = page.replace(report_anchor, panel + "\n" + report_anchor, 1)

core.PAGE = page
