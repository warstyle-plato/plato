"""Сверка «1-я Останкинская» (77:02:0018012:5) с внешней (банковской) сводкой.

Воспроизводит наш расчёт по вводным из PDF DevelopAid 0.25.74 (расчёт
57fb1045b1c7) и пошагово подставляет вводные внешней модели, чтобы отделить
разницу вводных от разницы методики. Разбор — docs/compare_ostankinskaya_external.md.

Запуск: python3 docs/experiments/compare_ostankinskaya_external.py
"""

from __future__ import annotations

import contextlib
import copy
import io
import os
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
for _key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "DEVELOPAID_WORKBOOK_CACHE",
             "NORMATIVES_WATCH", "NAGATINO_EGRN_READ"):
    os.environ.setdefault(_key, "0")
warnings.filterwarnings("ignore")
with contextlib.redirect_stderr(io.StringIO()):
    import main as wrapper  # noqa: E402
core = wrapper.core

# Статьи «Главы 2» внешней модели — наши статьи стройки (явная карта, а не по названию).
CHAPTER2 = ("ird", "design_p", "design_rd", "author_supervision", "preparation", "main_above",
            "main_under", "utilities", "landscaping", "commissioning", "site_maintenance",
            "gc_fee", "reserve", "project_management", "technical_supervision")
RATES = ("ird_th_per_sqm", "design_p_th_per_sqm", "design_rd_th_per_sqm", "preparation_th_per_sqm",
         "main_above_th_per_sqm", "main_under_th_per_sqm", "utilities_th_per_sqm",
         "landscaping_th_per_sqm", "commissioning_th_per_sqm", "site_maintenance_th_per_sqm")


def our_inputs(**over):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update({k: v for k, v in core.PROJECT_CLASS_PRESETS["business"].items() if k != "label"})
    x.update(dict(
        project_class="business", purchase_price_mln=460, apartment_price_th=695,
        commercial_price_th=650, parking_price_th=10000, main_above_th_per_sqm=170,
        main_under_th_per_sqm=140, utilities_th_per_sqm=7.0,
        social_mode="Денежная компенсация", social_compensation_mln=361.0,
        kindergarten_places=0, social_dou_gba_sqm=0, land_rights_cost_mln=761.6,
        vri_payment_mode="installment", underground_manual_spaces=119,
        rate_start_date="2026-10-14"))
    x.update(over)
    return x


def tep(ap=(13351, 8678, 90), com=(852, 767), und=(4462, 119)):
    t = copy.deepcopy(core.TEP_DEFAULT)
    for row in t.values():
        for field in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            row[field] = 0
        row.pop("guest_units", None)
        row.pop("transfer_units", None)
    t["apartments"].update(gns=ap[0], total_area=ap[0] * 0.9, useful=ap[1], saleable=ap[1], units=ap[2])
    t["ground_commercial"].update(gns=com[0], total_area=com[0] * 0.95, useful=com[1], saleable=com[1])
    t["underground_parking"].update(gns=und[0], total_area=und[0], units=und[1])
    return t


def scaled(x, k):
    x = dict(x)
    for field in RATES:
        x[field] = float(x[field]) * k
    return x


def run(x, t):
    r = core.calculate(core.CalcRequest(inputs=copy.deepcopy(x), tep=copy.deepcopy(t), rates=[]))
    s, c = r["summary"], r["capex"]
    return {
        "Выручка": s["revenue"] / 1e6,
        "Глава 2": sum(c.get(k, 0) for k in CHAPTER2) / 1e6,
        "ОД": (s["capex"] + s["commercial_costs"]) / 1e6,
        "%%": s["financing_cost"] / 1e6,
        "Налоги": (s["profit_tax"] + s["vat"]) / 1e6,
        "ЧП/NCF": s["net_profit"] / 1e6,
        "LLCR": s["llcr"],
        "БРИДЖ пик": r["finance"]["peak_bridge"] / 1e6,
    }


THEIR_TEP = dict(ap=(12780, 8450, 88), com=(1200, 1080), und=(6000, 160))
THEIR_PRICES = dict(apartment_price_th=691, commercial_price_th=544.7)
THEIR_DATES = dict(ird_months=23, construction_months=34)   # РнС 12.2028, ввод 10.2031
PARKING_CALIBRATED = 4942                                     # тыс ₽/шт: выручка = 8 742,4
THEIR_COMMERCIAL = dict(marketing_pct=440 / 8742.37 * 100 * 4.5 / 7,
                        selling_pct=440 / 8742.37 * 100 * 2.5 / 7)


def main() -> None:
    steps = []
    x0 = our_inputs()
    steps.append(("S0 наш расчёт", run(x0, tep())))
    x1 = our_inputs(underground_manual_spaces=160)
    t1 = tep(**THEIR_TEP)
    steps.append(("S1 + их ТЭП", run(x1, t1)))
    x2 = dict(x1, **THEIR_PRICES, parking_price_th=363.07, **THEIR_DATES)
    steps.append(("S2 + их цены (м/м 363,07 тыс/шт) и даты", run(x2, t1)))
    x3 = dict(x1, **THEIR_PRICES, parking_price_th=PARKING_CALIBRATED, **THEIR_DATES)
    s3 = run(x3, t1)
    steps.append(("S3 + их цены (м/м 4 942 тыс/шт) и даты", s3))
    x4 = scaled(dict(x3, social_compensation_mln=455, land_rights_cost_mln=585,
                     vri_payment_mode="lump", **THEIR_COMMERCIAL), 3901.17 / s3["Глава 2"])
    steps.append(("S4 + их статьи (соц 455, «585» как ВРИ, Гл.2 3 901, Гл.3 440)", run(x4, t1)))
    x5 = dict(x4, social_comp_date="2028-12-01", vri_obligation_date_mode="at_rns")
    steps.append(("S5 = S4, соц и ВРИ в РнС (вне БРИДЖа)", run(x5, t1)))
    steps.append(("S6 = наш, Глава 2 × 1,13 (удорожание ~5%/год)", run(scaled(x0, 1.13), tep())))
    steps.append(("S7 = наш, м/м 5 000 тыс/шт (база класса)", run(dict(x0, parking_price_th=5000), tep())))
    keys = list(steps[0][1])
    print("Шаг".ljust(66) + "".join(k.rjust(11) for k in keys))
    for name, row in steps:
        print(name.ljust(66) + "".join(
            (f"{row[k]:11.3f}" if k == "LLCR" else f"{row[k]:11.1f}") for k in keys))
    print("Внешняя модель".ljust(66) + "".join(f"{v:11}" for v in (
        8742.4, 3901.2, 5841.2, 1057.4, 397.8, 1473.8, 1.20, 656.0)))


if __name__ == "__main__":
    main()
