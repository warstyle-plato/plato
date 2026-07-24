from pathlib import Path

p=Path('main.py')
s=p.read_text(encoding='utf-8')

if 'version="0.12.21"' not in s:
    raise SystemExit('Expected v0.12.21 baseline')
s=s.replace('0.12.21','0.12.22')

# 1) Acquisition price must be shown separately from VRI/land-rights cost in expense structure.
old='''        ("Покупка и земельные права", purchase_value + op["capex_amounts"].get("land_rights", 0.0)),
'''
new='''        ("Цена приобретения", purchase_value),
        ("Смена ВРИ / земельные права", op["capex_amounts"].get("land_rights", 0.0)),
'''
if old not in s:
    raise SystemExit('expense structure acquisition anchor not found')
s=s.replace(old,new,1)

# 2) VRI is NOT bridge-funded. Purchase stays at project start; VRI is paid at RnS/permit and therefore funded by PF.
old='''    capex: dict[date, float] = defaultdict(float)
    capex[project_start] += amounts["land_rights"] + n(x, "purchase_price_mln") * 1_000_000
'''
new='''    capex: dict[date, float] = defaultdict(float)
    capex[project_start] += n(x, "purchase_price_mln") * 1_000_000
    # VRI is paid once PF is available, at RnS/permit; it must not inflate bridge.
    capex[permit] += amounts["land_rights"]
'''
if old not in s:
    raise SystemExit('VRI capex timing anchor not found')
s=s.replace(old,new,1)

# 3) Remove VRI from calculated bridge limit.
old='''    calculated_bridge_limit = (
        n(x, "purchase_price_mln") * 1_000_000
        + op["capex_amounts"]["land_rights"]
        + op["capex_amounts"]["design_p"]
        + op["capex_amounts"]["design_rd"]
    )
'''
new='''    calculated_bridge_limit = (
        n(x, "purchase_price_mln") * 1_000_000
        + op["capex_amounts"]["design_p"]
        + op["capex_amounts"]["design_rd"]
    )
'''
if old not in s:
    raise SystemExit('bridge limit VRI anchor not found')
s=s.replace(old,new,1)

# Update explanatory comments so code/documentation match actual financing logic.
s=s.replace(
'''    # VRI / land-rights payment is part of project investment needs and is included
    # in bridge/PF funding requirement together with the other eligible project CAPEX.
    debt_capex = dict(capex)
''',
'''    # VRI / land-rights payment is part of project investment needs, but is dated at RnS/permit,
    # so it is funded directly by PF rather than by the pre-RnS bridge.
    debt_capex = dict(capex)
''',1)

for marker in (
    'version="0.12.22"',
    '("Цена приобретения", purchase_value)',
    '("Смена ВРИ / земельные права", op["capex_amounts"].get("land_rights", 0.0))',
    'capex[permit] += amounts["land_rights"]',
):
    if marker not in s:
        raise SystemExit('missing marker '+marker)
if '+ op["capex_amounts"]["land_rights"]' in s[s.find('calculated_bridge_limit'):s.find('def run',s.find('calculated_bridge_limit'))]:
    raise SystemExit('VRI still included in calculated bridge limit')

p.write_text(s,encoding='utf-8')
print('VRI_PF_ACQUISITION_FIX_OK')
