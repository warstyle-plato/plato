from pathlib import Path

p = Path('main.py')
s = p.read_text(encoding='utf-8')

if 'version="0.12.18"' not in s:
    raise SystemExit('Expected v0.12.18 baseline')


def replace_once(old: str, new: str, label: str) -> None:
    global s
    if old not in s:
        raise SystemExit(f'Missing anchor: {label}')
    s = s.replace(old, new, 1)


s = s.replace('0.12.18', '0.12.19')

# VRI is an investment need. It must be funded in the same bridge/PF chain,
# not silently excluded from debt requirement.
replace_once(
'''    calculated_bridge_limit = (
        n(x, "purchase_price_mln") * 1_000_000
        + op["capex_amounts"]["design_p"]
''',
'''    calculated_bridge_limit = (
        n(x, "purchase_price_mln") * 1_000_000
        + op["capex_amounts"]["land_rights"]
        + op["capex_amounts"]["design_p"]
''',
'calculated bridge VRI',
)

replace_once(
'''    # Land/VRI is included in project investment CAPEX but is not automatically debt-funded.
    # This follows the current credit model more closely: the bridge/PF funding base is project construction cash needs.
    debt_capex = dict(capex)
    debt_capex[project_start] = max(
        debt_capex.get(project_start, 0.0) - amounts["land_rights"], 0.0
    )
''',
'''    # VRI / land-rights payment is part of project investment needs and is included
    # in bridge/PF funding requirement together with the other eligible project CAPEX.
    debt_capex = dict(capex)
''',
'VRI debt exclusion',
)

# Track release of accumulated escrow at RVE.
replace_once(
'''            pf_draw = pf_repayment = pf_interest = pf_cap = limit_fee = 0.0
            interest_payment = 0.0
''',
'''            pf_draw = pf_repayment = pf_interest = pf_cap = limit_fee = 0.0
            interest_payment = 0.0
            escrow_release = 0.0
''',
'monthly escrow variable',
)

replace_once(
'''                available_for_repayment = 0.0
                if month == rve:
                    available_for_repayment = escrow
                    escrow = 0.0
''',
'''                available_for_repayment = 0.0
                if month == rve:
                    escrow_release = escrow
                    available_for_repayment = escrow_release
                    escrow = 0.0
''',
'escrow release',
)

replace_once(
'''                "escrow": escrow,
                "coverage": coverage,
''',
'''                "escrow": escrow,
                "escrow_release": escrow_release,
                "coverage": coverage,
''',
'financing row escrow release',
)

# User metric = peak PF principal not covered by accumulated escrow.
replace_once(
'''            "peak_pf": max((r["pf_balance"] for r in rows), default=0.0),
            "avg_pf_rate": weighted_pf_num / weighted_pf_den if weighted_pf_den else 0.0,
''',
'''            "peak_pf": max((r["pf_balance"] for r in rows), default=0.0),
            "peak_uncovered_pf": max((max(r["pf_balance"] - r["escrow"], 0.0) for r in rows), default=0.0),
            "avg_pf_rate": weighted_pf_num / weighted_pf_den if weighted_pf_den else 0.0,
''',
'peak uncovered PF',
)

# Consolidated/phased finance if the aggregation block is present.
s = s.replace(
'''    peak_pf = max((r["pf_balance"] for r in rows), default=0.0)
    peak_total_debt = max((r["bridge_balance"] + r["pf_balance"] for r in rows), default=0.0)
''',
'''    peak_pf = max((r["pf_balance"] for r in rows), default=0.0)
    peak_uncovered_pf = max((max(r["pf_balance"] - r["escrow"], 0.0) for r in rows), default=0.0)
    peak_total_debt = max((r["bridge_balance"] + r["pf_balance"] for r in rows), default=0.0)
''', 1)
s = s.replace(
'''        "peak_pf": peak_pf,
        "pf_repayment_total": sum(f["pf_repayment_total"] for f in fs),
''',
'''        "peak_pf": peak_pf,
        "peak_uncovered_pf": peak_uncovered_pf,
        "pf_repayment_total": sum(f["pf_repayment_total"] for f in fs),
''', 1)

replace_once(
'''                "pf_peak": fin["peak_pf"],
                "pf_limit": fin["pf_limit"],
''',
'''                "pf_peak": fin["peak_pf"],
                "pf_uncovered_peak": fin.get("peak_uncovered_pf", 0.0),
                "pf_limit": fin["pf_limit"],
''',
'report financing uncovered PF',
)

# IRR distortion: pre-RVE sales are locked on escrow and cannot be treated as sponsor cash.
replace_once(
'''        project_cf.append(revenue_m - capex_m - opex_m - int_pay - fees - tax)
        equity_cf.append(
            revenue_m - capex_m - opex_m - int_pay - fees - tax
            + bridge_draw + pf_draw - bridge_repay - pf_repay
        )
''',
'''        project_cf.append(revenue_m - capex_m - opex_m - int_pay - fees - tax)
        escrow_release = float(fr.get("escrow_release", 0.0) or 0.0)
        cash_revenue_to_equity = 0.0 if month < op["rve"] else revenue_m + escrow_release
        equity_cf.append(
            cash_revenue_to_equity - capex_m - opex_m - int_pay - fees - tax
            + bridge_draw + pf_draw - bridge_repay - pf_repay
        )
''',
'equity cash flow escrow timing',
)

# Preliminary Telegram card: expenses next to revenue; exact requested PF wording;
# hide IRR equity because the model has no explicit sponsor-equity requirement and the proxy can be meaningless.
replace_once(
'''        "<b>Предварительная экономика</b>\n"
        f"• цена покупки — {_telegram_money_mln(summary.get('purchase_price_mln'))}\n"
        f"• выручка — {_telegram_money_mln(summary.get('revenue_mln'))}\n"
        f"• EBITDA — {_telegram_money_mln(summary.get('ebitda_mln'))}\n"
        f"• чистая прибыль — {_telegram_money_mln(summary.get('net_profit_mln'))}\n"
        f"• маржинальность — {margin_text}\n"
        f"• IRR equity — {irr_text}\n"
        f"• LLCR — {_telegram_number(summary.get('llcr'), 2)}x\n"
        f"• расчётный БРИДЖ — {_telegram_money_mln(summary.get('calculated_bridge_mln'))}\n"
        f"• пиковый ПФ — {_telegram_money_mln(summary.get('pf_peak_mln'))}\n\n"
''',
'''        "<b>Предварительная экономика</b>\n"
        f"• цена покупки — {_telegram_money_mln(summary.get('purchase_price_mln'))}\n"
        f"• выручка — {_telegram_money_mln(summary.get('revenue_mln'))}\n"
        f"• расходы всего — {_telegram_money_mln(summary.get('total_expenses_mln'))}\n"
        f"• EBITDA — {_telegram_money_mln(summary.get('ebitda_mln'))}\n"
        f"• чистая прибыль — {_telegram_money_mln(summary.get('net_profit_mln'))}\n"
        f"• маржинальность — {margin_text}\n"
        f"• LLCR — {_telegram_number(summary.get('llcr'), 2)}x\n"
        f"• расчётный БРИДЖ — {_telegram_money_mln(summary.get('calculated_bridge_mln'))}\n"
        f"• Пиковая (непокрытая эскроу) задолженность ПФ — {_telegram_money_mln(summary.get('pf_uncovered_peak_mln'))}\n\n"
''',
'preliminary economics card',
)

# Telegram payload.
replace_once(
'''    revenue_mln:Number(s.revenue||0)/1e6,
    ebitda_mln:Number(s.ebitda||0)/1e6,
''',
'''    revenue_mln:Number(s.revenue||0)/1e6,
    total_expenses_mln:Number(s.total_expenses||0)/1e6,
    ebitda_mln:Number(s.ebitda||0)/1e6,
''',
'telegram total expenses payload',
)
replace_once(
'''    calculated_bridge_mln:Number(f.calculated_bridge||0)/1e6,
    pf_peak_mln:Number(f.pf_peak||0)/1e6
''',
'''    calculated_bridge_mln:Number(f.calculated_bridge||0)/1e6,
    pf_uncovered_peak_mln:Number(f.pf_uncovered_peak||0)/1e6
''',
'telegram uncovered PF payload',
)

# Full model top KPIs: do not present misleading equity IRR proxy; show exact requested PF metric.
replace_once(
'''   ['NPV @'+Number(inputs.discount_rate_pct||20).toLocaleString('ru-RU')+'%',money(r.summary.npv)],
   ['IRR equity',irrFmt(r.summary.irr_equity)],
   ['LLCR (расчётный)',mult(r.summary.llcr)],
''',
'''   ['NPV @'+Number(inputs.discount_rate_pct||20).toLocaleString('ru-RU')+'%',money(r.summary.npv)],
   ['LLCR (расчётный)',mult(r.summary.llcr)],
''',
'report IRR display',
)
replace_once(
'''   ['Фактический БРИДЖ',money(r.report.financing.actual_bridge)],
   ['Пиковый ПФ',money(r.report.financing.pf_peak)]
''',
'''   ['Фактический БРИДЖ',money(r.report.financing.actual_bridge)],
   ['Пиковая (непокрытая эскроу) задолженность ПФ',money(r.report.financing.pf_uncovered_peak)]
''',
'report uncovered PF KPI',
)
replace_once(
'''   ['Пиковый БРИДЖ',money(f.peak_bridge)],
   ['Пиковый ПФ',money(f.peak_pf)],
''',
'''   ['Пиковый БРИДЖ',money(f.peak_bridge)],
   ['Пиковая (непокрытая эскроу) задолженность ПФ',money(f.peak_uncovered_pf)],
''',
'finance uncovered PF KPI',
)

# Phase comparison keeps the gross technical balance but names it accurately.
s = s.replace(
"   ['Пиковый ПФ',c.map(x=>money(x.peak_pf)),money(cons.finance.peak_pf)],",
"   ['Пиковый остаток ПФ',c.map(x=>money(x.peak_pf)),money(cons.finance.peak_pf)],",
1,
)

for marker in (
    'version="0.12.19"',
    '+ op["capex_amounts"]["land_rights"]',
    'escrow_release',
    'peak_uncovered_pf',
    'pf_uncovered_peak',
    'cash_revenue_to_equity',
    'total_expenses_mln',
    'расходы всего',
    'Пиковая (непокрытая эскроу) задолженность ПФ',
):
    if marker not in s:
        raise SystemExit('Missing post-patch marker: ' + marker)
if 'debt_capex[project_start] = max' in s:
    raise SystemExit('VRI is still excluded from debt funding')

p.write_text(s, encoding='utf-8')
print('URGENT_FINANCE_PATCH_OK')
