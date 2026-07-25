from __future__ import annotations

import base64
import copy
from pathlib import Path

import main

payload = base64.b64decode(
    Path('templates/DevelopAid_Шаблон_ТЭП.xlsx.b64').read_text(encoding='ascii'),
    validate=True,
)
tables = main._xlsx_read_tables(payload)
rows = tables['ТЭП DevelopAid']
assert main._find_parameter(rows, 'Версия шаблона') == 'DevelopAid_TEP_3'
instruction_text = ' '.join(str(cell or '') for row in tables['Инструкция'] for cell in row)
assert 'Платона Сергеевича' in instruction_text
assert 'инвестиционную оценку' in instruction_text.lower()

inputs = copy.deepcopy(main.DEFAULT_INPUTS)
inputs.update({
    'purchase_price_mln': 0,
    'apartment_price_th': 650,
    'commercial_price_th': 650,
    'parking_price_th': 5000,
    'main_above_th_per_sqm': 110,
    'main_under_th_per_sqm': 110,
})
result = main.investment_assessment_api(main.InvestmentAssessmentRequest(
    inputs=inputs,
    tep=copy.deepcopy(main.TEP_DEFAULT),
    rates=[],
    phasing={},
    target_llcr=1.20,
    target_npv_mln=0,
))
assert result['status'] in {'ceiling_calculated', 'not_feasible'}, result
assert 'llcr_ceiling' in result and 'npv_ceiling' in result, result
if result.get('available'):
    assert result['max_purchase_price_mln'] >= 0, result
    assert result['max_purchase_price_mln'] <= min(result['llcr_ceiling_mln'], result['npv_ceiling_mln']) + 0.02, result

page = main.PAGE
assert 'investmentAssessmentCard' in page
assert 'runInvestmentAssessment' in page
assert '/investment/assessment' in page
assert main.app.version == '0.12.28'
print('Template and investment assessment smoke tests passed')
