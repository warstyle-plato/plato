"""/v2 показывает результат живого движка, а не контрольные fixtures.

Прототип 2.0 рисовал зашитые показатели из приёмочных PDF. Пока их читал
только макет, это было безобидно; как только тем же экраном начинают
принимать решения, зашитая цифра неотличима от посчитанной — и расходится
с моделью молча. Здесь закреплено обратное: одни вводные → один вызов
действующего движка → один ProjectResult на все поверхности.

Что охраняется:

- ProjectResult собирается ровно одним вызовом движка;
- адаптер не считает: в нём нет ни одной арифметической операции;
- результат сериализуется стабильно и несёт своё происхождение
  (calculation_id, версия движка, время расчёта, отпечаток вводных);
- KPI из API равны summary движка на тех же вводных — до последнего знака;
- очереди и помесячные ряды доезжают целиком;
- production-маршруты не отдают fixtures и не кешируются.

Запуск: python3 -m pytest tests/test_developaid_v2_live_result.py -q
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import developaid_v2_demo as demo  # noqa: E402
import developaid_v2_result as project_result  # noqa: E402
import main as wrapper  # noqa: E402
from developaid_v2 import install  # noqa: E402

core = wrapper.core

_ADAPTER = Path(__file__).resolve().parent.parent / "developaid_v2_result.py"


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    install(app)
    return TestClient(app)


def simple_payload() -> dict:
    """Тот же payload, что шлёт действующее мини-приложение."""
    inputs = {**copy.deepcopy(core.DEFAULT_INPUTS),
              "purchase_price_mln": 700, "land_rights_cost_mln": 1267.539}
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return {"inputs": inputs, "tep": tep, "rates": [], "phasing": {},
            "project_name": "Контрольный расчёт", "sensitivity": False}


def phased_payload() -> dict:
    payload = simple_payload()
    payload["phasing"] = {
        "enabled": True, "phase_count": 3, "phase_gap_months": 12,
        "products": {key: [40, 32, 28] for key in
                     ("apartments", "ground_commercial", "underground_parking", "storage")},
        "cost_inflation_pct": 8, "sales_price_inflation_pct": 8,
    }
    return payload


def engine_bundle(payload: dict) -> dict:
    """Прямой вызов движка на тех же вводных — эталон для сверки."""
    return core._run_authoritative_model(
        copy.deepcopy(payload["inputs"]), copy.deepcopy(payload["tep"]),
        copy.deepcopy(payload["rates"]), copy.deepcopy(payload["phasing"]),
    )


# --- адаптер не считает -------------------------------------------------------

def test_the_adapter_contains_no_arithmetic():
    """Ни одной формулы в адаптере.

    Стоит начать «просто делить на миллион» — и появляется вторая реализация
    экономики: сначала единицы, потом доля, потом показатель. Разошедшаяся
    версия страницы после этого показывает достоверную неправду.
    """
    tree = ast.parse(_ADAPTER.read_text(encoding="utf-8"))
    arithmetic = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    found = [
        f"строка {node.lineno}: {type(node.op).__name__}"
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, arithmetic)
    ]
    assert not found, "в адаптере ProjectResult появилась арифметика: " + "; ".join(found)


def test_one_calculation_calls_the_engine_once(monkeypatch, client):
    """Один расчёт — один вызов движка.

    Поверхности, считающие каждая своё, уже давали две достоверные цифры на
    одни вводные: PDF по результату из окна, книгу — пересчётом на сервере.
    """
    calls: list[str] = []
    original = core._run_authoritative_model

    def counted(inputs, tep, rates, phasing):
        calls.append("run")
        return original(inputs, tep, rates, phasing)

    monkeypatch.setattr(core, "_run_authoritative_model", counted)
    response = client.post("/api/v2/calculate", json=simple_payload())

    assert response.status_code == 200, response.text
    assert len(calls) == 1, f"движок вызван {len(calls)} раз(а) на один расчёт"


# --- происхождение результата -------------------------------------------------

def test_the_result_carries_its_origin(client):
    payload = simple_payload()
    result = client.post("/api/v2/calculate", json=payload).json()

    # Идентификатор общий с PDF и книгой: сверка пары начинается с вопроса,
    # один ли это расчёт, и на него отвечает строка, а не сравнение цифр.
    assert result["calculation_id"] == core._calculation_fingerprint(
        payload["inputs"], payload["tep"], payload["phasing"])
    assert result["engine_version"] == core.VERSION
    assert result["calculated_at"]
    assert result["input_hash"].startswith("sha256:")
    assert result["engine_entry_point"] == "main_legacy._run_authoritative_model"
    assert result["source"] == "engine"
    assert result["prototype"] is False


def test_the_input_hash_follows_the_inputs():
    payload = simple_payload()
    first = project_result.input_hash(payload["inputs"], payload["tep"], [], {})
    same = project_result.input_hash(copy.deepcopy(payload["inputs"]),
                                     copy.deepcopy(payload["tep"]), [], {})
    changed_inputs = {**payload["inputs"], "purchase_price_mln": 701}
    changed = project_result.input_hash(changed_inputs, payload["tep"], [], {})

    assert first == same, "одни вводные обязаны давать один отпечаток"
    assert first != changed, "изменение вводных обязано менять отпечаток"


def test_the_result_serializes_stably(client):
    """Два расчёта на одних вводных различаются только временем расчёта."""
    first = client.post("/api/v2/calculate", json=simple_payload()).json()
    second = client.post("/api/v2/calculate", json=simple_payload()).json()

    assert first["input_hash"] == second["input_hash"]
    assert first["calculation_id"] == second["calculation_id"]
    stable = lambda item: json.dumps(  # noqa: E731
        {key: value for key, value in item.items() if key != "calculated_at"},
        sort_keys=True, ensure_ascii=False, allow_nan=False,
    )
    assert stable(first) == stable(second)


def test_the_static_assets_are_revalidated(client):
    """Страница и скрипт перепроверяются, а не живут в кеше вебвью.

    Без `Cache-Control` браузер считает файл свежим по эвристике: сервер уже
    новый, страница ещё прежняя — и это неотличимо от несостоявшейся выкатки.
    """
    for path in ("/v2", "/v2/assets/app.js", "/v2/assets/styles.css"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "no-cache" in response.headers.get("cache-control", ""), path
        # etag есть, но 304 на If-None-Match Starlette не отвечает: файл
        # приходит целиком. Тридцати килобайт свежесть страницы стоит.
        assert response.headers.get("etag"), path


def test_the_response_is_never_cached(client):
    for response in (
        client.post("/api/v2/calculate", json=simple_payload()),
        client.get("/api/v2/projects"),
        client.get("/api/v2/projects/mishina?sensitivity=false"),
    ):
        assert response.status_code == 200, response.text
        assert "no-store" in response.headers.get("cache-control", "")


# --- KPI равны движку ---------------------------------------------------------

@pytest.mark.parametrize("payload_factory", [simple_payload, phased_payload],
                         ids=["single", "phased"])
def test_api_kpis_equal_the_engine_result(payload_factory, client):
    payload = payload_factory()
    result = client.post("/api/v2/calculate", json=payload).json()
    summary = engine_bundle(payload)["consolidated"]["summary"]

    for key in ("revenue", "capex", "ebitda", "financing_cost", "profit_tax",
                "net_profit", "margin", "llcr", "npv", "total_expenses",
                "full_project_cost", "ending_pf"):
        assert result["kpi"][key] == pytest.approx(summary[key], rel=1e-12, abs=1e-9), key


def test_financing_and_bridge_reach_the_result(client):
    payload = simple_payload()
    result = client.post("/api/v2/calculate", json=payload).json()
    financing = engine_bundle(payload)["consolidated"]["report"]["financing"]

    for key in ("calculated_bridge", "actual_bridge", "bridge_peak_capitalized",
                "pf_peak", "pf_uncovered_peak", "pf_limit", "ending_pf",
                "interest_and_fees"):
        assert result["financing"][key] == pytest.approx(financing[key]), key


def test_vri_social_and_tep_reach_the_result(client):
    payload = simple_payload()
    result = client.post("/api/v2/calculate", json=payload).json()
    consolidated = engine_bundle(payload)["consolidated"]

    assert result["vri"]["totals"] == consolidated["vri"]["totals"]
    assert result["social"]["payment"] == pytest.approx(
        consolidated["summary"]["social_payment"])
    assert result["social"]["program"] == consolidated["summary"]["social_program"]
    assert [row["key"] for row in result["tep"]["rows"]] == \
        [row["key"] for row in consolidated["tep"]["rows"]]


def test_the_queues_reach_the_result(client):
    payload = phased_payload()
    result = client.post("/api/v2/calculate", json=payload).json()
    bundle = engine_bundle(payload)

    assert result["mode"] == "phased"
    assert [queue["name"] for queue in result["queues"]] == \
        [item["name"] for item in bundle["phases"]]
    for queue, item in zip(result["queues"], bundle["phases"]):
        summary = item["result"]["summary"]
        assert queue["kpi"]["llcr"] == pytest.approx(summary["llcr"])
        assert queue["kpi"]["net_profit"] == pytest.approx(summary["net_profit"])
        assert queue["kpi"]["revenue"] == pytest.approx(summary["revenue"])
        assert queue["monthly"]["months"], "у очереди нет помесячного ряда"


def test_the_monthly_series_reach_the_result(client):
    payload = simple_payload()
    result = client.post("/api/v2/calculate", json=payload).json()
    consolidated = engine_bundle(payload)["consolidated"]
    rows = consolidated["finance"]["rows"]
    months = consolidated["cashflow"]["months"]
    monthly = result["monthly"]

    assert monthly["months"] == months
    assert monthly["cashflow_project"] == pytest.approx(consolidated["cashflow"]["project"])
    assert monthly["escrow"] == pytest.approx([row["escrow"] for row in rows])
    assert monthly["pf_balance"] == pytest.approx([row["pf_balance"] for row in rows])
    assert monthly["bridge_balance"] == pytest.approx([row["bridge_balance"] for row in rows])
    assert len(monthly["escrow"]) == len(months)
    assert monthly["detail"]["costs"], "постатейная детализация по месяцам потеряна"


def test_the_tornado_comes_from_the_engine(client):
    payload = {**simple_payload(), "sensitivity": True}
    result = client.post("/api/v2/calculate", json=payload).json()

    assert result["sensitivity"], result.get("sensitivity_error")
    assert result["sensitivity"]["base"]["metric"] == "llcr"
    assert result["sensitivity"]["items"], "Tornado пуст"
    assert result["sensitivity"]["base"]["value"] == pytest.approx(
        engine_bundle(payload)["consolidated"]["summary"]["llcr"], abs=1e-6)


# --- fixtures вне production --------------------------------------------------

def test_production_endpoints_do_not_serve_fixtures(client):
    """Контрольные показатели прототипа не могут прийти как расчёт."""
    from developaid_v2_prototype_fixtures import PROTOTYPE_PROJECTS

    fixture = PROTOTYPE_PROJECTS["mishina"]["kpi"]
    result = client.get("/api/v2/projects/mishina?sensitivity=false").json()

    assert result["source"] == "engine"
    assert result["prototype"] is False
    # Fixture держит миллиарды, движок — рубли: совпасть они могут только
    # если fixture подставили в ответ.
    assert result["kpi"]["revenue"] != fixture["revenue"]
    assert result["kpi"]["llcr"] != fixture["llcr"]
    body = json.dumps(result, ensure_ascii=False)
    assert "Контрольный PDF DevelopAid" not in body


def test_the_prototype_fixtures_are_off_by_default(client, monkeypatch):
    monkeypatch.delenv("DEVELOPAID_V2_PROTOTYPE_FIXTURES", raising=False)
    response = client.get("/api/v2/prototype/projects/mishina")

    assert response.status_code == 404
    assert "fixtures" in response.json()["detail"].lower()


def test_the_prototype_fixtures_are_available_for_development(client, monkeypatch):
    monkeypatch.setenv("DEVELOPAID_V2_PROTOTYPE_FIXTURES", "1")
    response = client.get("/api/v2/prototype/projects/mishina")

    assert response.status_code == 200
    assert response.json()["source"] == "prototype_fixture"
    assert response.json()["prototype"] is True


def test_the_frontend_does_not_calculate():
    """Страница отправляет вводные и рисует ProjectResult — и только."""
    script = (Path(__file__).resolve().parent.parent
              / "frontend_v2" / "app.js").read_text(encoding="utf-8")

    assert "/api/v2/calculate" in script
    assert "engine_version" in script and "calculation_id" in script
    assert "calculated_at" in script
    # Прежний прототип держал вердикты и ответы Платона строками в коде.
    assert "Сильная третья очередь" not in script
    assert "LLCR 1,12x ниже цели" not in script


# --- контрольные проекты ------------------------------------------------------

@pytest.mark.parametrize("slug,mode,queues", [("mishina", "single", 0),
                                              ("mytishchi", "phased", 3)])
def test_the_control_projects_are_calculated_by_the_engine(slug, mode, queues, client):
    """Мишина и Мытищи считаются движком на демонстрационных вводных."""
    payload = demo.scenario_payload(core, slug)
    result = client.get(f"/api/v2/projects/{slug}?sensitivity=false").json()
    summary = core._run_authoritative_model(
        payload["inputs"], payload["tep"], payload["rates"], payload["phasing"],
    )["consolidated"]["summary"]

    assert result["mode"] == mode
    assert len(result["queues"]) == queues
    assert result["project"]["slug"] == slug
    assert result["kpi"]["revenue"] == pytest.approx(summary["revenue"])
    assert result["kpi"]["llcr"] == pytest.approx(summary["llcr"])
    assert result["kpi"]["net_profit"] == pytest.approx(summary["net_profit"])
    assert result["monthly"]["months"], "помесячный ряд пуст"


def test_the_mishina_demo_carries_its_cadastre_and_vri():
    payload = demo.scenario_payload(core, "mishina")

    assert payload["cadastral_numbers"] == ["77:09:0004014:13"]
    assert payload["inputs"]["land_rights_cost_mln"] == pytest.approx(1267.539)
    assert payload["inputs"]["vri_required"] is True
    assert payload["tep"]["apartments"]["saleable"] == pytest.approx(13920)
    assert not payload["phasing"], "Мишина — одноочередной проект"


def test_the_mytishchi_demo_carries_three_queues_and_offices():
    payload = demo.scenario_payload(core, "mytishchi")

    assert payload["phasing"]["phase_count"] == 3
    assert payload["phasing"]["products"]["apartments"] == [40, 32, 28]
    assert payload["inputs"]["offices_enabled"] is True
    assert payload["inputs"]["offices_saleable_sqm"] == pytest.approx(21360)
    assert payload["inputs"]["mo_district"] == "Городской округ Мытищи"
    assert payload["inputs"]["vri_region"] == "mo"
    assert payload["tep"]["offices"]["saleable"] == pytest.approx(21360)


def test_a_missing_project_is_a_404(client):
    assert client.get("/api/v2/projects/unknown").status_code == 404
