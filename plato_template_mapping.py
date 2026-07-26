from __future__ import annotations

"""Mapping for the formula-driven PLATO_template 2.xlsx master workbook.

The exporter writes the current web calculation into the Base scenario column E
and keeps C3 = "Базовый", so the existing selected-value formulas in column G
continue to drive the original PLATO cash-flow model.

Percentage inputs in the web app are stored as whole percentages (85, 5, 0.5)
while the workbook uses Excel decimals (0.85, 0.05, 0.005).  Such mappings use
transform="pct".
"""

MASTER_TEMPLATE_NAME = "PLATO_template 2.xlsx"
ACTIVE_SCENARIO_CELL = "Вводные!C3"
ACTIVE_SCENARIO_VALUE = "Базовый"

# Web input -> workbook hardcoded input cell for the Base scenario.
INPUT_CELL_MAP: dict[str, tuple[str, str]] = {
    "purchase_price_mln": ("Вводные!E6", "number"),
    "project_start": ("Вводные!E7", "date"),
    "construction_months": ("Вводные!E9", "number"),
    "apartment_price_th": ("Вводные!E11", "number"),
    "commercial_price_th": ("Вводные!E12", "number"),
    "parking_price_th": ("Вводные!E13", "number"),
    "storage_price_th": ("Вводные!E14", "number"),
    "share_before_rve_pct": ("Вводные!E15", "pct"),
    "pace_adjustment_pct": ("Вводные!E16", "pct"),
    "inflation_after_rve_pct": ("Вводные!E17", "pct"),
    "seasonal_reduction_pct": ("Вводные!E18", "pct"),
    "growth_stage1_pct": ("Вводные!E19", "pct"),
    "growth_stage2_pct": ("Вводные!E20", "pct"),
    "growth_stage3_pct": ("Вводные!E21", "pct"),
    "growth_stage4_pct": ("Вводные!E22", "pct"),
    "ird_th_per_sqm": ("Вводные!E23", "number"),
    "design_p_th_per_sqm": ("Вводные!E24", "number"),
    "design_rd_th_per_sqm": ("Вводные!E25", "number"),
    "preparation_th_per_sqm": ("Вводные!E26", "number"),
    "main_above_th_per_sqm": ("Вводные!E27", "number"),
    "utilities_th_per_sqm": ("Вводные!E28", "number"),
    "landscaping_th_per_sqm": ("Вводные!E29", "number"),
    "commissioning_th_per_sqm": ("Вводные!E30", "number"),
    "site_maintenance_th_per_sqm": ("Вводные!E31", "number"),
    "gc_fee_pct": ("Вводные!E32", "pct"),
    "reserve_pct": ("Вводные!E33", "pct"),
    "project_management_pct": ("Вводные!E34", "pct"),
    "marketing_pct": ("Вводные!E35", "pct"),
    "selling_pct": ("Вводные!E36", "pct"),
    "profit_tax_pct": ("Вводные!E37", "pct"),
    "vat_pct": ("Вводные!E38", "pct"),
    "bridge_spread_pp": ("Вводные!E39", "pct"),
    "bridge_cap_spread_pp": ("Вводные!E40", "pct"),
    "pf_spread_pp": ("Вводные!E41", "pct"),
    "pf_special_pct": ("Вводные!E42", "pct"),
    "limit_fee_pct": ("Вводные!E43", "pct"),
    "reservation_fee_pct": ("Вводные!E44", "pct"),
    "discount_rate_pct": ("Вводные!E45", "pct"),
    "ird_months": ("Вводные!E48", "number"),
    "sales_lag_months": ("Вводные!E49", "number"),
    "bridge_repay_lag_months": ("Вводные!E50", "number"),
    "residual_sales_months": ("Вводные!E51", "number"),

    "social_mode": ("Вводные!G82", "social_mode"),
    "social_comp_date": ("Вводные!E83", "date"),
    "kindergarten_places": ("Вводные!E84", "number"),
    "kindergarten_cost_mln_per_place": ("Вводные!E85", "number"),
    "kindergarten_start": ("Вводные!E86", "date"),
    "kindergarten_months": ("Вводные!E87", "number"),
    "school_places": ("Вводные!E89", "number"),
    "school_cost_mln_per_place": ("Вводные!E90", "number"),
    "school_start": ("Вводные!E91", "date"),
    "school_months": ("Вводные!E92", "number"),
    "clinic_capacity": ("Вводные!E94", "number"),
    "clinic_cost_mln_per_unit": ("Вводные!E95", "number"),
    "clinic_start": ("Вводные!E96", "date"),
    "clinic_months": ("Вводные!E97", "number"),
    "social_dou_norm_sqm": ("Вводные!I148", "number"),
    "social_school_norm_sqm": ("Вводные!I149", "number"),
    "social_clinic_norm_sqm": ("Вводные!I150", "number"),

    "offices_enabled": ("Вводные!G106", "bool_ru"),
    "offices_gba_sqm": ("Вводные!E107", "number"),
    "offices_saleable_sqm": ("Вводные!E108", "number"),
    "offices_start": ("Вводные!E109", "date"),
    "offices_months": ("Вводные!E110", "number"),
    "offices_cost_th_per_sqm": ("Вводные!E111", "number"),
    "offices_sales_start": ("Вводные!E112", "date"),
    "offices_price_th_per_sqm": ("Вводные!E113", "number"),
    "offices_share_before_rve_pct": ("Вводные!E114", "pct"),
    "offices_residual_months": ("Вводные!E115", "number"),
    "offices_growth_pre_pct": ("Вводные!E116", "pct"),
    "offices_growth_post_pct": ("Вводные!E117", "pct"),

    "retail_enabled": ("Вводные!G119", "bool_ru"),
    "retail_gba_sqm": ("Вводные!E120", "number"),
    "retail_saleable_sqm": ("Вводные!E121", "number"),
    "retail_start": ("Вводные!E122", "date"),
    "retail_months": ("Вводные!E123", "number"),
    "retail_cost_th_per_sqm": ("Вводные!E124", "number"),
    "retail_sales_start": ("Вводные!E125", "date"),
    "retail_price_th_per_sqm": ("Вводные!E126", "number"),
    "retail_share_before_rve_pct": ("Вводные!E127", "pct"),
    "retail_residual_months": ("Вводные!E128", "number"),
    "retail_growth_pre_pct": ("Вводные!E129", "pct"),
    "retail_growth_post_pct": ("Вводные!E130", "pct"),

    "above_parking_enabled": ("Вводные!G132", "bool_ru"),
    "above_parking_spaces": ("Вводные!E133", "number"),
    "above_parking_cost_mln_per_space": ("Вводные!E134", "number"),
    "above_parking_start": ("Вводные!E135", "date"),
    "above_parking_months": ("Вводные!E136", "number"),
    "above_parking_sales_start": ("Вводные!E137", "date"),
    "above_parking_price_mln_per_space": ("Вводные!E138", "number"),
    "above_parking_share_before_rve_pct": ("Вводные!E139", "pct"),
    "above_parking_residual_months": ("Вводные!E140", "number"),
    "above_parking_growth_pre_pct": ("Вводные!E141", "pct"),
    "above_parking_growth_post_pct": ("Вводные!E142", "pct"),
}

# Inputs outside the central assumptions sheet.
DIRECT_CELL_MAP: dict[str, tuple[str, str]] = {
    "land_rights_cost_mln": ("Расчет ВРИ (ТЭП)!D73", "number"),
    "social_compensation_mln": ("Расчет ВРИ (ТЭП)!D83", "number"),
}

# The ГлавАПУ-style calculation sheet feeds the formula-driven TEP sheet.
TEP_CELL_MAP: dict[str, dict[str, tuple[str, str]]] = {
    "apartments": {
        "gns": ("Расчет ВРИ (ТЭП)!D10", "number"),
        "total_area": ("Расчет ВРИ (ТЭП)!D18", "number"),
        "useful": ("Расчет ВРИ (ТЭП)!D24", "number"),
        "saleable": ("Расчет ВРИ (ТЭП)!D24", "number"),
        "units": ("Расчет ВРИ (ТЭП)!D6", "number"),
    },
    "ground_commercial": {
        "gns": ("Расчет ВРИ (ТЭП)!D11", "number"),
        "total_area": ("Расчет ВРИ (ТЭП)!D19", "number"),
        "useful": ("Расчет ВРИ (ТЭП)!D25", "number"),
        "saleable": ("Расчет ВРИ (ТЭП)!D25", "number"),
    },
    "underground_parking": {
        "units": ("Расчет ВРИ (ТЭП)!D68", "number"),
    },
    "storage": {
        "gns": ("ТЭП!C34", "number"),
        "total_area": ("ТЭП!D34", "number"),
        "useful": ("ТЭП!F34", "number"),
        "saleable": ("ТЭП!G34", "number"),
        "units": ("ТЭП!I34", "number"),
    },
}

# Values that are deliberately derived by the workbook and must not be overwritten.
DERIVED_WEB_INPUTS = {
    "monthly_growth_pre_pct",       # converted to target cumulative growth in Вводные!E52
    "monthly_growth_post_pct",      # derived from annual inflation in Вводные!E17 / E47
    "social_dou_gba_sqm",           # derived as places × norm in E148
    "social_school_gba_sqm",        # derived as places × norm in E149
    "social_clinic_gba_sqm",        # derived as capacity × norm in E150
    "above_parking_area_per_space_sqm",  # used to calculate E144 at export time
}

# Structural differences that the exporter must handle explicitly rather than
# silently dropping or averaging values.
STRUCTURAL_CONTROLS = {
    "main_under_th_per_sqm": "The master workbook has one ЖК construction rate in Вводные!E27. Export must calculate a weighted rate from above- and underground GNS or add a separate underground driver before release.",
    "author_supervision_pct": "The master workbook carries author supervision as a detailed CF article, but it is not exposed as a central Вводные assumption.",
    "technical_supervision_pct": "The master workbook carries technical customer / construction control in cf_1/cf_2, but the central Вводные block does not expose a separate editable row.",
    "bridge_interest_mode": "Mapped to КРЕДИТЫ!D42 after confirming the web enum against the workbook 1/0 convention.",
    "pf_transfer_income_pct": "Mapped to КРЕДИТЫ!D17 after confirming percentage semantics.",
}
