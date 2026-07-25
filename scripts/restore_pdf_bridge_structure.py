from pathlib import Path

p = Path('main.py')
s = p.read_text(encoding='utf-8')

if 'version="0.12.24"' not in s:
    raise SystemExit('Expected v0.12.24 baseline')

# Bump all user-visible/runtime version strings consistently.
s = s.replace('0.12.24', '0.12.25')

old = '''    story.append(table(finance_rows,[112*mm,58*mm],font_size=7.6))

    timeline_rows=list((result.get("finance") or {}).get("rows") or [])
'''
new = '''    story.append(table(finance_rows,[112*mm,58*mm],font_size=7.6))

    # Restore the bridge-purpose disclosure that exists in the web report.
    # VRI is deliberately absent: it is funded directly by PF at RnS/permit.
    bridge_total = float(financing.get("calculated_bridge") or 0.0)
    capex_data = result.get("capex") or {}
    bridge_social = (
        float(capex_data.get("social") or 0.0)
        if str(summary.get("social_payment_mode") or "") == "Денежная компенсация"
        else 0.0
    )
    bridge_design_p = float(capex_data.get("design_p") or 0.0)
    bridge_design_rd = float(capex_data.get("design_rd") or 0.0)
    bridge_purchase = max(
        0.0,
        bridge_total - bridge_social - bridge_design_p - bridge_design_rd,
    )
    bridge_uses = [
        ("Приобретение проекта", bridge_purchase),
        ("Социальная компенсация", bridge_social),
        ("Проектирование - стадия П", bridge_design_p),
        ("Проектирование - стадия РД", bridge_design_rd),
    ]
    bridge_uses = [(label, value) for label, value in bridge_uses if value > 0.5]
    bridge_rows = [["Цель", "Сумма", "Доля"]]
    for label, value in bridge_uses:
        share = _pdf_num(value / bridge_total * 100, 1) + "%" if bridge_total else "—"
        bridge_rows.append([label, _pdf_money(value), share])
    bridge_rows.append([
        "ИТОГО БРИДЖ",
        _pdf_money(bridge_total),
        "100,0%" if bridge_total else "—",
    ])
    story.append(KeepTogether([
        P("Структура расчётного БРИДЖА", h2),
        table(bridge_rows, [98*mm, 45*mm, 27*mm], font_size=8.0),
    ]))

    timeline_rows=list((result.get("finance") or {}).get("rows") or [])
'''
if old not in s:
    raise SystemExit('PDF financing insertion anchor not found')
s = s.replace(old, new, 1)

for marker in (
    'version="0.12.25"',
    'Структура расчётного БРИДЖА',
    'Приобретение проекта',
    'Социальная компенсация',
    'Проектирование - стадия П',
    'Проектирование - стадия РД',
    'VRI is deliberately absent',
):
    if marker not in s:
        raise SystemExit('Missing marker: ' + marker)

p.write_text(s, encoding='utf-8')
print('PDF_BRIDGE_STRUCTURE_RESTORED')
