
from __future__ import annotations

import json
import calendar
from datetime import date
from math import pow
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="PLATO Development Investment Model", version="0.3")


SCENARIOS = {"conservative": {"purchase_price_mln": 0, "construction_months": 27, "apartment_price_th": 300, "commercial_price_th": 250, "parking_price_th": 1000, "storage_price_th": 900, "share_before_rve_pct": 80, "pace_adjustment_pct": 20, "inflation_after_rve_pct": 2, "seasonal_reduction_pct": -20, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 1.1, "design_p_th_per_sqm": 2.75, "design_rd_th_per_sqm": 2.75, "preparation_th_per_sqm": 1.2, "main_above_th_per_sqm": 115, "utilities_th_per_sqm": 8.5, "landscaping_th_per_sqm": 5.5, "commissioning_th_per_sqm": 1.1, "site_maintenance_th_per_sqm": 1.2, "gc_fee_pct": 8, "reserve_pct": 7, "project_management_pct": 6, "marketing_pct": 4, "selling_pct": 5, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 7, "bridge_cap_spread_pp": 7, "pf_spread_pp": 5.5, "pf_special_pct": 5, "limit_fee_pct": 0.75, "reservation_fee_pct": 0.75, "discount_rate_pct": 25, "monthly_growth_pre_pct": 1, "monthly_growth_post_pct": 0.2, "ird_months": 24, "sales_lag_months": 1, "bridge_repay_lag_months": 0, "residual_sales_months": 12, "social_comp_date": "2028-12-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-12-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-12-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-12-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 250, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 450, "offices_share_before_rve_pct": 80, "offices_residual_months": 12, "offices_growth_pre_pct": 1, "offices_growth_post_pct": 0.2, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 450, "retail_share_before_rve_pct": 80, "retail_residual_months": 12, "retail_growth_pre_pct": 1, "retail_growth_post_pct": 0.2, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 1.5, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 1.8, "above_parking_share_before_rve_pct": 80, "above_parking_residual_months": 12, "above_parking_growth_pre_pct": 0.5, "above_parking_growth_post_pct": 0.1, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0}, "base": {"purchase_price_mln": 0, "construction_months": 24, "apartment_price_th": 375, "commercial_price_th": 300, "parking_price_th": 1500, "storage_price_th": 1000, "share_before_rve_pct": 85, "pace_adjustment_pct": 25, "inflation_after_rve_pct": 3, "seasonal_reduction_pct": -15, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 1, "design_p_th_per_sqm": 2.5, "design_rd_th_per_sqm": 2.5, "preparation_th_per_sqm": 1, "main_above_th_per_sqm": 110, "utilities_th_per_sqm": 7.5, "landscaping_th_per_sqm": 5, "commissioning_th_per_sqm": 1, "site_maintenance_th_per_sqm": 1, "gc_fee_pct": 7, "reserve_pct": 5, "project_management_pct": 5, "marketing_pct": 3, "selling_pct": 4, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 6, "bridge_cap_spread_pp": 6, "pf_spread_pp": 4.5, "pf_special_pct": 4.5, "limit_fee_pct": 0.5, "reservation_fee_pct": 0.5, "discount_rate_pct": 20, "monthly_growth_pre_pct": 1.5, "monthly_growth_post_pct": 0.25, "ird_months": 18, "sales_lag_months": 0, "bridge_repay_lag_months": 0, "residual_sales_months": 6, "social_comp_date": "2028-06-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-06-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-06-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-06-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 200, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 500, "offices_share_before_rve_pct": 85, "offices_residual_months": 6, "offices_growth_pre_pct": 1.5, "offices_growth_post_pct": 0.25, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 500, "retail_share_before_rve_pct": 85, "retail_residual_months": 6, "retail_growth_pre_pct": 1.5, "retail_growth_post_pct": 0.25, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 1, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 2, "above_parking_share_before_rve_pct": 85, "above_parking_residual_months": 6, "above_parking_growth_pre_pct": 0.75, "above_parking_growth_post_pct": 0.2, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0}, "optimistic": {"purchase_price_mln": 0, "construction_months": 22, "apartment_price_th": 400, "commercial_price_th": 325, "parking_price_th": 1750, "storage_price_th": 1100, "share_before_rve_pct": 90, "pace_adjustment_pct": 30, "inflation_after_rve_pct": 4, "seasonal_reduction_pct": -10, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 0.95, "design_p_th_per_sqm": 2.35, "design_rd_th_per_sqm": 2.35, "preparation_th_per_sqm": 0.9, "main_above_th_per_sqm": 100, "utilities_th_per_sqm": 7, "landscaping_th_per_sqm": 4.5, "commissioning_th_per_sqm": 0.9, "site_maintenance_th_per_sqm": 0.9, "gc_fee_pct": 5, "reserve_pct": 3, "project_management_pct": 4, "marketing_pct": 2, "selling_pct": 3, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 5, "bridge_cap_spread_pp": 5, "pf_spread_pp": 3.5, "pf_special_pct": 4, "limit_fee_pct": 0.35, "reservation_fee_pct": 0.35, "discount_rate_pct": 18, "monthly_growth_pre_pct": 2, "monthly_growth_post_pct": 0.3, "ird_months": 14, "sales_lag_months": 0, "bridge_repay_lag_months": 0, "residual_sales_months": 3, "social_comp_date": "2028-02-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-02-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-02-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-02-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 175, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 550, "offices_share_before_rve_pct": 90, "offices_residual_months": 3, "offices_growth_pre_pct": 2, "offices_growth_post_pct": 0.3, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 550, "retail_share_before_rve_pct": 90, "retail_residual_months": 3, "retail_growth_pre_pct": 2, "retail_growth_post_pct": 0.3, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 0.8, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 2.5, "above_parking_share_before_rve_pct": 90, "above_parking_residual_months": 3, "above_parking_growth_pre_pct": 1, "above_parking_growth_post_pct": 0.25, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0}}
RATE_CURVE = [{"date": "2027-01-01", "high": 15.0, "base": 13.0, "low": 11.0}, {"date": "2027-07-01", "high": 14.5, "base": 12.5, "low": 10.5}, {"date": "2028-01-01", "high": 13.5, "base": 11.5, "low": 9.5}, {"date": "2028-02-01", "high": 14.5, "base": 11.5, "low": 10.5}, {"date": "2028-03-01", "high": 14.25, "base": 11.25, "low": 10.25}, {"date": "2028-04-01", "high": 14.0, "base": 11.0, "low": 10.0}, {"date": "2028-05-01", "high": 13.75, "base": 11.0, "low": 9.75}, {"date": "2028-06-01", "high": 13.5, "base": 11.0, "low": 9.5}, {"date": "2028-07-01", "high": 13.25, "base": 11.0, "low": 9.25}, {"date": "2028-08-01", "high": 13.0, "base": 11.0, "low": 9.0}, {"date": "2028-09-01", "high": 12.75, "base": 10.75, "low": 8.75}, {"date": "2028-10-01", "high": 12.5, "base": 10.5, "low": 8.5}, {"date": "2028-11-01", "high": 12.25, "base": 10.25, "low": 8.25}, {"date": "2028-12-01", "high": 12.0, "base": 10.0, "low": 8.0}, {"date": "2029-01-01", "high": 11.75, "base": 9.75, "low": 7.75}, {"date": "2029-02-01", "high": 11.5, "base": 9.5, "low": 7.5}, {"date": "2029-03-01", "high": 11.25, "base": 9.25, "low": 7.25}, {"date": "2029-04-01", "high": 11.0, "base": 9.0, "low": 7.0}, {"date": "2029-05-01", "high": 10.75, "base": 8.75, "low": 6.75}, {"date": "2029-06-01", "high": 10.5, "base": 8.5, "low": 6.5}, {"date": "2029-07-01", "high": 10.25, "base": 8.25, "low": 6.25}, {"date": "2029-08-01", "high": 10.0, "base": 8.0, "low": 6.0}]
TEP_DEFAULT = {"apartments": {"label": "Квартиры", "gns": 130716.66012842482, "total_area": 117647.0588235294, "useful": 80000, "saleable": 80000, "transfer": 0, "units": 1361.815754339119}, "ground_commercial": {"label": "Коммерция 1 эт.", "gns": 9664.049734985854, "total_area": 8695.652173913044, "useful": 7826.08695652174, "saleable": 7826.08695652174, "transfer": 0, "units": 0}, "standalone_retail": {"label": "Коммерция ОСЗ", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "offices": {"label": "Офисы", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "above_parking": {"label": "Наземный паркинг", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "underground_parking": {"label": "Подземный паркинг", "gns": 38763, "total_area": 38763, "useful": 0, "saleable": 0, "transfer": 0, "units": 1107.5142857142857}, "storage": {"label": "Кладовки", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "kindergarten": {"label": "ДОУ", "gns": 0, "total_area": 3000, "useful": 0, "saleable": 0, "transfer": 3000, "units": 250}, "school": {"label": "СОШ", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "clinic": {"label": "Поликлиника", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}}
FIELD_GROUPS = [["Сделка и сроки", [["purchase_price_mln", "Стоимость покупки / цена входа", "млн ₽", "number"], ["project_start", "Начало проекта", "дата", "date"], ["ird_months", "Срок ИРД до РнС", "мес.", "number"], ["construction_months", "Срок строительства", "мес.", "number"], ["sales_lag_months", "Лаг старта продаж после РнС", "мес.", "number"], ["bridge_repay_lag_months", "Лаг погашения БРИДЖ после РнС", "мес.", "number"], ["residual_sales_months", "Остаточные продажи после РВЭ", "мес.", "number"]]], ["Продажи", [["apartment_price_th", "Стартовая цена квартир", "тыс. ₽/м²", "number"], ["commercial_price_th", "Стартовая цена коммерции 1 этажа", "тыс. ₽/м²", "number"], ["parking_price_th", "Цена подземного машино-места", "тыс. ₽/шт.", "number"], ["storage_price_th", "Цена кладовой", "тыс. ₽/шт.", "number"], ["share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["pace_adjustment_pct", "Корректировка темпа", "%", "number"], ["inflation_after_rve_pct", "Инфляция после РВЭ", "% год", "number"], ["seasonal_reduction_pct", "Сезонное снижение темпа", "%", "number"], ["growth_stage1_pct", "Рост цены — этап 1", "%", "number"], ["growth_stage2_pct", "Рост цены — этап 2", "%", "number"], ["growth_stage3_pct", "Рост цены — этап 3", "%", "number"], ["growth_stage4_pct", "Рост цены — этап 4", "%", "number"], ["monthly_growth_pre_pct", "Ежемесячный рост цены до РВЭ", "%/мес.", "number"], ["monthly_growth_post_pct", "Ежемесячный рост цены после РВЭ", "%/мес.", "number"]]], ["Строительство", [["ird_th_per_sqm", "ИРД и согласования", "тыс. ₽/м² ГНС", "number"], ["design_p_th_per_sqm", "Проектирование стадии П", "тыс. ₽/м² ГНС", "number"], ["design_rd_th_per_sqm", "Проектирование стадии РД", "тыс. ₽/м² ГНС", "number"], ["preparation_th_per_sqm", "Подготовительные работы", "тыс. ₽/м² ГНС", "number"], ["main_above_th_per_sqm", "Основное строительство — наземная часть", "тыс. ₽/м² ГНС", "number"], ["main_under_th_per_sqm", "Основное строительство — подземная часть", "тыс. ₽/м² ГНС", "number"], ["utilities_th_per_sqm", "Наружные инженерные сети", "тыс. ₽/м² ГНС", "number"], ["landscaping_th_per_sqm", "Благоустройство", "тыс. ₽/м² ГНС", "number"], ["commissioning_th_per_sqm", "Сдача и ввод", "тыс. ₽/м² ГНС", "number"], ["site_maintenance_th_per_sqm", "Содержание стройплощадки", "тыс. ₽/м² ГНС", "number"], ["gc_fee_pct", "Вознаграждение генподрядчика", "% СМР", "number"], ["reserve_pct", "Резерв", "%", "number"], ["project_management_pct", "Управление проектом", "%", "number"]]], ["Коммерческие расходы и налоги", [["marketing_pct", "Маркетинг", "% выручки", "number"], ["selling_pct", "Расходы на продажи", "% выручки", "number"], ["profit_tax_pct", "Налог на прибыль", "%", "number"], ["vat_pct", "НДС", "%", "number"]]], ["Финансирование", [["bridge_spread_pp", "Спред БРИДЖ", "п.п.", "number"], ["bridge_cap_spread_pp", "Спред капитализации БРИДЖ", "п.п.", "number"], ["pf_spread_pp", "Спред ПФ", "п.п.", "number"], ["pf_special_pct", "Специальная ставка ПФ", "%", "number"], ["limit_fee_pct", "Плата за лимит", "%", "number"], ["reservation_fee_pct", "Плата за резервирование", "%", "number"], ["discount_rate_pct", "Ставка дисконтирования", "%", "number"]]], ["Социальная нагрузка", [["social_mode", "Форма исполнения", "режим", "select"], ["social_comp_date", "Дата денежной компенсации", "дата", "date"], ["kindergarten_places", "ДОУ — количество мест", "мест", "number"], ["kindergarten_cost_mln_per_place", "ДОУ — себестоимость места", "млн ₽/место", "number"], ["kindergarten_start", "ДОУ — начало строительства", "дата", "date"], ["kindergarten_months", "ДОУ — срок строительства", "мес.", "number"], ["school_places", "СОШ — количество мест", "мест", "number"], ["school_cost_mln_per_place", "СОШ — себестоимость места", "млн ₽/место", "number"], ["school_start", "СОШ — начало строительства", "дата", "date"], ["school_months", "СОШ — срок строительства", "мес.", "number"], ["clinic_capacity", "Поликлиника — мощность", "пос./смену", "number"], ["clinic_cost_mln_per_unit", "Поликлиника — себестоимость мощности", "млн ₽/(пос./смену)", "number"], ["clinic_start", "Поликлиника — начало строительства", "дата", "date"], ["clinic_months", "Поликлиника — срок строительства", "мес.", "number"], ["social_dou_gba_sqm", "ДОУ — общая площадь", "м²", "number"], ["social_dou_norm_sqm", "ДОУ — норматив площади на место", "м²/место", "number"], ["social_school_gba_sqm", "СОШ — общая площадь", "м²", "number"], ["social_school_norm_sqm", "СОШ — норматив площади на место", "м²/место", "number"], ["social_clinic_gba_sqm", "Поликлиника — общая площадь", "м²", "number"], ["social_clinic_norm_sqm", "Поликлиника — норматив площади", "м²/ед.", "number"]]], ["МФОЦ / офисы", [["offices_enabled", "Объект включен", "Да / Нет", "checkbox"], ["offices_gba_sqm", "Общая площадь (GBA)", "м²", "number"], ["offices_saleable_sqm", "Продаваемая площадь", "м²", "number"], ["offices_start", "Начало строительства", "дата", "date"], ["offices_months", "Срок строительства", "мес.", "number"], ["offices_cost_th_per_sqm", "Себестоимость строительства", "тыс. ₽/м² GBA", "number"], ["offices_sales_start", "Старт продаж", "дата", "date"], ["offices_price_th_per_sqm", "Стартовая цена", "тыс. ₽/м²", "number"], ["offices_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["offices_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["offices_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["offices_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"]]], ["ТЦ / коммерция ОСЗ", [["retail_enabled", "Объект включен", "Да / Нет", "checkbox"], ["retail_gba_sqm", "Общая площадь (GBA)", "м²", "number"], ["retail_saleable_sqm", "Продаваемая площадь", "м²", "number"], ["retail_start", "Начало строительства", "дата", "date"], ["retail_months", "Срок строительства", "мес.", "number"], ["retail_cost_th_per_sqm", "Себестоимость строительства", "тыс. ₽/м² GBA", "number"], ["retail_sales_start", "Старт продаж", "дата", "date"], ["retail_price_th_per_sqm", "Стартовая цена", "тыс. ₽/м²", "number"], ["retail_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["retail_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["retail_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["retail_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"]]], ["Наземный паркинг", [["above_parking_enabled", "Объект включен", "Да / Нет", "checkbox"], ["above_parking_spaces", "Количество машино-мест", "шт.", "number"], ["above_parking_cost_mln_per_space", "Себестоимость одного места", "млн ₽/место", "number"], ["above_parking_start", "Начало строительства", "дата", "date"], ["above_parking_months", "Срок строительства", "мес.", "number"], ["above_parking_sales_start", "Старт продаж", "дата", "date"], ["above_parking_price_mln_per_space", "Стартовая цена места", "млн ₽/место", "number"], ["above_parking_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["above_parking_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["above_parking_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["above_parking_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"], ["above_parking_area_per_space_sqm", "Площадь на 1 место для ТЭП", "м²/место", "number"]]]]
DEFAULT_INPUTS = {"purchase_price_mln": 0, "construction_months": 24, "apartment_price_th": 375, "commercial_price_th": 300, "parking_price_th": 1500, "storage_price_th": 1000, "share_before_rve_pct": 85, "pace_adjustment_pct": 25, "inflation_after_rve_pct": 3, "seasonal_reduction_pct": -15, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 1, "design_p_th_per_sqm": 2.5, "design_rd_th_per_sqm": 2.5, "preparation_th_per_sqm": 1, "main_above_th_per_sqm": 110, "utilities_th_per_sqm": 7.5, "landscaping_th_per_sqm": 5, "commissioning_th_per_sqm": 1, "site_maintenance_th_per_sqm": 1, "gc_fee_pct": 7, "reserve_pct": 5, "project_management_pct": 5, "marketing_pct": 3, "selling_pct": 4, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 6, "bridge_cap_spread_pp": 6, "pf_spread_pp": 4.5, "pf_special_pct": 4.5, "limit_fee_pct": 0.5, "reservation_fee_pct": 0.5, "discount_rate_pct": 20, "monthly_growth_pre_pct": 1.5, "monthly_growth_post_pct": 0.25, "ird_months": 18, "sales_lag_months": 0, "bridge_repay_lag_months": 0, "residual_sales_months": 6, "social_comp_date": "2028-06-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-06-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-06-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-06-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 200, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 500, "offices_share_before_rve_pct": 85, "offices_residual_months": 6, "offices_growth_pre_pct": 1.5, "offices_growth_post_pct": 0.25, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 500, "retail_share_before_rve_pct": 85, "retail_residual_months": 6, "retail_growth_pre_pct": 1.5, "retail_growth_post_pct": 0.25, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 1, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 2, "above_parking_share_before_rve_pct": 85, "above_parking_residual_months": 6, "above_parking_growth_pre_pct": 0.75, "above_parking_growth_post_pct": 0.2, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0, "project_start": "2027-01-01", "main_under_th_per_sqm": 110, "social_mode": "Строительство", "social_dou_norm_sqm": 12, "social_school_norm_sqm": 13, "social_clinic_norm_sqm": 15, "offices_enabled": false, "retail_enabled": false, "above_parking_enabled": false, "above_parking_area_per_space_sqm": 25, "rate_scenario": "low"}


class CalcRequest(BaseModel):
    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = []


def add_months_iso(s: str, months: int) -> str:
    d = date.fromisoformat(s)
    m = d.month - 1 + int(months)
    y = d.year + m // 12
    mo = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, mo)[1])
    return date(y, mo, day).isoformat()


def n(x: dict, key: str, default: float = 0.0) -> float:
    try:
        v = x.get(key, default)
        return float(v if v not in (None, "") else default)
    except Exception:
        return default


def b(x: dict, key: str) -> bool:
    v = x.get(key, False)
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1","true","да","yes","on")


def sales_revenue(quantity: float, start_price: float, share_pre: float,
                  pre_months: int, post_months: int,
                  growth_pre: float, growth_post: float) -> float:
    if quantity <= 0 or start_price <= 0:
        return 0.0
    pre_months = max(1, int(pre_months))
    post_months = max(0, int(post_months))
    share_pre = max(0.0, min(1.0, share_pre))

    revenue = 0.0
    pre_q = quantity * share_pre / pre_months
    for i in range(pre_months):
        revenue += pre_q * start_price * pow(1 + growth_pre, i)

    if post_months:
        after_q = quantity * (1 - share_pre) / post_months
        completion_price = start_price * pow(1 + growth_pre, pre_months)
        for i in range(post_months):
            revenue += after_q * completion_price * pow(1 + growth_post, i)
    return revenue


def calculate(req: CalcRequest) -> dict:
    x = req.inputs
    t = req.tep

    project_start = str(x.get("project_start","2027-01-01"))
    permit_date = add_months_iso(project_start, int(n(x,"ird_months",18)))
    sales_start = add_months_iso(permit_date, int(n(x,"sales_lag_months",0)))
    rve_date = add_months_iso(permit_date, int(n(x,"construction_months",24)))
    bridge_repay = add_months_iso(permit_date, int(n(x,"bridge_repay_lag_months",0)))

    # TEP: core objects
    apt = t.get("apartments", {})
    com = t.get("ground_commercial", {})
    under = t.get("underground_parking", {})
    storage = t.get("storage", {})

    apartment_saleable = n(apt,"saleable")
    commercial_saleable = n(com,"saleable")
    parking_units = n(under,"units")
    storage_units = n(storage,"units")

    core_above_gns = n(apt,"gns") + n(com,"gns")
    core_under_gns = n(under,"gns") + n(storage,"gns")
    core_total_gns = core_above_gns + core_under_gns

    share = n(x,"share_before_rve_pct",85)/100
    pre_months = max(1, int(n(x,"construction_months",24)))
    post_months = int(n(x,"residual_sales_months",6))
    growth_pre = n(x,"monthly_growth_pre_pct",1.5)/100
    growth_post = n(x,"monthly_growth_post_pct",0.25)/100

    apartment_revenue = sales_revenue(apartment_saleable, n(x,"apartment_price_th")*1000, share, pre_months, post_months, growth_pre, growth_post)
    commercial_revenue = sales_revenue(commercial_saleable, n(x,"commercial_price_th")*1000, share, pre_months, post_months, growth_pre, growth_post)
    parking_revenue = sales_revenue(parking_units, n(x,"parking_price_th")*1000, share, pre_months, post_months, 0.0075, 0.002)
    storage_revenue = sales_revenue(storage_units, n(x,"storage_price_th")*1000, share, pre_months, post_months, 0.0075, 0.002)

    # Standalone products
    offices_revenue = 0.0
    offices_capex = 0.0
    if b(x,"offices_enabled"):
        offices_revenue = sales_revenue(
            n(x,"offices_saleable_sqm"), n(x,"offices_price_th_per_sqm")*1000,
            n(x,"offices_share_before_rve_pct",85)/100, int(n(x,"offices_months",24)),
            int(n(x,"offices_residual_months",6)), n(x,"offices_growth_pre_pct",1.5)/100,
            n(x,"offices_growth_post_pct",0.25)/100
        )
        offices_capex = n(x,"offices_gba_sqm") * n(x,"offices_cost_th_per_sqm") * 1000

    retail_revenue = 0.0
    retail_capex = 0.0
    if b(x,"retail_enabled"):
        retail_revenue = sales_revenue(
            n(x,"retail_saleable_sqm"), n(x,"retail_price_th_per_sqm")*1000,
            n(x,"retail_share_before_rve_pct",85)/100, int(n(x,"retail_months",24)),
            int(n(x,"retail_residual_months",6)), n(x,"retail_growth_pre_pct",1.5)/100,
            n(x,"retail_growth_post_pct",0.25)/100
        )
        retail_capex = n(x,"retail_gba_sqm") * n(x,"retail_cost_th_per_sqm") * 1000

    above_parking_revenue = 0.0
    above_parking_capex = 0.0
    if b(x,"above_parking_enabled"):
        above_parking_revenue = sales_revenue(
            n(x,"above_parking_spaces"), n(x,"above_parking_price_mln_per_space")*1_000_000,
            n(x,"above_parking_share_before_rve_pct",85)/100, int(n(x,"above_parking_months",18)),
            int(n(x,"above_parking_residual_months",6)), n(x,"above_parking_growth_pre_pct",0.75)/100,
            n(x,"above_parking_growth_post_pct",0.2)/100
        )
        above_parking_capex = n(x,"above_parking_spaces") * n(x,"above_parking_cost_mln_per_space") * 1_000_000

    total_revenue = apartment_revenue + commercial_revenue + parking_revenue + storage_revenue + offices_revenue + retail_revenue + above_parking_revenue

    # Core CAPEX. Underground is deliberately separate.
    ird = core_total_gns * n(x,"ird_th_per_sqm") * 1000
    design_p = core_total_gns * n(x,"design_p_th_per_sqm") * 1000
    design_rd = core_total_gns * n(x,"design_rd_th_per_sqm") * 1000
    preparation = core_total_gns * n(x,"preparation_th_per_sqm") * 1000
    main_above = core_above_gns * n(x,"main_above_th_per_sqm") * 1000
    main_under = core_under_gns * n(x,"main_under_th_per_sqm") * 1000
    utilities = core_total_gns * n(x,"utilities_th_per_sqm") * 1000
    landscaping = core_total_gns * n(x,"landscaping_th_per_sqm") * 1000
    commissioning = core_total_gns * n(x,"commissioning_th_per_sqm") * 1000
    site_maintenance = core_total_gns * n(x,"site_maintenance_th_per_sqm") * 1000

    social_construction = (
        n(x,"kindergarten_places")*n(x,"kindergarten_cost_mln_per_place")
        + n(x,"school_places")*n(x,"school_cost_mln_per_place")
        + n(x,"clinic_capacity")*n(x,"clinic_cost_mln_per_unit")
    ) * 1_000_000

    # Important diagnostic found in Excel:
    # Вводные!G99 = Расчет ВРИ!D83 / 1000 although D83 is already labelled in mln RUB.
    excel_social_compensation_mln = social_construction / 1_000_000 / 1000
    normalized_social_compensation = social_construction

    social_cost = social_construction if str(x.get("social_mode","Строительство")) == "Строительство" else normalized_social_compensation

    works_base = main_above + main_under + social_cost + offices_capex + retail_capex + above_parking_capex
    gc_fee = works_base * n(x,"gc_fee_pct")/100

    subtotal = (
        ird + design_p + design_rd + preparation + main_above + main_under +
        utilities + landscaping + commissioning + site_maintenance +
        social_cost + offices_capex + retail_capex + above_parking_capex + gc_fee
    )
    reserve = subtotal * n(x,"reserve_pct")/100
    management = subtotal * n(x,"project_management_pct")/100
    total_capex = subtotal + reserve + management

    purchase = n(x,"purchase_price_mln") * 1_000_000
    marketing = total_revenue * n(x,"marketing_pct")/100
    selling = total_revenue * n(x,"selling_pct")/100
    pre_fin_profit = total_revenue - total_capex - marketing - selling - purchase

    # TEP totals
    tep_rows = []
    for key,row in t.items():
        tep_rows.append({
            "key":key, "label":row.get("label",key),
            "gns":n(row,"gns"), "total_area":n(row,"total_area"), "useful":n(row,"useful"),
            "saleable":n(row,"saleable"), "transfer":n(row,"transfer"), "units":n(row,"units"),
        })
    tep_total = {
        "gns":sum(r["gns"] for r in tep_rows),
        "total_area":sum(r["total_area"] for r in tep_rows),
        "useful":sum(r["useful"] for r in tep_rows),
        "saleable":sum(r["saleable"] for r in tep_rows),
        "transfer":sum(r["transfer"] for r in tep_rows),
        "units":sum(r["units"] for r in tep_rows),
    }

    return {
        "dates":{"project_start":project_start,"permit":permit_date,"sales_start":sales_start,"rve":rve_date,"bridge_repay":bridge_repay},
        "tep":{"rows":tep_rows,"total":tep_total,"core_above_gns":core_above_gns,"core_under_gns":core_under_gns},
        "revenue":{
            "total":total_revenue,"apartments":apartment_revenue,"ground_commercial":commercial_revenue,
            "underground_parking":parking_revenue,"storage":storage_revenue,
            "offices":offices_revenue,"standalone_retail":retail_revenue,"above_parking":above_parking_revenue
        },
        "capex":{
            "total":total_capex,"ird":ird,"design_p":design_p,"design_rd":design_rd,"preparation":preparation,
            "main_above":main_above,"main_under":main_under,"utilities":utilities,"landscaping":landscaping,
            "commissioning":commissioning,"site_maintenance":site_maintenance,"social":social_cost,
            "offices":offices_capex,"standalone_retail":retail_capex,"above_parking":above_parking_capex,
            "gc_fee":gc_fee,"reserve":reserve,"project_management":management
        },
        "commercial_costs":{"marketing":marketing,"selling":selling},
        "summary":{
            "revenue":total_revenue,"capex":total_capex,"purchase":purchase,
            "pre_financing_profit":pre_fin_profit,
            "margin":(pre_fin_profit/total_revenue if total_revenue else 0)
        },
        "diagnostics":{
            "excel_social_compensation_g99_mln":excel_social_compensation_mln,
            "normalized_social_compensation_mln":normalized_social_compensation/1_000_000,
            "social_compensation_warning":"В текущем Excel Вводные!G99 дополнительно делит уже выраженный в млн ₽ Расчет ВРИ!D83 на 1000. В приложении это не повторено.",
            "finance_status":"Поля финансирования и ставка ЦБ уже внесены. Точный алгоритм БРИДЖ → ПФ → эскроу → проценты → LLCR будет подключен следующим блоком."
        }
    }


@app.get("/health")
def health():
    return {"status":"ok","version":"0.3"}


@app.get("/defaults")
def defaults():
    return {"inputs":DEFAULT_INPUTS,"tep":TEP_DEFAULT,"rates":RATE_CURVE,"scenarios":SCENARIOS}


@app.post("/calculate")
def calculate_api(req: CalcRequest):
    return calculate(req)


PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PLATO — Девелоперская модель</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;color:#182230;background:#f4f6f8}
*{box-sizing:border-box}body{margin:0}.wrap{max-width:1450px;margin:auto;padding:20px}
h1{margin:0 0 4px;font-size:27px}.sub{color:#667085;margin-bottom:15px}.top{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.tabs{display:flex;gap:6px;flex-wrap:wrap}.tab,.smallbtn{border:0;border-radius:8px;padding:9px 13px;background:#e4e7ec;color:#344054;font-weight:650;cursor:pointer}.tab.active{background:#182230;color:#fff}
.scenario{margin-left:auto;display:flex;gap:6px;align-items:center}.scenario select{padding:8px;border:1px solid #d0d5dd;border-radius:8px;background:#fff}
.panel{display:none}.panel.active{display:block}.grid{display:grid;grid-template-columns:minmax(370px,520px) 1fr;gap:16px}
.card{background:white;border-radius:13px;padding:16px;box-shadow:0 1px 6px rgba(16,24,40,.07);margin-bottom:14px}
details{border-top:1px solid #eaecf0;padding-top:7px;margin-top:7px}summary{font-weight:750;cursor:pointer;padding:7px 0}
.fields{display:grid;grid-template-columns:1fr 1fr;gap:9px 12px;padding:4px 0 10px}
.field label{display:block;font-size:12px;color:#475467;margin-bottom:4px}.unit{font-size:11px;color:#98a2b3}
input,select{width:100%;padding:8px 9px;border:1px solid #d0d5dd;border-radius:7px;background:#fff;font-size:14px}
input[type=checkbox]{width:auto;transform:scale(1.2);margin:8px}
.primary{width:100%;padding:11px;border:0;border-radius:8px;background:#182230;color:white;font-weight:750;cursor:pointer;margin-top:10px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.kpi{background:#f8fafc;border-radius:9px;padding:12px;font-size:12px;color:#667085}.kpi b{display:block;color:#182230;font-size:19px;margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid #eaecf0;padding:7px;text-align:right}th:first-child,td:first-child{text-align:left}th{position:sticky;top:0;background:#fff;color:#475467}
.teptable input{padding:6px;text-align:right;min-width:85px}.scroll{overflow:auto;max-height:70vh}
.notice{padding:11px;border-radius:8px;background:#fff7e6;color:#93370d;font-size:13px;line-height:1.4;margin-top:12px}
.ok{background:#ecfdf3;color:#067647}.dates{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.datebox{background:#f8fafc;padding:9px;border-radius:8px;font-size:12px}.datebox b{display:block;margin-top:3px;color:#182230}
.rate input{min-width:75px}.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
@media(max-width:950px){.grid{grid-template-columns:1fr}.fields{grid-template-columns:1fr}.kpis{grid-template-columns:1fr 1fr}.dates{grid-template-columns:1fr 1fr}.scenario{margin-left:0}}
</style>
</head>
<body><div class="wrap">
<h1>PLATO — Девелоперская модель</h1>
<div class="sub">v0.3 — весь блок «Вводные» и ТЭП перенесены в веб-интерфейс</div>

<div class="top">
<div class="tabs">
<button class="tab active" onclick="tab('inputs',this)">Вводные</button>
<button class="tab" onclick="tab('tep',this)">ТЭП</button>
<button class="tab" onclick="tab('rates',this)">Ключевая ставка</button>
<button class="tab" onclick="tab('report',this)">Отчёт</button>
</div>
<div class="scenario">Сценарий:
<select id="scenarioSelect" onchange="applyScenario(this.value)">
<option value="conservative">Консервативный</option>
<option value="base" selected>Базовый</option>
<option value="optimistic">Оптимистичный</option>
</select>
<button class="smallbtn" onclick="saveLocal()">Сохранить</button>
<button class="smallbtn" onclick="resetAll()">Сбросить</button>
</div></div>

<div id="inputs" class="panel active"><div class="grid">
<div>
<div class="card"><b>Параметры проекта</b><div id="inputGroups"></div>
<button class="primary" onclick="calculateAndShow()">Пересчитать проект</button></div>
</div>
<div>
<div class="card"><h3 style="margin-top:0">Контроль расчётных дат</h3><div class="dates" id="dateBoxes"></div>
<div class="notice ok">Поля финансирования уже внесены как вводные. Сам кредитный алгоритм пока не подключён к итоговой экономике — это следующий расчётный модуль.</div></div>
<div class="card"><h3 style="margin-top:0">Быстрый результат</h3><div class="kpis" id="quickKpi"></div></div>
</div></div></div>

<div id="tep" class="panel"><div class="card">
<div class="toolbar"><button class="smallbtn" onclick="syncTep()">Обновить производные ТЭП из вводных</button><span style="color:#667085;font-size:13px;padding-top:8px">Квартиры и коммерция 1 этажа остаются редактируемыми напрямую.</span></div>
<div class="scroll"><table class="teptable"><thead><tr>
<th>Продукт</th><th>ГНС, м²</th><th>Общая площадь, м²</th><th>Полезная, м²</th><th>Продаваемая, м²</th><th>Передаваемая, м²</th><th>Шт.</th>
</tr></thead><tbody id="tepBody"></tbody><tfoot><tr><th>ИТОГО</th><th id="tg"></th><th id="ta"></th><th id="tu"></th><th id="ts"></th><th id="tt"></th><th id="tn"></th></tr></tfoot></table></div>
<button class="primary" onclick="calculateAndShow()">Пересчитать с этим ТЭП</button>
</div></div>

<div id="rates" class="panel"><div class="card">
<div style="display:flex;gap:10px;align-items:center;margin-bottom:10px"><b>Прогноз ключевой ставки</b>
<select id="rateScenario"><option value="high">Высокая</option><option value="base">Базовая</option><option value="low" selected>Низкая</option></select></div>
<div class="scroll"><table class="rate"><thead><tr><th>Дата</th><th>Высокая, %</th><th>Базовая, %</th><th>Низкая, %</th></tr></thead><tbody id="rateBody"></tbody></table></div>
<div class="notice">Кривая перенесена полностью из `Вводные` (22 точки). Пока она хранится и редактируется, но в процентные расходы ПФ будет включена после переноса кредитного блока.</div>
</div></div>

<div id="report" class="panel">
<div class="card"><div class="kpis" id="reportKpi"></div></div>
<div class="grid">
<div class="card"><h3>Выручка по продуктам</h3><table><tbody id="revenueTable"></tbody></table></div>
<div class="card"><h3>Себестоимость / CAPEX</h3><table><tbody id="capexTable"></tbody></table></div>
</div>
<div class="card"><h3>ТЭП</h3><table><tbody id="reportTep"></tbody></table>
<div id="diagnostic"></div></div>
</div>
</div>

<script>
const SCENARIOS={"conservative": {"purchase_price_mln": 0, "construction_months": 27, "apartment_price_th": 300, "commercial_price_th": 250, "parking_price_th": 1000, "storage_price_th": 900, "share_before_rve_pct": 80, "pace_adjustment_pct": 20, "inflation_after_rve_pct": 2, "seasonal_reduction_pct": -20, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 1.1, "design_p_th_per_sqm": 2.75, "design_rd_th_per_sqm": 2.75, "preparation_th_per_sqm": 1.2, "main_above_th_per_sqm": 115, "utilities_th_per_sqm": 8.5, "landscaping_th_per_sqm": 5.5, "commissioning_th_per_sqm": 1.1, "site_maintenance_th_per_sqm": 1.2, "gc_fee_pct": 8, "reserve_pct": 7, "project_management_pct": 6, "marketing_pct": 4, "selling_pct": 5, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 7, "bridge_cap_spread_pp": 7, "pf_spread_pp": 5.5, "pf_special_pct": 5, "limit_fee_pct": 0.75, "reservation_fee_pct": 0.75, "discount_rate_pct": 25, "monthly_growth_pre_pct": 1, "monthly_growth_post_pct": 0.2, "ird_months": 24, "sales_lag_months": 1, "bridge_repay_lag_months": 0, "residual_sales_months": 12, "social_comp_date": "2028-12-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-12-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-12-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-12-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 250, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 450, "offices_share_before_rve_pct": 80, "offices_residual_months": 12, "offices_growth_pre_pct": 1, "offices_growth_post_pct": 0.2, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 450, "retail_share_before_rve_pct": 80, "retail_residual_months": 12, "retail_growth_pre_pct": 1, "retail_growth_post_pct": 0.2, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 1.5, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 1.8, "above_parking_share_before_rve_pct": 80, "above_parking_residual_months": 12, "above_parking_growth_pre_pct": 0.5, "above_parking_growth_post_pct": 0.1, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0}, "base": {"purchase_price_mln": 0, "construction_months": 24, "apartment_price_th": 375, "commercial_price_th": 300, "parking_price_th": 1500, "storage_price_th": 1000, "share_before_rve_pct": 85, "pace_adjustment_pct": 25, "inflation_after_rve_pct": 3, "seasonal_reduction_pct": -15, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 1, "design_p_th_per_sqm": 2.5, "design_rd_th_per_sqm": 2.5, "preparation_th_per_sqm": 1, "main_above_th_per_sqm": 110, "utilities_th_per_sqm": 7.5, "landscaping_th_per_sqm": 5, "commissioning_th_per_sqm": 1, "site_maintenance_th_per_sqm": 1, "gc_fee_pct": 7, "reserve_pct": 5, "project_management_pct": 5, "marketing_pct": 3, "selling_pct": 4, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 6, "bridge_cap_spread_pp": 6, "pf_spread_pp": 4.5, "pf_special_pct": 4.5, "limit_fee_pct": 0.5, "reservation_fee_pct": 0.5, "discount_rate_pct": 20, "monthly_growth_pre_pct": 1.5, "monthly_growth_post_pct": 0.25, "ird_months": 18, "sales_lag_months": 0, "bridge_repay_lag_months": 0, "residual_sales_months": 6, "social_comp_date": "2028-06-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-06-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-06-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-06-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 200, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 500, "offices_share_before_rve_pct": 85, "offices_residual_months": 6, "offices_growth_pre_pct": 1.5, "offices_growth_post_pct": 0.25, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 500, "retail_share_before_rve_pct": 85, "retail_residual_months": 6, "retail_growth_pre_pct": 1.5, "retail_growth_post_pct": 0.25, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 1, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 2, "above_parking_share_before_rve_pct": 85, "above_parking_residual_months": 6, "above_parking_growth_pre_pct": 0.75, "above_parking_growth_post_pct": 0.2, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0}, "optimistic": {"purchase_price_mln": 0, "construction_months": 22, "apartment_price_th": 400, "commercial_price_th": 325, "parking_price_th": 1750, "storage_price_th": 1100, "share_before_rve_pct": 90, "pace_adjustment_pct": 30, "inflation_after_rve_pct": 4, "seasonal_reduction_pct": -10, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 0.95, "design_p_th_per_sqm": 2.35, "design_rd_th_per_sqm": 2.35, "preparation_th_per_sqm": 0.9, "main_above_th_per_sqm": 100, "utilities_th_per_sqm": 7, "landscaping_th_per_sqm": 4.5, "commissioning_th_per_sqm": 0.9, "site_maintenance_th_per_sqm": 0.9, "gc_fee_pct": 5, "reserve_pct": 3, "project_management_pct": 4, "marketing_pct": 2, "selling_pct": 3, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 5, "bridge_cap_spread_pp": 5, "pf_spread_pp": 3.5, "pf_special_pct": 4, "limit_fee_pct": 0.35, "reservation_fee_pct": 0.35, "discount_rate_pct": 18, "monthly_growth_pre_pct": 2, "monthly_growth_post_pct": 0.3, "ird_months": 14, "sales_lag_months": 0, "bridge_repay_lag_months": 0, "residual_sales_months": 3, "social_comp_date": "2028-02-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-02-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-02-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-02-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 175, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 550, "offices_share_before_rve_pct": 90, "offices_residual_months": 3, "offices_growth_pre_pct": 2, "offices_growth_post_pct": 0.3, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 550, "retail_share_before_rve_pct": 90, "retail_residual_months": 3, "retail_growth_pre_pct": 2, "retail_growth_post_pct": 0.3, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 0.8, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 2.5, "above_parking_share_before_rve_pct": 90, "above_parking_residual_months": 3, "above_parking_growth_pre_pct": 1, "above_parking_growth_post_pct": 0.25, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0}};
const RATE_DEFAULT=[{"date": "2027-01-01", "high": 15.0, "base": 13.0, "low": 11.0}, {"date": "2027-07-01", "high": 14.5, "base": 12.5, "low": 10.5}, {"date": "2028-01-01", "high": 13.5, "base": 11.5, "low": 9.5}, {"date": "2028-02-01", "high": 14.5, "base": 11.5, "low": 10.5}, {"date": "2028-03-01", "high": 14.25, "base": 11.25, "low": 10.25}, {"date": "2028-04-01", "high": 14.0, "base": 11.0, "low": 10.0}, {"date": "2028-05-01", "high": 13.75, "base": 11.0, "low": 9.75}, {"date": "2028-06-01", "high": 13.5, "base": 11.0, "low": 9.5}, {"date": "2028-07-01", "high": 13.25, "base": 11.0, "low": 9.25}, {"date": "2028-08-01", "high": 13.0, "base": 11.0, "low": 9.0}, {"date": "2028-09-01", "high": 12.75, "base": 10.75, "low": 8.75}, {"date": "2028-10-01", "high": 12.5, "base": 10.5, "low": 8.5}, {"date": "2028-11-01", "high": 12.25, "base": 10.25, "low": 8.25}, {"date": "2028-12-01", "high": 12.0, "base": 10.0, "low": 8.0}, {"date": "2029-01-01", "high": 11.75, "base": 9.75, "low": 7.75}, {"date": "2029-02-01", "high": 11.5, "base": 9.5, "low": 7.5}, {"date": "2029-03-01", "high": 11.25, "base": 9.25, "low": 7.25}, {"date": "2029-04-01", "high": 11.0, "base": 9.0, "low": 7.0}, {"date": "2029-05-01", "high": 10.75, "base": 8.75, "low": 6.75}, {"date": "2029-06-01", "high": 10.5, "base": 8.5, "low": 6.5}, {"date": "2029-07-01", "high": 10.25, "base": 8.25, "low": 6.25}, {"date": "2029-08-01", "high": 10.0, "base": 8.0, "low": 6.0}];
const TEP_DEFAULT={"apartments": {"label": "Квартиры", "gns": 130716.66012842482, "total_area": 117647.0588235294, "useful": 80000, "saleable": 80000, "transfer": 0, "units": 1361.815754339119}, "ground_commercial": {"label": "Коммерция 1 эт.", "gns": 9664.049734985854, "total_area": 8695.652173913044, "useful": 7826.08695652174, "saleable": 7826.08695652174, "transfer": 0, "units": 0}, "standalone_retail": {"label": "Коммерция ОСЗ", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "offices": {"label": "Офисы", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "above_parking": {"label": "Наземный паркинг", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "underground_parking": {"label": "Подземный паркинг", "gns": 38763, "total_area": 38763, "useful": 0, "saleable": 0, "transfer": 0, "units": 1107.5142857142857}, "storage": {"label": "Кладовки", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "kindergarten": {"label": "ДОУ", "gns": 0, "total_area": 3000, "useful": 0, "saleable": 0, "transfer": 3000, "units": 250}, "school": {"label": "СОШ", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "clinic": {"label": "Поликлиника", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}};
const FIELD_GROUPS=[["Сделка и сроки", [["purchase_price_mln", "Стоимость покупки / цена входа", "млн ₽", "number"], ["project_start", "Начало проекта", "дата", "date"], ["ird_months", "Срок ИРД до РнС", "мес.", "number"], ["construction_months", "Срок строительства", "мес.", "number"], ["sales_lag_months", "Лаг старта продаж после РнС", "мес.", "number"], ["bridge_repay_lag_months", "Лаг погашения БРИДЖ после РнС", "мес.", "number"], ["residual_sales_months", "Остаточные продажи после РВЭ", "мес.", "number"]]], ["Продажи", [["apartment_price_th", "Стартовая цена квартир", "тыс. ₽/м²", "number"], ["commercial_price_th", "Стартовая цена коммерции 1 этажа", "тыс. ₽/м²", "number"], ["parking_price_th", "Цена подземного машино-места", "тыс. ₽/шт.", "number"], ["storage_price_th", "Цена кладовой", "тыс. ₽/шт.", "number"], ["share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["pace_adjustment_pct", "Корректировка темпа", "%", "number"], ["inflation_after_rve_pct", "Инфляция после РВЭ", "% год", "number"], ["seasonal_reduction_pct", "Сезонное снижение темпа", "%", "number"], ["growth_stage1_pct", "Рост цены — этап 1", "%", "number"], ["growth_stage2_pct", "Рост цены — этап 2", "%", "number"], ["growth_stage3_pct", "Рост цены — этап 3", "%", "number"], ["growth_stage4_pct", "Рост цены — этап 4", "%", "number"], ["monthly_growth_pre_pct", "Ежемесячный рост цены до РВЭ", "%/мес.", "number"], ["monthly_growth_post_pct", "Ежемесячный рост цены после РВЭ", "%/мес.", "number"]]], ["Строительство", [["ird_th_per_sqm", "ИРД и согласования", "тыс. ₽/м² ГНС", "number"], ["design_p_th_per_sqm", "Проектирование стадии П", "тыс. ₽/м² ГНС", "number"], ["design_rd_th_per_sqm", "Проектирование стадии РД", "тыс. ₽/м² ГНС", "number"], ["preparation_th_per_sqm", "Подготовительные работы", "тыс. ₽/м² ГНС", "number"], ["main_above_th_per_sqm", "Основное строительство — наземная часть", "тыс. ₽/м² ГНС", "number"], ["main_under_th_per_sqm", "Основное строительство — подземная часть", "тыс. ₽/м² ГНС", "number"], ["utilities_th_per_sqm", "Наружные инженерные сети", "тыс. ₽/м² ГНС", "number"], ["landscaping_th_per_sqm", "Благоустройство", "тыс. ₽/м² ГНС", "number"], ["commissioning_th_per_sqm", "Сдача и ввод", "тыс. ₽/м² ГНС", "number"], ["site_maintenance_th_per_sqm", "Содержание стройплощадки", "тыс. ₽/м² ГНС", "number"], ["gc_fee_pct", "Вознаграждение генподрядчика", "% СМР", "number"], ["reserve_pct", "Резерв", "%", "number"], ["project_management_pct", "Управление проектом", "%", "number"]]], ["Коммерческие расходы и налоги", [["marketing_pct", "Маркетинг", "% выручки", "number"], ["selling_pct", "Расходы на продажи", "% выручки", "number"], ["profit_tax_pct", "Налог на прибыль", "%", "number"], ["vat_pct", "НДС", "%", "number"]]], ["Финансирование", [["bridge_spread_pp", "Спред БРИДЖ", "п.п.", "number"], ["bridge_cap_spread_pp", "Спред капитализации БРИДЖ", "п.п.", "number"], ["pf_spread_pp", "Спред ПФ", "п.п.", "number"], ["pf_special_pct", "Специальная ставка ПФ", "%", "number"], ["limit_fee_pct", "Плата за лимит", "%", "number"], ["reservation_fee_pct", "Плата за резервирование", "%", "number"], ["discount_rate_pct", "Ставка дисконтирования", "%", "number"]]], ["Социальная нагрузка", [["social_mode", "Форма исполнения", "режим", "select"], ["social_comp_date", "Дата денежной компенсации", "дата", "date"], ["kindergarten_places", "ДОУ — количество мест", "мест", "number"], ["kindergarten_cost_mln_per_place", "ДОУ — себестоимость места", "млн ₽/место", "number"], ["kindergarten_start", "ДОУ — начало строительства", "дата", "date"], ["kindergarten_months", "ДОУ — срок строительства", "мес.", "number"], ["school_places", "СОШ — количество мест", "мест", "number"], ["school_cost_mln_per_place", "СОШ — себестоимость места", "млн ₽/место", "number"], ["school_start", "СОШ — начало строительства", "дата", "date"], ["school_months", "СОШ — срок строительства", "мес.", "number"], ["clinic_capacity", "Поликлиника — мощность", "пос./смену", "number"], ["clinic_cost_mln_per_unit", "Поликлиника — себестоимость мощности", "млн ₽/(пос./смену)", "number"], ["clinic_start", "Поликлиника — начало строительства", "дата", "date"], ["clinic_months", "Поликлиника — срок строительства", "мес.", "number"], ["social_dou_gba_sqm", "ДОУ — общая площадь", "м²", "number"], ["social_dou_norm_sqm", "ДОУ — норматив площади на место", "м²/место", "number"], ["social_school_gba_sqm", "СОШ — общая площадь", "м²", "number"], ["social_school_norm_sqm", "СОШ — норматив площади на место", "м²/место", "number"], ["social_clinic_gba_sqm", "Поликлиника — общая площадь", "м²", "number"], ["social_clinic_norm_sqm", "Поликлиника — норматив площади", "м²/ед.", "number"]]], ["МФОЦ / офисы", [["offices_enabled", "Объект включен", "Да / Нет", "checkbox"], ["offices_gba_sqm", "Общая площадь (GBA)", "м²", "number"], ["offices_saleable_sqm", "Продаваемая площадь", "м²", "number"], ["offices_start", "Начало строительства", "дата", "date"], ["offices_months", "Срок строительства", "мес.", "number"], ["offices_cost_th_per_sqm", "Себестоимость строительства", "тыс. ₽/м² GBA", "number"], ["offices_sales_start", "Старт продаж", "дата", "date"], ["offices_price_th_per_sqm", "Стартовая цена", "тыс. ₽/м²", "number"], ["offices_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["offices_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["offices_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["offices_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"]]], ["ТЦ / коммерция ОСЗ", [["retail_enabled", "Объект включен", "Да / Нет", "checkbox"], ["retail_gba_sqm", "Общая площадь (GBA)", "м²", "number"], ["retail_saleable_sqm", "Продаваемая площадь", "м²", "number"], ["retail_start", "Начало строительства", "дата", "date"], ["retail_months", "Срок строительства", "мес.", "number"], ["retail_cost_th_per_sqm", "Себестоимость строительства", "тыс. ₽/м² GBA", "number"], ["retail_sales_start", "Старт продаж", "дата", "date"], ["retail_price_th_per_sqm", "Стартовая цена", "тыс. ₽/м²", "number"], ["retail_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["retail_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["retail_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["retail_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"]]], ["Наземный паркинг", [["above_parking_enabled", "Объект включен", "Да / Нет", "checkbox"], ["above_parking_spaces", "Количество машино-мест", "шт.", "number"], ["above_parking_cost_mln_per_space", "Себестоимость одного места", "млн ₽/место", "number"], ["above_parking_start", "Начало строительства", "дата", "date"], ["above_parking_months", "Срок строительства", "мес.", "number"], ["above_parking_sales_start", "Старт продаж", "дата", "date"], ["above_parking_price_mln_per_space", "Стартовая цена места", "млн ₽/место", "number"], ["above_parking_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["above_parking_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["above_parking_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["above_parking_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"], ["above_parking_area_per_space_sqm", "Площадь на 1 место для ТЭП", "м²/место", "number"]]]];
const INPUT_DEFAULT={"purchase_price_mln": 0, "construction_months": 24, "apartment_price_th": 375, "commercial_price_th": 300, "parking_price_th": 1500, "storage_price_th": 1000, "share_before_rve_pct": 85, "pace_adjustment_pct": 25, "inflation_after_rve_pct": 3, "seasonal_reduction_pct": -15, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 1, "design_p_th_per_sqm": 2.5, "design_rd_th_per_sqm": 2.5, "preparation_th_per_sqm": 1, "main_above_th_per_sqm": 110, "utilities_th_per_sqm": 7.5, "landscaping_th_per_sqm": 5, "commissioning_th_per_sqm": 1, "site_maintenance_th_per_sqm": 1, "gc_fee_pct": 7, "reserve_pct": 5, "project_management_pct": 5, "marketing_pct": 3, "selling_pct": 4, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 6, "bridge_cap_spread_pp": 6, "pf_spread_pp": 4.5, "pf_special_pct": 4.5, "limit_fee_pct": 0.5, "reservation_fee_pct": 0.5, "discount_rate_pct": 20, "monthly_growth_pre_pct": 1.5, "monthly_growth_post_pct": 0.25, "ird_months": 18, "sales_lag_months": 0, "bridge_repay_lag_months": 0, "residual_sales_months": 6, "social_comp_date": "2028-06-01", "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-06-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-06-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-06-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 200, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 500, "offices_share_before_rve_pct": 85, "offices_residual_months": 6, "offices_growth_pre_pct": 1.5, "offices_growth_post_pct": 0.25, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 500, "retail_share_before_rve_pct": 85, "retail_residual_months": 6, "retail_growth_pre_pct": 1.5, "retail_growth_post_pct": 0.25, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 1, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 2, "above_parking_share_before_rve_pct": 85, "above_parking_residual_months": 6, "above_parking_growth_pre_pct": 0.75, "above_parking_growth_post_pct": 0.2, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0, "project_start": "2027-01-01", "main_under_th_per_sqm": 110, "social_mode": "Строительство", "social_dou_norm_sqm": 12, "social_school_norm_sqm": 13, "social_clinic_norm_sqm": 15, "offices_enabled": false, "retail_enabled": false, "above_parking_enabled": false, "above_parking_area_per_space_sqm": 25, "rate_scenario": "low"};

let inputs=JSON.parse(JSON.stringify(INPUT_DEFAULT));
let tep=JSON.parse(JSON.stringify(TEP_DEFAULT));
let rates=JSON.parse(JSON.stringify(RATE_DEFAULT));
let lastResult=null;

const fmt=v=>(Number(v||0)/1e9).toLocaleString('ru-RU',{maximumFractionDigits:2})+' млрд ₽';
const num=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:1});
const pct=v=>(Number(v||0)*100).toLocaleString('ru-RU',{maximumFractionDigits:1})+'%';

function tab(id,btn){document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));btn.classList.add('active')}

function renderInputs(){
 const box=document.getElementById('inputGroups');box.innerHTML='';
 FIELD_GROUPS.forEach((grp,idx)=>{
  const d=document.createElement('details'); if(idx<3)d.open=true;
  const s=document.createElement('summary');s.textContent=grp[0];d.appendChild(s);
  const grid=document.createElement('div');grid.className='fields';
  grp[1].forEach(f=>{
   const [id,label,unit,type]=f; const wrap=document.createElement('div');wrap.className='field';
   const l=document.createElement('label');l.innerHTML=label+' <span class="unit">'+unit+'</span>';wrap.appendChild(l);
   let el;
   if(type==='select'){el=document.createElement('select');['Строительство','Денежная компенсация'].forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o)})}
   else {el=document.createElement('input');el.type=type==='checkbox'?'checkbox':type; if(type==='number')el.step='any'}
   el.id='f_'+id;
   if(type==='checkbox')el.checked=!!inputs[id]; else el.value=inputs[id]??'';
   el.onchange=()=>{inputs[id]=type==='checkbox'?el.checked:(type==='number'?Number(el.value):el.value); if(['offices_enabled','retail_enabled','above_parking_enabled','social_mode','kindergarten_places','school_places','clinic_capacity','social_dou_gba_sqm','social_school_gba_sqm','social_clinic_gba_sqm','above_parking_spaces','above_parking_area_per_space_sqm'].includes(id))syncTep(false)};
   wrap.appendChild(el);grid.appendChild(wrap);
  });d.appendChild(grid);box.appendChild(d);
 });
}

function applyScenario(name){
 const keep={project_start:inputs.project_start,main_under_th_per_sqm:inputs.main_under_th_per_sqm,social_mode:inputs.social_mode,
 offices_enabled:inputs.offices_enabled,retail_enabled:inputs.retail_enabled,above_parking_enabled:inputs.above_parking_enabled,
 social_dou_norm_sqm:inputs.social_dou_norm_sqm,social_school_norm_sqm:inputs.social_school_norm_sqm,social_clinic_norm_sqm:inputs.social_clinic_norm_sqm,
 above_parking_area_per_space_sqm:inputs.above_parking_area_per_space_sqm};
 Object.assign(inputs,SCENARIOS[name],keep);renderInputs();syncTep(false);calculate();
}

function renderTep(){
 const body=document.getElementById('tepBody');body.innerHTML='';
 Object.entries(tep).forEach(([key,row])=>{
  const tr=document.createElement('tr');let html=`<td>${row.label}</td>`;
  ['gns','total_area','useful','saleable','transfer','units'].forEach(col=>{html+=`<td><input type="number" step="any" value="${row[col]||0}" onchange="tep['${key}']['${col}']=Number(this.value);updateTepTotals()"></td>`});
  tr.innerHTML=html;body.appendChild(tr);
 });updateTepTotals();
}
function updateTepTotals(){
 const sums={gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0};
 Object.values(tep).forEach(r=>Object.keys(sums).forEach(k=>sums[k]+=Number(r[k]||0)));
 tg.textContent=num(sums.gns);ta.textContent=num(sums.total_area);tu.textContent=num(sums.useful);ts.textContent=num(sums.saleable);tt.textContent=num(sums.transfer);tn.textContent=num(sums.units);
}

function syncTep(rerender=true){
 const socialBuild=inputs.social_mode==='Строительство';
 tep.underground_parking.gns=Number(tep.underground_parking.units||0)*35;
 tep.underground_parking.total_area=tep.underground_parking.gns;
 tep.offices.gns=inputs.offices_enabled?Number(inputs.offices_gba_sqm||0):0;tep.offices.total_area=tep.offices.gns;tep.offices.saleable=inputs.offices_enabled?Number(inputs.offices_saleable_sqm||0):0;tep.offices.useful=tep.offices.saleable;
 tep.standalone_retail.gns=inputs.retail_enabled?Number(inputs.retail_gba_sqm||0):0;tep.standalone_retail.total_area=tep.standalone_retail.gns;tep.standalone_retail.saleable=inputs.retail_enabled?Number(inputs.retail_saleable_sqm||0):0;tep.standalone_retail.useful=tep.standalone_retail.saleable;
 tep.above_parking.units=inputs.above_parking_enabled?Number(inputs.above_parking_spaces||0):0;tep.above_parking.gns=tep.above_parking.units*Number(inputs.above_parking_area_per_space_sqm||25);tep.above_parking.total_area=tep.above_parking.gns;
 tep.kindergarten.total_area=socialBuild?Number(inputs.social_dou_gba_sqm||0):0;tep.kindergarten.transfer=tep.kindergarten.total_area;tep.kindergarten.units=socialBuild?Number(inputs.kindergarten_places||0):0;
 tep.school.total_area=socialBuild?Number(inputs.social_school_gba_sqm||0):0;tep.school.transfer=tep.school.total_area;tep.school.units=socialBuild?Number(inputs.school_places||0):0;
 tep.clinic.total_area=socialBuild?Number(inputs.social_clinic_gba_sqm||0):0;tep.clinic.transfer=tep.clinic.total_area;tep.clinic.units=socialBuild?Number(inputs.clinic_capacity||0):0;
 if(rerender)renderTep(); else updateTepTotals();
}

function renderRates(){rateBody.innerHTML='';rates.forEach((r,i)=>{const tr=document.createElement('tr');tr.innerHTML=`<td><input type="date" value="${r.date}" onchange="rates[${i}].date=this.value"></td><td><input type="number" step="0.01" value="${r.high}" onchange="rates[${i}].high=Number(this.value)"></td><td><input type="number" step="0.01" value="${r.base}" onchange="rates[${i}].base=Number(this.value)"></td><td><input type="number" step="0.01" value="${r.low}" onchange="rates[${i}].low=Number(this.value)"></td>`;rateBody.appendChild(tr)})}

async function calculate(){
 // pull current controls first
 document.querySelectorAll('[id^=f_]').forEach(el=>{const id=el.id.slice(2);inputs[id]=el.type==='checkbox'?el.checked:(el.type==='number'?Number(el.value):el.value)});
 const resp=await fetch('/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inputs,tep,rates})});
 lastResult=await resp.json();renderResult();return lastResult;
}
async function calculateAndShow(){await calculate();document.querySelectorAll('.tab')[3].click()}

function renderResult(){
 if(!lastResult)return;const r=lastResult;
 dateBoxes.innerHTML=[
 ['Начало',r.dates.project_start],['РнС',r.dates.permit],['Старт продаж',r.dates.sales_start],['РВЭ',r.dates.rve],['Погашение БРИДЖ',r.dates.bridge_repay]
 ].map(x=>`<div class="datebox">${x[0]}<b>${x[1]}</b></div>`).join('');
 const k=[['Выручка',fmt(r.summary.revenue)],['CAPEX',fmt(r.summary.capex)],['До финансирования',fmt(r.summary.pre_financing_profit)],['Маржа',pct(r.summary.margin)]];
 quickKpi.innerHTML=reportKpi.innerHTML=k.map(x=>`<div class="kpi">${x[0]}<b>${x[1]}</b></div>`).join('');
 const revNames={apartments:'Квартиры',ground_commercial:'Коммерция 1 эт.',underground_parking:'Подземный паркинг',storage:'Кладовки',offices:'Офисы',standalone_retail:'Коммерция ОСЗ',above_parking:'Наземный паркинг'};
 revenueTable.innerHTML=Object.entries(r.revenue).filter(([k])=>k!=='total').map(([k,v])=>`<tr><td>${revNames[k]||k}</td><td>${fmt(v)}</td></tr>`).join('')+`<tr><th>ИТОГО</th><th>${fmt(r.revenue.total)}</th></tr>`;
 const capNames={ird:'ИРД',design_p:'Проект П',design_rd:'Проект РД',preparation:'Подготовительные работы',main_above:'Основное строительство — наземная часть',main_under:'Основное строительство — подземная часть',utilities:'Наружные сети',landscaping:'Благоустройство',commissioning:'Сдача и ввод',site_maintenance:'Содержание стройплощадки',social:'Социальная нагрузка',offices:'Офисы',standalone_retail:'Коммерция ОСЗ',above_parking:'Наземный паркинг',gc_fee:'Генподрядчик',reserve:'Резерв',project_management:'Управление проектом'};
 capexTable.innerHTML=Object.entries(r.capex).filter(([k])=>k!=='total').map(([k,v])=>`<tr><td>${capNames[k]||k}</td><td>${fmt(v)}</td></tr>`).join('')+`<tr><th>ИТОГО</th><th>${fmt(r.capex.total)}</th></tr>`;
 reportTep.innerHTML=r.tep.rows.map(x=>`<tr><td>${x.label}</td><td>ГНС ${num(x.gns)} м²</td><td>прод. ${num(x.saleable)} м²</td><td>${num(x.units)} шт.</td></tr>`).join('')+`<tr><th>ИТОГО</th><th>${num(r.tep.total.gns)} м²</th><th>${num(r.tep.total.saleable)} м²</th><th>${num(r.tep.total.units)} шт.</th></tr>`;
 diagnostic.innerHTML=`<div class="notice"><b>Контроль соцнагрузки:</b> ${r.diagnostics.social_compensation_warning}<br>Расчёт ВРИ: ${r.diagnostics.normalized_social_compensation_mln.toLocaleString('ru-RU')} млн ₽; текущее Excel G99: ${r.diagnostics.excel_social_compensation_g99_mln.toLocaleString('ru-RU')} млн ₽.<br><br>${r.diagnostics.finance_status}</div>`;
}

function saveLocal(){localStorage.setItem('plato_inputs_v03',JSON.stringify({inputs,tep,rates,scenario:scenarioSelect.value}));alert('Сохранено в этом браузере')}
function loadLocal(){try{const x=JSON.parse(localStorage.getItem('plato_inputs_v03'));if(x){inputs=x.inputs||inputs;tep=x.tep||tep;rates=x.rates||rates;scenarioSelect.value=x.scenario||'base'}}catch(e){}}
function resetAll(){localStorage.removeItem('plato_inputs_v03');inputs=JSON.parse(JSON.stringify(INPUT_DEFAULT));tep=JSON.parse(JSON.stringify(TEP_DEFAULT));rates=JSON.parse(JSON.stringify(RATE_DEFAULT));scenarioSelect.value='base';renderInputs();renderTep();renderRates();calculate()}

loadLocal();renderInputs();renderTep();renderRates();calculate();
</script></body></html>"""


@app.get("/",response_class=HTMLResponse)
def index():
    return PAGE
