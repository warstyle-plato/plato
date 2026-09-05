"""Модель считает и по объявленной цене торгов, а не только при нуле.

Базовый прогон скрининга идёт при НУЛЕВОЙ цене входа, и это верно: пока цены
нет, придумывать её нечем, а подбор отвечает, сколько площадка выдерживает.
Но у девяти площадок каталога на снимке прода 05.09.2026 лот опубликован и
цена названа — от 4,1 млн до 5,37 млрд ₽, — и «LLCR 1,26x при цене входа 0»
отвечает не на тот вопрос, который человек задаёт перед подачей заявки.

Сравнение с потолком отвечает «проходит или нет» по порогу 1,20x и молчит о
том, ЧТО выходит по этой цене: какой LLCR, какая маржа, сколько прибыли.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _Core:
    """Движок-заглушка: запоминает, с какой ценой входа его позвали."""

    def __init__(self) -> None:
        self.prices: list[float] = []

    def _run_authoritative_model(self, inputs, tep, rates, phasing):
        self.prices.append(float(inputs.get("purchase_price_mln") or 0.0))
        return {"consolidated": {"price": inputs.get("purchase_price_mln")}, "phases": []}


def _snapshot_for(price: float) -> dict[str, float]:
    # Дороже вход — ниже LLCR и маржа: направление, а не подгонка.
    return {"llcr_x": 1.60 - price / 1000.0, "margin_pct": 20.0 - price / 100.0,
            "net_profit_mln": 5000.0 - price}


def test_the_second_run_changes_only_the_entry_price(monkeypatch) -> None:
    """Это те же вводные с одной изменённой строкой, а не вторая модель."""
    from auction_search import krt_screening

    monkeypatch.setattr(krt_screening, "_snapshot",
                        lambda core, result: _snapshot_for(float(result.get("price") or 0.0)))
    monkeypatch.setattr(krt_screening, "_phase_rows", lambda bundle: [])

    core = _Core()
    inputs = {"purchase_price_mln": 0.0, "apartment_price_th": 400.0}
    got = krt_screening.model_at_asking_price(core, inputs, {}, {}, 400.0)

    assert core.prices == [400.0], "второй прогон пошёл не по объявленной цене"
    assert inputs["purchase_price_mln"] == 0.0, "базовые вводные переписаны на месте"
    assert got["price_mln"] == 400.0
    assert got["project_llcr_x"] == 1.2
    assert got["passes"] is True
    assert got["target_llcr_x"] == krt_screening.TARGET_LLCR


def test_a_price_that_does_not_pass_is_named_so(monkeypatch) -> None:
    """Порог тот же, по которому подбирается потолок: двух порогов не бывает."""
    from auction_search import krt_screening

    monkeypatch.setattr(krt_screening, "_snapshot",
                        lambda core, result: _snapshot_for(float(result.get("price") or 0.0)))
    monkeypatch.setattr(krt_screening, "_phase_rows", lambda bundle: [])
    got = krt_screening.model_at_asking_price(_Core(), {}, {}, {}, 600.0)
    assert got["project_llcr_x"] == 1.0
    assert got["passes"] is False


def test_the_answer_travels_to_the_ranking_row() -> None:
    """Посчитанное на сервере, но не доехавшее до строки, — непосчитанное."""
    from auction_search.krt_ranking import score_row

    priced = {"price_mln": 2403.7, "project_llcr_x": 0.94, "margin_pct": 3.2,
              "net_profit_mln": 800.0, "passes": False, "target_llcr_x": 1.2}
    row = score_row(
        {"slug": "varshavskoe", "name": "Варшавское ш., вл. 37"},
        {"available": True, "metrics": {}, "phasing": {}, "market": {},
         "entry_capacity": {}, "at_asking_price": priced},
    )
    assert row["at_asking_price"] == priced


def test_the_screen_answers_with_the_priced_model() -> None:
    """Пока модель по цене не посчитана, экран сравнивает с потолком.

    Оба ответа законны, но первый сильнее: он называет, ЧТО выходит по этой
    цене. Проверяется настоящей функцией страницы, а не пересказом.
    """
    import json
    import subprocess

    import auction_search.ui as ui

    page = ui.auctions_page()
    start = page.index("function krtPriceVerdict(")
    end = page.index("function krtBrokenSlug(")
    body = page[start:end]
    assert "at_asking_price" in body, "вердикт цены о втором прогоне не знает"

    script = (
        "const fmtMln=v=>String(v)+' млн';\n"
        "const krtAskingPrice=x=>x.asking;\n"
        "const state={krtRank:{}};\n"
        + body
        + "\nstate.krtRank.a={at_asking_price:"
          "{price_mln:2403.7,project_llcr_x:0.94,margin_pct:3.2,passes:false},"
          "entry_capacity_mln:1800};\n"
        "state.krtRank.b={entry_capacity_mln:1800};\n"
        "const priced=krtPriceVerdict({slug:'a',asking:{mln:2403.7}});\n"
        "const plain=krtPriceVerdict({slug:'b',asking:{mln:2403.7}});\n"
        "console.log(JSON.stringify({priced:priced.text,over:priced.over,"
        "modelled:!!priced.modelled,plain:plain.text}));\n"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert "LLCR 0.94x" in got["priced"], got["priced"]
    assert "не проходит" in got["priced"]
    assert got["over"] is True and got["modelled"] is True
    # Без второго прогона остаётся прежний ответ — сравнение с потолком.
    assert "потолка" in got["plain"], got["plain"]


def test_the_cheapest_named_price_is_the_one_asked() -> None:
    """Лотов бывает несколько, и вход меряется по самому мягкому.

    Неназванная цена не считается нулём: бесплатный вход выглядел бы
    посчитанным, а это «цену не опубликовали».
    """
    from auction_search.krt_tenders import asking_price_mln

    # Числа со снимка прода 05.09.2026 — Варшавское ш., вл. 37 и Шипиловский.
    assert asking_price_mln([{"price_rub": 2_403_657_113.51},
                             {"price_rub": 4_113_340.42}]) == 4.11334042
    assert asking_price_mln([{"price_rub": None}, {"price_rub": 0}]) is None
    assert asking_price_mln([]) is None
    assert asking_price_mln([{"price_rub": "не число"}]) is None


def test_the_run_puts_the_announced_price_into_the_row(monkeypatch) -> None:
    """Проверка идёт настоящим прогоном, а не поиском строки в исходнике.

    Чтение цены живёт внутри `install` и снаружи не вызывается: строковая
    проверка не знает, разрешается ли там имя, — а `NameError` в этой ветке
    виден только в живом прогоне (так уже было с маршрутом публикаций).
    """
    import importlib.util
    import time
    from types import SimpleNamespace

    import pytest

    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    spec = importlib.util.spec_from_file_location("developaid_core", ROOT / "main_legacy.py")
    core = importlib.util.module_from_spec(spec)
    sys.modules["developaid_core"] = core
    spec.loader.exec_module(core)

    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    site = {"slug": "varshavskoe", "name": "Варшавское ш., вл. 37", "okrug": "ЮАО",
            "status": "Планируемый", "area_ha": 14.0,
            "total_gfa_sqm": 200_000.0, "housing_gfa_sqm": 150_000.0}
    report = {"analysis": {"site": {"segment": "Бизнес", "price_per_sqm": 450_000,
                                    "sold_lot_avg": 58, "units_per_month": 25}},
              "price_hint": {}, "subject": {"query": "krt:varshavskoe"}}

    app = fastapi.FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        build_report=lambda query, **kw: dict(report),
        search=SimpleNamespace(configured=False),
        krt=SimpleNamespace(
            catalogue=lambda **_: [dict(site)],
            status=lambda: {"complete": True, "refreshing": False},
            decisions=lambda **_: {"decisions": []},
            requirements=lambda slug, **_: None,
            card_facts=lambda slug, **_: {"available": False},
            # Связка «площадка ↔ лот» в том виде, в каком её помнит сервер.
            tender_lots_known=lambda: {
                "varshavskoe": {"lots": [{"price_rub": 2_403_657_113.51}], "seen_at": 1},
            },
        ),
    )
    from auction_search import api as auction_api

    auction_api.install(app)
    client = TestClient(app)
    started = client.post("/auctions/krt/ranking/refresh",
                          headers={"X-Market-Key": "test-key"},
                          json={"slugs": ["varshavskoe"]})
    assert started.status_code == 200, started.text
    for _ in range(600):
        if not client.get("/auctions/krt/ranking").json()["progress"]["running"]:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("прогон не кончился — итог читался бы наугад")

    rows = {row["slug"]: row for row in client.get("/auctions/krt/ranking").json()["rows"]}
    row = rows.get("varshavskoe") or {}
    assert row.get("available") is True, row.get("reason")
    priced = row.get("at_asking_price") or {}
    assert priced, "цена торгов названа, а модель по ней до строки не доехала"
    assert priced["price_mln"] == pytest.approx(2403.7, abs=0.1)
    assert isinstance(priced.get("project_llcr_x"), float)
    assert isinstance(priced.get("passes"), bool)
    # Базовый прогон при этом остался прогоном при нулевой цене: потолок — это
    # ответ на «сколько площадка выдерживает», и подменять его нельзя.
    assert row.get("project_llcr_x") is not None
    assert priced["project_llcr_x"] <= row["project_llcr_x"] + 1e-9, (
        "цена входа 2,4 млрд не может улучшить LLCR")
