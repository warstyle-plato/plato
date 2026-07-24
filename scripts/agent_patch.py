from pathlib import Path
p=Path('main.py')
s=p.read_text(encoding='utf-8')
old='''    if b(x,"offices_enabled"):\n        x.setdefault("offices_start",add_months(project_start,18).isoformat())\n        x.setdefault("offices_sales_start",add_months(project_start,18).isoformat())\n    if b(x,"retail_enabled"):\n        x.setdefault("retail_start",add_months(project_start,18).isoformat())\n        x.setdefault("retail_sales_start",add_months(project_start,18).isoformat())\n    if b(x,"above_parking_enabled"):\n        x.setdefault("above_parking_start",add_months(project_start,18).isoformat())\n        x.setdefault("above_parking_sales_start",add_months(project_start,18).isoformat())\n'''
new='''    # Reporting/product KPI code reads these dates even when an optional product is disabled.\n    # Keep harmless defaults so the preliminary model can run with any TEP composition.\n    x.setdefault("offices_start",add_months(project_start,18).isoformat())\n    x.setdefault("offices_sales_start",add_months(project_start,18).isoformat())\n    x.setdefault("retail_start",add_months(project_start,18).isoformat())\n    x.setdefault("retail_sales_start",add_months(project_start,18).isoformat())\n    x.setdefault("above_parking_start",add_months(project_start,18).isoformat())\n    x.setdefault("above_parking_sales_start",add_months(project_start,18).isoformat())\n'''
if old not in s: raise SystemExit('date block not found')
p.write_text(s.replace(old,new,1),encoding='utf-8')
print('date defaults patched')
