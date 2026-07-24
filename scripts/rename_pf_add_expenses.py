from pathlib import Path

p = Path('main.py')
s = p.read_text(encoding='utf-8')

if 'version="0.12.18"' not in s:
    raise SystemExit('Expected v0.12.18 baseline')

s = s.replace('0.12.18', '0.12.19')

# VRI must be included in debt-funded project cash needs. Remove the explicit exclusion.
old = '''    # Land/VRI is included in project investment CAPEX but is not automatically debt-funded.
    # This follows the current credit model more closely: the bridge/PF funding base is project construction cash needs.
    debt_capex = dict(capex)
    debt_capex[project_start] = max(
        debt_capex.get(project_start, 0.0) - amounts["land_rights"], 0.0
    )
'''
new = '''    # VRI / land-rights payment is part of project investment needs and is included
    # in bridge/PF funding requirement together with the other eligible project CAPEX.
    debt_capex = dict(capex)
'''
if old not in s:
    raise SystemExit('VRI debt exclusion anchor not found')
s = s.replace(old, new, 1)

# Track escrow release explicitly and calculate the exact requested exposure metric.
old = '''                available_for_repayment = 0.0
                if month == rve:
                    available_for_repayment = escrow
                    escrow = 0.0
'''
new = '''                available_for_repayment = 0.0
                escrow_release = 0.0
                if month == rve:
                    escrow_release = escrow
                    available_for_repayment = escrow_release
                    escrow = 0.0
'''
if old not in s:
    raise SystemExit('escrow release anchor not found')
s = s.replace(old, new, 1)

# Ensure variable exists before the branch where it is used in the row.
old = '''            pf_draw = pf_repayment = pf_interest = pf_cap = limit_fee = 0.0
            interest_payment = 0.0
'''
new = '''            pf_draw = pf_repayment = pf_interest = pf_cap = limit_fee = 0.0
            interest_payment = 0.0
            escrow_release = 0.0
'''
if old not in s:
    raise SystemExit('monthly variable anchor not found')
s = s.replace(old, new, 1)

old = '''                "escrow": escrow,
                "coverage": coverage,
'''
new = '''                "escrow": escrow,
                "escrow_release": escrow_release,
                "coverage": coverage,
'''
if old not in s:
    raise SystemExit('financing row escrow anchor not found')
s = s.replace(old, new, 1)

old = '''            "peak_pf": max((r["pf_balance"] for r in rows), default=0.0),
            "avg_pf_rate": weighted_pf_num / weighted_pf_den if weighted_pf_den else 0.0,
'''
new = '''            "peak_pf": max((r["pf_balance"] for r in rows), default=0.0),
            "peak_uncovered_pf": max((max(r["pf_balance"] - r["escrow"], 0.0) for r in rows), default=0.0),
            "avg_pf_rate": weighted_pf_num / weighted_pf_den if weighted_pf_den else 0.0,
'''
if old not in s:
    raise SystemExit('simulate_financing peak_pf anchor not found')
s = s.replace(old, new, 1)

# Consolidated/phased calculations need the same metric.
old = '''    peak_pf = max((r["pf_balance"] for r in rows), default=0.0)
    peak_total_debt = max((r["bridge_balance"] + r["pf_balance"] for r in rows), default=0.0)
'''
new = '''    peak_pf = max((r["pf_balance"] for r in rows), default=0.0)
    peak_uncovered_pf = max((max(r["pf_balance"] - r["escrow"], 0.0) for r in rows), default=0.0)
    peak_total_debt = max((r["bridge_balance"] + r["pf_balance"] for r in rows), default=0.0)
'''
if old in s:
    s = s.replace(old, new, 1)
old = '''        "peak_pf": peak_pf,
        "pf_repayment_total": sum(f["pf_repayment_total"] for f in fs),
'''
new = '''        "peak_pf": peak_pf,
        "peak_uncovered_pf": peak_uncovered_pf,
        "pf_repayment_total": sum(f["pf_repayment_total"] for f in fs),
'''
if old in s:
    s = s.replace(old, new, 1)

old = '''                "pf_peak": fin["peak_pf"],
                "pf_limit": fin["pf_limit"],
'''
new = '''                "pf_peak": fin["peak_pf"],
                "pf_uncovered_peak": fin.get("peak_uncovered_pf", 0.0),
                "pf_limit": fin["pf_limit"],
'''
if old not in s:
    raise SystemExit('report financing pf_peak anchor not found')
s = s.replace(old, new, 1)

# Fix equity IRR cash flow: pre-RVE apartment sales are trapped on escrow and cannot be
# treated as sponsor cash. At RVE only released escrow after PF repayment can reach equity.
old = '''        project_cf.append(revenue_m - capex_m - opex_m - int_pay - fees - tax)
        equity_cf.append(
            revenue_m - capex_m - opex_m - int_pay - fees - tax
            + bridge_draw + pf_draw - bridge_repay - pf_repay
        )
'''
new = '''        project_cf.append(revenue_m - capex_m - opex_m - int_pay - fees - tax)
        escrow_release = float(fr.get("escrow_release", 0.0) or 0.0)
        cash_revenue_to_equity = 0.0 if month < op["rve"] else revenue_m + escrow_release
        equity_cf.append(
            cash_revenue_to_equity - capex_m - opex_m - int_pay - fees - tax
            + bridge_draw + pf_draw - bridge_repay - pf_repay
        )
'''
if old not in s:
    raise SystemExit('equity CF anchor not found')
s = s.replace(old, new, 1)

# Telegram preliminary economics: show total expenses and requested PF wording.
old = '''        f"• выручка — {_telegram_money_mln(summary.get('revenue_mln'))}\n"
        f"• EBITDA — {_telegram_money_mln(summary.get('ebitda_mln'))}\n"
'''
new = '''        f"• выручка — {_telegram_money_mln(summary.get('revenue_mln'))}\n"
        f"• расходы всего — {_telegram_money_mln(summary.get('total_expenses_mln'))}\n"
        f"• EBITDA — {_telegram_money_mln(summary.get('ebitda_mln'))}\n"
'''
if old not in s:
    raise SystemExit('telegram revenue/EBITDA anchor not found')
s = s.replace(old, new, 1)

old = '''        f"• пиковый ПФ — {_telegram_money_mln(summary.get('pf_peak_mln'))}\n\n"
'''
new = '''        f"• Пиковая (непокрытая эскроу) задолженность ПФ — {_telegram_money_mln(summary.get('pf_uncovered_peak_mln'))}\n\n"
'''
if old not in s:
    raise SystemExit('telegram peak PF label anchor not found')
s = s.replace(old, new, 1)

old = '''    revenue_mln:Number(s.revenue||0)/1e6,
    ebitda_mln:Number(s.ebitda||0)/1e6,
'''
new = '''    revenue_mln:Number(s.revenue||0)/1e6,
    total_expenses_mln:Number(s.total_expenses||0)/1e6,
    ebitda_mln:Number(s.ebitda||0)/1e6,
'''
if old not in s:
    raise SystemExit('telegram payload revenue anchor not found')
s = s.replace(old, new, 1)

old = '''    calculated_bridge_mln:Number(f.calculated_bridge||0)/1e6,
    pf_peak_mln:Number(f.pf_peak||0)/1e6
'''
new = '''    calculated_bridge_mln:Number(f.calculated_bridge||0)/1e6,
    pf_uncovered_peak_mln:Number(f.pf_uncovered_peak||0)/1e6
'''
if old not in s:
    raise SystemExit('telegram payload PF anchor not found')
s = s.replace(old, new, 1)

# Replace visible old KPI labels where present, but retain internal pf_peak field for compatibility.
s = s.replace('Пиковый ПФ', 'Пиковая (непокрытая эскроу) задолженность ПФ')
s = s.replace('пиковый ПФ', 'Пиковая (непокрытая эскроу) задолженность ПФ')

for marker in (
    'version="0.12.19"',
    'debt_capex = dict(capex)',
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

p.write_text(s, encoding='utf-8')
print('URGENT_FINANCE_PATCH_OK')
