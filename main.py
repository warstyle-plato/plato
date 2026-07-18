
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from math import ceil, pow
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="PLATO Development Investment Model", version="0.4")

SCENARIOS = {'conservative': {'purchase_price_mln': 0, 'construction_months': 27, 'apartment_price_th': 300, 'commercial_price_th': 250, 'parking_price_th': 1000, 'storage_price_th': 900, 'share_before_rve_pct': 80, 'pace_adjustment_pct': 20, 'inflation_after_rve_pct': 2, 'seasonal_reduction_pct': -20, 'growth_stage1_pct': 0, 'growth_stage2_pct': 0, 'growth_stage3_pct': 0, 'growth_stage4_pct': 0, 'ird_th_per_sqm': 1.1, 'design_p_th_per_sqm': 2.75, 'design_rd_th_per_sqm': 2.75, 'preparation_th_per_sqm': 1.2, 'main_above_th_per_sqm': 115, 'utilities_th_per_sqm': 8.5, 'landscaping_th_per_sqm': 5.5, 'commissioning_th_per_sqm': 1.1, 'site_maintenance_th_per_sqm': 1.2, 'gc_fee_pct': 8, 'reserve_pct': 7, 'project_management_pct': 6, 'marketing_pct': 4, 'selling_pct': 5, 'profit_tax_pct': 25, 'vat_pct': 22, 'bridge_spread_pp': 7, 'bridge_cap_spread_pp': 7, 'pf_spread_pp': 5.5, 'pf_special_pct': 5, 'limit_fee_pct': 0.75, 'reservation_fee_pct': 0.75, 'discount_rate_pct': 25, 'monthly_growth_pre_pct': 1, 'monthly_growth_post_pct': 0.2, 'ird_months': 24, 'sales_lag_months': 1, 'bridge_repay_lag_months': 0, 'residual_sales_months': 12, 'social_comp_date': '2028-12-01', 'kindergarten_places': 250, 'kindergarten_cost_mln_per_place': 2.75, 'kindergarten_start': '2028-12-01', 'kindergarten_months': 24, 'school_places': 0, 'school_cost_mln_per_place': 3, 'school_start': '2028-12-01', 'school_months': 30, 'clinic_capacity': 0, 'clinic_cost_mln_per_unit': 3, 'clinic_start': '2028-12-01', 'clinic_months': 24, 'offices_gba_sqm': 10000, 'offices_saleable_sqm': 6000, 'offices_start': '2028-07-01', 'offices_months': 24, 'offices_cost_th_per_sqm': 250, 'offices_sales_start': '2028-07-01', 'offices_price_th_per_sqm': 450, 'offices_share_before_rve_pct': 80, 'offices_residual_months': 12, 'offices_growth_pre_pct': 1, 'offices_growth_post_pct': 0.2, 'retail_gba_sqm': 10000, 'retail_saleable_sqm': 6000, 'retail_start': '2028-07-01', 'retail_months': 24, 'retail_cost_th_per_sqm': 200, 'retail_sales_start': '2028-07-01', 'retail_price_th_per_sqm': 450, 'retail_share_before_rve_pct': 80, 'retail_residual_months': 12, 'retail_growth_pre_pct': 1, 'retail_growth_post_pct': 0.2, 'above_parking_spaces': 550, 'above_parking_cost_mln_per_space': 1.5, 'above_parking_start': '2028-07-01', 'above_parking_months': 18, 'above_parking_sales_start': '2028-07-01', 'above_parking_price_mln_per_space': 1.8, 'above_parking_share_before_rve_pct': 80, 'above_parking_residual_months': 12, 'above_parking_growth_pre_pct': 0.5, 'above_parking_growth_post_pct': 0.1, 'social_dou_gba_sqm': 3000, 'social_school_gba_sqm': 0, 'social_clinic_gba_sqm': 0, 'land_rights_cost_mln': 2864.291514155844, 'author_supervision_mln': 19.55, 'bridge_interest_mode': 'Капитализация в ПФ', 'pf_transfer_income_pct': 5.0}, 'base': {'purchase_price_mln': 0, 'construction_months': 24, 'apartment_price_th': 375, 'commercial_price_th': 300, 'parking_price_th': 1500, 'storage_price_th': 1000, 'share_before_rve_pct': 85, 'pace_adjustment_pct': 25, 'inflation_after_rve_pct': 3, 'seasonal_reduction_pct': -15, 'growth_stage1_pct': 0, 'growth_stage2_pct': 0, 'growth_stage3_pct': 0, 'growth_stage4_pct': 0, 'ird_th_per_sqm': 1, 'design_p_th_per_sqm': 2.5, 'design_rd_th_per_sqm': 2.5, 'preparation_th_per_sqm': 1, 'main_above_th_per_sqm': 110, 'utilities_th_per_sqm': 7.5, 'landscaping_th_per_sqm': 5, 'commissioning_th_per_sqm': 1, 'site_maintenance_th_per_sqm': 1, 'gc_fee_pct': 7, 'reserve_pct': 5, 'project_management_pct': 5, 'marketing_pct': 3, 'selling_pct': 4, 'profit_tax_pct': 25, 'vat_pct': 22, 'bridge_spread_pp': 6, 'bridge_cap_spread_pp': 6, 'pf_spread_pp': 4.5, 'pf_special_pct': 4.5, 'limit_fee_pct': 0.5, 'reservation_fee_pct': 0.5, 'discount_rate_pct': 20, 'monthly_growth_pre_pct': 1.5, 'monthly_growth_post_pct': 0.25, 'ird_months': 18, 'sales_lag_months': 0, 'bridge_repay_lag_months': 0, 'residual_sales_months': 6, 'social_comp_date': '2028-06-01', 'kindergarten_places': 250, 'kindergarten_cost_mln_per_place': 2.75, 'kindergarten_start': '2028-06-01', 'kindergarten_months': 24, 'school_places': 0, 'school_cost_mln_per_place': 3, 'school_start': '2028-06-01', 'school_months': 30, 'clinic_capacity': 0, 'clinic_cost_mln_per_unit': 3, 'clinic_start': '2028-06-01', 'clinic_months': 24, 'offices_gba_sqm': 10000, 'offices_saleable_sqm': 6000, 'offices_start': '2028-07-01', 'offices_months': 24, 'offices_cost_th_per_sqm': 200, 'offices_sales_start': '2028-07-01', 'offices_price_th_per_sqm': 500, 'offices_share_before_rve_pct': 85, 'offices_residual_months': 6, 'offices_growth_pre_pct': 1.5, 'offices_growth_post_pct': 0.25, 'retail_gba_sqm': 10000, 'retail_saleable_sqm': 6000, 'retail_start': '2028-07-01', 'retail_months': 24, 'retail_cost_th_per_sqm': 200, 'retail_sales_start': '2028-07-01', 'retail_price_th_per_sqm': 500, 'retail_share_before_rve_pct': 85, 'retail_residual_months': 6, 'retail_growth_pre_pct': 1.5, 'retail_growth_post_pct': 0.25, 'above_parking_spaces': 550, 'above_parking_cost_mln_per_space': 1, 'above_parking_start': '2028-07-01', 'above_parking_months': 18, 'above_parking_sales_start': '2028-07-01', 'above_parking_price_mln_per_space': 2, 'above_parking_share_before_rve_pct': 85, 'above_parking_residual_months': 6, 'above_parking_growth_pre_pct': 0.75, 'above_parking_growth_post_pct': 0.2, 'social_dou_gba_sqm': 3000, 'social_school_gba_sqm': 0, 'social_clinic_gba_sqm': 0, 'land_rights_cost_mln': 2864.291514155844, 'author_supervision_mln': 19.55, 'bridge_interest_mode': 'Капитализация в ПФ', 'pf_transfer_income_pct': 5.0}, 'optimistic': {'purchase_price_mln': 0, 'construction_months': 22, 'apartment_price_th': 400, 'commercial_price_th': 325, 'parking_price_th': 1750, 'storage_price_th': 1100, 'share_before_rve_pct': 90, 'pace_adjustment_pct': 30, 'inflation_after_rve_pct': 4, 'seasonal_reduction_pct': -10, 'growth_stage1_pct': 0, 'growth_stage2_pct': 0, 'growth_stage3_pct': 0, 'growth_stage4_pct': 0, 'ird_th_per_sqm': 0.95, 'design_p_th_per_sqm': 2.35, 'design_rd_th_per_sqm': 2.35, 'preparation_th_per_sqm': 0.9, 'main_above_th_per_sqm': 100, 'utilities_th_per_sqm': 7, 'landscaping_th_per_sqm': 4.5, 'commissioning_th_per_sqm': 0.9, 'site_maintenance_th_per_sqm': 0.9, 'gc_fee_pct': 5, 'reserve_pct': 3, 'project_management_pct': 4, 'marketing_pct': 2, 'selling_pct': 3, 'profit_tax_pct': 25, 'vat_pct': 22, 'bridge_spread_pp': 5, 'bridge_cap_spread_pp': 5, 'pf_spread_pp': 3.5, 'pf_special_pct': 4, 'limit_fee_pct': 0.35, 'reservation_fee_pct': 0.35, 'discount_rate_pct': 18, 'monthly_growth_pre_pct': 2, 'monthly_growth_post_pct': 0.3, 'ird_months': 14, 'sales_lag_months': 0, 'bridge_repay_lag_months': 0, 'residual_sales_months': 3, 'social_comp_date': '2028-02-01', 'kindergarten_places': 250, 'kindergarten_cost_mln_per_place': 2.75, 'kindergarten_start': '2028-02-01', 'kindergarten_months': 24, 'school_places': 0, 'school_cost_mln_per_place': 3, 'school_start': '2028-02-01', 'school_months': 30, 'clinic_capacity': 0, 'clinic_cost_mln_per_unit': 3, 'clinic_start': '2028-02-01', 'clinic_months': 24, 'offices_gba_sqm': 10000, 'offices_saleable_sqm': 6000, 'offices_start': '2028-07-01', 'offices_months': 24, 'offices_cost_th_per_sqm': 175, 'offices_sales_start': '2028-07-01', 'offices_price_th_per_sqm': 550, 'offices_share_before_rve_pct': 90, 'offices_residual_months': 3, 'offices_growth_pre_pct': 2, 'offices_growth_post_pct': 0.3, 'retail_gba_sqm': 10000, 'retail_saleable_sqm': 6000, 'retail_start': '2028-07-01', 'retail_months': 24, 'retail_cost_th_per_sqm': 200, 'retail_sales_start': '2028-07-01', 'retail_price_th_per_sqm': 550, 'retail_share_before_rve_pct': 90, 'retail_residual_months': 3, 'retail_growth_pre_pct': 2, 'retail_growth_post_pct': 0.3, 'above_parking_spaces': 550, 'above_parking_cost_mln_per_space': 0.8, 'above_parking_start': '2028-07-01', 'above_parking_months': 18, 'above_parking_sales_start': '2028-07-01', 'above_parking_price_mln_per_space': 2.5, 'above_parking_share_before_rve_pct': 90, 'above_parking_residual_months': 3, 'above_parking_growth_pre_pct': 1, 'above_parking_growth_post_pct': 0.25, 'social_dou_gba_sqm': 3000, 'social_school_gba_sqm': 0, 'social_clinic_gba_sqm': 0, 'land_rights_cost_mln': 2864.291514155844, 'author_supervision_mln': 19.55, 'bridge_interest_mode': 'Капитализация в ПФ', 'pf_transfer_income_pct': 5.0}}
RATE_CURVE = [{'date': '2027-01-01', 'high': 15.0, 'base': 13.0, 'low': 11.0}, {'date': '2027-07-01', 'high': 14.5, 'base': 12.5, 'low': 10.5}, {'date': '2028-01-01', 'high': 13.5, 'base': 11.5, 'low': 9.5}, {'date': '2028-02-01', 'high': 14.5, 'base': 11.5, 'low': 10.5}, {'date': '2028-03-01', 'high': 14.25, 'base': 11.25, 'low': 10.25}, {'date': '2028-04-01', 'high': 14.0, 'base': 11.0, 'low': 10.0}, {'date': '2028-05-01', 'high': 13.75, 'base': 11.0, 'low': 9.75}, {'date': '2028-06-01', 'high': 13.5, 'base': 11.0, 'low': 9.5}, {'date': '2028-07-01', 'high': 13.25, 'base': 11.0, 'low': 9.25}, {'date': '2028-08-01', 'high': 13.0, 'base': 11.0, 'low': 9.0}, {'date': '2028-09-01', 'high': 12.75, 'base': 10.75, 'low': 8.75}, {'date': '2028-10-01', 'high': 12.5, 'base': 10.5, 'low': 8.5}, {'date': '2028-11-01', 'high': 12.25, 'base': 10.25, 'low': 8.25}, {'date': '2028-12-01', 'high': 12.0, 'base': 10.0, 'low': 8.0}, {'date': '2029-01-01', 'high': 11.75, 'base': 9.75, 'low': 7.75}, {'date': '2029-02-01', 'high': 11.5, 'base': 9.5, 'low': 7.5}, {'date': '2029-03-01', 'high': 11.25, 'base': 9.25, 'low': 7.25}, {'date': '2029-04-01', 'high': 11.0, 'base': 9.0, 'low': 7.0}, {'date': '2029-05-01', 'high': 10.75, 'base': 8.75, 'low': 6.75}, {'date': '2029-06-01', 'high': 10.5, 'base': 8.5, 'low': 6.5}, {'date': '2029-07-01', 'high': 10.25, 'base': 8.25, 'low': 6.25}, {'date': '2029-08-01', 'high': 10.0, 'base': 8.0, 'low': 6.0}]
TEP_DEFAULT = {'apartments': {'label': 'Квартиры', 'gns': 130716.66012842482, 'total_area': 117647.0588235294, 'useful': 80000, 'saleable': 80000, 'transfer': 0, 'units': 1361.815754339119}, 'ground_commercial': {'label': 'Коммерция 1 эт.', 'gns': 9664.049734985854, 'total_area': 8695.652173913044, 'useful': 7826.08695652174, 'saleable': 7826.08695652174, 'transfer': 0, 'units': 0}, 'standalone_retail': {'label': 'Коммерция ОСЗ', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}, 'offices': {'label': 'Офисы', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}, 'above_parking': {'label': 'Наземный паркинг', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}, 'underground_parking': {'label': 'Подземный паркинг', 'gns': 38763, 'total_area': 38763, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 1107.5142857142857}, 'storage': {'label': 'Кладовки', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}, 'kindergarten': {'label': 'ДОУ', 'gns': 0, 'total_area': 3000, 'useful': 0, 'saleable': 0, 'transfer': 3000, 'units': 250}, 'school': {'label': 'СОШ', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}, 'clinic': {'label': 'Поликлиника', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}}
FIELD_GROUPS = [['Сделка и сроки', [['purchase_price_mln', 'Стоимость покупки / цена входа', 'млн ₽', 'number'], ['land_rights_cost_mln', 'Оформление земельных правоотношений / смена ВРИ', 'млн ₽', 'number'], ['project_start', 'Начало проекта', 'дата', 'date'], ['ird_months', 'Срок ИРД до РнС', 'мес.', 'number'], ['construction_months', 'Срок строительства', 'мес.', 'number'], ['sales_lag_months', 'Лаг старта продаж после РнС', 'мес.', 'number'], ['bridge_repay_lag_months', 'Лаг погашения БРИДЖ после РнС', 'мес.', 'number'], ['residual_sales_months', 'Остаточные продажи после РВЭ', 'мес.', 'number']]], ['Продажи', [['apartment_price_th', 'Стартовая цена квартир', 'тыс. ₽/м²', 'number'], ['commercial_price_th', 'Стартовая цена коммерции 1 этажа', 'тыс. ₽/м²', 'number'], ['parking_price_th', 'Цена подземного машино-места', 'тыс. ₽/шт.', 'number'], ['storage_price_th', 'Цена кладовой', 'тыс. ₽/шт.', 'number'], ['share_before_rve_pct', 'Доля продаж до РВЭ', '%', 'number'], ['pace_adjustment_pct', 'Корректировка темпа', '%', 'number'], ['inflation_after_rve_pct', 'Инфляция после РВЭ', '% год', 'number'], ['seasonal_reduction_pct', 'Сезонное снижение темпа', '%', 'number'], ['growth_stage1_pct', 'Рост цены — этап 1', '%', 'number'], ['growth_stage2_pct', 'Рост цены — этап 2', '%', 'number'], ['growth_stage3_pct', 'Рост цены — этап 3', '%', 'number'], ['growth_stage4_pct', 'Рост цены — этап 4', '%', 'number'], ['monthly_growth_pre_pct', 'Ежемесячный рост цены до РВЭ', '%/мес.', 'number'], ['monthly_growth_post_pct', 'Ежемесячный рост цены после РВЭ', '%/мес.', 'number']]], ['Строительство', [['ird_th_per_sqm', 'ИРД и согласования', 'тыс. ₽/м² ГНС', 'number'], ['design_p_th_per_sqm', 'Проектирование стадии П', 'тыс. ₽/м² ГНС', 'number'], ['design_rd_th_per_sqm', 'Проектирование стадии РД', 'тыс. ₽/м² ГНС', 'number'], ['preparation_th_per_sqm', 'Подготовительные работы', 'тыс. ₽/м² ГНС', 'number'], ['main_above_th_per_sqm', 'Основное строительство — наземная часть', 'тыс. ₽/м² ГНС', 'number'], ['main_under_th_per_sqm', 'Основное строительство — подземная часть', 'тыс. ₽/м² ГНС', 'number'], ['utilities_th_per_sqm', 'Наружные инженерные сети', 'тыс. ₽/м² ГНС', 'number'], ['landscaping_th_per_sqm', 'Благоустройство', 'тыс. ₽/м² ГНС', 'number'], ['commissioning_th_per_sqm', 'Сдача и ввод', 'тыс. ₽/м² ГНС', 'number'], ['site_maintenance_th_per_sqm', 'Содержание стройплощадки', 'тыс. ₽/м² ГНС', 'number'], ['gc_fee_pct', 'Вознаграждение генподрядчика', '% СМР', 'number'], ['reserve_pct', 'Резерв', '%', 'number'], ['project_management_pct', 'Управление проектом', '%', 'number'], ['author_supervision_mln', 'Авторский надзор', 'млн ₽', 'number']]], ['Коммерческие расходы и налоги', [['marketing_pct', 'Маркетинг', '% выручки', 'number'], ['selling_pct', 'Расходы на продажи', '% выручки', 'number'], ['profit_tax_pct', 'Налог на прибыль', '%', 'number'], ['vat_pct', 'НДС', '%', 'number']]], ['Финансирование', [['bridge_spread_pp', 'Спред БРИДЖ', 'п.п.', 'number'], ['bridge_cap_spread_pp', 'Спред капитализации БРИДЖ', 'п.п.', 'number'], ['pf_spread_pp', 'Спред ПФ', 'п.п.', 'number'], ['pf_special_pct', 'Специальная ставка ПФ', '%', 'number'], ['limit_fee_pct', 'Плата за лимит', '%', 'number'], ['reservation_fee_pct', 'Плата за резервирование', '%', 'number'], ['discount_rate_pct', 'Ставка дисконтирования', '%', 'number'], ['bridge_interest_mode', 'Проценты БРИДЖ при рефинансировании', 'режим', 'finance_select'], ['pf_transfer_income_pct', 'Снижение спецставки при покрытии эскроу > 1x', 'п.п. на 1x', 'number']]], ['Социальная нагрузка', [['social_mode', 'Форма исполнения', 'режим', 'select'], ['social_comp_date', 'Дата денежной компенсации', 'дата', 'date'], ['kindergarten_places', 'ДОУ — количество мест', 'мест', 'number'], ['kindergarten_cost_mln_per_place', 'ДОУ — себестоимость места', 'млн ₽/место', 'number'], ['kindergarten_start', 'ДОУ — начало строительства', 'дата', 'date'], ['kindergarten_months', 'ДОУ — срок строительства', 'мес.', 'number'], ['school_places', 'СОШ — количество мест', 'мест', 'number'], ['school_cost_mln_per_place', 'СОШ — себестоимость места', 'млн ₽/место', 'number'], ['school_start', 'СОШ — начало строительства', 'дата', 'date'], ['school_months', 'СОШ — срок строительства', 'мес.', 'number'], ['clinic_capacity', 'Поликлиника — мощность', 'пос./смену', 'number'], ['clinic_cost_mln_per_unit', 'Поликлиника — себестоимость мощности', 'млн ₽/(пос./смену)', 'number'], ['clinic_start', 'Поликлиника — начало строительства', 'дата', 'date'], ['clinic_months', 'Поликлиника — срок строительства', 'мес.', 'number'], ['social_dou_gba_sqm', 'ДОУ — общая площадь', 'м²', 'number'], ['social_dou_norm_sqm', 'ДОУ — норматив площади на место', 'м²/место', 'number'], ['social_school_gba_sqm', 'СОШ — общая площадь', 'м²', 'number'], ['social_school_norm_sqm', 'СОШ — норматив площади на место', 'м²/место', 'number'], ['social_clinic_gba_sqm', 'Поликлиника — общая площадь', 'м²', 'number'], ['social_clinic_norm_sqm', 'Поликлиника — норматив площади', 'м²/ед.', 'number']]], ['МФОЦ / офисы', [['offices_enabled', 'Объект включен', 'Да / Нет', 'checkbox'], ['offices_gba_sqm', 'Общая площадь (GBA)', 'м²', 'number'], ['offices_saleable_sqm', 'Продаваемая площадь', 'м²', 'number'], ['offices_start', 'Начало строительства', 'дата', 'date'], ['offices_months', 'Срок строительства', 'мес.', 'number'], ['offices_cost_th_per_sqm', 'Себестоимость строительства', 'тыс. ₽/м² GBA', 'number'], ['offices_sales_start', 'Старт продаж', 'дата', 'date'], ['offices_price_th_per_sqm', 'Стартовая цена', 'тыс. ₽/м²', 'number'], ['offices_share_before_rve_pct', 'Доля продаж до РВЭ', '%', 'number'], ['offices_residual_months', 'Остаточные продажи после РВЭ', 'мес.', 'number'], ['offices_growth_pre_pct', 'Рост цены до РВЭ', '%/мес.', 'number'], ['offices_growth_post_pct', 'Рост цены после РВЭ', '%/мес.', 'number']]], ['ТЦ / коммерция ОСЗ', [['retail_enabled', 'Объект включен', 'Да / Нет', 'checkbox'], ['retail_gba_sqm', 'Общая площадь (GBA)', 'м²', 'number'], ['retail_saleable_sqm', 'Продаваемая площадь', 'м²', 'number'], ['retail_start', 'Начало строительства', 'дата', 'date'], ['retail_months', 'Срок строительства', 'мес.', 'number'], ['retail_cost_th_per_sqm', 'Себестоимость строительства', 'тыс. ₽/м² GBA', 'number'], ['retail_sales_start', 'Старт продаж', 'дата', 'date'], ['retail_price_th_per_sqm', 'Стартовая цена', 'тыс. ₽/м²', 'number'], ['retail_share_before_rve_pct', 'Доля продаж до РВЭ', '%', 'number'], ['retail_residual_months', 'Остаточные продажи после РВЭ', 'мес.', 'number'], ['retail_growth_pre_pct', 'Рост цены до РВЭ', '%/мес.', 'number'], ['retail_growth_post_pct', 'Рост цены после РВЭ', '%/мес.', 'number']]], ['Наземный паркинг', [['above_parking_enabled', 'Объект включен', 'Да / Нет', 'checkbox'], ['above_parking_spaces', 'Количество машино-мест', 'шт.', 'number'], ['above_parking_cost_mln_per_space', 'Себестоимость одного места', 'млн ₽/место', 'number'], ['above_parking_start', 'Начало строительства', 'дата', 'date'], ['above_parking_months', 'Срок строительства', 'мес.', 'number'], ['above_parking_sales_start', 'Старт продаж', 'дата', 'date'], ['above_parking_price_mln_per_space', 'Стартовая цена места', 'млн ₽/место', 'number'], ['above_parking_share_before_rve_pct', 'Доля продаж до РВЭ', '%', 'number'], ['above_parking_residual_months', 'Остаточные продажи после РВЭ', 'мес.', 'number'], ['above_parking_growth_pre_pct', 'Рост цены до РВЭ', '%/мес.', 'number'], ['above_parking_growth_post_pct', 'Рост цены после РВЭ', '%/мес.', 'number'], ['above_parking_area_per_space_sqm', 'Площадь на 1 место для ТЭП', 'м²/место', 'number']]]]
DEFAULT_INPUTS = {'purchase_price_mln': 0, 'construction_months': 24, 'apartment_price_th': 375, 'commercial_price_th': 300, 'parking_price_th': 1500, 'storage_price_th': 1000, 'share_before_rve_pct': 85, 'pace_adjustment_pct': 25, 'inflation_after_rve_pct': 3, 'seasonal_reduction_pct': -15, 'growth_stage1_pct': 0, 'growth_stage2_pct': 0, 'growth_stage3_pct': 0, 'growth_stage4_pct': 0, 'ird_th_per_sqm': 1, 'design_p_th_per_sqm': 2.5, 'design_rd_th_per_sqm': 2.5, 'preparation_th_per_sqm': 1, 'main_above_th_per_sqm': 110, 'utilities_th_per_sqm': 7.5, 'landscaping_th_per_sqm': 5, 'commissioning_th_per_sqm': 1, 'site_maintenance_th_per_sqm': 1, 'gc_fee_pct': 7, 'reserve_pct': 5, 'project_management_pct': 5, 'marketing_pct': 3, 'selling_pct': 4, 'profit_tax_pct': 25, 'vat_pct': 22, 'bridge_spread_pp': 6, 'bridge_cap_spread_pp': 6, 'pf_spread_pp': 4.5, 'pf_special_pct': 4.5, 'limit_fee_pct': 0.5, 'reservation_fee_pct': 0.5, 'discount_rate_pct': 20, 'monthly_growth_pre_pct': 1.5, 'monthly_growth_post_pct': 0.25, 'ird_months': 18, 'sales_lag_months': 0, 'bridge_repay_lag_months': 0, 'residual_sales_months': 6, 'social_comp_date': '2028-06-01', 'kindergarten_places': 250, 'kindergarten_cost_mln_per_place': 2.75, 'kindergarten_start': '2028-06-01', 'kindergarten_months': 24, 'school_places': 0, 'school_cost_mln_per_place': 3, 'school_start': '2028-06-01', 'school_months': 30, 'clinic_capacity': 0, 'clinic_cost_mln_per_unit': 3, 'clinic_start': '2028-06-01', 'clinic_months': 24, 'offices_gba_sqm': 10000, 'offices_saleable_sqm': 6000, 'offices_start': '2028-07-01', 'offices_months': 24, 'offices_cost_th_per_sqm': 200, 'offices_sales_start': '2028-07-01', 'offices_price_th_per_sqm': 500, 'offices_share_before_rve_pct': 85, 'offices_residual_months': 6, 'offices_growth_pre_pct': 1.5, 'offices_growth_post_pct': 0.25, 'retail_gba_sqm': 10000, 'retail_saleable_sqm': 6000, 'retail_start': '2028-07-01', 'retail_months': 24, 'retail_cost_th_per_sqm': 200, 'retail_sales_start': '2028-07-01', 'retail_price_th_per_sqm': 500, 'retail_share_before_rve_pct': 85, 'retail_residual_months': 6, 'retail_growth_pre_pct': 1.5, 'retail_growth_post_pct': 0.25, 'above_parking_spaces': 550, 'above_parking_cost_mln_per_space': 1, 'above_parking_start': '2028-07-01', 'above_parking_months': 18, 'above_parking_sales_start': '2028-07-01', 'above_parking_price_mln_per_space': 2, 'above_parking_share_before_rve_pct': 85, 'above_parking_residual_months': 6, 'above_parking_growth_pre_pct': 0.75, 'above_parking_growth_post_pct': 0.2, 'social_dou_gba_sqm': 3000, 'social_school_gba_sqm': 0, 'social_clinic_gba_sqm': 0, 'project_start': '2027-01-01', 'main_under_th_per_sqm': 110, 'social_mode': 'Строительство', 'social_dou_norm_sqm': 12, 'social_school_norm_sqm': 13, 'social_clinic_norm_sqm': 15, 'offices_enabled': False, 'retail_enabled': False, 'above_parking_enabled': False, 'above_parking_area_per_space_sqm': 25, 'rate_scenario': 'low', 'land_rights_cost_mln': 2864.291514155844, 'author_supervision_mln': 19.55, 'bridge_interest_mode': 'Капитализация в ПФ', 'pf_transfer_income_pct': 5.0}
EXCEL_CONTROL = {'llcr': 1.103956112148479, 'bridge_principal_mln': 1345.8299811734776, 'bridge_interest_mln': 61.01315248705002, 'pf_draw_mln': 30011.506226781967, 'pf_interest_and_fees_mln': 2112.072941531574, 'all_interest_and_fees_mln': 2173.086094018624}
LOGO_B64 = "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"


class CalcRequest(BaseModel):
    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = []


def n(x: dict, key: str, default: float = 0.0) -> float:
    try:
        value = x.get(key, default)
        return float(default if value in (None, "") else value)
    except (TypeError, ValueError):
        return float(default)


def b(x: dict, key: str) -> bool:
    value = x.get(key, False)
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "да", "yes", "on")


def d(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def add_months(value: str | date, months: int) -> date:
    value = d(value)
    m = value.month - 1 + int(months)
    year = value.year + m // 12
    month = m % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def month_range(start: date, end: date) -> list[date]:
    cur = date(start.year, start.month, 1)
    end = date(end.year, end.month, 1)
    out = []
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def rate_lookup(rates: list[dict[str, Any]], month: date, scenario: str) -> float:
    scenario = scenario if scenario in ("high", "base", "low") else "low"
    if not rates:
        return 0.0
    selected = float(rates[0].get(scenario, 0.0))
    for row in rates:
        if d(row["date"]) <= month:
            selected = float(row.get(scenario, selected))
        else:
            break
    return selected / 100.0


def sales_schedule(
    quantity: float,
    start_price: float,
    start: date,
    rve: date,
    share_before: float,
    residual_months: int,
    growth_before: float,
    growth_after: float,
) -> dict[date, float]:
    out: dict[date, float] = defaultdict(float)
    if quantity <= 0 or start_price <= 0:
        return dict(out)

    pre_months = max(1, months_between(start, rve))
    share_before = max(0.0, min(1.0, share_before))
    pre_qty = quantity * share_before
    pre_each = pre_qty / pre_months

    for i in range(pre_months):
        month = add_months(start, i)
        price = start_price * pow(1 + growth_before, i)
        out[month] += pre_each * price

    residual_months = max(0, int(residual_months))
    if residual_months:
        after_qty = quantity * (1 - share_before)
        after_each = after_qty / residual_months
        price_at_rve = start_price * pow(1 + growth_before, pre_months)
        for i in range(residual_months):
            month = add_months(rve, i)
            price = price_at_rve * pow(1 + growth_after, i)
            out[month] += after_each * price

    return dict(out)


def spread_evenly(target: dict[date, float], amount: float, start: date, months: int) -> None:
    months = max(1, int(months))
    if not amount:
        return
    each = amount / months
    for i in range(months):
        target[add_months(start, i)] += each


def build_operating_model(x: dict, t: dict) -> dict:
    project_start = d(x.get("project_start", "2027-01-01"))
    permit = add_months(project_start, int(n(x, "ird_months", 18)))
    sales_start = add_months(permit, int(n(x, "sales_lag_months", 0)))
    rve = add_months(permit, int(n(x, "construction_months", 24)))
    residual = int(n(x, "residual_sales_months", 6))
    end = add_months(rve, max(residual + 3, 12))

    apartment = t.get("apartments", {})
    commercial = t.get("ground_commercial", {})
    underground = t.get("underground_parking", {})
    storage = t.get("storage", {})

    core_above_gns = n(apartment, "gns") + n(commercial, "gns")
    core_under_gns = n(underground, "gns") + n(storage, "gns")
    core_total_gns = core_above_gns + core_under_gns

    revenue: dict[date, float] = defaultdict(float)
    revenue_by_product: dict[str, float] = {}

    def add_product(name: str, schedule: dict[date, float]) -> None:
        revenue_by_product[name] = sum(schedule.values())
        for month, value in schedule.items():
            revenue[month] += value

    share = n(x, "share_before_rve_pct", 85) / 100
    growth_pre = n(x, "monthly_growth_pre_pct", 1.5) / 100
    growth_post = n(x, "monthly_growth_post_pct", 0.25) / 100

    add_product("apartments", sales_schedule(
        n(apartment, "saleable"), n(x, "apartment_price_th") * 1000,
        sales_start, rve, share, residual, growth_pre, growth_post
    ))
    add_product("ground_commercial", sales_schedule(
        n(commercial, "saleable"), n(x, "commercial_price_th") * 1000,
        sales_start, rve, share, residual, growth_pre, growth_post
    ))
    add_product("underground_parking", sales_schedule(
        n(underground, "units"), n(x, "parking_price_th") * 1000,
        sales_start, rve, share, residual, 0.0075, 0.002
    ))
    add_product("storage", sales_schedule(
        n(storage, "units"), n(x, "storage_price_th") * 1000,
        sales_start, rve, share, residual, 0.0075, 0.002
    ))

    standalone_capex = {}
    if b(x, "offices_enabled"):
        add_product("offices", sales_schedule(
            n(x, "offices_saleable_sqm"), n(x, "offices_price_th_per_sqm") * 1000,
            d(x["offices_sales_start"]), add_months(d(x["offices_start"]), int(n(x, "offices_months", 24))),
            n(x, "offices_share_before_rve_pct", 85) / 100,
            int(n(x, "offices_residual_months", 6)),
            n(x, "offices_growth_pre_pct", 1.5) / 100,
            n(x, "offices_growth_post_pct", 0.25) / 100,
        ))
        standalone_capex["offices"] = n(x, "offices_gba_sqm") * n(x, "offices_cost_th_per_sqm") * 1000
    else:
        revenue_by_product["offices"] = 0.0
        standalone_capex["offices"] = 0.0

    if b(x, "retail_enabled"):
        add_product("standalone_retail", sales_schedule(
            n(x, "retail_saleable_sqm"), n(x, "retail_price_th_per_sqm") * 1000,
            d(x["retail_sales_start"]), add_months(d(x["retail_start"]), int(n(x, "retail_months", 24))),
            n(x, "retail_share_before_rve_pct", 85) / 100,
            int(n(x, "retail_residual_months", 6)),
            n(x, "retail_growth_pre_pct", 1.5) / 100,
            n(x, "retail_growth_post_pct", 0.25) / 100,
        ))
        standalone_capex["standalone_retail"] = n(x, "retail_gba_sqm") * n(x, "retail_cost_th_per_sqm") * 1000
    else:
        revenue_by_product["standalone_retail"] = 0.0
        standalone_capex["standalone_retail"] = 0.0

    if b(x, "above_parking_enabled"):
        above_parking_end = add_months(d(x["above_parking_start"]), int(n(x, "above_parking_months", 18)))
        add_product("above_parking", sales_schedule(
            n(x, "above_parking_spaces"), n(x, "above_parking_price_mln_per_space") * 1_000_000,
            d(x["above_parking_sales_start"]), above_parking_end,
            n(x, "above_parking_share_before_rve_pct", 85) / 100,
            int(n(x, "above_parking_residual_months", 6)),
            n(x, "above_parking_growth_pre_pct", 0.75) / 100,
            n(x, "above_parking_growth_post_pct", 0.2) / 100,
        ))
        standalone_capex["above_parking"] = n(x, "above_parking_spaces") * n(x, "above_parking_cost_mln_per_space") * 1_000_000
    else:
        revenue_by_product["above_parking"] = 0.0
        standalone_capex["above_parking"] = 0.0

    amounts = {
        "land_rights": n(x, "land_rights_cost_mln") * 1_000_000,
        "ird": core_total_gns * n(x, "ird_th_per_sqm") * 1000,
        "design_p": core_total_gns * n(x, "design_p_th_per_sqm") * 1000,
        "design_rd": core_total_gns * n(x, "design_rd_th_per_sqm") * 1000,
        "author_supervision": n(x, "author_supervision_mln") * 1_000_000,
        "preparation": core_total_gns * n(x, "preparation_th_per_sqm") * 1000,
        "main_above": core_above_gns * n(x, "main_above_th_per_sqm") * 1000,
        "main_under": core_under_gns * n(x, "main_under_th_per_sqm") * 1000,
        "utilities": core_total_gns * n(x, "utilities_th_per_sqm") * 1000,
        "landscaping": core_total_gns * n(x, "landscaping_th_per_sqm") * 1000,
        "commissioning": core_total_gns * n(x, "commissioning_th_per_sqm") * 1000,
        "site_maintenance": core_total_gns * n(x, "site_maintenance_th_per_sqm") * 1000,
        "offices": standalone_capex["offices"],
        "standalone_retail": standalone_capex["standalone_retail"],
        "above_parking": standalone_capex["above_parking"],
    }

    social_total = (
        n(x, "kindergarten_places") * n(x, "kindergarten_cost_mln_per_place")
        + n(x, "school_places") * n(x, "school_cost_mln_per_place")
        + n(x, "clinic_capacity") * n(x, "clinic_cost_mln_per_unit")
    ) * 1_000_000
    amounts["social"] = social_total

    works_base = (
        amounts["main_above"] + amounts["main_under"] + amounts["social"]
        + amounts["offices"] + amounts["standalone_retail"] + amounts["above_parking"]
    )
    amounts["gc_fee"] = works_base * n(x, "gc_fee_pct") / 100

    base_for_overheads = sum(amounts.values())
    amounts["reserve"] = base_for_overheads * n(x, "reserve_pct") / 100
    amounts["project_management"] = base_for_overheads * n(x, "project_management_pct") / 100

    capex: dict[date, float] = defaultdict(float)
    capex[project_start] += amounts["land_rights"] + n(x, "purchase_price_mln") * 1_000_000

    ird_months = max(1, int(n(x, "ird_months", 18)))
    spread_evenly(capex, amounts["ird"], project_start, ird_months)
    # Project design cash flow is concentrated toward RnS rather than spread evenly from acquisition.
    # This materially improves bridge timing and follows the schedule logic of the current workbook.
    design_window = min(6, ird_months)
    spread_evenly(capex, amounts["design_p"], add_months(permit, -design_window), design_window)
    spread_evenly(capex, amounts["design_rd"], add_months(permit, -design_window), design_window)
    spread_evenly(capex, amounts["preparation"], add_months(permit, -design_window), design_window)

    construction_months = max(1, int(n(x, "construction_months", 24)))
    spread_evenly(capex, amounts["main_above"], permit, construction_months)
    spread_evenly(capex, amounts["main_under"], permit, construction_months)
    spread_evenly(capex, amounts["utilities"], permit, construction_months)
    spread_evenly(capex, amounts["site_maintenance"], permit, construction_months)
    spread_evenly(capex, amounts["author_supervision"], permit, construction_months)
    spread_evenly(capex, amounts["landscaping"], add_months(rve, -3), 3)
    spread_evenly(capex, amounts["commissioning"], add_months(rve, -3), 3)

    if str(x.get("social_mode", "Строительство")) == "Строительство":
        if n(x, "kindergarten_places"):
            spread_evenly(capex, n(x, "kindergarten_places") * n(x, "kindergarten_cost_mln_per_place") * 1_000_000,
                          d(x["kindergarten_start"]), int(n(x, "kindergarten_months", 24)))
        if n(x, "school_places"):
            spread_evenly(capex, n(x, "school_places") * n(x, "school_cost_mln_per_place") * 1_000_000,
                          d(x["school_start"]), int(n(x, "school_months", 30)))
        if n(x, "clinic_capacity"):
            spread_evenly(capex, n(x, "clinic_capacity") * n(x, "clinic_cost_mln_per_unit") * 1_000_000,
                          d(x["clinic_start"]), int(n(x, "clinic_months", 24)))
    else:
        capex[d(x["social_comp_date"])] += social_total

    if amounts["offices"]:
        spread_evenly(capex, amounts["offices"], d(x["offices_start"]), int(n(x, "offices_months", 24)))
    if amounts["standalone_retail"]:
        spread_evenly(capex, amounts["standalone_retail"], d(x["retail_start"]), int(n(x, "retail_months", 24)))
    if amounts["above_parking"]:
        spread_evenly(capex, amounts["above_parking"], d(x["above_parking_start"]), int(n(x, "above_parking_months", 18)))

    # GC, reserve and project management belong to the construction phase rather than the pre-RnS bridge period.
    # This is closer to the timing used in the current Excel cash-flow model.
    spread_evenly(capex, amounts["gc_fee"], permit, construction_months)
    spread_evenly(capex, amounts["reserve"], permit, construction_months)
    spread_evenly(capex, amounts["project_management"], permit, construction_months)

    operating: dict[date, float] = defaultdict(float)
    for month, value in revenue.items():
        operating[month] += value * (n(x, "marketing_pct") + n(x, "selling_pct")) / 100

    # Land/VRI is included in project investment CAPEX but is not automatically debt-funded.
    # This follows the current credit model more closely: the bridge/PF funding base is project construction cash needs.
    debt_capex = dict(capex)
    debt_capex[project_start] = max(
        debt_capex.get(project_start, 0.0) - amounts["land_rights"], 0.0
    )

    return {
        "project_start": project_start,
        "permit": permit,
        "sales_start": sales_start,
        "rve": rve,
        "end": end,
        "revenue": dict(revenue),
        "revenue_by_product": revenue_by_product,
        "capex": dict(capex),
        "debt_capex": debt_capex,
        "operating": dict(operating),
        "capex_amounts": amounts,
        "core_above_gns": core_above_gns,
        "core_under_gns": core_under_gns,
    }


def simulate_financing(x: dict, t: dict, rates: list[dict[str, Any]], op: dict) -> dict:
    project_start = op["project_start"]
    permit = op["permit"]
    rve = op["rve"]
    end = op["end"]
    months = month_range(project_start, end)
    scenario = str(x.get("rate_scenario", "low"))
    transfer_income = n(x, "pf_transfer_income_pct", 5) / 100
    interest_mode = str(x.get("bridge_interest_mode", "Капитализация в ПФ"))

    # Excel input logic: purchase + social compensation + P/RD design.
    calculated_bridge_limit = (
        n(x, "purchase_price_mln") * 1_000_000
        + op["capex_amounts"]["design_p"]
        + op["capex_amounts"]["design_rd"]
    )
    if str(x.get("social_mode")) == "Денежная компенсация":
        calculated_bridge_limit += op["capex_amounts"]["social"]

    def run(pf_limit: float | None) -> dict:
        bridge_balance = 0.0
        bridge_interest_payable = 0.0
        pf_balance = 0.0
        pf_interest_payable = 0.0
        escrow = 0.0

        bridge_draw_total = bridge_repayment_total = 0.0
        bridge_interest_total = bridge_cap_total = 0.0
        bridge_fee = calculated_bridge_limit * n(x, "reservation_fee_pct") / 100

        pf_draw_total = pf_repayment_total = 0.0
        pf_interest_total = pf_cap_total = pf_limit_fee_total = 0.0
        pf_reservation_fee = (pf_limit or 0.0) * n(x, "reservation_fee_pct") / 100 if pf_limit else 0.0
        transferred_bridge_interest = 0.0

        weighted_bridge_num = weighted_bridge_den = 0.0
        weighted_pf_num = weighted_pf_den = 0.0
        rows = []

        for month in months:
            sales = op["revenue"].get(month, 0.0)
            project_costs = op["debt_capex"].get(month, 0.0) + op["operating"].get(month, 0.0)

            key_rate = rate_lookup(rates, month, scenario)
            bridge_rate = key_rate + n(x, "bridge_spread_pp") / 100
            bridge_cap_rate = key_rate + n(x, "bridge_cap_spread_pp") / 100
            pf_base_rate = key_rate + n(x, "pf_spread_pp") / 100
            special_rate = n(x, "pf_special_pct") / 100

            bridge_draw = bridge_repayment = bridge_interest = bridge_cap = 0.0
            pf_draw = pf_repayment = pf_interest = pf_cap = limit_fee = 0.0
            interest_payment = 0.0

            if month < rve:
                escrow += sales

            # BРИДЖ finances project cash needs before RnS.
            if month < permit:
                bridge_draw = max(project_costs, 0.0)
                bridge_balance += bridge_draw
                bridge_draw_total += bridge_draw
                if bridge_balance > 0:
                    bridge_interest = bridge_balance * bridge_rate / 12
                    bridge_cap = bridge_interest_payable * bridge_cap_rate / 12
                    bridge_interest_payable += bridge_interest + bridge_cap
                    bridge_interest_total += bridge_interest
                    bridge_cap_total += bridge_cap
                    weighted_bridge_num += bridge_balance * bridge_rate
                    weighted_bridge_den += bridge_balance

            # At RnS, refinance bridge body. Bridge interest is transferred as accrued PF interest by default.
            if month == permit:
                bridge_repayment = bridge_balance
                bridge_repayment_total += bridge_repayment
                pf_draw += bridge_balance
                bridge_balance = 0.0

                transferred_bridge_interest = bridge_interest_payable
                if interest_mode == "Капитализация в ПФ":
                    pf_interest_payable += bridge_interest_payable
                else:
                    project_costs += bridge_interest_payable
                bridge_interest_payable = 0.0

            if month >= permit:
                # PF finances all project costs; escrow is not available before RVE.
                pf_draw += max(project_costs, 0.0)
                pf_balance += pf_draw
                pf_draw_total += pf_draw

                coverage = escrow / pf_balance if pf_balance > 0 else 0.0

                # Same economic logic as current Excel: weighted base/special rate up to 1x,
                # then special rate falls as escrow exceeds debt.
                if coverage <= 1:
                    pf_rate = pf_base_rate * (1 - coverage) + special_rate * coverage
                elif coverage <= 2:
                    pf_rate = max(special_rate - transfer_income * (coverage - 1), 0.0001)
                else:
                    pf_rate = 0.0001

                if pf_balance > 0:
                    pf_interest = pf_balance * pf_rate / 12
                    pf_cap = pf_interest_payable * pf_rate / 12
                    pf_interest_payable += pf_interest + pf_cap
                    pf_interest_total += pf_interest
                    pf_cap_total += pf_cap
                    weighted_pf_num += pf_balance * pf_rate
                    weighted_pf_den += pf_balance

                    if pf_limit:
                        limit_fee = max(pf_limit - pf_balance, 0.0) * n(x, "limit_fee_pct") / 100 / 12
                        pf_interest_payable += limit_fee
                        pf_limit_fee_total += limit_fee

                # Release escrow at RVE; subsequent sales also repay PF.
                available_for_repayment = 0.0
                if month == rve:
                    available_for_repayment = escrow
                    escrow = 0.0
                elif month > rve:
                    available_for_repayment = sales

                if available_for_repayment > 0 and pf_balance > 0:
                    pf_repayment = min(available_for_repayment, pf_balance)
                    pf_balance -= pf_repayment
                    pf_repayment_total += pf_repayment

                # Current Excel pays accumulated interest at RVE and current interest thereafter.
                if month >= rve and pf_interest_payable > 0:
                    interest_payment = pf_interest_payable
                    pf_interest_payable = 0.0
            else:
                coverage = 0.0
                pf_rate = 0.0

            rows.append({
                "month": month.isoformat(),
                "sales": sales,
                "project_costs": project_costs,
                "key_rate": key_rate,
                "bridge_rate": bridge_rate,
                "bridge_draw": bridge_draw,
                "bridge_balance": bridge_balance,
                "bridge_interest": bridge_interest,
                "bridge_capitalization": bridge_cap,
                "pf_draw": pf_draw,
                "pf_repayment": pf_repayment,
                "pf_balance": pf_balance,
                "escrow": escrow,
                "coverage": coverage,
                "pf_rate": pf_rate,
                "pf_interest": pf_interest,
                "pf_interest_capitalization": pf_cap,
                "limit_fee": limit_fee,
                "interest_payment": interest_payment,
            })

        return {
            "rows": rows,
            "calculated_bridge_limit": calculated_bridge_limit,
            "bridge_fee": bridge_fee,
            "bridge_draw_total": bridge_draw_total,
            "bridge_repayment_total": bridge_repayment_total,
            "bridge_interest": bridge_interest_total,
            "bridge_capitalization": bridge_cap_total,
            "transferred_bridge_interest": transferred_bridge_interest,
            "peak_bridge": max((r["bridge_balance"] for r in rows), default=0.0),
            "avg_bridge_rate": weighted_bridge_num / weighted_bridge_den if weighted_bridge_den else 0.0,

            "pf_draw_total": pf_draw_total,
            "pf_repayment_total": pf_repayment_total,
            "pf_reservation_fee": pf_reservation_fee,
            "pf_interest": pf_interest_total,
            "pf_interest_capitalization": pf_cap_total,
            "pf_limit_fee": pf_limit_fee_total,
            "peak_pf": max((r["pf_balance"] for r in rows), default=0.0),
            "avg_pf_rate": weighted_pf_num / weighted_pf_den if weighted_pf_den else 0.0,
            "ending_pf": pf_balance,
            "ending_interest_payable": pf_interest_payable,
        }

    # First pass determines the calculated PF limit; Excel rounds the financing requirement to 10m.
    first = run(None)
    pf_limit = ceil(first["pf_draw_total"] / 10_000_000) * 10_000_000 if first["pf_draw_total"] else 0.0
    result = run(pf_limit)
    result["pf_limit"] = pf_limit

    total_revenue = sum(op["revenue"].values())
    total_capex = sum(op["capex"].values())
    commercial_costs = sum(op["operating"].values())

    financing_cost = (
        result["bridge_interest"] + result["bridge_capitalization"] + result["bridge_fee"]
        + result["pf_interest"] + result["pf_interest_capitalization"]
        + result["pf_limit_fee"] + result["pf_reservation_fee"]
    )
    profit_before_tax = total_revenue - total_capex - commercial_costs - financing_cost
    profit_tax = max(profit_before_tax, 0.0) * n(x, "profit_tax_pct", 25) / 100

    # LLCR methodology mirrors the current workbook presentation:
    # numerator = project receipts - operating/tax - investment + PF inflow.
    # denominator = PF principal + interest/commissions, excluding duplicated transferred bridge interest.
    llcr_numerator = total_revenue - commercial_costs - profit_tax - total_capex + result["pf_draw_total"]

    # To reproduce Excel's correction concept, create a "reported" total where transferred bridge interest
    # appears in both bridge and PF buckets, then subtract it once.
    reported_interest_and_fees = financing_cost + result["transferred_bridge_interest"]
    llcr_denominator = (
        result["pf_draw_total"] + reported_interest_and_fees - result["transferred_bridge_interest"]
    )
    llcr = llcr_numerator / llcr_denominator if llcr_denominator else 0.0

    result.update({
        "financing_cost": financing_cost,
        "profit_tax": profit_tax,
        "profit_before_tax": profit_before_tax,
        "llcr": llcr,
        "llcr_numerator": llcr_numerator,
        "llcr_denominator": llcr_denominator,
        "reported_interest_and_fees": reported_interest_and_fees,
        "total_revenue": total_revenue,
        "total_capex": total_capex,
        "commercial_costs": commercial_costs,
    })
    return result


def calculate(req: CalcRequest) -> dict:
    x = req.inputs
    t = req.tep
    rates = req.rates or RATE_CURVE

    op = build_operating_model(x, t)
    fin = simulate_financing(x, t, rates, op)

    tep_rows = []
    for key, row in t.items():
        tep_rows.append({
            "key": key,
            "label": row.get("label", key),
            "gns": n(row, "gns"),
            "total_area": n(row, "total_area"),
            "useful": n(row, "useful"),
            "saleable": n(row, "saleable"),
            "transfer": n(row, "transfer"),
            "units": n(row, "units"),
        })

    tep_total = {
        key: sum(row[key] for row in tep_rows)
        for key in ("gns", "total_area", "useful", "saleable", "transfer", "units")
    }

    total_revenue = fin["total_revenue"]
    total_capex = fin["total_capex"]
    after_finance_pre_tax = fin["profit_before_tax"]
    net_profit = after_finance_pre_tax - fin["profit_tax"]

    return {
        "dates": {
            "project_start": op["project_start"].isoformat(),
            "permit": op["permit"].isoformat(),
            "sales_start": op["sales_start"].isoformat(),
            "rve": op["rve"].isoformat(),
        },
        "tep": {
            "rows": tep_rows,
            "total": tep_total,
            "core_above_gns": op["core_above_gns"],
            "core_under_gns": op["core_under_gns"],
        },
        "revenue": {"total": total_revenue, **op["revenue_by_product"]},
        "capex": {"total": total_capex, **op["capex_amounts"]},
        "commercial_costs": fin["commercial_costs"],
        "finance": fin,
        "summary": {
            "revenue": total_revenue,
            "capex": total_capex,
            "financing_cost": fin["financing_cost"],
            "profit_tax": fin["profit_tax"],
            "net_profit": net_profit,
            "margin": net_profit / total_revenue if total_revenue else 0.0,
            "llcr": fin["llcr"],
        },
        "excel_control": EXCEL_CONTROL,
        "notes": {
            "llcr": "LLCR рассчитан по структуре действующего листа LLCR: поступления минус операционные/инвестиционные расходы плюс ПФ, делённые на ПФ и стоимость долга.",
            "finance": "Помесячная логика БРИДЖ/ПФ/эскроу перенесена в код. До окончательной замены Excel требуется контрольная сверка нескольких сценариев по месяцам.",
        },
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "0.4"}


@app.get("/defaults")
def defaults() -> dict:
    return {
        "inputs": DEFAULT_INPUTS,
        "tep": TEP_DEFAULT,
        "rates": RATE_CURVE,
        "scenarios": SCENARIOS,
        "excel_control": EXCEL_CONTROL,
    }


@app.post("/calculate")
def calculate_api(req: CalcRequest) -> dict:
    return calculate(req)


PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ПЛАТО — Девелоперская инвестиционная модель</title>
<style>
:root{
  --black:#080808;--ink:#171717;--muted:#727272;--line:#dedede;--soft:#f5f5f3;
  --paper:#ffffff;--positive:#166534;--negative:#b42318;--warn:#8a4b08;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;
}
*{box-sizing:border-box}body{margin:0;background:#f2f2ef;color:var(--ink)}
.shell{max-width:1540px;margin:0 auto;background:var(--paper);min-height:100vh}
.brandbar{padding:22px 34px 0;background:#fff}.brandbar img{display:block;width:min(360px,58vw);height:auto}
.brandline{height:8px;background:#050505;margin-top:12px}
.header{padding:18px 34px 12px;display:flex;gap:18px;align-items:end;flex-wrap:wrap;border-bottom:1px solid var(--line)}
.title h1{font-size:22px;margin:0;font-weight:620;letter-spacing:.01em}.title p{margin:5px 0 0;color:var(--muted);font-size:13px}
.actions{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.tabs{padding:0 34px;border-bottom:1px solid var(--line);display:flex;gap:28px;overflow:auto;background:#fff}
.tab{border:0;background:none;padding:15px 0 12px;font-size:14px;font-weight:620;color:#777;white-space:nowrap;border-bottom:3px solid transparent;cursor:pointer}
.tab.active{color:#000;border-color:#000}
.content{padding:24px 34px 40px}.panel{display:none}.panel.active{display:block}
.grid{display:grid;grid-template-columns:minmax(390px,540px) 1fr;gap:20px}
.card{border:1px solid var(--line);background:#fff;padding:20px;margin-bottom:18px}
.card h2,.card h3{margin:0 0 14px}.section-title{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:#777;margin-bottom:10px;font-weight:750}
details{border-top:1px solid #e5e5e5;padding:4px 0}details:first-child{border-top:0}
summary{padding:11px 0;font-size:14px;font-weight:700;cursor:pointer}
.fields{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px;padding:0 0 15px}
.field label{font-size:12px;color:#555;display:block;margin-bottom:4px}.unit{color:#aaa;font-size:10px}
input,select{width:100%;border:1px solid #cfcfcf;background:#fff;border-radius:0;padding:9px 10px;font-size:14px;color:#111}
input:focus,select:focus{outline:2px solid #111;outline-offset:-1px}
input[type=checkbox]{width:auto;transform:scale(1.15);margin:8px}
.btn{border:1px solid #111;background:#fff;padding:9px 13px;color:#111;font-weight:700;cursor:pointer}
.btn.dark{background:#070707;color:#fff}.btn:hover{opacity:.8}.scenario select{width:auto;min-width:145px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));border-top:1px solid #111;border-left:1px solid var(--line)}
.kpi{padding:17px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);min-height:92px}
.kpi span{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#777}.kpi b{display:block;font-size:22px;margin-top:9px;font-weight:620}
.kpi small{display:block;color:#888;margin-top:5px}
.dates{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border-top:1px solid #111;border-left:1px solid var(--line)}
.datebox{padding:12px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);font-size:11px;color:#777;text-transform:uppercase;letter-spacing:.05em}
.datebox b{display:block;color:#111;font-size:14px;margin-top:5px;text-transform:none;letter-spacing:0}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:9px 8px;border-bottom:1px solid #e2e2e2;text-align:right;vertical-align:middle}
th:first-child,td:first-child{text-align:left}th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#777;background:#fafafa}
tfoot th{border-top:2px solid #111;color:#111;background:#fff}
.scroll{overflow:auto;max-height:68vh}.teptable input{min-width:94px;text-align:right;padding:7px}
.note{padding:13px 15px;background:#f6f6f4;border-left:3px solid #111;font-size:12px;line-height:1.55;color:#555;margin-top:14px}
.warning{border-left-color:#9a6700;background:#fff8e6;color:#704800}
.finance-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.metric-table td:first-child{color:#555}.metric-table td:last-child{font-weight:650}
.llcr-hero{display:flex;align-items:end;gap:24px;border-top:8px solid #000;padding-top:18px}
.llcr-value{font-size:58px;line-height:.95;font-weight:570;letter-spacing:-.04em}.llcr-label{font-size:12px;color:#777;max-width:330px;line-height:1.5}
.compare{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:15px}.compare div{padding:12px;background:#f7f7f5}
.compare small{color:#777;display:block}.compare b{display:block;margin-top:5px}
.rate-good{color:var(--positive)}.rate-warn{color:var(--warn)}.negative{color:var(--negative)}
.chart{height:230px;border:1px solid var(--line);margin-top:14px;position:relative;background:linear-gradient(to bottom,#fff,#fafafa)}
.chart svg{width:100%;height:100%}.legend{display:flex;gap:18px;font-size:11px;color:#666;margin-top:8px}.legend i{display:inline-block;width:18px;height:3px;background:#111;vertical-align:middle;margin-right:5px}.legend i.gray{background:#999}
.monthly th{position:sticky;top:0;z-index:2}.monthly td{white-space:nowrap}.monthly .money{font-variant-numeric:tabular-nums}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:13px}
.mobile-hint{display:none}
@media(max-width:1000px){
 .brandbar,.header,.tabs,.content{padding-left:18px;padding-right:18px}.grid,.finance-grid{grid-template-columns:1fr}
 .kpis{grid-template-columns:1fr 1fr}.dates{grid-template-columns:1fr 1fr}.actions{margin-left:0}
 .fields{grid-template-columns:1fr}.llcr-value{font-size:46px}.mobile-hint{display:block}
}
</style>
</head>
<body>
<div class="shell">
  <div class="brandbar"><img src="data:image/webp;base64,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"><div class="brandline"></div></div>
  <div class="header">
    <div class="title"><h1>Девелоперская инвестиционная модель</h1><p>v0.4 · ТЭП · экономика · БРИДЖ · проектное финансирование · эскроу · LLCR</p></div>
    <div class="actions">
      <div class="scenario">Сценарий&nbsp;
        <select id="scenarioSelect" onchange="applyScenario(this.value)">
          <option value="conservative">Консервативный</option><option value="base" selected>Базовый</option><option value="optimistic">Оптимистичный</option>
        </select>
      </div>
      <button class="btn" onclick="saveLocal()">Сохранить</button>
      <button class="btn" onclick="resetAll()">Сбросить</button>
      <button class="btn dark" onclick="calculateAndOpen('report')">Пересчитать</button>
    </div>
  </div>
  <div class="tabs">
    <button class="tab active" data-tab="inputs" onclick="openTab('inputs',this)">Вводные</button>
    <button class="tab" data-tab="tep" onclick="openTab('tep',this)">ТЭП</button>
    <button class="tab" data-tab="rates" onclick="openTab('rates',this)">Ключевая ставка</button>
    <button class="tab" data-tab="finance" onclick="openTab('finance',this)">Финансирование</button>
    <button class="tab" data-tab="report" onclick="openTab('report',this)">Отчёт</button>
  </div>

  <div class="content">
    <div id="inputs" class="panel active">
      <div class="grid">
        <div class="card"><div class="section-title">Вводные данные</div><div id="inputGroups"></div><button class="btn dark" style="width:100%;margin-top:12px" onclick="calculateAndOpen('report')">Пересчитать проект</button></div>
        <div>
          <div class="card"><div class="section-title">Контрольные даты</div><div class="dates" id="dateBoxes"></div></div>
          <div class="card"><div class="section-title">Ключевые показатели</div><div class="kpis" id="quickKpi"></div></div>
          <div class="note">Поля финансирования участвуют в помесячном расчёте. БРИДЖ рефинансируется в ПФ на РнС, продажи до РВЭ накапливаются на эскроу, ставка ПФ меняется в зависимости от покрытия.</div>
        </div>
      </div>
    </div>

    <div id="tep" class="panel">
      <div class="card">
        <div class="toolbar"><button class="btn" onclick="syncTep()">Обновить производные ТЭП из вводных</button><span style="color:#777;font-size:12px">В интерфейсе показывается 1 знак после запятой; внутри до редактирования сохраняется исходная точность.</span></div>
        <div class="scroll"><table class="teptable"><thead><tr><th>Продукт</th><th>ГНС, м²</th><th>Общая площадь, м²</th><th>Полезная, м²</th><th>Продаваемая, м²</th><th>Передаваемая, м²</th><th>Шт.</th></tr></thead><tbody id="tepBody"></tbody><tfoot><tr><th>Итого</th><th id="tg"></th><th id="ta"></th><th id="tu"></th><th id="ts"></th><th id="tt"></th><th id="tn"></th></tr></tfoot></table></div>
      </div>
    </div>

    <div id="rates" class="panel">
      <div class="card">
        <div class="toolbar"><div class="section-title" style="margin:0">Прогноз ключевой ставки</div><select id="rateScenario" onchange="inputs.rate_scenario=this.value;calculate()"><option value="high">Высокая</option><option value="base">Базовая</option><option value="low">Низкая</option></select></div>
        <div class="scroll"><table><thead><tr><th>Дата</th><th>Высокая, %</th><th>Базовая, %</th><th>Низкая, %</th></tr></thead><tbody id="rateBody"></tbody></table></div>
      </div>
    </div>

    <div id="finance" class="panel">
      <div class="card">
        <div class="llcr-hero"><div><div class="section-title">LLCR</div><div id="llcrValue" class="llcr-value">—</div></div><div class="llcr-label">Расчёт по той же структуре показателя, что и на листе LLCR текущей модели. Ниже — раскрытие числителя, знаменателя, процентов и долга.</div></div>
        <div class="compare"><div><small>Веб-модель</small><b id="llcrWeb">—</b></div><div><small>Контроль исходного Excel</small><b id="llcrExcel">1,104x</b></div></div>
      </div>
      <div class="kpis" id="financeKpi"></div>

      <div class="finance-grid" style="margin-top:18px">
        <div class="card"><div class="section-title">БРИДЖ</div><table class="metric-table" id="bridgeTable"></table></div>
        <div class="card"><div class="section-title">Проектное финансирование</div><table class="metric-table" id="pfTable"></table></div>
        <div class="card"><div class="section-title">Проценты и комиссии</div><table class="metric-table" id="interestTable"></table></div>
      </div>

      <div class="card">
        <div class="section-title">Долг и эскроу</div>
        <div id="financeChart" class="chart"></div>
        <div class="legend"><span><i></i>ПФ, остаток</span><span><i class="gray"></i>Эскроу</span></div>
      </div>

      <div class="card">
        <div class="section-title">Расчёт LLCR</div>
        <table class="metric-table" id="llcrTable"></table>
      </div>

      <div class="card">
        <div class="section-title">Помесячное финансирование</div>
        <div class="scroll"><table class="monthly"><thead><tr><th>Месяц</th><th>Ключевая</th><th>БРИДЖ</th><th>Ставка БРИДЖ</th><th>% БРИДЖ</th><th>ПФ</th><th>Эскроу</th><th>Покрытие</th><th>Ставка ПФ</th><th>% ПФ</th><th>Комиссия лимита</th><th>Погашение ПФ</th></tr></thead><tbody id="monthlyFinance"></tbody></table></div>
      </div>
      <div class="note warning">Контрольная цифра LLCR из исходного Excel — 1,104x. Веб-расчёт динамический и уже реагирует на вводные, но до полного отказа от Excel надо сверить помесячно 3–5 контрольных сценариев.</div>
    </div>

    <div id="report" class="panel">
      <div class="card"><div class="section-title">Итог проекта</div><div class="kpis" id="reportKpi"></div></div>
      <div class="grid">
        <div class="card"><div class="section-title">Выручка по продуктам</div><table id="revenueTable"></table></div>
        <div class="card"><div class="section-title">CAPEX</div><table id="capexTable"></table></div>
      </div>
      <div class="card"><div class="section-title">ТЭП</div><table id="reportTep"></table></div>
    </div>
  </div>
</div>

<script>
const SCENARIOS={"conservative": {"purchase_price_mln": 0, "construction_months": 27, "apartment_price_th": 300, "commercial_price_th": 250, "parking_price_th": 1000, "storage_price_th": 900, "share_before_rve_pct": 80, "pace_adjustment_pct": 20, "inflation_after_rve_pct": 2, "seasonal_reduction_pct": -20, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 1.1, "design_p_th_per_sqm": 2.75, "design_rd_th_per_sqm": 2.75, "preparation_th_per_sqm": 1.2, "main_above_th_per_sqm": 115, "utilities_th_per_sqm": 8.5, "landscaping_th_per_sqm": 5.5, "commissioning_th_per_sqm": 1.1, "site_maintenance_th_per_sqm": 1.2, "gc_fee_pct": 8, "reserve_pct": 7, "project_management_pct": 6, "marketing_pct": 4, "selling_pct": 5, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 7, "bridge_cap_spread_pp": 7, "pf_spread_pp": 5.5, "pf_special_pct": 5, "limit_fee_pct": 0.75, "reservation_fee_pct": 0.75, "discount_rate_pct": 25, "monthly_growth_pre_pct": 1, "monthly_growth_post_pct": 0.2, "ird_months": 24, "sales_lag_months": 1, "bridge_repay_lag_months": 0, "residual_sales_months": 12, "social_comp_date": "2028-12-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-12-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-12-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-12-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 250, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 450, "offices_share_before_rve_pct": 80, "offices_residual_months": 12, "offices_growth_pre_pct": 1, "offices_growth_post_pct": 0.2, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 450, "retail_share_before_rve_pct": 80, "retail_residual_months": 12, "retail_growth_pre_pct": 1, "retail_growth_post_pct": 0.2, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 1.5, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 1.8, "above_parking_share_before_rve_pct": 80, "above_parking_residual_months": 12, "above_parking_growth_pre_pct": 0.5, "above_parking_growth_post_pct": 0.1, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0, "land_rights_cost_mln": 2864.291514155844, "author_supervision_mln": 19.55, "bridge_interest_mode": "Капитализация в ПФ", "pf_transfer_income_pct": 5.0}, "base": {"purchase_price_mln": 0, "construction_months": 24, "apartment_price_th": 375, "commercial_price_th": 300, "parking_price_th": 1500, "storage_price_th": 1000, "share_before_rve_pct": 85, "pace_adjustment_pct": 25, "inflation_after_rve_pct": 3, "seasonal_reduction_pct": -15, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 1, "design_p_th_per_sqm": 2.5, "design_rd_th_per_sqm": 2.5, "preparation_th_per_sqm": 1, "main_above_th_per_sqm": 110, "utilities_th_per_sqm": 7.5, "landscaping_th_per_sqm": 5, "commissioning_th_per_sqm": 1, "site_maintenance_th_per_sqm": 1, "gc_fee_pct": 7, "reserve_pct": 5, "project_management_pct": 5, "marketing_pct": 3, "selling_pct": 4, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 6, "bridge_cap_spread_pp": 6, "pf_spread_pp": 4.5, "pf_special_pct": 4.5, "limit_fee_pct": 0.5, "reservation_fee_pct": 0.5, "discount_rate_pct": 20, "monthly_growth_pre_pct": 1.5, "monthly_growth_post_pct": 0.25, "ird_months": 18, "sales_lag_months": 0, "bridge_repay_lag_months": 0, "residual_sales_months": 6, "social_comp_date": "2028-06-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-06-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-06-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-06-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 200, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 500, "offices_share_before_rve_pct": 85, "offices_residual_months": 6, "offices_growth_pre_pct": 1.5, "offices_growth_post_pct": 0.25, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 500, "retail_share_before_rve_pct": 85, "retail_residual_months": 6, "retail_growth_pre_pct": 1.5, "retail_growth_post_pct": 0.25, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 1, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 2, "above_parking_share_before_rve_pct": 85, "above_parking_residual_months": 6, "above_parking_growth_pre_pct": 0.75, "above_parking_growth_post_pct": 0.2, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0, "land_rights_cost_mln": 2864.291514155844, "author_supervision_mln": 19.55, "bridge_interest_mode": "Капитализация в ПФ", "pf_transfer_income_pct": 5.0}, "optimistic": {"purchase_price_mln": 0, "construction_months": 22, "apartment_price_th": 400, "commercial_price_th": 325, "parking_price_th": 1750, "storage_price_th": 1100, "share_before_rve_pct": 90, "pace_adjustment_pct": 30, "inflation_after_rve_pct": 4, "seasonal_reduction_pct": -10, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 0.95, "design_p_th_per_sqm": 2.35, "design_rd_th_per_sqm": 2.35, "preparation_th_per_sqm": 0.9, "main_above_th_per_sqm": 100, "utilities_th_per_sqm": 7, "landscaping_th_per_sqm": 4.5, "commissioning_th_per_sqm": 0.9, "site_maintenance_th_per_sqm": 0.9, "gc_fee_pct": 5, "reserve_pct": 3, "project_management_pct": 4, "marketing_pct": 2, "selling_pct": 3, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 5, "bridge_cap_spread_pp": 5, "pf_spread_pp": 3.5, "pf_special_pct": 4, "limit_fee_pct": 0.35, "reservation_fee_pct": 0.35, "discount_rate_pct": 18, "monthly_growth_pre_pct": 2, "monthly_growth_post_pct": 0.3, "ird_months": 14, "sales_lag_months": 0, "bridge_repay_lag_months": 0, "residual_sales_months": 3, "social_comp_date": "2028-02-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-02-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-02-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-02-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 175, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 550, "offices_share_before_rve_pct": 90, "offices_residual_months": 3, "offices_growth_pre_pct": 2, "offices_growth_post_pct": 0.3, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 550, "retail_share_before_rve_pct": 90, "retail_residual_months": 3, "retail_growth_pre_pct": 2, "retail_growth_post_pct": 0.3, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 0.8, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 2.5, "above_parking_share_before_rve_pct": 90, "above_parking_residual_months": 3, "above_parking_growth_pre_pct": 1, "above_parking_growth_post_pct": 0.25, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0, "land_rights_cost_mln": 2864.291514155844, "author_supervision_mln": 19.55, "bridge_interest_mode": "Капитализация в ПФ", "pf_transfer_income_pct": 5.0}};
const RATE_DEFAULT=[{"date": "2027-01-01", "high": 15.0, "base": 13.0, "low": 11.0}, {"date": "2027-07-01", "high": 14.5, "base": 12.5, "low": 10.5}, {"date": "2028-01-01", "high": 13.5, "base": 11.5, "low": 9.5}, {"date": "2028-02-01", "high": 14.5, "base": 11.5, "low": 10.5}, {"date": "2028-03-01", "high": 14.25, "base": 11.25, "low": 10.25}, {"date": "2028-04-01", "high": 14.0, "base": 11.0, "low": 10.0}, {"date": "2028-05-01", "high": 13.75, "base": 11.0, "low": 9.75}, {"date": "2028-06-01", "high": 13.5, "base": 11.0, "low": 9.5}, {"date": "2028-07-01", "high": 13.25, "base": 11.0, "low": 9.25}, {"date": "2028-08-01", "high": 13.0, "base": 11.0, "low": 9.0}, {"date": "2028-09-01", "high": 12.75, "base": 10.75, "low": 8.75}, {"date": "2028-10-01", "high": 12.5, "base": 10.5, "low": 8.5}, {"date": "2028-11-01", "high": 12.25, "base": 10.25, "low": 8.25}, {"date": "2028-12-01", "high": 12.0, "base": 10.0, "low": 8.0}, {"date": "2029-01-01", "high": 11.75, "base": 9.75, "low": 7.75}, {"date": "2029-02-01", "high": 11.5, "base": 9.5, "low": 7.5}, {"date": "2029-03-01", "high": 11.25, "base": 9.25, "low": 7.25}, {"date": "2029-04-01", "high": 11.0, "base": 9.0, "low": 7.0}, {"date": "2029-05-01", "high": 10.75, "base": 8.75, "low": 6.75}, {"date": "2029-06-01", "high": 10.5, "base": 8.5, "low": 6.5}, {"date": "2029-07-01", "high": 10.25, "base": 8.25, "low": 6.25}, {"date": "2029-08-01", "high": 10.0, "base": 8.0, "low": 6.0}];
const TEP_DEFAULT={"apartments": {"label": "Квартиры", "gns": 130716.66012842482, "total_area": 117647.0588235294, "useful": 80000, "saleable": 80000, "transfer": 0, "units": 1361.815754339119}, "ground_commercial": {"label": "Коммерция 1 эт.", "gns": 9664.049734985854, "total_area": 8695.652173913044, "useful": 7826.08695652174, "saleable": 7826.08695652174, "transfer": 0, "units": 0}, "standalone_retail": {"label": "Коммерция ОСЗ", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "offices": {"label": "Офисы", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "above_parking": {"label": "Наземный паркинг", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "underground_parking": {"label": "Подземный паркинг", "gns": 38763, "total_area": 38763, "useful": 0, "saleable": 0, "transfer": 0, "units": 1107.5142857142857}, "storage": {"label": "Кладовки", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "kindergarten": {"label": "ДОУ", "gns": 0, "total_area": 3000, "useful": 0, "saleable": 0, "transfer": 3000, "units": 250}, "school": {"label": "СОШ", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "clinic": {"label": "Поликлиника", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}};
const FIELD_GROUPS=[["Сделка и сроки", [["purchase_price_mln", "Стоимость покупки / цена входа", "млн ₽", "number"], ["land_rights_cost_mln", "Оформление земельных правоотношений / смена ВРИ", "млн ₽", "number"], ["project_start", "Начало проекта", "дата", "date"], ["ird_months", "Срок ИРД до РнС", "мес.", "number"], ["construction_months", "Срок строительства", "мес.", "number"], ["sales_lag_months", "Лаг старта продаж после РнС", "мес.", "number"], ["bridge_repay_lag_months", "Лаг погашения БРИДЖ после РнС", "мес.", "number"], ["residual_sales_months", "Остаточные продажи после РВЭ", "мес.", "number"]]], ["Продажи", [["apartment_price_th", "Стартовая цена квартир", "тыс. ₽/м²", "number"], ["commercial_price_th", "Стартовая цена коммерции 1 этажа", "тыс. ₽/м²", "number"], ["parking_price_th", "Цена подземного машино-места", "тыс. ₽/шт.", "number"], ["storage_price_th", "Цена кладовой", "тыс. ₽/шт.", "number"], ["share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["pace_adjustment_pct", "Корректировка темпа", "%", "number"], ["inflation_after_rve_pct", "Инфляция после РВЭ", "% год", "number"], ["seasonal_reduction_pct", "Сезонное снижение темпа", "%", "number"], ["growth_stage1_pct", "Рост цены — этап 1", "%", "number"], ["growth_stage2_pct", "Рост цены — этап 2", "%", "number"], ["growth_stage3_pct", "Рост цены — этап 3", "%", "number"], ["growth_stage4_pct", "Рост цены — этап 4", "%", "number"], ["monthly_growth_pre_pct", "Ежемесячный рост цены до РВЭ", "%/мес.", "number"], ["monthly_growth_post_pct", "Ежемесячный рост цены после РВЭ", "%/мес.", "number"]]], ["Строительство", [["ird_th_per_sqm", "ИРД и согласования", "тыс. ₽/м² ГНС", "number"], ["design_p_th_per_sqm", "Проектирование стадии П", "тыс. ₽/м² ГНС", "number"], ["design_rd_th_per_sqm", "Проектирование стадии РД", "тыс. ₽/м² ГНС", "number"], ["preparation_th_per_sqm", "Подготовительные работы", "тыс. ₽/м² ГНС", "number"], ["main_above_th_per_sqm", "Основное строительство — наземная часть", "тыс. ₽/м² ГНС", "number"], ["main_under_th_per_sqm", "Основное строительство — подземная часть", "тыс. ₽/м² ГНС", "number"], ["utilities_th_per_sqm", "Наружные инженерные сети", "тыс. ₽/м² ГНС", "number"], ["landscaping_th_per_sqm", "Благоустройство", "тыс. ₽/м² ГНС", "number"], ["commissioning_th_per_sqm", "Сдача и ввод", "тыс. ₽/м² ГНС", "number"], ["site_maintenance_th_per_sqm", "Содержание стройплощадки", "тыс. ₽/м² ГНС", "number"], ["gc_fee_pct", "Вознаграждение генподрядчика", "% СМР", "number"], ["reserve_pct", "Резерв", "%", "number"], ["project_management_pct", "Управление проектом", "%", "number"], ["author_supervision_mln", "Авторский надзор", "млн ₽", "number"]]], ["Коммерческие расходы и налоги", [["marketing_pct", "Маркетинг", "% выручки", "number"], ["selling_pct", "Расходы на продажи", "% выручки", "number"], ["profit_tax_pct", "Налог на прибыль", "%", "number"], ["vat_pct", "НДС", "%", "number"]]], ["Финансирование", [["bridge_spread_pp", "Спред БРИДЖ", "п.п.", "number"], ["bridge_cap_spread_pp", "Спред капитализации БРИДЖ", "п.п.", "number"], ["pf_spread_pp", "Спред ПФ", "п.п.", "number"], ["pf_special_pct", "Специальная ставка ПФ", "%", "number"], ["limit_fee_pct", "Плата за лимит", "%", "number"], ["reservation_fee_pct", "Плата за резервирование", "%", "number"], ["discount_rate_pct", "Ставка дисконтирования", "%", "number"], ["bridge_interest_mode", "Проценты БРИДЖ при рефинансировании", "режим", "finance_select"], ["pf_transfer_income_pct", "Снижение спецставки при покрытии эскроу > 1x", "п.п. на 1x", "number"]]], ["Социальная нагрузка", [["social_mode", "Форма исполнения", "режим", "select"], ["social_comp_date", "Дата денежной компенсации", "дата", "date"], ["kindergarten_places", "ДОУ — количество мест", "мест", "number"], ["kindergarten_cost_mln_per_place", "ДОУ — себестоимость места", "млн ₽/место", "number"], ["kindergarten_start", "ДОУ — начало строительства", "дата", "date"], ["kindergarten_months", "ДОУ — срок строительства", "мес.", "number"], ["school_places", "СОШ — количество мест", "мест", "number"], ["school_cost_mln_per_place", "СОШ — себестоимость места", "млн ₽/место", "number"], ["school_start", "СОШ — начало строительства", "дата", "date"], ["school_months", "СОШ — срок строительства", "мес.", "number"], ["clinic_capacity", "Поликлиника — мощность", "пос./смену", "number"], ["clinic_cost_mln_per_unit", "Поликлиника — себестоимость мощности", "млн ₽/(пос./смену)", "number"], ["clinic_start", "Поликлиника — начало строительства", "дата", "date"], ["clinic_months", "Поликлиника — срок строительства", "мес.", "number"], ["social_dou_gba_sqm", "ДОУ — общая площадь", "м²", "number"], ["social_dou_norm_sqm", "ДОУ — норматив площади на место", "м²/место", "number"], ["social_school_gba_sqm", "СОШ — общая площадь", "м²", "number"], ["social_school_norm_sqm", "СОШ — норматив площади на место", "м²/место", "number"], ["social_clinic_gba_sqm", "Поликлиника — общая площадь", "м²", "number"], ["social_clinic_norm_sqm", "Поликлиника — норматив площади", "м²/ед.", "number"]]], ["МФОЦ / офисы", [["offices_enabled", "Объект включен", "Да / Нет", "checkbox"], ["offices_gba_sqm", "Общая площадь (GBA)", "м²", "number"], ["offices_saleable_sqm", "Продаваемая площадь", "м²", "number"], ["offices_start", "Начало строительства", "дата", "date"], ["offices_months", "Срок строительства", "мес.", "number"], ["offices_cost_th_per_sqm", "Себестоимость строительства", "тыс. ₽/м² GBA", "number"], ["offices_sales_start", "Старт продаж", "дата", "date"], ["offices_price_th_per_sqm", "Стартовая цена", "тыс. ₽/м²", "number"], ["offices_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["offices_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["offices_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["offices_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"]]], ["ТЦ / коммерция ОСЗ", [["retail_enabled", "Объект включен", "Да / Нет", "checkbox"], ["retail_gba_sqm", "Общая площадь (GBA)", "м²", "number"], ["retail_saleable_sqm", "Продаваемая площадь", "м²", "number"], ["retail_start", "Начало строительства", "дата", "date"], ["retail_months", "Срок строительства", "мес.", "number"], ["retail_cost_th_per_sqm", "Себестоимость строительства", "тыс. ₽/м² GBA", "number"], ["retail_sales_start", "Старт продаж", "дата", "date"], ["retail_price_th_per_sqm", "Стартовая цена", "тыс. ₽/м²", "number"], ["retail_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["retail_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["retail_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["retail_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"]]], ["Наземный паркинг", [["above_parking_enabled", "Объект включен", "Да / Нет", "checkbox"], ["above_parking_spaces", "Количество машино-мест", "шт.", "number"], ["above_parking_cost_mln_per_space", "Себестоимость одного места", "млн ₽/место", "number"], ["above_parking_start", "Начало строительства", "дата", "date"], ["above_parking_months", "Срок строительства", "мес.", "number"], ["above_parking_sales_start", "Старт продаж", "дата", "date"], ["above_parking_price_mln_per_space", "Стартовая цена места", "млн ₽/место", "number"], ["above_parking_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["above_parking_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["above_parking_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["above_parking_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"], ["above_parking_area_per_space_sqm", "Площадь на 1 место для ТЭП", "м²/место", "number"]]]];
const INPUT_DEFAULT={"purchase_price_mln": 0, "construction_months": 24, "apartment_price_th": 375, "commercial_price_th": 300, "parking_price_th": 1500, "storage_price_th": 1000, "share_before_rve_pct": 85, "pace_adjustment_pct": 25, "inflation_after_rve_pct": 3, "seasonal_reduction_pct": -15, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 1, "design_p_th_per_sqm": 2.5, "design_rd_th_per_sqm": 2.5, "preparation_th_per_sqm": 1, "main_above_th_per_sqm": 110, "utilities_th_per_sqm": 7.5, "landscaping_th_per_sqm": 5, "commissioning_th_per_sqm": 1, "site_maintenance_th_per_sqm": 1, "gc_fee_pct": 7, "reserve_pct": 5, "project_management_pct": 5, "marketing_pct": 3, "selling_pct": 4, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 6, "bridge_cap_spread_pp": 6, "pf_spread_pp": 4.5, "pf_special_pct": 4.5, "limit_fee_pct": 0.5, "reservation_fee_pct": 0.5, "discount_rate_pct": 20, "monthly_growth_pre_pct": 1.5, "monthly_growth_post_pct": 0.25, "ird_months": 18, "sales_lag_months": 0, "bridge_repay_lag_months": 0, "residual_sales_months": 6, "social_comp_date": "2028-06-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-06-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-06-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-06-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 200, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 500, "offices_share_before_rve_pct": 85, "offices_residual_months": 6, "offices_growth_pre_pct": 1.5, "offices_growth_post_pct": 0.25, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 500, "retail_share_before_rve_pct": 85, "retail_residual_months": 6, "retail_growth_pre_pct": 1.5, "retail_growth_post_pct": 0.25, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 1, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 2, "above_parking_share_before_rve_pct": 85, "above_parking_residual_months": 6, "above_parking_growth_pre_pct": 0.75, "above_parking_growth_post_pct": 0.2, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0, "project_start": "2027-01-01", "main_under_th_per_sqm": 110, "social_mode": "Строительство", "social_dou_norm_sqm": 12, "social_school_norm_sqm": 13, "social_clinic_norm_sqm": 15, "offices_enabled": false, "retail_enabled": false, "above_parking_enabled": false, "above_parking_area_per_space_sqm": 25, "rate_scenario": "low", "land_rights_cost_mln": 2864.291514155844, "author_supervision_mln": 19.55, "bridge_interest_mode": "Капитализация в ПФ", "pf_transfer_income_pct": 5.0};

let inputs=structuredClone(INPUT_DEFAULT), tep=structuredClone(TEP_DEFAULT), rates=structuredClone(RATE_DEFAULT), lastResult=null;
const money=v=>(Number(v||0)/1e9).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:2})+' млрд ₽';
const mln=v=>(Number(v||0)/1e6).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:1})+' млн ₽';
const pct=v=>(Number(v||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:2})+'%';
const mult=v=>Number(v||0).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x';
const num=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:1});
const inputDisplay=v=>Math.round(Number(v||0)*10)/10;

function openTab(id,btn){
 document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');
 document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
 (btn||document.querySelector(`[data-tab="${id}"]`)).classList.add('active');
}
function calculateAndOpen(id){calculate().then(()=>openTab(id))}

function renderInputs(){
 const box=document.getElementById('inputGroups');box.innerHTML='';
 FIELD_GROUPS.forEach((grp,idx)=>{
   const det=document.createElement('details');if(idx<3)det.open=true;
   const sum=document.createElement('summary');sum.textContent=grp[0];det.appendChild(sum);
   const grid=document.createElement('div');grid.className='fields';
   grp[1].forEach(f=>{
     const [id,label,unit,type]=f;const wrap=document.createElement('div');wrap.className='field';
     wrap.innerHTML=`<label>${label} <span class="unit">${unit}</span></label>`;
     let el;
     if(type==='select'){el=document.createElement('select');['Строительство','Денежная компенсация'].forEach(v=>{let o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o)})}
     else if(type==='finance_select'){el=document.createElement('select');['Капитализация в ПФ','Выплата при рефинансировании'].forEach(v=>{let o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o)})}
     else {el=document.createElement('input');el.type=type==='checkbox'?'checkbox':type;if(type==='number')el.step='any'}
     el.id='f_'+id;
     if(type==='checkbox')el.checked=!!inputs[id];else el.value=inputs[id]??'';
     el.onchange=()=>{inputs[id]=type==='checkbox'?el.checked:(type==='number'?Number(el.value):el.value);if(['offices_enabled','retail_enabled','above_parking_enabled','social_mode','kindergarten_places','school_places','clinic_capacity','social_dou_gba_sqm','social_school_gba_sqm','social_clinic_gba_sqm','above_parking_spaces','above_parking_area_per_space_sqm'].includes(id))syncTep(false)};
     wrap.appendChild(el);grid.appendChild(wrap);
   });det.appendChild(grid);box.appendChild(det);
 });
 rateScenario.value=inputs.rate_scenario||'low';
}

function applyScenario(name){
 const preserve={project_start:inputs.project_start,main_under_th_per_sqm:inputs.main_under_th_per_sqm,bridge_interest_mode:inputs.bridge_interest_mode,
 rate_scenario:inputs.rate_scenario,social_mode:inputs.social_mode,offices_enabled:inputs.offices_enabled,retail_enabled:inputs.retail_enabled,above_parking_enabled:inputs.above_parking_enabled,
 above_parking_area_per_space_sqm:inputs.above_parking_area_per_space_sqm};
 Object.assign(inputs,SCENARIOS[name],preserve);renderInputs();syncTep(false);calculate();
}

function renderTep(){
 const body=tepBody;body.innerHTML='';
 Object.entries(tep).forEach(([key,row])=>{
   const tr=document.createElement('tr');let html=`<td>${row.label}</td>`;
   ['gns','total_area','useful','saleable','transfer','units'].forEach(col=>{
     html+=`<td><input type="number" step="0.1" value="${inputDisplay(row[col])}" onchange="tep['${key}']['${col}']=Number(this.value);updateTepTotals()"></td>`;
   });tr.innerHTML=html;body.appendChild(tr);
 });updateTepTotals();
}
function updateTepTotals(){
 const sums={gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0};
 Object.values(tep).forEach(r=>Object.keys(sums).forEach(k=>sums[k]+=Number(r[k]||0)));
 tg.textContent=num(sums.gns);ta.textContent=num(sums.total_area);tu.textContent=num(sums.useful);ts.textContent=num(sums.saleable);tt.textContent=num(sums.transfer);tn.textContent=num(sums.units);
}
function syncTep(rerender=true){
 const socialBuild=inputs.social_mode==='Строительство';
 tep.underground_parking.gns=Number(tep.underground_parking.units||0)*35;tep.underground_parking.total_area=tep.underground_parking.gns;
 tep.offices.gns=inputs.offices_enabled?Number(inputs.offices_gba_sqm||0):0;tep.offices.total_area=tep.offices.gns;tep.offices.saleable=inputs.offices_enabled?Number(inputs.offices_saleable_sqm||0):0;tep.offices.useful=tep.offices.saleable;
 tep.standalone_retail.gns=inputs.retail_enabled?Number(inputs.retail_gba_sqm||0):0;tep.standalone_retail.total_area=tep.standalone_retail.gns;tep.standalone_retail.saleable=inputs.retail_enabled?Number(inputs.retail_saleable_sqm||0):0;tep.standalone_retail.useful=tep.standalone_retail.saleable;
 tep.above_parking.units=inputs.above_parking_enabled?Number(inputs.above_parking_spaces||0):0;tep.above_parking.gns=tep.above_parking.units*Number(inputs.above_parking_area_per_space_sqm||25);tep.above_parking.total_area=tep.above_parking.gns;
 tep.kindergarten.total_area=socialBuild?Number(inputs.social_dou_gba_sqm||0):0;tep.kindergarten.transfer=tep.kindergarten.total_area;tep.kindergarten.units=socialBuild?Number(inputs.kindergarten_places||0):0;
 tep.school.total_area=socialBuild?Number(inputs.social_school_gba_sqm||0):0;tep.school.transfer=tep.school.total_area;tep.school.units=socialBuild?Number(inputs.school_places||0):0;
 tep.clinic.total_area=socialBuild?Number(inputs.social_clinic_gba_sqm||0):0;tep.clinic.transfer=tep.clinic.total_area;tep.clinic.units=socialBuild?Number(inputs.clinic_capacity||0):0;
 if(rerender)renderTep();else updateTepTotals();
}
function renderRates(){
 rateBody.innerHTML='';rates.forEach((r,i)=>{const tr=document.createElement('tr');tr.innerHTML=`<td><input type="date" value="${r.date}" onchange="rates[${i}].date=this.value"></td><td><input type="number" step=".01" value="${r.high}" onchange="rates[${i}].high=Number(this.value)"></td><td><input type="number" step=".01" value="${r.base}" onchange="rates[${i}].base=Number(this.value)"></td><td><input type="number" step=".01" value="${r.low}" onchange="rates[${i}].low=Number(this.value)"></td>`;rateBody.appendChild(tr)});
}

async function calculate(){
 document.querySelectorAll('[id^=f_]').forEach(el=>{const id=el.id.slice(2);inputs[id]=el.type==='checkbox'?el.checked:(el.type==='number'?Number(el.value):el.value)});
 inputs.rate_scenario=rateScenario.value;
 const response=await fetch('/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inputs,tep,rates})});
 lastResult=await response.json();renderResult();return lastResult;
}

function row(label,value){return `<tr><td>${label}</td><td>${value}</td></tr>`}
function renderResult(){
 if(!lastResult)return;const r=lastResult,f=r.finance;
 dateBoxes.innerHTML=[['Начало',r.dates.project_start],['РнС',r.dates.permit],['Старт продаж',r.dates.sales_start],['РВЭ',r.dates.rve]].map(x=>`<div class="datebox">${x[0]}<b>${x[1]}</b></div>`).join('');
 const kpis=[['Выручка',money(r.summary.revenue)],['CAPEX',money(r.summary.capex)],['Стоимость долга',money(r.summary.financing_cost)],['LLCR',mult(r.summary.llcr)]];
 quickKpi.innerHTML=reportKpi.innerHTML=kpis.map(x=>`<div class="kpi"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('');

 llcrValue.textContent=mult(r.summary.llcr);llcrWeb.textContent=mult(r.summary.llcr);llcrExcel.textContent=mult(r.excel_control.llcr);
 financeKpi.innerHTML=[
  ['Пиковый БРИДЖ',money(f.peak_bridge)],['Пиковый ПФ',money(f.peak_pf)],['Средняя ставка БРИДЖ',pct(f.avg_bridge_rate)],['Средняя ставка ПФ',pct(f.avg_pf_rate)],
  ['Все проценты и комиссии',money(f.financing_cost)],['Налог на прибыль',money(f.profit_tax)],['Лимит ПФ',money(f.pf_limit)],['Остаток ПФ',money(f.ending_pf)]
 ].map(x=>`<div class="kpi"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('');

 bridgeTable.innerHTML=
  row('Расчётный лимит',money(f.calculated_bridge_limit))+
  row('Фактическая выборка',money(f.bridge_draw_total))+
  row('Пиковый остаток',money(f.peak_bridge))+
  row('Средневзвешенная ставка',pct(f.avg_bridge_rate))+
  row('Начисленные проценты',money(f.bridge_interest))+
  row('Капитализация процентов',money(f.bridge_capitalization))+
  row('Перенесено в ПФ',money(f.transferred_bridge_interest));

 pfTable.innerHTML=
  row('Лимит ПФ',money(f.pf_limit))+
  row('Совокупная выборка',money(f.pf_draw_total))+
  row('Пиковый остаток',money(f.peak_pf))+
  row('Погашено основного долга',money(f.pf_repayment_total))+
  row('Остаток',money(f.ending_pf))+
  row('Средневзвешенная ставка',pct(f.avg_pf_rate));

 interestTable.innerHTML=
  row('Проценты БРИДЖ',money(f.bridge_interest))+
  row('Капитализация БРИДЖ',money(f.bridge_capitalization))+
  row('Комиссия БРИДЖ',money(f.bridge_fee))+
  row('Проценты ПФ',money(f.pf_interest))+
  row('Капитализация процентов ПФ',money(f.pf_interest_capitalization))+
  row('Плата за невыбранный лимит',money(f.pf_limit_fee))+
  row('Комиссия за резервирование ПФ',money(f.pf_reservation_fee))+
  `<tr><th>Итого стоимость долга</th><th>${money(f.financing_cost)}</th></tr>`;

 llcrTable.innerHTML=
  row('Поступления проекта',money(f.total_revenue))+
  row('Коммерческие расходы',`(${money(f.commercial_costs)})`)+
  row('Налог на прибыль',`(${money(f.profit_tax)})`)+
  row('Инвестиционные расходы',`(${money(f.total_capex)})`)+
  row('Поступление ПФ',money(f.pf_draw_total))+
  `<tr><th>Числитель LLCR</th><th>${money(f.llcr_numerator)}</th></tr>`+
  row('Основной долг ПФ',money(f.pf_draw_total))+
  row('Проценты и комиссии',money(f.reported_interest_and_fees))+
  row('Корректировка переноса процентов БРИДЖ',`(${money(f.transferred_bridge_interest)})`)+
  `<tr><th>Знаменатель LLCR</th><th>${money(f.llcr_denominator)}</th></tr>`+
  `<tr><th>LLCR</th><th>${mult(f.llcr)}</th></tr>`;

 renderFinanceChart(f.rows);
 monthlyFinance.innerHTML=f.rows.filter((_,i)=>i%1===0).map(x=>`<tr>
  <td>${x.month.slice(0,7)}</td><td>${pct(x.key_rate)}</td><td class="money">${mln(x.bridge_balance)}</td><td>${pct(x.bridge_rate)}</td><td>${mln(x.bridge_interest+x.bridge_capitalization)}</td>
  <td class="money">${mln(x.pf_balance)}</td><td class="money">${mln(x.escrow)}</td><td>${mult(x.coverage)}</td><td>${pct(x.pf_rate)}</td><td>${mln(x.pf_interest+x.pf_interest_capitalization)}</td><td>${mln(x.limit_fee)}</td><td>${mln(x.pf_repayment)}</td>
 </tr>`).join('');

 const revNames={apartments:'Квартиры',ground_commercial:'Коммерция 1 этажа',underground_parking:'Подземный паркинг',storage:'Кладовки',offices:'Офисы',standalone_retail:'Коммерция ОСЗ',above_parking:'Наземный паркинг'};
 revenueTable.innerHTML=Object.entries(r.revenue).filter(([key])=>key!=='total').map(([key,v])=>row(revNames[key]||key,money(v))).join('')+`<tr><th>Итого</th><th>${money(r.revenue.total)}</th></tr>`;
 const capNames={land_rights:'Земля / смена ВРИ',ird:'ИРД',design_p:'Проект П',design_rd:'Проект РД',author_supervision:'Авторский надзор',preparation:'Подготовительные работы',main_above:'Основное строительство — наземная часть',main_under:'Основное строительство — подземная часть',utilities:'Наружные сети',landscaping:'Благоустройство',commissioning:'Сдача и ввод',site_maintenance:'Содержание стройплощадки',social:'Социальная нагрузка',offices:'Офисы',standalone_retail:'Коммерция ОСЗ',above_parking:'Наземный паркинг',gc_fee:'Генподрядчик',reserve:'Резерв',project_management:'Управление проектом'};
 capexTable.innerHTML=Object.entries(r.capex).filter(([key])=>key!=='total').map(([key,v])=>row(capNames[key]||key,money(v))).join('')+`<tr><th>Итого</th><th>${money(r.capex.total)}</th></tr>`;
 reportTep.innerHTML=r.tep.rows.map(x=>`<tr><td>${x.label}</td><td>ГНС ${num(x.gns)} м²</td><td>прод. ${num(x.saleable)} м²</td><td>${num(x.units)} шт.</td></tr>`).join('')+`<tr><th>Итого</th><th>${num(r.tep.total.gns)} м²</th><th>${num(r.tep.total.saleable)} м²</th><th>${num(r.tep.total.units)} шт.</th></tr>`;
}

function renderFinanceChart(rows){
 const data=rows.filter(x=>x.pf_balance>0||x.escrow>0);
 if(!data.length){financeChart.innerHTML='';return}
 const W=900,H=220,pad=18,max=Math.max(...data.flatMap(x=>[x.pf_balance,x.escrow]),1);
 const pts=(key)=>data.map((x,i)=>`${pad+i*(W-2*pad)/Math.max(data.length-1,1)},${H-pad-(x[key]/max)*(H-2*pad)}`).join(' ');
 financeChart.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
 <line x1="${pad}" y1="${H-pad}" x2="${W-pad}" y2="${H-pad}" stroke="#ddd"/>
 <polyline points="${pts('pf_balance')}" fill="none" stroke="#050505" stroke-width="3" vector-effect="non-scaling-stroke"/>
 <polyline points="${pts('escrow')}" fill="none" stroke="#999" stroke-width="2" vector-effect="non-scaling-stroke"/>
 </svg>`;
}

function saveLocal(){localStorage.setItem('plato_v04',JSON.stringify({inputs,tep,rates,scenario:scenarioSelect.value}));alert('Сохранено в этом браузере')}
function loadLocal(){try{const x=JSON.parse(localStorage.getItem('plato_v04'));if(x){inputs=x.inputs||inputs;tep=x.tep||tep;rates=x.rates||rates;scenarioSelect.value=x.scenario||'base'}}catch(e){}}
function resetAll(){localStorage.removeItem('plato_v04');inputs=structuredClone(INPUT_DEFAULT);tep=structuredClone(TEP_DEFAULT);rates=structuredClone(RATE_DEFAULT);scenarioSelect.value='base';renderInputs();renderTep();renderRates();calculate()}

loadLocal();renderInputs();renderTep();renderRates();calculate();
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE
