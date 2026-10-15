"""Средняя цена в таблице продаж называет траекторию цены, из которой вышла.

Вопрос владельца (прод 0.25.76, участок 77:05:0001008:2969, класс «Элитный»):
стартовая цена квартир 1 246,4 тыс. ₽/м², а средняя в PDF — 946, и у
коммерции и паркинга то же отношение ≈ 0,76. Причина — вводная «Ежемесячный
рост цены до РВЭ» = −2%/мес.: `sales_schedule` ведёт цену от стартовой с этим
ростом, средняя = выручка ÷ объём. Методика верна, но ни экран, ни PDF не
называли, откуда средняя ниже стартовой, — подписи под таблицей были только
для лестницы и профиля продаж.

Траектория — одна строка движка (`price_path`) на продукт; отрицательный рост
— предупреждение в `schedule_warnings`, которое экран и PDF уже печатают.

Запуск: python3 -m pytest tests/test_avg_price_names_its_price_path.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402

core = _wrapper.core
PORT = 19811


def _inputs(growth_pre: float) -> tuple[dict, dict]:
    x = {**core.DEFAULT_INPUTS, "project_class": "elite",
         "apartment_price_th": 1246.4, "commercial_price_th": 1500,
         "parking_price_th": 20000, "storage_price_th": 5000,
         "share_before_rve_pct": 80, "monthly_growth_pre_pct": growth_pre}
    return x, {key: dict(row) for key, row in core.TEP_DEFAULT.items()}


def _run(growth_pre: float) -> dict:
    x, t = _inputs(growth_pre)
    return core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))


@pytest.fixture(scope="module")
def falling() -> dict:
    return _run(-2)


def _core_products(result: dict) -> list[dict]:
    return [p for p in result["report"]["products"]
            if p["key"] in ("apartments", "ground_commercial", "underground_parking")
            and float(p.get("quantity") or 0) > 0]


def test_negative_growth_is_named_where_average_is_shown(falling):
    products = _core_products(falling)
    assert len(products) == 3
    for p in products:
        # Средняя действительно ниже стартовой — ровно случай владельца.
        assert p["avg_price_th"] < p["start_price_th"] * 0.8, p
        assert "−2%/мес." in p["price_path"], p["price_path"]
        # Предупреждение называет величину эффекта — ту же, что в таблице.
        effect = f"средняя {(p['avg_price_th'] / p['start_price_th'] - 1) * 100:+.1f}% к стартовой"
        effect = effect.replace(".", ",").replace("-", "−")
        assert any("отрицательный" in w and effect in w for w in p["schedule_warnings"]), (
            effect, p["schedule_warnings"])


def test_the_rate_names_where_it_came_from(falling):
    # Не отмеченное и не равное умолчанию — «источник не отмечен», а не
    # «вписано вручную» и не «умолчание»: отсутствие записи не решение.
    assert all("−2%/мес. (источник не отмечен)" in p["price_path"]
               for p in _core_products(falling))
    assert all("+0,25%/мес. (умолчание)" in p["price_path"]
               for p in _core_products(falling))
    x, t = _inputs(-2)
    x["_field_origin"] = {"inputs.monthly_growth_pre_pct":
                          {"source": "manual", "text": "вписано вручную"}}
    marked = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    for p in _core_products(marked):
        assert "−2%/мес. (вписано вручную)" in p["price_path"], p["price_path"]
        assert any("вписано вручную" in w for w in p["schedule_warnings"])


def test_positive_growth_names_path_without_warning():
    for p in _core_products(_run(1.0)):
        assert "+1%/мес. (умолчание)" in p["price_path"], p["price_path"]
        assert not any("отрицательный" in w for w in p["schedule_warnings"])


def test_ladder_replaces_monthly_growth_in_the_text():
    x, t = _inputs(-2)
    x["growth_stage1_pct"] = 5
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    for p in _core_products(result):
        # Лестница задана — ежемесячный рост до РВЭ не применяется, и его
        # минус не должен ни печататься, ни пугать предупреждением.
        assert "лестница" in p["price_path"] and "−2" not in p["price_path"]
        assert not any("отрицательный" in w for w in p["schedule_warnings"])


def test_pdf_prints_price_path_under_sales_table(falling):
    pypdf = pytest.importorskip("pypdf")
    x, t = _inputs(-2)
    data = core._build_developaid_pdf({"result": falling, "inputs": x, "tep": t, "rates": [],
                                       "phasing": {}, "scenario": "base",
                                       "project_name": "Средняя цена"})
    text = " ".join(" ".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages).split())
    assert "средняя цена — рост цены до РВЭ −2%/мес." in text
    assert "рост цены до РВЭ отрицательный" in text


def test_in_a_real_browser_the_sales_table_names_the_price_path():
    """Проверяется отрисованная таблица продаж, а не литерал в исходнике."""
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    from main_registry import app as registry_app

    x, _ = _inputs(-2)
    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(f"{base}/classic", wait_until="domcontentloaded")
            tab.wait_for_function("window.__developaidBooted===true", timeout=60000)
            got = tab.evaluate(
                """async (payload)=>{
                  // Форма главнее объекта `inputs`: расчёт перечитывает поля f_*.
                  for(const [k,v] of Object.entries(payload)){
                    const el=document.getElementById('f_'+k);
                    if(el&&el.type!=='checkbox')el.value=v;
                  }
                  Object.assign(inputs, payload);
                  // Рост цены вводится так, как вводит человек: правкой поля.
                  // Её обработчик и ставит отметку происхождения.
                  const growth=document.getElementById('f_monthly_growth_pre_pct');
                  growth.value=payload.monthly_growth_pre_pct;
                  growth.dispatchEvent(new Event('change'));
                  phasing = {enabled:false, phases:[]};
                  const done=await calculate();
                  const table=document.getElementById('salesReportTable');
                  return {superseded: done===null, sales:(table&&table.textContent)||''};
                }""",
                {k: v for k, v in x.items() if not k.startswith("_")})
        finally:
            browser.close()

    assert got["superseded"] is False
    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    assert "цена: рост цены до РВЭ −2%/мес. (вписано вручную)" in got["sales"], got["sales"][:600]
    assert "рост цены до РВЭ отрицательный" in got["sales"]
