"""Presentation schema shared by the native form and request validation."""
COMMON = ['land_cost_rub', 'gross_area_sqm', 'construction_cost_rub_sqm',
          'soft_cost_pct', 'contingency_pct', 'construction_months']
INCOME = ['opening_occupancy_pct', 'occupancy_pct', 'stabilization_months',
          'hold_years', 'exit_cap_rate_pct', 'exit_cost_pct']
SALE = ['sale_start_month', 'sale_months', 'sales_curve', 'sale_price_growth_pct', 'selling_cost_pct']
OPERATIONS = {
    'office': ['income_area_sqm', 'rent_rub_sqm_month', 'rent_growth_pct',
               'other_income_pct', 'opex_pct', 'leasing_cost_pct'],
    'retail': ['income_area_sqm', 'rent_rub_sqm_month', 'sales_rub_sqm_month',
               'turnover_rent_pct', 'rent_growth_pct', 'opex_pct', 'marketing_pct'],
    'hotel': ['keys', 'adr_rub', 'adr_growth_pct', 'other_revenue_pct',
              'opex_pct', 'management_fee_pct', 'ffe_reserve_pct'],
}
FINANCE = ['debt_share_pct', 'debt_rate_pct', 'loan_fee_pct']


def field_groups(asset, strategy, financing):
    development = COMMON + (['preopening_cost_rub'] if asset == 'hotel' else [])
    if strategy == 'income':
        operation = OPERATIONS[asset] + INCOME
    else:
        operation = (['saleable_keys', 'sale_price_rub_key'] if asset == 'hotel'
                     else ['saleable_area_sqm', 'sale_price_rub_sqm']) + SALE
    groups = [{'label': 'Девелопмент', 'keys': development},
              {'label': 'Эксплуатация и выход' if strategy == 'income' else 'Продажи', 'keys': operation}]
    if financing == 'equity_debt':
        groups.append({'label': 'Обычный кредит', 'keys': FINANCE +
                       (['sales_cash_sweep_pct'] if strategy == 'sale' else [])})
    groups.append({'label': 'Доходность', 'keys': ['project_discount_rate_pct', 'equity_hurdle_rate_pct']})
    return groups


def field_keys(asset, strategy, financing):
    return [key for group in field_groups(asset, strategy, financing) for key in group['keys']]


def field_limits(key):
    result = {'min': 0, 'max': 1e13, 'step': 'any'}
    if key.endswith('_pct'):
        result['max'] = 100
    if key in {'construction_months', 'stabilization_months', 'sale_months'}:
        result.update(min=1, max=240, step=1)
    if key == 'sale_start_month':
        result.update(max=240, step=1)
    if key == 'hold_years':
        result.update(min=1, max=20, step=1)
    if key in {'keys', 'saleable_keys'}:
        result.update(step=1)
    if key == 'exit_cap_rate_pct':
        result.update(min=0.01)
    if key == 'debt_share_pct':
        result.update(max=95)
    if key == 'opex_pct':
        result.update(max=95)
    if key in {'management_fee_pct', 'ffe_reserve_pct'}:
        result.update(max=25)
    return result
