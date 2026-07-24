from pathlib import Path
import re

p = Path('main.py')
s = p.read_text(encoding='utf-8')

if 'version="0.12.18"' not in s:
    raise SystemExit('Expected v0.12.18 baseline')

s = s.replace('0.12.18', '0.12.19')

# 1. VRI must be part of financed project investment needs.
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

# 2. Track escrow release explicitly.
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

old = '''                available_for_repayment = 0.0
                if month == rve:
                    available_for_repayment = escrow
                    escrow = 0.0
'''
new = '''                available_for_repayment = 0.0
                if month == rve:
                    escrow_release = escrow
                    available_for_repayment = escrow_release
                    escrow = 0.0
'''
if old not in s:
    raise SystemExit('escrow release anchor not found')
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

# 3. Correct user-facing PF exposure: maximum principal not covered by accumulated escrow.
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

# Consolidated/phased finance if present.
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

# 4. Fix the largest IRR distortion: pre-RVE sales are locked on escrow and are not sponsor cash.
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

# 5. Telegram preliminary economics: add total expenses immediately after revenue.
pattern = r'(f"• выручка — \{_telegram_money_mln\(summary\.get\(\'revenue_mln\'\)\)\}\\n"\n)'
replacement = r'''\1        f"• расходы всего — {_telegram_money_mln(summary.get('total_expenses_mln'))}\\n"\n'''
s, count = re.subn(pattern, replacement, s, count=1)
if count != 1:
    raise SystemExit('telegram revenue insertion failed')

# Exact requested wording and metric key.
pattern = r'''\s*f"• (?:пиковый|Пиковый) ПФ — \{_telegram_money_mln\(summary\.get\('pf_peak_mln'\)\)\}\\n\\n"'''
replacement = '''        f"• Пиковая (непокрытая эскроу) задолженность ПФ — {_telegram_money_mln(summary.get('pf_uncovered_peak_mln'))}\\n\\n"'''
s, count = re.subn(pattern, replacement, s, count=1)
if count != 1:
    raise SystemExit('telegram PF label replacement failed')

# The current financing engine has no explicit sponsor-equity requirement; displaying IRR equity as a hard
# preliminary KPI is misleading and can become extremely high when debt finances nearly all costs.
# Keep the internal proxy for diagnostics/full model, but remove it from the preliminary Telegram card.
s, irr_removed = re.subn(
    r'''\s*f"• IRR equity — \{irr_text\}\\n"''',
    '',
    s,
    count=1,
)
if irr_removed != 1:
    raise SystemExit('preliminary IRR line removal failed')

# 6. Send total expenses and uncovered PF exposure in the Telegram payload.
pattern = r'(\s*revenue_mln:Number\(s\.revenue\|\|0\)/1e6,\n)'
replacement = r'''\1    total_expenses_mln:Number(s.total_expenses||0)/1e6,\n'''
s, count = re.subn(pattern, replacement, s, count=1)
if count != 1:
    raise SystemExit('telegram payload total expenses insertion failed')

pattern = r'\s*pf_peak_mln:Number\(f\.pf_peak\|\|0\)/1e6'
replacement = '    pf_uncovered_peak_mln:Number(f.pf_uncovered_peak||0)/1e6'
s, count = re.subn(pattern, replacement, s, count=1)
if count != 1:
    raise SystemExit('telegram payload PF replacement failed')

# Replace any remaining visible old label, not internal field names.
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
if 'debt_capex[project_start] = max' in s:
    raise SystemExit('VRI is still excluded from debt funding')

p.write_text(s, encoding='utf-8')
print('URGENT_FINANCE_PATCH_OK')
