from pathlib import Path

p = Path('main.py')
s = p.read_text(encoding='utf-8')

if 'version="0.12.18"' not in s:
    raise SystemExit('Expected v0.12.18 baseline')

s = s.replace('0.12.18', '0.12.19')

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

old = '''    peak_pf = max((r["pf_balance"] for r in rows), default=0.0)
    peak_total_debt = max((r["bridge_balance"] + r["pf_balance"] for r in rows), default=0.0)
'''
new = '''    peak_pf = max((r["pf_balance"] for r in rows), default=0.0)
    peak_uncovered_pf = max((max(r["pf_balance"] - r["escrow"], 0.0) for r in rows), default=0.0)
    peak_total_debt = max((r["bridge_balance"] + r["pf_balance"] for r in rows), default=0.0)
'''
if old not in s:
    raise SystemExit('aggregate peak_pf anchor not found')
s = s.replace(old, new, 1)

old = '''        "peak_pf": peak_pf,
        "pf_repayment_total": sum(f["pf_repayment_total"] for f in fs),
'''
new = '''        "peak_pf": peak_pf,
        "peak_uncovered_pf": peak_uncovered_pf,
        "pf_repayment_total": sum(f["pf_repayment_total"] for f in fs),
'''
if old not in s:
    raise SystemExit('aggregate return peak_pf anchor not found')
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
new = '''        f"• макс. не покрытая эскроу задолженность по ПФ — {_telegram_money_mln(summary.get('pf_uncovered_peak_mln'))}\n\n"
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

for marker in (
    'version="0.12.19"',
    'peak_uncovered_pf',
    'pf_uncovered_peak',
    'total_expenses_mln',
    'расходы всего',
    'макс. не покрытая эскроу задолженность по ПФ',
):
    if marker not in s:
        raise SystemExit('Missing post-patch marker: ' + marker)

p.write_text(s, encoding='utf-8')
print('PF_AND_EXPENSES_PATCH_OK')
