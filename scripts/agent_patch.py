from pathlib import Path
p=Path('main.py')
s=p.read_text(encoding='utf-8')

old_dates='''    if b(x,"offices_enabled"):\n        x.setdefault("offices_start",add_months(project_start,18).isoformat())\n        x.setdefault("offices_sales_start",add_months(project_start,18).isoformat())\n    if b(x,"retail_enabled"):\n        x.setdefault("retail_start",add_months(project_start,18).isoformat())\n        x.setdefault("retail_sales_start",add_months(project_start,18).isoformat())\n    if b(x,"above_parking_enabled"):\n        x.setdefault("above_parking_start",add_months(project_start,18).isoformat())\n        x.setdefault("above_parking_sales_start",add_months(project_start,18).isoformat())\n'''
new_dates='''    # Reporting/product KPI code reads these dates even when an optional product is disabled.\n    x.setdefault("offices_start",add_months(project_start,18).isoformat())\n    x.setdefault("offices_sales_start",add_months(project_start,18).isoformat())\n    x.setdefault("retail_start",add_months(project_start,18).isoformat())\n    x.setdefault("retail_sales_start",add_months(project_start,18).isoformat())\n    x.setdefault("above_parking_start",add_months(project_start,18).isoformat())\n    x.setdefault("above_parking_sales_start",add_months(project_start,18).isoformat())\n'''
if old_dates in s:
    s=s.replace(old_dates,new_dates,1)

old='''    revenue=_telegram_result_value(result,"total_revenue")/1_000_000\n    capex=_telegram_result_value(result,"total_capex")/1_000_000\n    ebitda=_telegram_result_value(result,"ebitda")/1_000_000\n    net_profit=_telegram_result_value(result,"net_profit")/1_000_000\n    llcr=_telegram_result_value(result,"llcr")\n    irr=result.get("irr_equity")\n'''
new='''    calc_summary=result.get("summary") or {}\n    revenue=_telegram_result_value(calc_summary,"revenue")/1_000_000\n    capex=_telegram_result_value(calc_summary,"capex")/1_000_000\n    ebitda=_telegram_result_value(calc_summary,"ebitda")/1_000_000\n    net_profit=_telegram_result_value(calc_summary,"net_profit")/1_000_000\n    llcr=_telegram_result_value(calc_summary,"llcr")\n    irr=calc_summary.get("irr_equity")\n'''
if old not in s:
    raise SystemExit('result mapping block not found')
s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
print('runtime mapping patched')
