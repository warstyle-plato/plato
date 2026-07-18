
from __future__ import annotations

import calendar
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from math import ceil, pow
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="PLATO Development Investment Model", version="0.6.5")

SCENARIOS = {
    'conservative': {'scenario_revenue_multiplier': 0.90, 'scenario_cost_multiplier': 1.10},
    'base': {'scenario_revenue_multiplier': 1.00, 'scenario_cost_multiplier': 1.00},
    'optimistic': {'scenario_revenue_multiplier': 1.10, 'scenario_cost_multiplier': 0.90},
}

PROJECT_CLASS_PRESETS = {
    "comfort": {
        "label": "Комфорт",
        "apartment_price_th": 350,
        "commercial_price_th": 350,
        "parking_price_th": 1500,
        "main_above_th_per_sqm": 110,
        "main_under_th_per_sqm": 110,
    },
    "business": {
        "label": "Бизнес",
        "apartment_price_th": 650,
        "commercial_price_th": 650,
        "parking_price_th": 5000,
        "main_above_th_per_sqm": 190,
        "main_under_th_per_sqm": 190,
    },
    "elite": {
        "label": "Элитный",
        "apartment_price_th": 1500,
        "commercial_price_th": 1500,
        "parking_price_th": 20000,
        "main_above_th_per_sqm": 300,
        "main_under_th_per_sqm": 300,
    },
}
RATE_CURVE = [{'date': '2027-01-01', 'high': 15.0, 'base': 13.0, 'low': 11.0}, {'date': '2027-07-01', 'high': 14.5, 'base': 12.5, 'low': 10.5}, {'date': '2028-01-01', 'high': 13.5, 'base': 11.5, 'low': 9.5}, {'date': '2028-02-01', 'high': 14.5, 'base': 11.5, 'low': 10.5}, {'date': '2028-03-01', 'high': 14.25, 'base': 11.25, 'low': 10.25}, {'date': '2028-04-01', 'high': 14.0, 'base': 11.0, 'low': 10.0}, {'date': '2028-05-01', 'high': 13.75, 'base': 11.0, 'low': 9.75}, {'date': '2028-06-01', 'high': 13.5, 'base': 11.0, 'low': 9.5}, {'date': '2028-07-01', 'high': 13.25, 'base': 11.0, 'low': 9.25}, {'date': '2028-08-01', 'high': 13.0, 'base': 11.0, 'low': 9.0}, {'date': '2028-09-01', 'high': 12.75, 'base': 10.75, 'low': 8.75}, {'date': '2028-10-01', 'high': 12.5, 'base': 10.5, 'low': 8.5}, {'date': '2028-11-01', 'high': 12.25, 'base': 10.25, 'low': 8.25}, {'date': '2028-12-01', 'high': 12.0, 'base': 10.0, 'low': 8.0}, {'date': '2029-01-01', 'high': 11.75, 'base': 9.75, 'low': 7.75}, {'date': '2029-02-01', 'high': 11.5, 'base': 9.5, 'low': 7.5}, {'date': '2029-03-01', 'high': 11.25, 'base': 9.25, 'low': 7.25}, {'date': '2029-04-01', 'high': 11.0, 'base': 9.0, 'low': 7.0}, {'date': '2029-05-01', 'high': 10.75, 'base': 8.75, 'low': 6.75}, {'date': '2029-06-01', 'high': 10.5, 'base': 8.5, 'low': 6.5}, {'date': '2029-07-01', 'high': 10.25, 'base': 8.25, 'low': 6.25}, {'date': '2029-08-01', 'high': 10.0, 'base': 8.0, 'low': 6.0}]
TEP_DEFAULT = {'apartments': {'label': 'Квартиры', 'gns': 130716.66012842482, 'total_area': 117647.0588235294, 'useful': 80000, 'saleable': 80000, 'transfer': 0, 'units': 1361.815754339119}, 'ground_commercial': {'label': 'Коммерция 1 эт.', 'gns': 9664.049734985854, 'total_area': 8695.652173913044, 'useful': 7826.08695652174, 'saleable': 7826.08695652174, 'transfer': 0, 'units': 0}, 'standalone_retail': {'label': 'Коммерция ОСЗ', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}, 'offices': {'label': 'Офисы', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}, 'above_parking': {'label': 'Наземный паркинг', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}, 'underground_parking': {'label': 'Подземный паркинг', 'gns': 38763, 'total_area': 38763, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 1107.5142857142857}, 'storage': {'label': 'Кладовки', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}, 'kindergarten': {'label': 'ДОУ', 'gns': 0, 'total_area': 3000, 'useful': 0, 'saleable': 0, 'transfer': 3000, 'units': 250}, 'school': {'label': 'СОШ', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}, 'clinic': {'label': 'Поликлиника', 'gns': 0, 'total_area': 0, 'useful': 0, 'saleable': 0, 'transfer': 0, 'units': 0}}
FIELD_GROUPS = [['Сделка и сроки', [['purchase_price_mln', 'Стоимость покупки / цена входа', 'млн ₽', 'number'], ['land_rights_cost_mln', 'Оформление земельных правоотношений / смена ВРИ', 'млн ₽', 'number'], ['project_start', 'Начало проекта', 'дата', 'date'], ['ird_months', 'Срок ИРД до РнС', 'мес.', 'number'], ['construction_months', 'Срок строительства', 'мес.', 'number'], ['sales_lag_months', 'Лаг старта продаж после РнС', 'мес.', 'number'], ['bridge_repay_lag_months', 'Лаг погашения БРИДЖ после РнС', 'мес.', 'number'], ['residual_sales_months', 'Остаточные продажи после РВЭ', 'мес.', 'number']]], ['Продажи', [['apartment_price_th', 'Стартовая цена квартир', 'тыс. ₽/м²', 'number'], ['commercial_price_th', 'Стартовая цена коммерции 1 этажа', 'тыс. ₽/м²', 'number'], ['parking_price_th', 'Цена подземного машино-места', 'тыс. ₽/шт.', 'number'], ['storage_price_th', 'Цена кладовой', 'тыс. ₽/шт.', 'number'], ['share_before_rve_pct', 'Доля продаж до РВЭ', '%', 'number'], ['pace_adjustment_pct', 'Корректировка темпа', '%', 'number'], ['inflation_after_rve_pct', 'Инфляция после РВЭ', '% год', 'number'], ['seasonal_reduction_pct', 'Сезонное снижение темпа', '%', 'number'], ['growth_stage1_pct', 'Рост цены — этап 1', '%', 'number'], ['growth_stage2_pct', 'Рост цены — этап 2', '%', 'number'], ['growth_stage3_pct', 'Рост цены — этап 3', '%', 'number'], ['growth_stage4_pct', 'Рост цены — этап 4', '%', 'number'], ['monthly_growth_pre_pct', 'Ежемесячный рост цены до РВЭ', '%/мес.', 'number'], ['monthly_growth_post_pct', 'Ежемесячный рост цены после РВЭ', '%/мес.', 'number']]], ['Строительство', [['ird_th_per_sqm', 'ИРД и согласования', 'тыс. ₽/м² ГНС', 'number'], ['design_p_th_per_sqm', 'Проектирование стадии П', 'тыс. ₽/м² ГНС', 'number'], ['design_rd_th_per_sqm', 'Проектирование стадии РД', 'тыс. ₽/м² ГНС', 'number'], ['preparation_th_per_sqm', 'Подготовительные работы', 'тыс. ₽/м² ГНС', 'number'], ['main_above_th_per_sqm', 'Основное строительство — наземная часть', 'тыс. ₽/м² ГНС', 'number'], ['main_under_th_per_sqm', 'Основное строительство — подземная часть', 'тыс. ₽/м² ГНС', 'number'], ['utilities_th_per_sqm', 'Наружные инженерные сети', 'тыс. ₽/м² ГНС', 'number'], ['landscaping_th_per_sqm', 'Благоустройство', 'тыс. ₽/м² ГНС', 'number'], ['commissioning_th_per_sqm', 'Сдача и ввод', 'тыс. ₽/м² ГНС', 'number'], ['site_maintenance_th_per_sqm', 'Содержание стройплощадки', 'тыс. ₽/м² ГНС', 'number'], ['gc_fee_pct', 'Вознаграждение генподрядчика', '% СМР', 'number'], ['reserve_pct', 'Резерв', '%', 'number'], ['project_management_pct', 'Управление проектом', '%', 'number'], ['author_supervision_mln', 'Авторский надзор', 'млн ₽', 'number']]], ['Коммерческие расходы и налоги', [['marketing_pct', 'Маркетинг', '% выручки', 'number'], ['selling_pct', 'Расходы на продажи', '% выручки', 'number'], ['profit_tax_pct', 'Налог на прибыль', '%', 'number'], ['vat_pct', 'НДС', '%', 'number']]], ['Финансирование', [['bridge_spread_pp', 'Спред БРИДЖ', 'п.п.', 'number'], ['bridge_cap_spread_pp', 'Спред капитализации БРИДЖ', 'п.п.', 'number'], ['pf_spread_pp', 'Спред ПФ', 'п.п.', 'number'], ['pf_special_pct', 'Специальная ставка ПФ', '%', 'number'], ['limit_fee_pct', 'Плата за лимит', '%', 'number'], ['reservation_fee_pct', 'Плата за резервирование', '%', 'number'], ['discount_rate_pct', 'Ставка дисконтирования', '%', 'number'], ['bridge_interest_mode', 'Проценты БРИДЖ при рефинансировании', 'режим', 'finance_select'], ['pf_transfer_income_pct', 'Снижение спецставки при покрытии эскроу > 1x', 'п.п. на 1x', 'number']]], ['Социальная нагрузка', [['social_mode', 'Форма исполнения', 'режим', 'select'], ['social_comp_date', 'Дата денежной компенсации', 'дата', 'date'], ['social_compensation_mln', 'Социальный платеж / компенсация по ГлавАПУ', 'млн ₽', 'number'], ['kindergarten_places', 'ДОУ — количество мест', 'мест', 'number'], ['kindergarten_cost_mln_per_place', 'ДОУ — себестоимость места', 'млн ₽/место', 'number'], ['kindergarten_start', 'ДОУ — начало строительства', 'дата', 'date'], ['kindergarten_months', 'ДОУ — срок строительства', 'мес.', 'number'], ['school_places', 'СОШ — количество мест', 'мест', 'number'], ['school_cost_mln_per_place', 'СОШ — себестоимость места', 'млн ₽/место', 'number'], ['school_start', 'СОШ — начало строительства', 'дата', 'date'], ['school_months', 'СОШ — срок строительства', 'мес.', 'number'], ['clinic_capacity', 'Поликлиника — мощность', 'пос./смену', 'number'], ['clinic_cost_mln_per_unit', 'Поликлиника — себестоимость мощности', 'млн ₽/(пос./смену)', 'number'], ['clinic_start', 'Поликлиника — начало строительства', 'дата', 'date'], ['clinic_months', 'Поликлиника — срок строительства', 'мес.', 'number'], ['social_dou_gba_sqm', 'ДОУ — общая площадь', 'м²', 'number'], ['social_dou_norm_sqm', 'ДОУ — норматив площади на место', 'м²/место', 'number'], ['social_school_gba_sqm', 'СОШ — общая площадь', 'м²', 'number'], ['social_school_norm_sqm', 'СОШ — норматив площади на место', 'м²/место', 'number'], ['social_clinic_gba_sqm', 'Поликлиника — общая площадь', 'м²', 'number'], ['social_clinic_norm_sqm', 'Поликлиника — норматив площади', 'м²/ед.', 'number']]], ['МФОЦ / офисы', [['offices_enabled', 'Объект включен', 'Да / Нет', 'checkbox'], ['offices_gba_sqm', 'Общая площадь (GBA)', 'м²', 'number'], ['offices_saleable_sqm', 'Продаваемая площадь', 'м²', 'number'], ['offices_start', 'Начало строительства', 'дата', 'date'], ['offices_months', 'Срок строительства', 'мес.', 'number'], ['offices_cost_th_per_sqm', 'Себестоимость строительства', 'тыс. ₽/м² GBA', 'number'], ['offices_sales_start', 'Старт продаж', 'дата', 'date'], ['offices_price_th_per_sqm', 'Стартовая цена', 'тыс. ₽/м²', 'number'], ['offices_share_before_rve_pct', 'Доля продаж до РВЭ', '%', 'number'], ['offices_residual_months', 'Остаточные продажи после РВЭ', 'мес.', 'number'], ['offices_growth_pre_pct', 'Рост цены до РВЭ', '%/мес.', 'number'], ['offices_growth_post_pct', 'Рост цены после РВЭ', '%/мес.', 'number']]], ['ТЦ / коммерция ОСЗ', [['retail_enabled', 'Объект включен', 'Да / Нет', 'checkbox'], ['retail_gba_sqm', 'Общая площадь (GBA)', 'м²', 'number'], ['retail_saleable_sqm', 'Продаваемая площадь', 'м²', 'number'], ['retail_start', 'Начало строительства', 'дата', 'date'], ['retail_months', 'Срок строительства', 'мес.', 'number'], ['retail_cost_th_per_sqm', 'Себестоимость строительства', 'тыс. ₽/м² GBA', 'number'], ['retail_sales_start', 'Старт продаж', 'дата', 'date'], ['retail_price_th_per_sqm', 'Стартовая цена', 'тыс. ₽/м²', 'number'], ['retail_share_before_rve_pct', 'Доля продаж до РВЭ', '%', 'number'], ['retail_residual_months', 'Остаточные продажи после РВЭ', 'мес.', 'number'], ['retail_growth_pre_pct', 'Рост цены до РВЭ', '%/мес.', 'number'], ['retail_growth_post_pct', 'Рост цены после РВЭ', '%/мес.', 'number']]], ['Наземный паркинг', [['above_parking_enabled', 'Объект включен', 'Да / Нет', 'checkbox'], ['above_parking_spaces', 'Количество машино-мест', 'шт.', 'number'], ['above_parking_cost_mln_per_space', 'Себестоимость одного места', 'млн ₽/место', 'number'], ['above_parking_start', 'Начало строительства', 'дата', 'date'], ['above_parking_months', 'Срок строительства', 'мес.', 'number'], ['above_parking_sales_start', 'Старт продаж', 'дата', 'date'], ['above_parking_price_mln_per_space', 'Стартовая цена места', 'млн ₽/место', 'number'], ['above_parking_share_before_rve_pct', 'Доля продаж до РВЭ', '%', 'number'], ['above_parking_residual_months', 'Остаточные продажи после РВЭ', 'мес.', 'number'], ['above_parking_growth_pre_pct', 'Рост цены до РВЭ', '%/мес.', 'number'], ['above_parking_growth_post_pct', 'Рост цены после РВЭ', '%/мес.', 'number'], ['above_parking_area_per_space_sqm', 'Площадь на 1 место для ТЭП', 'м²/место', 'number']]]]
DEFAULT_INPUTS = {'project_class': 'comfort', 'purchase_price_mln': 0, 'construction_months': 24, 'apartment_price_th': 350, 'commercial_price_th': 350, 'parking_price_th': 1500, 'storage_price_th': 1000, 'share_before_rve_pct': 85, 'pace_adjustment_pct': 25, 'inflation_after_rve_pct': 3, 'seasonal_reduction_pct': -15, 'growth_stage1_pct': 0, 'growth_stage2_pct': 0, 'growth_stage3_pct': 0, 'growth_stage4_pct': 0, 'ird_th_per_sqm': 1, 'design_p_th_per_sqm': 2.5, 'design_rd_th_per_sqm': 2.5, 'preparation_th_per_sqm': 1, 'main_above_th_per_sqm': 110, 'utilities_th_per_sqm': 7.5, 'landscaping_th_per_sqm': 5, 'commissioning_th_per_sqm': 1, 'site_maintenance_th_per_sqm': 1, 'gc_fee_pct': 7, 'reserve_pct': 5, 'project_management_pct': 5, 'marketing_pct': 3, 'selling_pct': 4, 'profit_tax_pct': 25, 'vat_pct': 22, 'bridge_spread_pp': 6, 'bridge_cap_spread_pp': 6, 'pf_spread_pp': 4.5, 'pf_special_pct': 4.5, 'limit_fee_pct': 0.5, 'reservation_fee_pct': 0.5, 'discount_rate_pct': 20, 'monthly_growth_pre_pct': 1.5, 'monthly_growth_post_pct': 0.25, 'ird_months': 18, 'sales_lag_months': 0, 'bridge_repay_lag_months': 0, 'residual_sales_months': 6, 'social_comp_date': '2028-06-01', 'social_compensation_mln': 0, 'kindergarten_places': 250, 'kindergarten_cost_mln_per_place': 2.75, 'kindergarten_start': '2028-06-01', 'kindergarten_months': 24, 'school_places': 0, 'school_cost_mln_per_place': 3, 'school_start': '2028-06-01', 'school_months': 30, 'clinic_capacity': 0, 'clinic_cost_mln_per_unit': 3, 'clinic_start': '2028-06-01', 'clinic_months': 24, 'offices_gba_sqm': 10000, 'offices_saleable_sqm': 6000, 'offices_start': '2028-07-01', 'offices_months': 24, 'offices_cost_th_per_sqm': 200, 'offices_sales_start': '2028-07-01', 'offices_price_th_per_sqm': 500, 'offices_share_before_rve_pct': 85, 'offices_residual_months': 6, 'offices_growth_pre_pct': 1.5, 'offices_growth_post_pct': 0.25, 'retail_gba_sqm': 10000, 'retail_saleable_sqm': 6000, 'retail_start': '2028-07-01', 'retail_months': 24, 'retail_cost_th_per_sqm': 200, 'retail_sales_start': '2028-07-01', 'retail_price_th_per_sqm': 500, 'retail_share_before_rve_pct': 85, 'retail_residual_months': 6, 'retail_growth_pre_pct': 1.5, 'retail_growth_post_pct': 0.25, 'above_parking_spaces': 550, 'above_parking_cost_mln_per_space': 1, 'above_parking_start': '2028-07-01', 'above_parking_months': 18, 'above_parking_sales_start': '2028-07-01', 'above_parking_price_mln_per_space': 2, 'above_parking_share_before_rve_pct': 85, 'above_parking_residual_months': 6, 'above_parking_growth_pre_pct': 0.75, 'above_parking_growth_post_pct': 0.2, 'social_dou_gba_sqm': 3000, 'social_school_gba_sqm': 0, 'social_clinic_gba_sqm': 0, 'project_start': '2027-01-01', 'main_under_th_per_sqm': 110, 'social_mode': 'Строительство', 'social_dou_norm_sqm': 12, 'social_school_norm_sqm': 13, 'social_clinic_norm_sqm': 15, 'offices_enabled': False, 'retail_enabled': False, 'above_parking_enabled': False, 'above_parking_area_per_space_sqm': 25, 'rate_scenario': 'low', 'land_rights_cost_mln': 2864.291514155844, 'author_supervision_mln': 19.55, 'bridge_interest_mode': 'Капитализация в ПФ', 'pf_transfer_income_pct': 5.0}
EXCEL_CONTROL = {'llcr': 1.103956112148479, 'bridge_principal_mln': 1345.8299811734776, 'bridge_interest_mln': 61.01315248705002, 'pf_draw_mln': 30011.506226781967, 'pf_interest_and_fees_mln': 2112.072941531574, 'all_interest_and_fees_mln': 2173.086094018624}
LOGO_B64 = "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"


class CalcRequest(BaseModel):
    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = []



_XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XLSX_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XLSX_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _xlsx_col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return 0
    result = 0
    for ch in letters.group(0):
        result = result * 26 + ord(ch) - 64
    return result - 1


def _xlsx_read_tables(data: bytes) -> dict[str, list[list[Any]]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception as exc:
        raise ValueError("Файл не является корректным XLSX") from exc

    ns = {"m": _XLSX_MAIN_NS, "r": _XLSX_REL_NS}
    try:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    except KeyError as exc:
        raise ValueError("В XLSX отсутствует структура книги Excel") from exc

    rels = {}
    for rel in rels_root:
        rels[rel.attrib.get("Id")] = rel.attrib.get("Target", "")

    shared: list[str] = []
    try:
        sst = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in sst.findall(f"{{{_XLSX_MAIN_NS}}}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_XLSX_MAIN_NS}}}t")))
    except KeyError:
        pass

    tables: dict[str, list[list[Any]]] = {}
    sheets = workbook.find("m:sheets", ns)
    if sheets is None:
        return tables

    for sheet in sheets:
        name = sheet.attrib.get("name", "")
        rid = sheet.attrib.get(f"{{{_XLSX_REL_NS}}}id")
        target = rels.get(rid, "")
        if target.startswith("/"):
            path = target.lstrip("/")
        elif target.startswith("xl/"):
            path = target
        else:
            path = "xl/" + target.lstrip("/")
        try:
            root = ET.fromstring(zf.read(path))
        except KeyError:
            continue

        rows_out: list[list[Any]] = []
        sheet_data = root.find(f"{{{_XLSX_MAIN_NS}}}sheetData")
        if sheet_data is None:
            tables[name] = rows_out
            continue

        for row in sheet_data.findall(f"{{{_XLSX_MAIN_NS}}}row"):
            values: dict[int, Any] = {}
            max_col = -1
            for cell in row.findall(f"{{{_XLSX_MAIN_NS}}}c"):
                ref = cell.attrib.get("r", "")
                col = _xlsx_col_index(ref)
                max_col = max(max_col, col)
                ctype = cell.attrib.get("t")
                value = None

                if ctype == "inlineStr":
                    node = cell.find(f"{{{_XLSX_MAIN_NS}}}is")
                    if node is not None:
                        value = "".join(t.text or "" for t in node.iter(f"{{{_XLSX_MAIN_NS}}}t"))
                else:
                    vnode = cell.find(f"{{{_XLSX_MAIN_NS}}}v")
                    raw = vnode.text if vnode is not None else None
                    if raw is not None:
                        if ctype == "s":
                            try:
                                value = shared[int(raw)]
                            except Exception:
                                value = raw
                        elif ctype == "b":
                            value = raw == "1"
                        elif ctype in ("str", "e"):
                            value = raw
                        else:
                            try:
                                num = float(raw)
                                value = int(num) if num.is_integer() else num
                            except ValueError:
                                value = raw
                values[col] = value

            if max_col >= 0:
                rows_out.append([values.get(i) for i in range(max_col + 1)])

        tables[name] = rows_out
    return tables


def _ru_number(value: Any) -> float | None:
    """Russian number parser: NBSP/space = thousands, comma = decimal.
    Only the leading numeric token is used, so '0,651 (100,0%)' -> 0.651.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s in {"—", "-", "–"}:
        return None
    m = re.match(r"^[+-]?[0-9][0-9 \u00A0\u202F]*(?:[,.][0-9]+)?", s)
    if not m:
        return None
    token = m.group(0).replace("\u00A0", "").replace("\u202F", "").replace(" ", "")
    # In ГлавАПУ exports comma is the decimal separator. A dot is already decimal when present.
    if "," in token:
        token = token.replace(".", "").replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def _code(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else ("%g" % value)
    return str(value).strip().replace(",", ".")


def _row_map(rows: list[list[Any]]) -> tuple[dict[str, list[Any]], list[list[Any]]]:
    by_code: dict[str, list[Any]] = {}
    for row in rows:
        if not row:
            continue
        code = _code(row[0] if len(row) > 0 else None)
        if code:
            by_code[code] = row
    return by_code, rows


def _row_val(by_code: dict[str, list[Any]], code: str, col: int = 3) -> Any:
    row = by_code.get(code)
    return row[col] if row and len(row) > col else None


def _row_num(by_code: dict[str, list[Any]], code: str, scale: float = 1.0, col: int = 3) -> float | None:
    value = _ru_number(_row_val(by_code, code, col))
    return None if value is None else value * scale


def _find_named(rows: list[list[Any]], needle: str, value_col: int = 3) -> Any:
    needle = needle.lower()
    for row in rows:
        if len(row) > 1 and needle in str(row[1] or "").lower():
            return row[value_col] if len(row) > value_col else None
    return None


def _find_parameter(rows: list[list[Any]], name: str) -> Any:
    target = name.strip().lower()
    for row in rows:
        if row and str(row[0] or "").strip().lower() == target:
            return row[1] if len(row) > 1 else None
    return None


def parse_glavapu_xlsx(data: bytes, filename: str = "") -> dict[str, Any]:
    tables = _xlsx_read_tables(data)
    tep_sheet = next((name for name in tables if name.strip().lower() == "тэп"), None)
    if not tep_sheet:
        tep_sheet = next((name for name in tables if "тэп" in name.lower()), None)
    if not tep_sheet:
        raise ValueError("Не найден лист «ТЭП». Ожидается формат калькулятора ГлавАПУ.")

    rows = tables[tep_sheet]
    by, all_rows = _row_map(rows)

    parking_sheet = next((name for name in tables if "машино" in name.lower()), None)
    params_sheet = next((name for name in tables if "параметры территории" in name.lower()), None)
    params_rows = tables.get(params_sheet, []) if params_sheet else []

    # Source data. СПП/НП are stored in тыс. кв. м and converted to m².
    data_norm: dict[str, Any] = {
        "site_area_ha": _row_num(by, "1"),
        "density_spp_th_sqm_ha": _row_num(by, "2"),
        "density_np_th_sqm_ha": _row_num(by, "3"),
        "population": _row_num(by, "4"),
        "apartment_units": _row_num(by, "5"),

        "spp_total_sqm": _row_num(by, "6", 1000),
        "residential_spp_sqm": _row_num(by, "7.1", 1000),
        "ground_commercial_spp_sqm": _row_num(by, "7.2", 1000),
        "standalone_nonres_spp_sqm": _row_num(by, "8.1", 1000),
        "social_spp_sqm": _row_num(by, "8.2", 1000),

        "np_total_sqm": _row_num(by, "9", 1000),
        "residential_np_sqm": _row_num(by, "9.1.1", 1000),
        "ground_commercial_np_sqm": _row_num(by, "9.1.2", 1000),
        "standalone_nonres_np_sqm": _row_num(by, "9.2.1", 1000),
        "social_np_sqm": _row_num(by, "9.2.2", 1000),

        "apartment_area_sqm": _row_num(by, "10", 1000),
        "nonresidential_aboveground_sqm": _row_num(by, "11", 1000),

        "actual_kindergarten_places": _row_num(by, "18"),
        "actual_kindergarten_spp_sqm": _row_num(by, "19", 1000),
        "actual_kindergarten_np_sqm": _row_num(by, "20", 1000),
        "actual_kindergarten_land_ha": _row_num(by, "21"),

        "actual_school_places": _row_num(by, "22"),
        "actual_school_spp_sqm": _row_num(by, "23", 1000),
        "actual_school_np_sqm": _row_num(by, "24", 1000),
        "actual_school_land_ha": _row_num(by, "25"),

        "actual_clinic_capacity": _row_num(by, "26"),
        "actual_clinic_spp_sqm": _row_num(by, "27", 1000),
        "actual_clinic_np_sqm": _row_num(by, "28", 1000),
        "actual_clinic_land_ha": _row_num(by, "29"),

        "required_kindergarten_places": _row_num(by, "30"),
        "required_school_places": _row_num(by, "31"),
        "required_clinic_capacity": _row_num(by, "32"),

        "parking_required_total": _row_num(by, "42"),
        "parking_permanent": _row_num(by, "42.1"),
        "parking_guest": _row_num(by, "42.2"),
        "parking_attached": _row_num(by, "42.3"),
        "parking_short_stop": _row_num(by, "43"),

        "change_vri_mln": _row_num(by, "44"),
        "social_compensation_total_mln": _ru_number(_find_named(all_rows, "расчёт компенсации за социальные объекты")),
        "social_compensation_kindergarten_mln": _row_num(by, "54"),
        "social_compensation_school_mln": _row_num(by, "55"),
        "social_compensation_clinic_mln": _row_num(by, "56"),

        "district": _find_parameter(params_rows, "Район"),
        "calculation_zone": _find_parameter(params_rows, "Расчётная зона"),
        "cadastral_quarter": _find_parameter(params_rows, "Кадастровый квартал"),
        "rent_coefficient": _ru_number(_find_parameter(params_rows, "Коэффициент аренды")),
        "mpt_coefficient": _find_parameter(params_rows, "Коэффициент МПТ"),
    }

    # Derived underground parking for the financial TEP:
    # permanent + guest spaces. Attached/on-site and short-stop spaces are not underground sellable/storage parking.
    underground_spaces = (data_norm.get("parking_permanent") or 0) + (data_norm.get("parking_guest") or 0)
    data_norm["underground_parking_spaces"] = underground_spaces
    data_norm["underground_parking_gns_sqm"] = underground_spaces * 35.0

    # Fallback compensation total = components.
    if data_norm["social_compensation_total_mln"] is None:
        parts = [
            data_norm["social_compensation_kindergarten_mln"],
            data_norm["social_compensation_school_mln"],
            data_norm["social_compensation_clinic_mln"],
        ]
        if any(v is not None for v in parts):
            data_norm["social_compensation_total_mln"] = sum(v or 0 for v in parts)

    actual_social_units = sum([
        data_norm["actual_kindergarten_places"] or 0,
        data_norm["actual_school_places"] or 0,
        data_norm["actual_clinic_capacity"] or 0,
    ])
    suggested_social_mode = (
        "Денежная компенсация"
        if actual_social_units == 0 and (data_norm["social_compensation_total_mln"] or 0) > 0
        else "Строительство"
    )

    # Safe mappings: urban-planning source values -> model.
    input_mapping: dict[str, Any] = {
        "land_rights_cost_mln": data_norm["change_vri_mln"],
        "social_compensation_mln": data_norm["social_compensation_total_mln"],
        "social_mode": suggested_social_mode,
        "kindergarten_places": data_norm["actual_kindergarten_places"] or 0,
        "school_places": data_norm["actual_school_places"] or 0,
        "clinic_capacity": data_norm["actual_clinic_capacity"] or 0,
        "social_dou_gba_sqm": data_norm["actual_kindergarten_np_sqm"] or 0,
        "social_school_gba_sqm": data_norm["actual_school_np_sqm"] or 0,
        "social_clinic_gba_sqm": data_norm["actual_clinic_np_sqm"] or 0,
    }
    input_mapping = {k: v for k, v in input_mapping.items() if v is not None}

    tep_mapping: dict[str, dict[str, float]] = {
        "apartments": {
            "gns": data_norm["residential_spp_sqm"] or 0,
            "total_area": data_norm["residential_np_sqm"] or 0,
            "useful": data_norm["apartment_area_sqm"] or 0,
            "saleable": data_norm["apartment_area_sqm"] or 0,
            "units": data_norm["apartment_units"] or 0,
        },
        "ground_commercial": {
            "gns": data_norm["ground_commercial_spp_sqm"] or 0,
            "total_area": data_norm["ground_commercial_np_sqm"] or 0,
            "useful": data_norm["ground_commercial_np_sqm"] or 0,
            "saleable": data_norm["ground_commercial_np_sqm"] or 0,
            "units": 0,
        },
        "underground_parking": {
            "gns": data_norm["underground_parking_gns_sqm"] or 0,
            "total_area": data_norm["underground_parking_gns_sqm"] or 0,
            "useful": 0,
            "saleable": 0,
            "transfer": 0,
            "units": data_norm["underground_parking_spaces"] or 0,
        },
        "standalone_retail": {
            "gns": data_norm["standalone_nonres_spp_sqm"] or 0,
            "total_area": data_norm["standalone_nonres_np_sqm"] or 0,
            "useful": data_norm["standalone_nonres_np_sqm"] or 0,
            "saleable": data_norm["standalone_nonres_np_sqm"] or 0,
            "units": 0,
        },
        "kindergarten": {
            "gns": data_norm["actual_kindergarten_spp_sqm"] or 0,
            "total_area": data_norm["actual_kindergarten_np_sqm"] or 0,
            "transfer": data_norm["actual_kindergarten_np_sqm"] or 0,
            "units": data_norm["actual_kindergarten_places"] or 0,
        },
        "school": {
            "gns": data_norm["actual_school_spp_sqm"] or 0,
            "total_area": data_norm["actual_school_np_sqm"] or 0,
            "transfer": data_norm["actual_school_np_sqm"] or 0,
            "units": data_norm["actual_school_places"] or 0,
        },
        "clinic": {
            "gns": data_norm["actual_clinic_spp_sqm"] or 0,
            "total_area": data_norm["actual_clinic_np_sqm"] or 0,
            "transfer": data_norm["actual_clinic_np_sqm"] or 0,
            "units": data_norm["actual_clinic_capacity"] or 0,
        },
    }

    def item(label: str, key: str, unit: str, target: str, decimals: int = 1) -> dict[str, Any]:
        value = data_norm.get(key)
        if isinstance(value, (int, float)):
            display = f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")
        elif value is None:
            display = "—"
        else:
            display = str(value)
        return {"label": label, "key": key, "value": value, "display": display, "unit": unit, "target": target}

    recognized = [
        item("Площадь территории", "site_area_ha", "га", "Справочно / ГлавАПУ", 3),
        item("Плотность от СПП", "density_spp_th_sqm_ha", "тыс. м²/га", "Справочно / ГлавАПУ", 2),
        item("Плотность от НП", "density_np_th_sqm_ha", "тыс. м²/га", "Справочно / ГлавАПУ", 2),
        item("Население", "population", "чел.", "Справочно / ГлавАПУ", 0),
        item("Количество квартир", "apartment_units", "шт.", "ТЭП → Квартиры", 0),
        item("СПП жилая", "residential_spp_sqm", "м²", "ТЭП → Квартиры → ГНС", 1),
        item("НП жилая", "residential_np_sqm", "м²", "ТЭП → Квартиры → Общая площадь", 1),
        item("Площадь квартир", "apartment_area_sqm", "м²", "ТЭП → Квартиры → Продаваемая", 1),
        item("СПП нежилой части МКД", "ground_commercial_spp_sqm", "м²", "ТЭП → Коммерция 1 эт. → ГНС", 1),
        item("НП нежилой части МКД", "ground_commercial_np_sqm", "м²", "ТЭП → Коммерция 1 эт. → Продаваемая", 1),
        item("Стоимость смены ВРИ", "change_vri_mln", "млн ₽", "Вводные → оформление земельных правоотношений", 3),
        item("Компенсация за соцобъекты", "social_compensation_total_mln", "млн ₽", "Вводные → социальная нагрузка", 3),
        item("Расчётная потребность ДОО", "required_kindergarten_places", "мест", "Справочно / ГлавАПУ", 0),
        item("Расчётная потребность СОШ", "required_school_places", "мест", "Справочно / ГлавАПУ", 0),
        item("Расчётная потребность поликлиника", "required_clinic_capacity", "пос./см.", "Справочно / ГлавАПУ", 0),
        item("Требуемые машино-места", "parking_required_total", "м/м", "Справочно", 0),
        item("Постоянные парковки", "parking_permanent", "м/м", "Подземный паркинг", 0),
        item("Гостевые парковки", "parking_guest", "м/м", "Подземный паркинг", 0),
        item("Приобъектные парковки", "parking_attached", "м/м", "Не включаются в подземный паркинг", 0),
        item("Кратковременная остановка", "parking_short_stop", "м/м", "Не включаются в подземный паркинг", 0),
        item("Подземный паркинг — расчётное количество", "underground_parking_spaces", "м/м", "ТЭП → Подземный паркинг → Количество", 0),
        item("Подземный паркинг — ГНС (35 м²/м/м)", "underground_parking_gns_sqm", "м²", "ТЭП → Подземный паркинг → ГНС", 1),
        item("Район", "district", "", "Справочно / ГлавАПУ"),
        item("Кадастровый квартал", "cadastral_quarter", "", "Справочно / ГлавАПУ"),
    ]

    warnings = [
        "Числа нормализованы по русскому формату: пробел/неразрывный пробел — разделитель тысяч, запятая — десятичный разделитель.",
        "Показатели в тыс. кв. м автоматически приведены к м²; суммы в млн руб. сохранены в млн ₽.",
        "Подземный паркинг рассчитывается автоматически как постоянные + гостевые машино-места. Приобъектные и кратковременные места исключаются. Норматив площади — 35 м² на 1 м/м.",
        "Для квартир ГНС принимается из «СПП жилая», общая площадь — из «НП жилая», продаваемая — из «Площадь квартир».",
    ]

    return {
        "source": {
            "filename": filename,
            "format": "Калькулятор ТЭП ГлавАПУ",
            "sheets": list(tables.keys()),
            "tep_sheet": tep_sheet,
            "parking_sheet": parking_sheet,
            "params_sheet": params_sheet,
        },
        "normalized": data_norm,
        "recognized": recognized,
        "mappings": {"inputs": input_mapping, "tep": tep_mapping},
        "warnings": warnings,
    }


@app.post("/import/glavapu")
async def import_glavapu(request: Request, filename: str = "") -> dict[str, Any]:
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Файл не передан")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл слишком большой. Лимит 15 МБ.")
    try:
        return parse_glavapu_xlsx(data, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось разобрать Excel: {exc}") from exc


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



def _monthly_npv(cashflows: list[float], annual_rate: float) -> float:
    if not cashflows:
        return 0.0
    monthly_rate = pow(1.0 + max(annual_rate, -0.999999), 1.0 / 12.0) - 1.0
    return sum(cf / pow(1.0 + monthly_rate, i) for i, cf in enumerate(cashflows))


def _monthly_irr(cashflows: list[float]) -> float | None:
    if not cashflows or not any(v < 0 for v in cashflows) or not any(v > 0 for v in cashflows):
        return None

    def npv(rate: float) -> float:
        if rate <= -0.999999:
            return float("inf")
        try:
            return sum(cf / pow(1.0 + rate, i) for i, cf in enumerate(cashflows))
        except OverflowError:
            return 0.0

    lo, hi = -0.95, 1.0
    f_lo, f_hi = npv(lo), npv(hi)
    expand = 0
    while f_lo * f_hi > 0 and hi < 100 and expand < 30:
        hi *= 2
        f_hi = npv(hi)
        expand += 1
    if f_lo * f_hi > 0:
        return None

    for _ in range(180):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-5:
            lo = hi = mid
            break
        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid

    monthly = (lo + hi) / 2
    return pow(1 + monthly, 12) - 1


def _iso(value: date) -> str:
    return value.isoformat()


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
    revenue_product_schedules: dict[str, dict[date, float]] = {}

    def add_product(name: str, schedule: dict[date, float]) -> None:
        revenue_product_schedules[name] = dict(schedule)
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

    # Scenario model:
    # base = 100% revenue / 100% project costs
    # conservative = 90% revenue / 110% project costs
    # optimistic = 110% revenue / 90% project costs
    revenue_multiplier = n(x, "scenario_revenue_multiplier", 1.0)
    cost_multiplier = n(x, "scenario_cost_multiplier", 1.0)

    # Keep the base revenue profile so variable operating expenses can be
    # scenarioed independently from the income side.
    base_revenue = dict(revenue)

    if abs(revenue_multiplier - 1.0) > 1e-12:
        revenue = defaultdict(float, {
            month: value * revenue_multiplier for month, value in revenue.items()
        })
        for key in list(revenue_by_product):
            revenue_by_product[key] *= revenue_multiplier
        for key in list(revenue_product_schedules):
            revenue_product_schedules[key] = {
                month: value * revenue_multiplier
                for month, value in revenue_product_schedules[key].items()
            }

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

    social_construction_total = (
        n(x, "kindergarten_places") * n(x, "kindergarten_cost_mln_per_place")
        + n(x, "school_places") * n(x, "school_cost_mln_per_place")
        + n(x, "clinic_capacity") * n(x, "clinic_cost_mln_per_unit")
    ) * 1_000_000
    imported_social_compensation = n(x, "social_compensation_mln") * 1_000_000
    if str(x.get("social_mode", "Строительство")) == "Денежная компенсация":
        social_total = imported_social_compensation if imported_social_compensation > 0 else social_construction_total
    else:
        social_total = social_construction_total
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

    # Apply expense scenario to ALL project-side cash outflows exactly once:
    # acquisition, VRI, social burden, design, construction, overheads, etc.
    if abs(cost_multiplier - 1.0) > 1e-12:
        capex = defaultdict(float, {
            month: value * cost_multiplier for month, value in capex.items()
        })
        for key in list(amounts):
            amounts[key] *= cost_multiplier

    # Marketing + selling expenses are also scenarioed as expenses relative to BASE,
    # not reduced merely because conservative revenue is lower.
    operating: dict[date, float] = defaultdict(float)
    for month, value in base_revenue.items():
        operating[month] += (
            value
            * (n(x, "marketing_pct") + n(x, "selling_pct")) / 100
            * cost_multiplier
        )

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
        "revenue_product_schedules": revenue_product_schedules,
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

    # ГлавАПУ is the authoritative source for required underground parking.
    # Repair stale browser/localStorage TEP values before every calculation.
    imported = (x.get("_glavapu_import") or {}).get("normalized", {})
    if imported:
        permanent = n(imported, "parking_permanent")
        guest = n(imported, "parking_guest")
        underground_spaces = permanent + guest
        if underground_spaces > 0 and "underground_parking" in t:
            t["underground_parking"]["units"] = underground_spaces
            t["underground_parking"]["gns"] = underground_spaces * 35.0
            t["underground_parking"]["total_area"] = underground_spaces * 35.0
            t["underground_parking"]["useful"] = 0.0
            t["underground_parking"]["saleable"] = 0.0
            t["underground_parking"]["transfer"] = 0.0

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

    # Report-level project metrics.
    monetizable_saleable_sqm = sum(
        n(row, "saleable") for key, row in t.items()
        if key in ("apartments", "ground_commercial", "standalone_retail", "offices")
    )
    apartment_saleable_sqm = n(t.get("apartments", {}), "saleable")
    core_gns = op["core_above_gns"] + op["core_under_gns"]

    construction_capex = sum(op["capex_amounts"].get(k, 0.0) for k in (
        "ird", "design_p", "design_rd", "author_supervision", "preparation",
        "main_above", "main_under", "utilities", "landscaping",
        "commissioning", "site_maintenance", "gc_fee", "reserve"
    ))
    full_project_cost = total_capex + fin["commercial_costs"] + fin["financing_cost"] + fin["profit_tax"]
    avg_apartment_price = (
        op["revenue_by_product"].get("apartments", 0.0) / apartment_saleable_sqm / 1000
        if apartment_saleable_sqm else 0.0
    )
    full_cost_per_saleable = full_project_cost / monetizable_saleable_sqm / 1000 if monetizable_saleable_sqm else 0.0
    construction_cost_per_gns = construction_capex / core_gns / 1000 if core_gns else 0.0
    ebitda = total_revenue - total_capex - fin["commercial_costs"]
    ebitda_per_saleable = ebitda / monetizable_saleable_sqm / 1000 if monetizable_saleable_sqm else 0.0
    net_profit_per_saleable = net_profit / monetizable_saleable_sqm / 1000 if monetizable_saleable_sqm else 0.0

    # Unit economics by total GNS and monetizable saleable area.
    project_gns_sqm = sum(n(row, "gns") for row in t.values())
    total_expenses = total_capex + fin["commercial_costs"] + fin["financing_cost"] + fin["profit_tax"]

    def per_sqm_th(value: float, area: float) -> float:
        return value / area / 1000 if area else 0.0

    unit_economics = [
        {
            "label": "Выручка",
            "total": total_revenue,
            "per_gns_th": per_sqm_th(total_revenue, project_gns_sqm),
            "per_saleable_th": per_sqm_th(total_revenue, monetizable_saleable_sqm),
        },
        {
            "label": "CAPEX",
            "total": total_capex,
            "per_gns_th": per_sqm_th(total_capex, project_gns_sqm),
            "per_saleable_th": per_sqm_th(total_capex, monetizable_saleable_sqm),
        },
        {
            "label": "Маркетинг и продажи",
            "total": fin["commercial_costs"],
            "per_gns_th": per_sqm_th(fin["commercial_costs"], project_gns_sqm),
            "per_saleable_th": per_sqm_th(fin["commercial_costs"], monetizable_saleable_sqm),
        },
        {
            "label": "EBITDA",
            "total": ebitda,
            "per_gns_th": per_sqm_th(ebitda, project_gns_sqm),
            "per_saleable_th": per_sqm_th(ebitda, monetizable_saleable_sqm),
        },
        {
            "label": "Проценты и комиссии",
            "total": fin["financing_cost"],
            "per_gns_th": per_sqm_th(fin["financing_cost"], project_gns_sqm),
            "per_saleable_th": per_sqm_th(fin["financing_cost"], monetizable_saleable_sqm),
        },
        {
            "label": "Налог на прибыль",
            "total": fin["profit_tax"],
            "per_gns_th": per_sqm_th(fin["profit_tax"], project_gns_sqm),
            "per_saleable_th": per_sqm_th(fin["profit_tax"], monetizable_saleable_sqm),
        },
        {
            "label": "Полные расходы",
            "total": total_expenses,
            "per_gns_th": per_sqm_th(total_expenses, project_gns_sqm),
            "per_saleable_th": per_sqm_th(total_expenses, monetizable_saleable_sqm),
        },
        {
            "label": "Чистая прибыль",
            "total": net_profit,
            "per_gns_th": per_sqm_th(net_profit, project_gns_sqm),
            "per_saleable_th": per_sqm_th(net_profit, monetizable_saleable_sqm),
        },
    ]

    # Expense structure: categories are mutually exclusive and sum to total expenses.
    purchase_value = n(x, "purchase_price_mln") * 1_000_000
    expense_groups = [
        ("Покупка и земельные права", purchase_value + op["capex_amounts"].get("land_rights", 0.0)),
        ("ИРД и проектирование",
         op["capex_amounts"].get("ird", 0.0)
         + op["capex_amounts"].get("design_p", 0.0)
         + op["capex_amounts"].get("design_rd", 0.0)
         + op["capex_amounts"].get("author_supervision", 0.0)),
        ("Основное строительство",
         op["capex_amounts"].get("preparation", 0.0)
         + op["capex_amounts"].get("main_above", 0.0)
         + op["capex_amounts"].get("main_under", 0.0)
         + op["capex_amounts"].get("utilities", 0.0)
         + op["capex_amounts"].get("landscaping", 0.0)
         + op["capex_amounts"].get("commissioning", 0.0)
         + op["capex_amounts"].get("site_maintenance", 0.0)
         + op["capex_amounts"].get("gc_fee", 0.0)),
        ("Отдельные объекты",
         op["capex_amounts"].get("offices", 0.0)
         + op["capex_amounts"].get("standalone_retail", 0.0)
         + op["capex_amounts"].get("above_parking", 0.0)),
        ("Социальная нагрузка", op["capex_amounts"].get("social", 0.0)),
        ("Управление и резерв",
         op["capex_amounts"].get("project_management", 0.0)
         + op["capex_amounts"].get("reserve", 0.0)),
        ("Маркетинг и продажи", fin["commercial_costs"]),
        ("Проценты и комиссии", fin["financing_cost"]),
        ("Налог на прибыль", fin["profit_tax"]),
    ]
    expense_structure = []
    expense_base = sum(value for _, value in expense_groups)
    for label, value in expense_groups:
        if value <= 0:
            continue
        expense_structure.append({
            "label": label,
            "value": value,
            "share": value / expense_base if expense_base else 0.0,
        })
    expense_structure.sort(key=lambda item: item["value"], reverse=True)

    # Project/equity cash flow proxy for NPV / IRR.
    row_by_month = {d(r["month"]): r for r in fin["rows"]}
    timeline = month_range(op["project_start"], op["end"])
    project_cf = []
    equity_cf = []
    for month in timeline:
        revenue_m = op["revenue"].get(month, 0.0)
        capex_m = op["capex"].get(month, 0.0)
        opex_m = op["operating"].get(month, 0.0)
        fr = row_by_month.get(month, {})
        bridge_draw = float(fr.get("bridge_draw", 0.0) or 0.0)
        bridge_repay = float(fr.get("bridge_repayment", 0.0) or 0.0)
        pf_draw = float(fr.get("pf_draw", 0.0) or 0.0)
        pf_repay = float(fr.get("pf_repayment", 0.0) or 0.0)
        int_pay = float(fr.get("interest_payment", 0.0) or 0.0)
        fees = float(fr.get("limit_fee", 0.0) or 0.0)
        tax = fin["profit_tax"] if month == op["end"] else 0.0
        project_cf.append(revenue_m - capex_m - opex_m - int_pay - fees - tax)
        equity_cf.append(
            revenue_m - capex_m - opex_m - int_pay - fees - tax
            + bridge_draw + pf_draw - bridge_repay - pf_repay
        )

    if project_cf:
        project_cf[0] -= fin["bridge_fee"]
    if equity_cf:
        equity_cf[0] -= fin["bridge_fee"]
    permit_idx = months_between(op["project_start"], op["permit"])
    if 0 <= permit_idx < len(project_cf):
        project_cf[permit_idx] -= fin["pf_reservation_fee"]
        equity_cf[permit_idx] -= fin["pf_reservation_fee"]

    discount_rate = n(x, "discount_rate_pct", 20) / 100
    project_npv = _monthly_npv(project_cf, discount_rate)
    irr_equity = _monthly_irr(equity_cf)

    # Product economics / sales KPIs.
    product_specs = {
        "apartments": {
            "label": "Квартиры", "quantity": n(t.get("apartments", {}), "saleable"),
            "unit": "м²", "start_price": n(x, "apartment_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
        "ground_commercial": {
            "label": "Коммерция 1 этажа", "quantity": n(t.get("ground_commercial", {}), "saleable"),
            "unit": "м²", "start_price": n(x, "commercial_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
        "underground_parking": {
            "label": "Подземный паркинг", "quantity": n(t.get("underground_parking", {}), "units"),
            "unit": "шт.", "start_price": n(x, "parking_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
        "storage": {
            "label": "Кладовые", "quantity": n(t.get("storage", {}), "units"),
            "unit": "шт.", "start_price": n(x, "storage_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
        "offices": {
            "label": "Офисы / МФОЦ", "quantity": n(x, "offices_saleable_sqm") if b(x, "offices_enabled") else 0,
            "unit": "м²", "start_price": n(x, "offices_price_th_per_sqm"), "share": n(x, "offices_share_before_rve_pct", 85)/100,
            "start": d(x["offices_sales_start"]), "end_ref": add_months(d(x["offices_start"]), int(n(x, "offices_months", 24))),
            "residual": int(n(x, "offices_residual_months", 6))
        },
        "standalone_retail": {
            "label": "Коммерция ОСЗ", "quantity": n(x, "retail_saleable_sqm") if b(x, "retail_enabled") else 0,
            "unit": "м²", "start_price": n(x, "retail_price_th_per_sqm"), "share": n(x, "retail_share_before_rve_pct", 85)/100,
            "start": d(x["retail_sales_start"]), "end_ref": add_months(d(x["retail_start"]), int(n(x, "retail_months", 24))),
            "residual": int(n(x, "retail_residual_months", 6))
        },
        "above_parking": {
            "label": "Наземный паркинг", "quantity": n(x, "above_parking_spaces") if b(x, "above_parking_enabled") else 0,
            "unit": "шт.", "start_price": n(x, "above_parking_price_mln_per_space")*1000, "share": n(x, "above_parking_share_before_rve_pct", 85)/100,
            "start": d(x["above_parking_sales_start"]), "end_ref": add_months(d(x["above_parking_start"]), int(n(x, "above_parking_months", 18))),
            "residual": int(n(x, "above_parking_residual_months", 6))
        }
    }

    products_report = []
    for key, spec in product_specs.items():
        quantity = float(spec["quantity"] or 0)
        revenue_value = op["revenue_by_product"].get(key, 0.0)
        schedule = op["revenue_product_schedules"].get(key, {})
        months_pre = max(1, months_between(spec["start"], spec["end_ref"]))
        pace = quantity * spec["share"] / months_pre if quantity else 0.0
        avg_price = revenue_value / quantity / 1000 if quantity else 0.0
        start_date = min(schedule.keys()).isoformat() if schedule else None
        end_date = max(schedule.keys()).isoformat() if schedule else None
        products_report.append({
            "key": key,
            "label": spec["label"],
            "unit": spec["unit"],
            "quantity": quantity,
            "revenue": revenue_value,
            "start_price_th": spec["start_price"],
            "avg_price_th": avg_price,
            "pace_pre": pace,
            "share_before_rve": spec["share"],
            "sales_start": start_date,
            "sales_end": end_date,
        })

    # Calendar / Gantt, mirroring the conceptual structure of the Excel Calendar sheet.
    calendar_events = []
    def add_event(label: str, start: date, end: date | None = None, group: str = "Проект", kind: str = "bar"):
        calendar_events.append({
            "label": label, "start": _iso(start), "end": _iso(end or start),
            "group": group, "kind": kind
        })

    add_event("Сделка / начало проекта", op["project_start"], group="Ключевые вехи", kind="milestone")
    add_event("ИРД и согласования", op["project_start"], op["permit"], group="Подготовка")
    design_start = add_months(op["permit"], -min(6, max(1, int(n(x, "ird_months", 18)))))
    add_event("Проектирование П и РД", design_start, op["permit"], group="Подготовка")
    bridge_end = add_months(op["permit"], int(n(x, "bridge_repay_lag_months", 0)))
    add_event("БРИДЖ", op["project_start"], bridge_end, group="Финансирование")
    add_event("РнС", op["permit"], group="Ключевые вехи", kind="milestone")
    add_event("Старт продаж", op["sales_start"], group="Ключевые вехи", kind="milestone")
    add_event("Строительство ЖК", op["permit"], op["rve"], group="Строительство")
    if any(v > 0 for v in (op["capex_amounts"].get("utilities", 0), op["capex_amounts"].get("landscaping", 0))):
        add_event("Сети и благоустройство", op["permit"], op["rve"], group="Строительство")

    if str(x.get("social_mode")) == "Денежная компенсация":
        add_event("Социальный платёж", d(x["social_comp_date"]), group="Социальная нагрузка", kind="milestone")
    else:
        if n(x, "kindergarten_places"):
            add_event("ДОУ", d(x["kindergarten_start"]), add_months(d(x["kindergarten_start"]), int(n(x, "kindergarten_months", 24))), group="Социальная нагрузка")
        if n(x, "school_places"):
            add_event("СОШ", d(x["school_start"]), add_months(d(x["school_start"]), int(n(x, "school_months", 30))), group="Социальная нагрузка")
        if n(x, "clinic_capacity"):
            add_event("Поликлиника", d(x["clinic_start"]), add_months(d(x["clinic_start"]), int(n(x, "clinic_months", 24))), group="Социальная нагрузка")

    if b(x, "offices_enabled"):
        add_event("Офисы / МФОЦ", d(x["offices_start"]), add_months(d(x["offices_start"]), int(n(x, "offices_months", 24))), group="Отдельные объекты")
    if b(x, "retail_enabled"):
        add_event("Коммерция ОСЗ", d(x["retail_start"]), add_months(d(x["retail_start"]), int(n(x, "retail_months", 24))), group="Отдельные объекты")
    if b(x, "above_parking_enabled"):
        add_event("Наземный паркинг", d(x["above_parking_start"]), add_months(d(x["above_parking_start"]), int(n(x, "above_parking_months", 18))), group="Отдельные объекты")

    sales_months = [month for sched in op["revenue_product_schedules"].values() for month in sched]
    sales_end = max(sales_months) if sales_months else add_months(op["rve"], int(n(x, "residual_sales_months", 6)))
    add_event("Продажи", op["sales_start"], sales_end, group="Продажи")
    add_event("РВЭ / РНВ", op["rve"], group="Ключевые вехи", kind="milestone")
    add_event("Окончание продаж", sales_end, group="Ключевые вехи", kind="milestone")

    pf_active_months = [d(row["month"]) for row in fin["rows"] if (row.get("pf_balance", 0) or row.get("pf_draw", 0) or row.get("pf_repayment", 0))]
    if pf_active_months:
        add_event("Проектное финансирование", min(pf_active_months), max(pf_active_months), group="Финансирование")

    calendar_start = min(d(e["start"]) for e in calendar_events)
    calendar_end = max(d(e["end"]) for e in calendar_events)

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
            "commercial_costs": fin["commercial_costs"],
            "ebitda": ebitda,
            "financing_cost": fin["financing_cost"],
            "profit_before_tax": after_finance_pre_tax,
            "profit_tax": fin["profit_tax"],
            "net_profit": net_profit,
            "margin": net_profit / total_revenue if total_revenue else 0.0,
            "llcr": fin["llcr"],
            "scenario_revenue_multiplier": n(x, "scenario_revenue_multiplier", 1.0),
            "scenario_cost_multiplier": n(x, "scenario_cost_multiplier", 1.0),
            "npv": project_npv,
            "irr_equity": irr_equity,
            "full_project_cost": full_project_cost,
            "monetizable_saleable_sqm": monetizable_saleable_sqm,
            "apartment_saleable_sqm": apartment_saleable_sqm,
            "average_apartment_price_th": avg_apartment_price,
            "full_cost_per_saleable_th": full_cost_per_saleable,
            "construction_cost_per_gns_th": construction_cost_per_gns,
            "ebitda_per_saleable_th": ebitda_per_saleable,
            "net_profit_per_saleable_th": net_profit_per_saleable,
            "project_gns_sqm": project_gns_sqm,
            "total_expenses": total_expenses,
            "social_payment": op["capex_amounts"].get("social", 0.0),
            "social_payment_mode": str(x.get("social_mode", "")),
            "social_payment_breakdown": {
                "kindergarten_mln": n((x.get("_glavapu_import") or {}).get("normalized", {}), "social_compensation_kindergarten_mln"),
                "school_mln": n((x.get("_glavapu_import") or {}).get("normalized", {}), "social_compensation_school_mln"),
                "clinic_mln": n((x.get("_glavapu_import") or {}).get("normalized", {}), "social_compensation_clinic_mln"),
            },
        },
        "report": {
            "products": products_report,
            "unit_economics": unit_economics,
            "expense_structure": expense_structure,
            "calendar": {
                "start": calendar_start.isoformat(),
                "end": calendar_end.isoformat(),
                "events": calendar_events,
            },
            "financing": {
                "calculated_bridge": fin["calculated_bridge_limit"],
                "actual_bridge": fin["peak_bridge"],
                "pf_peak": fin["peak_pf"],
                "pf_limit": fin["pf_limit"],
                "avg_bridge_rate": fin["avg_bridge_rate"],
                "avg_pf_rate": fin["avg_pf_rate"],
                "interest_and_fees": fin["financing_cost"],
            }
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
.import-card{border-top:8px solid #000}
.preset-card{border-top:8px solid #000}
.preset-grid{display:grid;grid-template-columns:1.3fr repeat(5,1fr);gap:0;border-left:1px solid #ddd;border-top:1px solid #111;margin-top:14px}
.preset-grid>div{padding:10px 12px;border-right:1px solid #ddd;border-bottom:1px solid #ddd}
.preset-grid small{display:block;color:#777;font-size:10px;text-transform:uppercase;letter-spacing:.05em}
.preset-grid b{display:block;margin-top:5px;font-size:13px}
.expense-bars{display:grid;gap:11px;margin-top:8px}
.expense-row{display:grid;grid-template-columns:minmax(180px,1.25fr) minmax(220px,3fr) 70px 120px;gap:10px;align-items:center;font-size:12px}
.expense-label{line-height:1.25}
.expense-track{height:15px;background:#eee;position:relative;overflow:hidden}
.expense-fill{height:100%;background:#111;min-width:2px}
.expense-pct{text-align:right;font-weight:700}
.expense-value{text-align:right;color:#666}
.unit-table td:not(:first-child),.unit-table th:not(:first-child){text-align:right}
@media(max-width:900px){
 .preset-grid{grid-template-columns:1fr 1fr}.expense-row{grid-template-columns:1fr}.expense-pct,.expense-value{text-align:left}
}
.import-head{display:flex;align-items:flex-start;gap:22px;justify-content:space-between;flex-wrap:wrap}
.import-head h2{font-size:18px;margin:0 0 6px}.import-head p{font-size:12px;color:#666;margin:0;max-width:760px;line-height:1.5}
.upload-line{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:16px}
.upload-line input[type=file]{max-width:520px;background:#fafafa}
.import-status{font-size:12px;color:#666;margin-top:10px}
.import-preview{margin-top:16px;border-top:1px solid #ddd;padding-top:16px}
.import-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border-left:1px solid #ddd;border-top:1px solid #111;margin-bottom:14px}
.import-summary div{padding:11px;border-right:1px solid #ddd;border-bottom:1px solid #ddd}
.import-summary small{display:block;color:#777;font-size:10px;text-transform:uppercase;letter-spacing:.06em}
.import-summary b{display:block;margin-top:4px;font-size:13px}
.import-actions{display:flex;gap:8px;margin-top:14px;align-items:center;flex-wrap:wrap}
.import-ok{color:var(--positive);font-weight:650}.import-error{color:var(--negative);font-weight:650}
.mobile-hint{display:none}

.report-hero{border-top:8px solid #000}
.report-kpis{grid-template-columns:repeat(5,minmax(140px,1fr))}
.report-section{margin-top:20px}
.report-title{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:12px}
.report-title h2{margin:0;font-size:18px}.report-title small{color:#777}
.report-3col{display:grid;grid-template-columns:1.15fr 1fr 1fr;gap:18px}
.report-2col{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.value-muted{color:#777}
.gantt-wrap{overflow:auto;border:1px solid var(--line);background:#fff}
.gantt{min-width:1050px}
.gantt-axis,.gantt-row{display:grid;grid-template-columns:250px 1fr;min-height:38px;border-bottom:1px solid #e7e7e7}
.gantt-axis{position:sticky;top:0;background:#fff;z-index:4;border-bottom:2px solid #111}
.gantt-label{padding:9px 12px;font-size:12px;border-right:1px solid #ddd;white-space:nowrap}
.gantt-label.group{font-weight:750;background:#f7f7f5;text-transform:uppercase;letter-spacing:.05em;color:#666}
.gantt-track{position:relative;min-height:38px;background-image:linear-gradient(to right,rgba(0,0,0,.055) 1px,transparent 1px)}
.gantt-year{position:absolute;top:0;bottom:0;border-left:1px solid #bbb;padding:8px 0 0 7px;font-size:11px;font-weight:700}
.gantt-bar{position:absolute;top:9px;height:20px;background:#111;min-width:4px}
.gantt-bar.finance{background:#555}.gantt-bar.sales{background:#888}.gantt-bar.social{background:#b1b1b1}
.gantt-diamond{position:absolute;top:13px;width:12px;height:12px;background:#111;transform:rotate(45deg);margin-left:-6px}
.gantt-date{font-size:10px;color:#777;margin-left:6px}
.gantt-legend{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;font-size:11px;color:#666}
.gantt-legend span:before{content:"";display:inline-block;width:18px;height:7px;background:#111;margin-right:5px;vertical-align:middle}
.gantt-legend span:nth-child(2):before{background:#555}.gantt-legend span:nth-child(3):before{background:#888}
.metric-compact td,.metric-compact th{padding:7px 8px}
.kpi .sub{font-size:10px;color:#999;margin-top:3px}
@media(max-width:1100px){.report-3col,.report-2col{grid-template-columns:1fr}.report-kpis{grid-template-columns:1fr 1fr}}
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
    <div class="title"><h1>Девелоперская инвестиционная модель</h1><p>v0.6.5 · ТЭП · экономика · БРИДЖ · проектное финансирование · эскроу · LLCR</p></div>
    <div class="actions">
      <div class="scenario">Сценарий&nbsp;
        <select id="scenarioSelect" onchange="applyScenario(this.value)">
          <option value="conservative">Консервативный</option><option value="base" selected>Базовый</option><option value="optimistic">Оптимистичный</option>
        </select>
        <div id="scenarioNote" style="font-size:10px;color:#777;margin-top:4px;text-align:right">
          Доходы без корректировки · расходы без корректировки
        </div>
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
    <button class="tab" data-tab="calendar" onclick="openTab('calendar',this)">Календарь</button>
    <button class="tab" data-tab="report" onclick="openTab('report',this)">Отчёт</button>
  </div>

  <div class="content">
    <div id="inputs" class="panel active">
      <div class="card preset-card">
        <div class="import-head">
          <div>
            <div class="section-title">Базовые настройки проекта</div>
            <h2>Класс проекта</h2>
            <p>Пресет меняет только стартовые цены квартир и коммерции, цену подземного машино-места и базовую себестоимость надземной/подземной части. Остальные вводные проекта не затрагиваются.</p>
          </div>
          <div class="upload-line" style="margin-top:0">
            <select id="projectClassSelect" style="min-width:170px">
              <option value="comfort">Комфорт</option>
              <option value="business">Бизнес</option>
              <option value="elite">Элитный</option>
              <option value="custom">Пользовательский</option>
            </select>
            <button class="btn dark" onclick="applyProjectClassPreset()">Применить пресет</button>
          </div>
        </div>
        <div id="projectClassPreview" class="preset-grid"></div>
      </div>

      <div class="card import-card">
        <div class="import-head">
          <div>
            <div class="section-title">Автозагрузка исходных данных</div>
            <h2>Калькулятор ТЭП ГлавАПУ</h2>
            <p>Загрузите Excel из калькулятора ГлавАПУ. Система распознает СПП, НП, площади квартир и коммерции, стоимость смены ВРИ, социальную нагрузку и парковки. Подземная часть рассчитывается из постоянных и гостевых м/м по 35 м² на место. Перед применением данные показываются для проверки.</p>
          </div>
          <div style="font-size:11px;color:#777;text-align:right">Поддерживается<br><b style="color:#111">.xlsx</b></div>
        </div>
        <div class="upload-line">
          <input type="file" id="glavapuFile" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet">
          <button class="btn dark" onclick="uploadGlavapu()">Разобрать файл</button>
        </div>
        <div id="glavapuStatus" class="import-status">Формат: лист «ТЭП» калькулятора ГлавАПУ. Запятые и регистры единиц обрабатываются автоматически.</div>
        <div id="glavapuPreview" class="import-preview" style="display:none">
          <div id="glavapuSummary" class="import-summary"></div>
          <div class="scroll" style="max-height:360px"><table>
            <thead><tr><th>Показатель</th><th>Распознано</th><th>Ед.</th><th>Куда попадёт</th></tr></thead>
            <tbody id="glavapuRows"></tbody>
          </table></div>
          <div id="glavapuWarnings" class="note warning"></div>
          <div class="import-actions">
            <button class="btn dark" onclick="applyGlavapu()">Применить к Вводным и ТЭП</button>
            <span style="font-size:11px;color:#777">Текущие значения ТЭП квартир/коммерции будут заменены распознанными.</span>
          </div>
        </div>
      </div>
      <div class="grid">
        <div class="card"><div class="section-title">Вводные данные</div><div id="inputGroups"></div><button class="btn dark" style="width:100%;margin-top:12px" onclick="calculateAndOpen('report')">Пересчитать проект</button></div>
        <div>
          <div class="card"><div class="section-title">Контрольные даты</div><div class="dates" id="dateBoxes"></div></div>
          <div class="card"><div class="section-title">Ключевые показатели</div><div class="kpis" id="quickKpi"></div></div>
          <div class="note">Поля финансирования участвуют в помесячном расчёте. «Проценты и комиссии» — денежная стоимость финансирования БРИДЖ + ПФ. EBITDA считается до финансирования и налога: выручка минус CAPEX проекта, маркетинг и продажи.</div>
        </div>
      </div>
    </div>

    <div id="tep" class="panel">
      <div class="card">
        <div class="toolbar"><button class="btn" onclick="syncTep()">Обновить производные ТЭП из вводных</button><span style="color:#777;font-size:12px">В интерфейсе показывается 1 знак после запятой. При загруженном ГлавАПУ подземный паркинг является производным: постоянные + гостевые × 35 м².</span></div>
        <div class="scroll"><table class="teptable"><thead><tr><th>Продукт</th><th>ГНС, м²</th><th>Общая площадь, м²</th><th>Полезная площадь, м²</th><th>Продаваемая площадь, м²</th><th>Передаваемая площадь, м²</th><th>Количество, шт.</th></tr></thead><tbody id="tepBody"></tbody><tfoot><tr><th>Итого</th><th id="tg"></th><th id="ta"></th><th id="tu"></th><th id="ts"></th><th id="tt"></th><th id="tn"></th></tr></tfoot></table></div>
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
        <div class="llcr-hero"><div><div class="section-title">LLCR</div><div id="llcrValue" class="llcr-value">—</div></div><div class="llcr-label">Расчётный LLCR веб-модели. Контрольное значение текущего Excel — 1,08x. До полной помесячной сверки показатель веб-модели не считается финальным.</div></div>
        <div class="compare"><div><small>Расчётный LLCR веб-модели</small><b id="llcrWeb">—</b></div><div><small>Контроль исходного Excel</small><b id="llcrExcel">1,08x</b></div></div>
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
      <div class="note warning">Контрольная цифра LLCR из исходного Excel — 1,08x. Веб-расчёт динамический и уже реагирует на вводные, но до полного отказа от Excel надо сверить помесячно 3–5 контрольных сценариев.</div>
    </div>

    <div id="calendar" class="panel">
      <div class="card">
        <div class="report-title"><div><div class="section-title">Календарный график проекта</div><h2>Этапы, финансирование, продажи и ключевые вехи</h2></div><small id="calendarRange">—</small></div>
        <div style="font-size:11px;color:#777;margin:-4px 0 12px">Полный календарный график находится только здесь и не дублируется в Отчёте.</div>
        <div id="calendarGantt" class="gantt-wrap"></div>
        <div class="gantt-legend"><span>Проект / строительство</span><span>Финансирование</span><span>Продажи</span></div>
      </div>
    </div>

    <div id="report" class="panel">
      <div class="card report-hero">
        <div class="report-title">
          <div><div class="section-title">Управленческий отчёт</div><h2>Экономика и ключевые показатели проекта</h2></div>
          <small>Агрегированный отчёт · значения пересчитываются из текущих вводных</small>
        </div>
        <div class="kpis report-kpis" id="reportKpi"></div>
      </div>

      <div class="report-3col">
        <div class="card">
          <div class="section-title">Экономика проекта</div>
          <table class="metric-table metric-compact" id="economicsTable"></table>
        </div>
        <div class="card">
          <div class="section-title">Ключевые параметры</div>
          <table class="metric-table metric-compact" id="projectParamsTable"></table>
        </div>
        <div class="card">
          <div class="section-title">Финансирование</div>
          <table class="metric-table metric-compact" id="reportFinanceTable"></table>
        </div>
      </div>

      <div class="card">
        <div class="report-title">
          <div>
            <div class="section-title">Структура расходов</div>
            <h2>Из чего складываются полные расходы проекта</h2>
          </div>
          <small>Сумма и доля каждой категории от 100% расходов</small>
        </div>
        <div class="report-2col">
          <div id="expenseStructureChart" class="expense-bars"></div>
          <div class="scroll" style="max-height:none">
            <table class="metric-table metric-compact">
              <thead><tr><th>Категория</th><th>Сумма</th><th>Доля</th></tr></thead>
              <tbody id="expenseStructureTable"></tbody>
              <tfoot><tr><th>Итого расходов</th><th id="expenseTotal"></th><th>100%</th></tr></tfoot>
            </table>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="section-title">Удельная экономика</div>
        <div style="font-size:11px;color:#777;margin:-5px 0 10px">
          Все значения приведены одновременно на 1 м² ГНС и на 1 м² продаваемой площади.
        </div>
        <div class="scroll" style="max-height:none">
          <table class="unit-table">
            <thead><tr><th>Показатель</th><th>Всего</th><th>тыс. ₽ / м² ГНС</th><th>тыс. ₽ / м² продаваемой</th></tr></thead>
            <tbody id="unitEconomicsTable"></tbody>
          </table>
        </div>
      </div>

      <div class="report-2col">
        <div class="card">
          <div class="section-title">Структура выручки</div>
          <table id="revenueTable"></table>
        </div>
        <div class="card">
          <div class="section-title">Структура затрат</div>
          <table id="capexTable"></table>
        </div>
      </div>

      <div class="card">
        <div class="section-title">ТЭП</div>
        <div class="scroll" style="max-height:none"><table id="reportTep"></table></div>
      </div>

      <div class="card">
        <div class="section-title">Темпы и цены продаж</div>
        <div class="scroll" style="max-height:none">
          <table>
            <thead><tr><th>Продукт</th><th>Объём</th><th>Темп до РВЭ</th><th>Продажи до РВЭ</th><th>Стартовая цена</th><th>Средняя цена</th><th>Выручка</th><th>Старт продаж</th><th>Финиш продаж</th></tr></thead>
            <tbody id="salesReportTable"></tbody>
          </table>
        </div>
      </div>

      <div class="report-2col">
        <div class="card">
          <div class="section-title">Социальная нагрузка</div>
          <table class="metric-table metric-compact" id="socialTable"></table>
        </div>
        <div class="card">
          <div class="section-title">Ставки и долговая нагрузка</div>
          <table class="metric-table metric-compact" id="ratesDebtTable"></table>
        </div>
      </div>

      <div class="note warning">LLCR, NPV и IRR в веб-модели являются расчётными показателями текущего движка. До полного отказа от Excel кредитный CF и доходность должны быть окончательно сверены помесячно с эталонной моделью.</div>
    </div>
  </div>
</div>

<script>
const SCENARIOS={"conservative":{"scenario_revenue_multiplier":0.9,"scenario_cost_multiplier":1.1},"base":{"scenario_revenue_multiplier":1.0,"scenario_cost_multiplier":1.0},"optimistic":{"scenario_revenue_multiplier":1.1,"scenario_cost_multiplier":0.9}};
const PROJECT_CLASS_PRESETS={
 "comfort":{"label":"Комфорт","apartment_price_th":350,"commercial_price_th":350,"parking_price_th":1500,"main_above_th_per_sqm":110,"main_under_th_per_sqm":110},
 "business":{"label":"Бизнес","apartment_price_th":650,"commercial_price_th":650,"parking_price_th":5000,"main_above_th_per_sqm":190,"main_under_th_per_sqm":190},
 "elite":{"label":"Элитный","apartment_price_th":1500,"commercial_price_th":1500,"parking_price_th":20000,"main_above_th_per_sqm":300,"main_under_th_per_sqm":300}
};
const RATE_DEFAULT=[{"date": "2027-01-01", "high": 15.0, "base": 13.0, "low": 11.0}, {"date": "2027-07-01", "high": 14.5, "base": 12.5, "low": 10.5}, {"date": "2028-01-01", "high": 13.5, "base": 11.5, "low": 9.5}, {"date": "2028-02-01", "high": 14.5, "base": 11.5, "low": 10.5}, {"date": "2028-03-01", "high": 14.25, "base": 11.25, "low": 10.25}, {"date": "2028-04-01", "high": 14.0, "base": 11.0, "low": 10.0}, {"date": "2028-05-01", "high": 13.75, "base": 11.0, "low": 9.75}, {"date": "2028-06-01", "high": 13.5, "base": 11.0, "low": 9.5}, {"date": "2028-07-01", "high": 13.25, "base": 11.0, "low": 9.25}, {"date": "2028-08-01", "high": 13.0, "base": 11.0, "low": 9.0}, {"date": "2028-09-01", "high": 12.75, "base": 10.75, "low": 8.75}, {"date": "2028-10-01", "high": 12.5, "base": 10.5, "low": 8.5}, {"date": "2028-11-01", "high": 12.25, "base": 10.25, "low": 8.25}, {"date": "2028-12-01", "high": 12.0, "base": 10.0, "low": 8.0}, {"date": "2029-01-01", "high": 11.75, "base": 9.75, "low": 7.75}, {"date": "2029-02-01", "high": 11.5, "base": 9.5, "low": 7.5}, {"date": "2029-03-01", "high": 11.25, "base": 9.25, "low": 7.25}, {"date": "2029-04-01", "high": 11.0, "base": 9.0, "low": 7.0}, {"date": "2029-05-01", "high": 10.75, "base": 8.75, "low": 6.75}, {"date": "2029-06-01", "high": 10.5, "base": 8.5, "low": 6.5}, {"date": "2029-07-01", "high": 10.25, "base": 8.25, "low": 6.25}, {"date": "2029-08-01", "high": 10.0, "base": 8.0, "low": 6.0}];
const TEP_DEFAULT={"apartments": {"label": "Квартиры", "gns": 130716.66012842482, "total_area": 117647.0588235294, "useful": 80000, "saleable": 80000, "transfer": 0, "units": 1361.815754339119}, "ground_commercial": {"label": "Коммерция 1 эт.", "gns": 9664.049734985854, "total_area": 8695.652173913044, "useful": 7826.08695652174, "saleable": 7826.08695652174, "transfer": 0, "units": 0}, "standalone_retail": {"label": "Коммерция ОСЗ", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "offices": {"label": "Офисы", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "above_parking": {"label": "Наземный паркинг", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "underground_parking": {"label": "Подземный паркинг", "gns": 38763, "total_area": 38763, "useful": 0, "saleable": 0, "transfer": 0, "units": 1107.5142857142857}, "storage": {"label": "Кладовки", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "kindergarten": {"label": "ДОУ", "gns": 0, "total_area": 3000, "useful": 0, "saleable": 0, "transfer": 3000, "units": 250}, "school": {"label": "СОШ", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}, "clinic": {"label": "Поликлиника", "gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0}};
const FIELD_GROUPS=[["Сделка и сроки", [["purchase_price_mln", "Стоимость покупки / цена входа", "млн ₽", "number"], ["land_rights_cost_mln", "Оформление земельных правоотношений / смена ВРИ", "млн ₽", "number"], ["project_start", "Начало проекта", "дата", "date"], ["ird_months", "Срок ИРД до РнС", "мес.", "number"], ["construction_months", "Срок строительства", "мес.", "number"], ["sales_lag_months", "Лаг старта продаж после РнС", "мес.", "number"], ["bridge_repay_lag_months", "Лаг погашения БРИДЖ после РнС", "мес.", "number"], ["residual_sales_months", "Остаточные продажи после РВЭ", "мес.", "number"]]], ["Продажи", [["apartment_price_th", "Стартовая цена квартир", "тыс. ₽/м²", "number"], ["commercial_price_th", "Стартовая цена коммерции 1 этажа", "тыс. ₽/м²", "number"], ["parking_price_th", "Цена подземного машино-места", "тыс. ₽/шт.", "number"], ["storage_price_th", "Цена кладовой", "тыс. ₽/шт.", "number"], ["share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["pace_adjustment_pct", "Корректировка темпа", "%", "number"], ["inflation_after_rve_pct", "Инфляция после РВЭ", "% год", "number"], ["seasonal_reduction_pct", "Сезонное снижение темпа", "%", "number"], ["growth_stage1_pct", "Рост цены — этап 1", "%", "number"], ["growth_stage2_pct", "Рост цены — этап 2", "%", "number"], ["growth_stage3_pct", "Рост цены — этап 3", "%", "number"], ["growth_stage4_pct", "Рост цены — этап 4", "%", "number"], ["monthly_growth_pre_pct", "Ежемесячный рост цены до РВЭ", "%/мес.", "number"], ["monthly_growth_post_pct", "Ежемесячный рост цены после РВЭ", "%/мес.", "number"]]], ["Строительство", [["ird_th_per_sqm", "ИРД и согласования", "тыс. ₽/м² ГНС", "number"], ["design_p_th_per_sqm", "Проектирование стадии П", "тыс. ₽/м² ГНС", "number"], ["design_rd_th_per_sqm", "Проектирование стадии РД", "тыс. ₽/м² ГНС", "number"], ["preparation_th_per_sqm", "Подготовительные работы", "тыс. ₽/м² ГНС", "number"], ["main_above_th_per_sqm", "Основное строительство — наземная часть", "тыс. ₽/м² ГНС", "number"], ["main_under_th_per_sqm", "Основное строительство — подземная часть", "тыс. ₽/м² ГНС", "number"], ["utilities_th_per_sqm", "Наружные инженерные сети", "тыс. ₽/м² ГНС", "number"], ["landscaping_th_per_sqm", "Благоустройство", "тыс. ₽/м² ГНС", "number"], ["commissioning_th_per_sqm", "Сдача и ввод", "тыс. ₽/м² ГНС", "number"], ["site_maintenance_th_per_sqm", "Содержание стройплощадки", "тыс. ₽/м² ГНС", "number"], ["gc_fee_pct", "Вознаграждение генподрядчика", "% СМР", "number"], ["reserve_pct", "Резерв", "%", "number"], ["project_management_pct", "Управление проектом", "%", "number"], ["author_supervision_mln", "Авторский надзор", "млн ₽", "number"]]], ["Коммерческие расходы и налоги", [["marketing_pct", "Маркетинг", "% выручки", "number"], ["selling_pct", "Расходы на продажи", "% выручки", "number"], ["profit_tax_pct", "Налог на прибыль", "%", "number"], ["vat_pct", "НДС", "%", "number"]]], ["Финансирование", [["bridge_spread_pp", "Спред БРИДЖ", "п.п.", "number"], ["bridge_cap_spread_pp", "Спред капитализации БРИДЖ", "п.п.", "number"], ["pf_spread_pp", "Спред ПФ", "п.п.", "number"], ["pf_special_pct", "Специальная ставка ПФ", "%", "number"], ["limit_fee_pct", "Плата за лимит", "%", "number"], ["reservation_fee_pct", "Плата за резервирование", "%", "number"], ["discount_rate_pct", "Ставка дисконтирования", "%", "number"], ["bridge_interest_mode", "Проценты БРИДЖ при рефинансировании", "режим", "finance_select"], ["pf_transfer_income_pct", "Снижение спецставки при покрытии эскроу > 1x", "п.п. на 1x", "number"]]], ["Социальная нагрузка", [["social_mode", "Форма исполнения", "режим", "select"], ["social_comp_date", "Дата денежной компенсации", "дата", "date"], ["social_compensation_mln", "Социальный платеж / компенсация по ГлавАПУ", "млн ₽", "number"], ["kindergarten_places", "ДОУ — количество мест", "мест", "number"], ["kindergarten_cost_mln_per_place", "ДОУ — себестоимость места", "млн ₽/место", "number"], ["kindergarten_start", "ДОУ — начало строительства", "дата", "date"], ["kindergarten_months", "ДОУ — срок строительства", "мес.", "number"], ["school_places", "СОШ — количество мест", "мест", "number"], ["school_cost_mln_per_place", "СОШ — себестоимость места", "млн ₽/место", "number"], ["school_start", "СОШ — начало строительства", "дата", "date"], ["school_months", "СОШ — срок строительства", "мес.", "number"], ["clinic_capacity", "Поликлиника — мощность", "пос./смену", "number"], ["clinic_cost_mln_per_unit", "Поликлиника — себестоимость мощности", "млн ₽/(пос./смену)", "number"], ["clinic_start", "Поликлиника — начало строительства", "дата", "date"], ["clinic_months", "Поликлиника — срок строительства", "мес.", "number"], ["social_dou_gba_sqm", "ДОУ — общая площадь", "м²", "number"], ["social_dou_norm_sqm", "ДОУ — норматив площади на место", "м²/место", "number"], ["social_school_gba_sqm", "СОШ — общая площадь", "м²", "number"], ["social_school_norm_sqm", "СОШ — норматив площади на место", "м²/место", "number"], ["social_clinic_gba_sqm", "Поликлиника — общая площадь", "м²", "number"], ["social_clinic_norm_sqm", "Поликлиника — норматив площади", "м²/ед.", "number"]]], ["МФОЦ / офисы", [["offices_enabled", "Объект включен", "Да / Нет", "checkbox"], ["offices_gba_sqm", "Общая площадь (GBA)", "м²", "number"], ["offices_saleable_sqm", "Продаваемая площадь", "м²", "number"], ["offices_start", "Начало строительства", "дата", "date"], ["offices_months", "Срок строительства", "мес.", "number"], ["offices_cost_th_per_sqm", "Себестоимость строительства", "тыс. ₽/м² GBA", "number"], ["offices_sales_start", "Старт продаж", "дата", "date"], ["offices_price_th_per_sqm", "Стартовая цена", "тыс. ₽/м²", "number"], ["offices_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["offices_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["offices_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["offices_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"]]], ["ТЦ / коммерция ОСЗ", [["retail_enabled", "Объект включен", "Да / Нет", "checkbox"], ["retail_gba_sqm", "Общая площадь (GBA)", "м²", "number"], ["retail_saleable_sqm", "Продаваемая площадь", "м²", "number"], ["retail_start", "Начало строительства", "дата", "date"], ["retail_months", "Срок строительства", "мес.", "number"], ["retail_cost_th_per_sqm", "Себестоимость строительства", "тыс. ₽/м² GBA", "number"], ["retail_sales_start", "Старт продаж", "дата", "date"], ["retail_price_th_per_sqm", "Стартовая цена", "тыс. ₽/м²", "number"], ["retail_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["retail_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["retail_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["retail_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"]]], ["Наземный паркинг", [["above_parking_enabled", "Объект включен", "Да / Нет", "checkbox"], ["above_parking_spaces", "Количество машино-мест", "шт.", "number"], ["above_parking_cost_mln_per_space", "Себестоимость одного места", "млн ₽/место", "number"], ["above_parking_start", "Начало строительства", "дата", "date"], ["above_parking_months", "Срок строительства", "мес.", "number"], ["above_parking_sales_start", "Старт продаж", "дата", "date"], ["above_parking_price_mln_per_space", "Стартовая цена места", "млн ₽/место", "number"], ["above_parking_share_before_rve_pct", "Доля продаж до РВЭ", "%", "number"], ["above_parking_residual_months", "Остаточные продажи после РВЭ", "мес.", "number"], ["above_parking_growth_pre_pct", "Рост цены до РВЭ", "%/мес.", "number"], ["above_parking_growth_post_pct", "Рост цены после РВЭ", "%/мес.", "number"], ["above_parking_area_per_space_sqm", "Площадь на 1 место для ТЭП", "м²/место", "number"]]]];
const INPUT_DEFAULT={"project_class":"comfort","purchase_price_mln": 0, "construction_months": 24, "apartment_price_th": 350, "commercial_price_th": 350, "parking_price_th": 1500, "storage_price_th": 1000, "share_before_rve_pct": 85, "pace_adjustment_pct": 25, "inflation_after_rve_pct": 3, "seasonal_reduction_pct": -15, "growth_stage1_pct": 0, "growth_stage2_pct": 0, "growth_stage3_pct": 0, "growth_stage4_pct": 0, "ird_th_per_sqm": 1, "design_p_th_per_sqm": 2.5, "design_rd_th_per_sqm": 2.5, "preparation_th_per_sqm": 1, "main_above_th_per_sqm": 110, "utilities_th_per_sqm": 7.5, "landscaping_th_per_sqm": 5, "commissioning_th_per_sqm": 1, "site_maintenance_th_per_sqm": 1, "gc_fee_pct": 7, "reserve_pct": 5, "project_management_pct": 5, "marketing_pct": 3, "selling_pct": 4, "profit_tax_pct": 25, "vat_pct": 22, "bridge_spread_pp": 6, "bridge_cap_spread_pp": 6, "pf_spread_pp": 4.5, "pf_special_pct": 4.5, "limit_fee_pct": 0.5, "reservation_fee_pct": 0.5, "discount_rate_pct": 20, "monthly_growth_pre_pct": 1.5, "monthly_growth_post_pct": 0.25, "ird_months": 18, "sales_lag_months": 0, "bridge_repay_lag_months": 0, "residual_sales_months": 6, "social_comp_date": "2028-06-01", "social_compensation_mln": 0, "kindergarten_places": 250, "kindergarten_cost_mln_per_place": 2.75, "kindergarten_start": "2028-06-01", "kindergarten_months": 24, "school_places": 0, "school_cost_mln_per_place": 3, "school_start": "2028-06-01", "school_months": 30, "clinic_capacity": 0, "clinic_cost_mln_per_unit": 3, "clinic_start": "2028-06-01", "clinic_months": 24, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000, "offices_start": "2028-07-01", "offices_months": 24, "offices_cost_th_per_sqm": 200, "offices_sales_start": "2028-07-01", "offices_price_th_per_sqm": 500, "offices_share_before_rve_pct": 85, "offices_residual_months": 6, "offices_growth_pre_pct": 1.5, "offices_growth_post_pct": 0.25, "retail_gba_sqm": 10000, "retail_saleable_sqm": 6000, "retail_start": "2028-07-01", "retail_months": 24, "retail_cost_th_per_sqm": 200, "retail_sales_start": "2028-07-01", "retail_price_th_per_sqm": 500, "retail_share_before_rve_pct": 85, "retail_residual_months": 6, "retail_growth_pre_pct": 1.5, "retail_growth_post_pct": 0.25, "above_parking_spaces": 550, "above_parking_cost_mln_per_space": 1, "above_parking_start": "2028-07-01", "above_parking_months": 18, "above_parking_sales_start": "2028-07-01", "above_parking_price_mln_per_space": 2, "above_parking_share_before_rve_pct": 85, "above_parking_residual_months": 6, "above_parking_growth_pre_pct": 0.75, "above_parking_growth_post_pct": 0.2, "social_dou_gba_sqm": 3000, "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0, "project_start": "2027-01-01", "main_under_th_per_sqm": 110, "social_mode": "Строительство", "social_dou_norm_sqm": 12, "social_school_norm_sqm": 13, "social_clinic_norm_sqm": 15, "offices_enabled": false, "retail_enabled": false, "above_parking_enabled": false, "above_parking_area_per_space_sqm": 25, "rate_scenario": "low", "land_rights_cost_mln": 2864.291514155844, "author_supervision_mln": 19.55, "bridge_interest_mode": "Капитализация в ПФ", "pf_transfer_income_pct": 5.0};

let inputs=structuredClone(INPUT_DEFAULT), tep=structuredClone(TEP_DEFAULT), rates=structuredClone(RATE_DEFAULT), lastResult=null, glavapuImport=null;
const money=v=>(Number(v||0)/1e9).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:2})+' млрд ₽';
const mln=v=>(Number(v||0)/1e6).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:1})+' млн ₽';
const pct=v=>(Number(v||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:2})+'%';
const mult=v=>Number(v||0).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x';
const num=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:1});
const th=v=>Number(v||0).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:1})+' тыс. ₽';
const dateRu=v=>{if(!v)return '—';const [y,m,d]=String(v).slice(0,10).split('-');return `${d}.${m}.${y}`};
const irrFmt=v=>v==null?'N/A':pct(v);
const inputDisplay=v=>Math.round(Number(v||0)*10)/10;

function openTab(id,btn){
 document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');
 document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
 (btn||document.querySelector(`[data-tab="${id}"]`)).classList.add('active');
}
function calculateAndOpen(id){calculate().then(()=>openTab(id))}


async function uploadGlavapu(){
 const file=document.getElementById('glavapuFile').files[0];
 if(!file){glavapuStatus.innerHTML='<span class="import-error">Выберите Excel-файл.</span>';return}
 if(!file.name.toLowerCase().endsWith('.xlsx')){glavapuStatus.innerHTML='<span class="import-error">Нужен файл .xlsx калькулятора ГлавАПУ.</span>';return}
 glavapuStatus.textContent='Разбираю '+file.name+'…';
 glavapuPreview.style.display='none';
 try{
   const response=await fetch('/import/glavapu?filename='+encodeURIComponent(file.name),{
     method:'POST',
     headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
     body:await file.arrayBuffer()
   });
   const payload=await response.json();
   if(!response.ok)throw new Error(payload.detail||'Ошибка импорта');
   glavapuImport=payload;
   renderGlavapuPreview(payload);
   glavapuStatus.innerHTML='<span class="import-ok">Файл распознан. Проверьте значения перед применением.</span>';
 }catch(e){
   glavapuStatus.innerHTML='<span class="import-error">'+String(e.message||e)+'</span>';
 }
}

function renderGlavapuPreview(data){
 if(!data)return;
 const n=data.normalized||{};
 const src=data.source||{};
 glavapuSummary.innerHTML=[
   ['Файл',src.filename||'—'],
   ['Площадь территории',(n.site_area_ha??'—')+(n.site_area_ha!=null?' га':'')],
   ['Площадь квартир',(n.apartment_area_sqm!=null?num(n.apartment_area_sqm)+' м²':'—')],
   ['Смена ВРИ',(n.change_vri_mln!=null?Number(n.change_vri_mln).toLocaleString('ru-RU',{maximumFractionDigits:3})+' млн ₽':'—')],
   ['Соцплатеж',(n.social_compensation_total_mln!=null?Number(n.social_compensation_total_mln).toLocaleString('ru-RU',{maximumFractionDigits:3})+' млн ₽':'—')]
 ].map(x=>`<div><small>${x[0]}</small><b>${x[1]}</b></div>`).join('');
 glavapuRows.innerHTML=(data.recognized||[]).map(x=>`<tr>
   <td>${x.label}</td><td>${x.display}</td><td>${x.unit||''}</td><td>${x.target}</td>
 </tr>`).join('');
 glavapuWarnings.innerHTML=(data.warnings||[]).map(x=>'• '+x).join('<br>');
 glavapuPreview.style.display='block';
}

function applyGlavapu(){
 if(!glavapuImport){glavapuStatus.innerHTML='<span class="import-error">Сначала разберите файл.</span>';return}
 Object.assign(inputs,glavapuImport.mappings.inputs||{});
 Object.entries(glavapuImport.mappings.tep||{}).forEach(([key,vals])=>{
   if(tep[key])Object.assign(tep[key],vals);
 });
 inputs._glavapu_import={
   source:glavapuImport.source,
   normalized:glavapuImport.normalized,
   recognized:glavapuImport.recognized,
   warnings:glavapuImport.warnings
 };
 // Force underground parking from ГлавАПУ source, even if an old project was saved in localStorage.
 repairParkingFromGlavapu();
 renderInputs();
 renderTep();
 renderGlavapuPreview(glavapuImport);
 glavapuStatus.innerHTML='<span class="import-ok">Данные ГлавАПУ применены к Вводным и ТЭП. Подземный паркинг пересчитан как постоянные + гостевые места × 35 м²; приобъектные и кратковременные исключены.</span>';
 calculate();
}

function renderStoredGlavapu(){
 const stored=inputs._glavapu_import;
 if(!stored)return;
 glavapuImport={source:stored.source||{},normalized:stored.normalized||{},recognized:stored.recognized||[],warnings:stored.warnings||[],mappings:{inputs:{},tep:{}}};
 renderGlavapuPreview(glavapuImport);
 glavapuStatus.innerHTML='<span class="import-ok">Показаны данные последнего применённого файла ГлавАПУ.</span>';
}


function getGlavapuUnderground(){
 const stored=inputs._glavapu_import;
 const n=stored&&stored.normalized?stored.normalized:null;
 if(!n)return null;
 const permanent=Number(n.parking_permanent||0);
 const guest=Number(n.parking_guest||0);
 const spaces=permanent+guest;
 if(spaces<=0)return null;
 return {permanent,guest,spaces,gns:spaces*35};
}

function repairParkingFromGlavapu(){
 const p=getGlavapuUnderground();
 if(!p||!tep.underground_parking)return false;
 tep.underground_parking.units=p.spaces;
 tep.underground_parking.gns=p.gns;
 tep.underground_parking.total_area=p.gns;
 tep.underground_parking.useful=0;
 tep.underground_parking.saleable=0;
 tep.underground_parking.transfer=0;
 return true;
}


function renderProjectClassPreview(){
 const select=document.getElementById('projectClassSelect');
 const key=select?select.value:(inputs.project_class||'comfort');
 const p=PROJECT_CLASS_PRESETS[key];
 const box=document.getElementById('projectClassPreview');
 if(!box)return;
 if(!p){
   box.innerHTML=`<div><small>Режим</small><b>Пользовательские значения</b></div>`;
   return;
 }
 box.innerHTML=[
   ['Класс',p.label],
   ['Квартиры',Number(p.apartment_price_th).toLocaleString('ru-RU')+' тыс. ₽/м²'],
   ['Коммерция',Number(p.commercial_price_th).toLocaleString('ru-RU')+' тыс. ₽/м²'],
   ['Машино-место',Number(p.parking_price_th).toLocaleString('ru-RU')+' тыс. ₽'],
   ['Надземная часть',Number(p.main_above_th_per_sqm).toLocaleString('ru-RU')+' тыс. ₽/м²'],
   ['Подземная часть',Number(p.main_under_th_per_sqm).toLocaleString('ru-RU')+' тыс. ₽/м²']
 ].map(x=>`<div><small>${x[0]}</small><b>${x[1]}</b></div>`).join('');
}

function applyProjectClassPreset(){
 const select=document.getElementById('projectClassSelect');
 const key=select?select.value:'comfort';
 const p=PROJECT_CLASS_PRESETS[key];
 if(!p)return;
 inputs.project_class=key;
 ['apartment_price_th','commercial_price_th','parking_price_th','main_above_th_per_sqm','main_under_th_per_sqm'].forEach(k=>inputs[k]=Number(p[k]));
 renderInputs();
 if(document.getElementById('projectClassSelect'))document.getElementById('projectClassSelect').value=key;
 renderProjectClassPreview();
 calculate();
}

function syncProjectClassSelector(){
 const select=document.getElementById('projectClassSelect');
 if(!select)return;
 const key=inputs.project_class&&PROJECT_CLASS_PRESETS[inputs.project_class]?inputs.project_class:'custom';
 select.value=key;
 renderProjectClassPreview();
}

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
     el.onchange=()=>{inputs[id]=type==='checkbox'?el.checked:(type==='number'?Number(el.value):el.value);if(['apartment_price_th','commercial_price_th','parking_price_th','main_above_th_per_sqm','main_under_th_per_sqm'].includes(id)){inputs.project_class='custom';syncProjectClassSelector()}if(['offices_enabled','retail_enabled','above_parking_enabled','social_mode','kindergarten_places','school_places','clinic_capacity','social_dou_gba_sqm','social_school_gba_sqm','social_clinic_gba_sqm','above_parking_spaces','above_parking_area_per_space_sqm'].includes(id))syncTep(false)};
     wrap.appendChild(el);grid.appendChild(wrap);
   });det.appendChild(grid);box.appendChild(det);
 });
 rateScenario.value=inputs.rate_scenario||'low';
}

function applyScenario(name){
 const sc=SCENARIOS[name]||SCENARIOS.base;
 inputs.scenario_revenue_multiplier=Number(sc.scenario_revenue_multiplier||1);
 inputs.scenario_cost_multiplier=Number(sc.scenario_cost_multiplier||1);
 scenarioSelect.value=name;
 renderScenarioNote();
 calculate();
}

function renderScenarioNote(){
 const rev=Number(inputs.scenario_revenue_multiplier||1);
 const cost=Number(inputs.scenario_cost_multiplier||1);
 const revPct=Math.round((rev-1)*100);
 const costPct=Math.round((cost-1)*100);
 const box=document.getElementById('scenarioNote');
 if(box){
   const f=v=>v===0?'без корректировки':(v>0?'+':'')+v+'%';
   box.textContent=`Доходы ${f(revPct)} · расходы ${f(costPct)}`;
 }
}

function renderTep(){
 repairParkingFromGlavapu();
 const body=tepBody;body.innerHTML='';
 const importedParking=getGlavapuUnderground();
 Object.entries(tep).forEach(([key,row])=>{
   const tr=document.createElement('tr');
   let label=row.label;
   if(key==='underground_parking'&&importedParking){
     label+=` <span style="display:block;font-size:10px;color:#777;margin-top:3px">ГлавАПУ: ${num(importedParking.permanent)} постоянных + ${num(importedParking.guest)} гостевых = ${num(importedParking.spaces)} м/м × 35 м²</span>`;
   }
   let html=`<td>${label}</td>`;
   ['gns','total_area','useful','saleable','transfer','units'].forEach(col=>{
     const locked=key==='underground_parking'&&importedParking&&['gns','total_area','useful','saleable','transfer','units'].includes(col);
     html+=`<td><input type="number" step="0.1" value="${inputDisplay(row[col])}" ${locked?'readonly style="background:#f3f3f1;color:#555"':''} onchange="tep['${key}']['${col}']=Number(this.value);updateTepTotals()"></td>`;
   });tr.innerHTML=html;body.appendChild(tr);
 });updateTepTotals();
}
function updateTepTotals(){
 repairParkingFromGlavapu();
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
 // ГлавАПУ has priority over any old/stale underground-parking TEP values.
 repairParkingFromGlavapu();
 if(rerender)renderTep();else updateTepTotals();
}
function renderRates(){
 rateBody.innerHTML='';rates.forEach((r,i)=>{const tr=document.createElement('tr');tr.innerHTML=`<td><input type="date" value="${r.date}" onchange="rates[${i}].date=this.value"></td><td><input type="number" step=".01" value="${r.high}" onchange="rates[${i}].high=Number(this.value)"></td><td><input type="number" step=".01" value="${r.base}" onchange="rates[${i}].base=Number(this.value)"></td><td><input type="number" step=".01" value="${r.low}" onchange="rates[${i}].low=Number(this.value)"></td>`;rateBody.appendChild(tr)});
}

async function calculate(){
 document.querySelectorAll('[id^=f_]').forEach(el=>{const id=el.id.slice(2);inputs[id]=el.type==='checkbox'?el.checked:(el.type==='number'?Number(el.value):el.value)});
 inputs.rate_scenario=rateScenario.value;
 repairParkingFromGlavapu();
 const response=await fetch('/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inputs,tep,rates})});
 lastResult=await response.json();
 // The server is authoritative for derived TEP. Synchronize corrected values
 // back into the editable browser state (especially ГлавАПУ underground parking).
 if(lastResult&&lastResult.tep&&Array.isArray(lastResult.tep.rows)){
   lastResult.tep.rows.forEach(r=>{
     if(!tep[r.key])return;
     ['gns','total_area','useful','saleable','transfer','units'].forEach(k=>{
       if(r[k]!=null)tep[r.key][k]=Number(r[k]);
     });
   });
 }
 repairParkingFromGlavapu();
 renderResult();
 if(document.getElementById('tep')&&document.getElementById('tep').classList.contains('active'))renderTep();
 return lastResult;
}

function row(label,value){return `<tr><td>${label}</td><td>${value}</td></tr>`}
function renderResult(){
 if(!lastResult)return;const r=lastResult,f=r.finance;
 dateBoxes.innerHTML=[['Начало',r.dates.project_start],['РнС',r.dates.permit],['Старт продаж',r.dates.sales_start],['РВЭ',r.dates.rve]].map(x=>`<div class="datebox">${x[0]}<b>${x[1]}</b></div>`).join('');
 const kpis=[
  ['Выручка',money(r.summary.revenue)],
  ['CAPEX',money(r.summary.capex)],
  ['Проценты и комиссии',money(r.summary.financing_cost)],
  ['LLCR',mult(r.summary.llcr)]
 ];
 quickKpi.innerHTML=kpis.map(x=>`<div class="kpi"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('');

 const reportKpis=[
  ['Выручка',money(r.summary.revenue)],
  ['EBITDA',money(r.summary.ebitda)],
  ['Чистая прибыль',money(r.summary.net_profit)],
  ['Маржинальность',pct(r.summary.margin)],
  ['NPV @'+Number(inputs.discount_rate_pct||20).toLocaleString('ru-RU')+'%',money(r.summary.npv)],
  ['IRR equity',irrFmt(r.summary.irr_equity)],
  ['LLCR',mult(r.summary.llcr)],
  ['Расчётный БРИДЖ',money(r.report.financing.calculated_bridge)],
  ['Фактический БРИДЖ',money(r.report.financing.actual_bridge)],
  ['Пиковый ПФ',money(r.report.financing.pf_peak)]
 ];
 reportKpi.innerHTML=reportKpis.map(x=>`<div class="kpi"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('');

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
  `<tr><th>Итого проценты и комиссии</th><th>${money(f.financing_cost)}</th></tr>`;

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

 economicsTable.innerHTML=
  row('Выручка',money(r.summary.revenue))+
  row('CAPEX проекта',`(${money(r.summary.capex)})`)+
  row('Маркетинг и продажи',`(${money(r.summary.commercial_costs)})`)+
  `<tr><th>EBITDA</th><th>${money(r.summary.ebitda)}</th></tr>`+
  row('Проценты и комиссии',`(${money(r.summary.financing_cost)})`)+
  `<tr><th>Прибыль до налога</th><th>${money(r.summary.profit_before_tax)}</th></tr>`+
  row('Налог на прибыль',`(${money(r.summary.profit_tax)})`)+
  `<tr><th>Чистая прибыль</th><th>${money(r.summary.net_profit)}</th></tr>`+
  row('Маржинальность',pct(r.summary.margin))+
  row('NPV',money(r.summary.npv))+
  row('IRR equity',irrFmt(r.summary.irr_equity));

 projectParamsTable.innerHTML=
  row('Класс проекта',inputs.project_class&&PROJECT_CLASS_PRESETS[inputs.project_class]?PROJECT_CLASS_PRESETS[inputs.project_class].label:'Пользовательский')+
  row('Сценарий',scenarioSelect.options[scenarioSelect.selectedIndex].text)+
  row('Доходы к базовому сценарию',Number(r.summary.scenario_revenue_multiplier||1).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x')+
  row('Расходы к базовому сценарию',Number(r.summary.scenario_cost_multiplier||1).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x')+
  row('Стоимость покупки',money(Number(inputs.purchase_price_mln||0)*1e6))+
  row('Стоимость смены ВРИ / права',money(Number(inputs.land_rights_cost_mln||0)*1e6))+
  row('Социальный платёж',money(r.summary.social_payment))+
  row('Проектирование П и РД',money((r.capex.design_p||0)+(r.capex.design_rd||0)))+
  row('Продаваемая площадь',num(r.summary.monetizable_saleable_sqm)+' м²')+
  row('Средняя цена квартир',th(r.summary.average_apartment_price_th))+
  row('Полная себестоимость',th(r.summary.full_cost_per_saleable_th)+'/м²')+
  row('Строительная себестоимость',th(r.summary.construction_cost_per_gns_th)+'/м² ГНС')+
  row('EBITDA на продаваемый м²',th(r.summary.ebitda_per_saleable_th)+'/м²')+
  row('Чистая прибыль на продаваемый м²',th(r.summary.net_profit_per_saleable_th)+'/м²');

 reportFinanceTable.innerHTML=
  row('Расчётный БРИДЖ',money(r.report.financing.calculated_bridge))+
  row('Фактический / пиковый БРИДЖ',money(r.report.financing.actual_bridge))+
  row('Лимит ПФ',money(r.report.financing.pf_limit))+
  row('Пиковый ПФ',money(r.report.financing.pf_peak))+
  row('Средняя ставка БРИДЖ',pct(r.report.financing.avg_bridge_rate))+
  row('Средняя ставка ПФ',pct(r.report.financing.avg_pf_rate))+
  row('Проценты и комиссии',money(r.report.financing.interest_and_fees))+
  `<tr><th>LLCR</th><th>${mult(r.summary.llcr)}</th></tr>`;

 const sb=r.summary.social_payment_breakdown||{};
 const socialMode=r.summary.social_payment_mode||'—';
 socialTable.innerHTML=
  row('Режим',socialMode)+
  row('ДОО — компенсация',money(Number(sb.kindergarten_mln||0)*1e6))+
  row('СОШ — компенсация',money(Number(sb.school_mln||0)*1e6))+
  row('Поликлиника — компенсация',money(Number(sb.clinic_mln||0)*1e6))+
  `<tr><th>Социальный платёж / всего</th><th>${money(r.summary.social_payment)}</th></tr>`;

 unitEconomicsTable.innerHTML=(r.report.unit_economics||[]).map(x=>`<tr>
  <td>${x.label}</td>
  <td>${money(x.total)}</td>
  <td>${Number(x.per_gns_th||0).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})}</td>
  <td>${Number(x.per_saleable_th||0).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})}</td>
 </tr>`).join('');

 const expenseRows=(r.report.expense_structure||[]);
 expenseStructureChart.innerHTML=expenseRows.map(x=>`<div class="expense-row">
   <div class="expense-label">${x.label}</div>
   <div class="expense-track"><div class="expense-fill" style="width:${Math.max(0,Math.min(100,Number(x.share||0)*100))}%"></div></div>
   <div class="expense-pct">${(Number(x.share||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})}%</div>
   <div class="expense-value">${money(x.value)}</div>
 </div>`).join('');
 expenseStructureTable.innerHTML=expenseRows.map(x=>`<tr>
   <td>${x.label}</td>
   <td>${money(x.value)}</td>
   <td>${(Number(x.share||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})}%</td>
 </tr>`).join('');
 expenseTotal.textContent=money(r.summary.total_expenses||expenseRows.reduce((s,x)=>s+Number(x.value||0),0));

 ratesDebtTable.innerHTML=
  row('Сценарий ключевой ставки',String(inputs.rate_scenario||'—'))+
  row('Средняя ставка БРИДЖ',pct(r.report.financing.avg_bridge_rate))+
  row('Средняя ставка ПФ',pct(r.report.financing.avg_pf_rate))+
  row('Пиковый БРИДЖ',money(r.report.financing.actual_bridge))+
  row('Пиковый ПФ',money(r.report.financing.pf_peak))+
  row('Лимит ПФ',money(r.report.financing.pf_limit))+
  row('Проценты и комиссии',money(r.report.financing.interest_and_fees))+
  row('LLCR',mult(r.summary.llcr));

 salesReportTable.innerHTML=(r.report.products||[]).map(p=>`<tr>
  <td>${p.label}</td>
  <td>${num(p.quantity)} ${p.unit}</td>
  <td>${num(p.pace_pre)} ${p.unit}/мес</td>
  <td>${pct(p.share_before_rve)}</td>
  <td>${th(p.start_price_th)}</td>
  <td>${th(p.avg_price_th)}</td>
  <td>${money(p.revenue)}</td>
  <td>${dateRu(p.sales_start)}</td>
  <td>${dateRu(p.sales_end)}</td>
 </tr>`).join('');

 renderGantt('calendarGantt',r.report.calendar);
 calendarRange.textContent=dateRu(r.report.calendar.start)+' — '+dateRu(r.report.calendar.end);

 const revNames={apartments:'Квартиры',ground_commercial:'Коммерция 1 этажа',underground_parking:'Подземный паркинг',storage:'Кладовки',offices:'Офисы',standalone_retail:'Коммерция ОСЗ',above_parking:'Наземный паркинг'};
 revenueTable.innerHTML=Object.entries(r.revenue).filter(([key])=>key!=='total').map(([key,v])=>row(revNames[key]||key,money(v))).join('')+`<tr><th>Итого</th><th>${money(r.revenue.total)}</th></tr>`;
 const capNames={land_rights:'Земля / смена ВРИ',ird:'ИРД',design_p:'Проект П',design_rd:'Проект РД',author_supervision:'Авторский надзор',preparation:'Подготовительные работы',main_above:'Основное строительство — наземная часть',main_under:'Основное строительство — подземная часть',utilities:'Наружные сети',landscaping:'Благоустройство',commissioning:'Сдача и ввод',site_maintenance:'Содержание стройплощадки',social:'Социальный платеж / соцобъекты',offices:'Офисы',standalone_retail:'Коммерция ОСЗ',above_parking:'Наземный паркинг',gc_fee:'Генподрядчик',reserve:'Резерв',project_management:'Управление проектом'};
 capexTable.innerHTML=Object.entries(r.capex).filter(([key])=>key!=='total').map(([key,v])=>row(capNames[key]||key,money(v))).join('')+`<tr><th>Итого</th><th>${money(r.capex.total)}</th></tr>`;
 reportTep.innerHTML=
  `<thead><tr><th>Продукт</th><th>ГНС, м²</th><th>Продаваемая площадь, м²</th><th>Количество, шт.</th></tr></thead>`+
  `<tbody>`+
  r.tep.rows.map(x=>`<tr><td>${x.label}</td><td>${num(x.gns)}</td><td>${num(x.saleable)}</td><td>${num(x.units)}</td></tr>`).join('')+
  `</tbody><tfoot><tr><th>Итого</th><th>${num(r.tep.total.gns)}</th><th>${num(r.tep.total.saleable)}</th><th>${num(r.tep.total.units)}</th></tr></tfoot>`;
}


function renderGantt(targetId,calendar){
 const target=document.getElementById(targetId);if(!target||!calendar){return}
 const events=calendar.events||[];if(!events.length){target.innerHTML='';return}
 const start=new Date(calendar.start+'T00:00:00'),end=new Date(calendar.end+'T00:00:00');
 const total=Math.max(1,(end-start)/(1000*60*60*24));
 const pos=iso=>Math.max(0,Math.min(100,(new Date(iso+'T00:00:00')-start)/(1000*60*60*24)/total*100));
 const groups=[];events.forEach(e=>{if(!groups.includes(e.group))groups.push(e.group)});
 let years='';for(let y=start.getFullYear();y<=end.getFullYear();y++){const x=pos(`${y}-01-01`);years+=`<div class="gantt-year" style="left:${x}%">${y}</div>`}
 let html=`<div class="gantt"><div class="gantt-axis"><div class="gantt-label"><b>Этап / событие</b></div><div class="gantt-track">${years}</div></div>`;
 groups.forEach(g=>{
   html+=`<div class="gantt-row"><div class="gantt-label group">${g}</div><div class="gantt-track"></div></div>`;
   events.filter(e=>e.group===g).forEach(e=>{
     const l=pos(e.start),rgt=pos(e.end),w=Math.max(.4,rgt-l);
     let cls='';if(g==='Финансирование')cls=' finance';else if(g==='Продажи')cls=' sales';else if(g==='Социальная нагрузка')cls=' social';
     const shape=e.kind==='milestone'
       ? `<div class="gantt-diamond" style="left:${l}%"></div>`
       : `<div class="gantt-bar${cls}" style="left:${l}%;width:${w}%"></div>`;
     html+=`<div class="gantt-row"><div class="gantt-label">${e.label}<span class="gantt-date">${dateRu(e.start)}${e.end!==e.start?' — '+dateRu(e.end):''}</span></div><div class="gantt-track">${years}${shape}</div></div>`;
   });
 });
 html+='</div>';target.innerHTML=html;
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
function resetAll(){localStorage.removeItem('plato_v04');inputs=structuredClone(INPUT_DEFAULT);tep=structuredClone(TEP_DEFAULT);rates=structuredClone(RATE_DEFAULT);scenarioSelect.value='base';inputs.project_class='comfort';inputs.scenario_revenue_multiplier=1;inputs.scenario_cost_multiplier=1;renderInputs();renderTep();renderRates();renderScenarioNote();syncProjectClassSelector();calculate()}

loadLocal();
{
 const sc=SCENARIOS[scenarioSelect.value]||SCENARIOS.base;
 // Old saved projects did not have the new transparent scenario multipliers.
 // Treat their current inputs as the BASE model and only apply the selected +/-10% overlay.
 if(inputs.scenario_revenue_multiplier==null)inputs.scenario_revenue_multiplier=Number(sc.scenario_revenue_multiplier||1);
 if(inputs.scenario_cost_multiplier==null)inputs.scenario_cost_multiplier=Number(sc.scenario_cost_multiplier||1);
}
repairParkingFromGlavapu();renderInputs();renderTep();renderRates();renderStoredGlavapu();renderScenarioNote();syncProjectClassSelector();calculate();
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE
