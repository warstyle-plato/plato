"""Богатый проект (КРТ: десятки кадастровых номеров, много продуктов, очередей,
ограничений и рисков) собирает тизер ровно в две страницы.

Раньше обе колонки страницы лежали в одной строке таблицы, которую ReportLab не
переносит: колонка выше листа роняла весь PDF с `LayoutError`, и пользователь
видел дамп Flowable вместо тизера. Теперь длинные перечни обрезаны со ссылкой
на полный отчёт, а страница как последний предохранитель ужимается в лист.
Числа ТЭП и экономики при этом не выкидываются — это проверяется по тексту.
"""
from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main as _wrapper  # noqa: E402
import teaser_pdf  # noqa: E402

core = _wrapper.core


@pytest.fixture(scope="module")
def rich_model() -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    bundle = core._run_authoritative_model(inputs, tep, [], None)
    model = copy.deepcopy(core.project_presentation(bundle, inputs, tep, None))
    numbers = [f"77:05:0004004:{1000 + i}" for i in range(40)]
    model["project_name"] = "КРТ Нагатинская пойма"
    model["site"].update({
        "cadastral_numbers": numbers,
        "address": ("г. Москва, внутригородская территория муниципальный округ Нагатинский Затон, "
                    "проспект Андропова, земельные участки в границах комплексного развития "
                    "территории нежилой застройки «Нагатинская пойма», кварталы 1–7"),
        "land_area_sqm": 1_234_567.0, "land_area_ha": 123.4567, "density_sqm_per_ha": 18000.0,
        "permitted_use": ("Многоэтажная жилая застройка (высотная застройка); хранение автотранспорта; "
                          "образование и просвещение; деловое управление; магазины"),
        "category": "Земли населённых пунктов",
        "screened": True,
        "verdict_headline": "Участок в нескольких ЗОУИТ; часть площади под охранными зонами сетей",
        "free_pct": 61.0,
        "findings": [{"flag_class": "", "name": f"Охранная зона инженерных коммуникаций № {i} "
                      "(кабельная линия 10 кВ, водовод Ду 1200)", "coverage_pct": 3.0 + i}
                     for i in range(14)],
        "parcels": [{"cadastral_number": n, "area_sqm": 50_000.0 + i} for i, n in enumerate(numbers[:14])],
    })
    products = []
    for block in range(4):
        for p in model["products"]:
            q = dict(p)
            q["key"] = f"{p['key']}_{block}" if block else p["key"]
            q["label"] = f"{p['label']} · ОСЗ {block + 1}"
            products.append(q)
    model["products"] = products
    for risk in model["risks"]:
        risk["active"] = True
        risk["value"] = risk.get("value") or 123.4
        risk["detail"] = "очередь 3, 2031-06-01; раскрытого эскроу не хватило на погашение ПФ"
    model["construction_costs"] = model["construction_costs"] * 2
    model["expense_structure"] = model["expense_structure"] * 2
    model["phases"] = [{"name": f"Очередь {i + 1}",
                        "dates": {"project_start": "2027-01-01", "permit": f"{2027 + i // 3}-0{1 + i % 3 * 3}-01",
                                  "rve": f"{2030 + i // 3}-06-01", "sales_start": f"{2028 + i // 3}-01-01",
                                  "sales_end": f"{2031 + i // 3}-12-01"}} for i in range(14)]
    model["land"].update({"kindergarten_places": 900, "school_places": 2200, "social_payment_mln": 1234.5,
                          "social_payment_mode": "Строит застройщик", "vri_required": True,
                          "vri_amount_mln": 2345.6, "vri_payment_mode": "installment",
                          "vri_relief_mln": 100.0, "vri_interest_mln": 55.5})
    return model


def _build(model: dict) -> bytes:
    return teaser_pdf.build_teaser_pdf(model, core._pdf_font_names(), core._pdf_num)


def _pages_text(pdf: bytes) -> list[str]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf))
    return [page.extract_text() for page in reader.pages]


def test_a_rich_project_builds_exactly_two_pages(rich_model):
    pages = _pages_text(_build(rich_model))
    assert len(pages) == 2, f"тизер — две страницы, а вышло {len(pages)}"


def test_the_rich_teaser_keeps_every_number(rich_model):
    """Обрезаются перечни (номера, ограничения, очереди), а не числа: каждая
    строка продуктов, каждый активный риск и итоги ТЭП и экономики на месте."""
    text = " ".join(_pages_text(_build(rich_model)))
    flat = " ".join(text.split())
    fm = teaser_pdf._Formats(core._pdf_num)
    for product in rich_model["products"]:
        assert product["label"] in flat, product["label"]
    for risk in rich_model["risks"]:
        assert risk["label"] in flat, risk["label"]
    eff = rich_model["efficiency"]
    tep = rich_model["tep"]
    for shown in (fm.sqm(tep["project_gns_sqm"]), fm.sqm(tep["saleable_sqm"]),
                  fm.mln(eff["revenue_mln"]), fm.mln(eff["ebitda_mln"]), fm.mln(eff["npv_mln"]),
                  fm.mln(eff["net_profit_mln"])):
        assert " ".join(shown.split()) in flat, shown


def test_long_lists_point_to_the_full_report(rich_model):
    """Перечень, обрезанный ради листа, называет остаток — молча не пропадает."""
    flat = " ".join(" ".join(_pages_text(_build(rich_model))).split())
    numbers = rich_model["site"]["cadastral_numbers"]
    assert numbers[0] in flat
    assert numbers[-1] not in flat
    assert f"ещё {len(numbers) - teaser_pdf.MAX_CADASTRAL_SHOWN}" in flat
    assert f"ещё {len(rich_model['site']['findings']) - teaser_pdf.MAX_FINDINGS_SHOWN}" in flat
    assert f"ещё {len(rich_model['phases']) - teaser_pdf.MAX_GANTT_PHASES} очеред" in flat
    assert "в полном отчёте" in flat


def test_a_layout_failure_is_told_in_words(rich_model, monkeypatch):
    """Без предохранителя лист переполняется — и тогда пользователь читает, какая
    страница не влезла, а не дамп Flowable из ReportLab."""
    monkeypatch.setattr(teaser_pdf, "_fit_page", lambda flowables, width: flowables)
    monkeypatch.setattr(teaser_pdf, "MAX_CADASTRAL_SHOWN", 10_000)
    monkeypatch.setattr(teaser_pdf, "MAX_FINDINGS_SHOWN", 10_000)
    model = copy.deepcopy(rich_model)
    model["site"]["cadastral_numbers"] = model["site"]["cadastral_numbers"] * 8
    model["site"]["findings"] = model["site"]["findings"] * 4
    with pytest.raises(teaser_pdf.TeaserLayoutError) as caught:
        _build(model)
    message = str(caught.value)
    assert "Flowable" not in message and "<" not in message
    assert "«Девелоперский проект»" in message
