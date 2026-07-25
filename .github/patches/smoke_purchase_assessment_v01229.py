from __future__ import annotations

import base64
import copy
import re
from pathlib import Path

import main

payload = base64.b64decode(
    Path('templates/DevelopAid_Шаблон_ТЭП.xlsx.b64').read_text(encoding='ascii'),
    validate=True,
)
tables = main._xlsx_read_tables(payload)
assert main._find_parameter(tables['ТЭП DevelopAid'], 'Версия шаблона') == 'DevelopAid_TEP_3'
instruction = ' '.join(str(cell or '') for row in tables['Инструкция'] for cell in row)
assert 'Платона Сергеевича' in instruction
assert 'инвестиционную оценку' in instruction.lower()

inputs = copy.deepcopy(main.DEFAULT_INPUTS)
inputs.update({
    'purchase_price_mln': 0,
    'apartment_price_th': 650,
    'commercial_price_th': 650,
    'parking_price_th': 5000,
    'main_above_th_per_sqm': 110,
    'main_under_th_per_sqm': 110,
})
result = main.purchase_assessment_api(main.PurchaseAssessmentRequest(
    inputs=inputs,
    tep=copy.deepcopy(main.TEP_DEFAULT),
    rates=[],
    phasing={},
    target_llcr=1.20,
    target_npv_mln=0,
))
assert result['status'] in {'ceiling_calculated', 'not_feasible'}, result
if result.get('available'):
    assert result['max_purchase_price_mln'] >= 0, result
    assert result['max_purchase_price_mln'] <= min(result['llcr_ceiling_mln'], result['npv_ceiling_mln']) + 0.02, result

assert main.app.version == '0.12.29'
assert 'purchaseAssessmentCard' in main.PAGE
assert '/investment/purchase-assessment' in main.PAGE
assert main.PAGE.count('await runPurchaseAssessment(true);') >= 2
scripts = re.findall(r'<script[^>]*>(.*?)</script>', main.PAGE, flags=re.S)
Path('/tmp/developaid-page.js').write_text('\n'.join(scripts), encoding='utf-8')
print('Purchase assessment integration test passed')
