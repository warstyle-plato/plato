"""Стадия строительства в поиске рекомендованной цены.

Владелец (03.10.2026): Пульс даёт руками выбрать стадию строительства, а у нас
это нигде не видно. Проверяется:

* словарь стадий один и называет происхождение стадии аналога: поле Пульса,
  оценка по срокам или «стадия не указана» — последнее не равно «любая»;
* ориентир пересчитывается сервером по выбранным стадиям, аналог без стадии
  при отборе не проходит, а недобор не подменяется медианой округа/города;
* на отрисованной странице «Как посчитано» стадии выбираются, пересчёт уходит
  на сервер, видно, по какой стадии посчитано и сколько аналогов;
* у кнопки «Рекомендация DevelopAid» выбранная стадия уходит в запрос и
  называется в подписи.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from market_search import price_hint_ui, stage  # noqa: E402
from market_search.pulse import PulseProject, _stage_from_payload  # noqa: E402
from market_search.service_v6 import MarketDiscoveryService  # noqa: E402


# --- словарь и разбор -------------------------------------------------------

def test_stage_text_maps_to_one_dictionary_and_unknown_stays_unknown() -> None:
    assert stage.stage_from_text("Котлован") == "pit"
    assert stage.stage_from_text("Монолитные работы") == "frame"
    assert stage.stage_from_text("каркас возведён, идёт отделка") == "finish"
    assert stage.stage_from_text("Введён в эксплуатацию") == "done"
    # «готовность 30%» — не «сдан»; «строится» — не стадия.
    assert stage.stage_from_text("готовность 30%") is None
    assert stage.stage_from_text("строится") is None

    from_pulse = stage.analog_stage("Котлован", 0.9)
    assert (from_pulse["code"], from_pulse["origin"]) == ("pit", "pulse")
    estimated = stage.analog_stage(None, 0.1)
    assert (estimated["code"], estimated["origin"]) == ("pit", "calendar")
    unknown = stage.analog_stage("строится", None)
    assert unknown["code"] is None and unknown["origin"] is None
    assert unknown["label"] == "стадия не указана"
    # Нераспознанный текст источника не теряется.
    assert unknown["raw"] == "строится"


def test_selected_stage_codes_are_checked_not_guessed() -> None:
    assert stage.normalize_stage_codes(["done", "pit"]) == ["pit", "done"]
    assert stage.normalize_stage_codes("frame,finish") == ["frame", "finish"]
    assert stage.normalize_stage_codes(None) == []
    with pytest.raises(ValueError):
        stage.normalize_stage_codes(["котлован"])


def test_api_rejects_an_unknown_stage() -> None:
    from pydantic import ValidationError

    from market_search.api import PriceHintRequest

    assert PriceHintRequest(address="Москва", stages=["pit"]).stages == ["pit"]
    with pytest.raises(ValidationError):
        PriceHintRequest(address="Москва", stages=["any"])


def test_stage_is_read_from_a_pulse_payload_by_meaning() -> None:
    payload = {"buildings": [{"construction_stage": "Отделка"},
                             {"construction_stage": "Котлован"}],
               "sales_stage": "старт"}
    # Проект стоит на самой ранней стадии корпусов; «стадия продаж» — не она.
    assert _stage_from_payload(payload) == "Котлован"
    assert _stage_from_payload({"name": "ЖК", "sales_status": "идут"}) is None


def test_suggestion_for_our_project() -> None:
    assert stage.suggest_project_stage()["code"] == "pit"
    got = stage.suggest_project_stage("2025-01-01", "2027-01-01", "2025-10-01")
    assert got["code"] == "frame" and "по срокам проекта" in got["reason"]


# --- сервер -----------------------------------------------------------------

PEERS = {
    # id: (цена, сырая стадия Пульса, старт продаж, ввод)
    1: (500_000, "Котлован", None, None),
    2: (520_000, None, "2026-08-01", "2029-08-01"),   # оценка: котлован
    3: (540_000, "нулевой цикл", None, None),
    4: (700_000, "Сдан", None, None),
    5: (720_000, None, None, None),                   # стадия не указана
}


def _service(tmp_path: Path, monkeypatch) -> MarketDiscoveryService:
    service = MarketDiscoveryService(tmp_path)
    service.pulse.login = "x"
    service.pulse.password = "x"
    service.verified_prices.today = date(2026, 9, 22)
    projects = [PulseProject(i, f"P{i}", 55.75 + i / 1000, 37.60) for i in PEERS]
    monkeypatch.setattr(service.pulse, "near",
                        lambda *_a, **_k: [(0.3 * i, p) for i, p in enumerate(projects, 1)])
    monkeypatch.setattr(service.pulse, "segments", lambda: {i: "Комфорт" for i in PEERS})
    monkeypatch.setattr(service.pulse, "price", lambda cid: {
        "price_per_sqm": PEERS[cid][0], "lot_count": 10, "observed_at": "2026-09-01"})
    monkeypatch.setattr(service.cards, "card", lambda cid: {})
    monkeypatch.setattr(service.pulse, "project_dates", lambda cid: {
        "sales_start": PEERS[cid][2], "commissioning": PEERS[cid][3]})
    monkeypatch.setattr(service.pulse, "project_stage", lambda cid: {"raw": PEERS[cid][1]})
    monkeypatch.setattr(service.dynamics, "latest", lambda *_a, **_k: {})
    monkeypatch.setattr(service.dynamics, "series", lambda *_a, **_k: [])
    return service


def _hint(service, **kwargs):
    return service.price_hint(address="Москва", latitude=55.75, longitude=37.60,
                              include_projects=True, **kwargs)


def test_price_is_recalculated_by_the_chosen_stage(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)

    plain = _hint(service)
    assert plain["price_per_sqm"] == 540_000
    assert plain["stage_filter"]["active"] is False
    options = {row["code"]: row["count"] for row in plain["stage_filter"]["options"]}
    assert options == {"pit": 3, "frame": 0, "finish": 0, "done": 1}
    assert plain["stage_filter"]["without_stage_total"] == 1

    pit = _hint(service, stages=["pit"])
    assert pit["basis"] == "peers"
    assert pit["price_per_sqm"] == 520_000
    got = pit["stage_filter"]
    assert got["title"] == "«котлован»"
    assert (got["matched"], got["considered"]) == (3, 5)
    assert (got["without_stage"], got["other_stage"]) == (1, 1)
    rows = {row["complex_id"]: row for row in pit["projects"]}
    # Без стадии — не «любая»: при отборе аналог не проходит и назван.
    assert rows[5]["eligible"] is False
    assert rows[5]["excluded_reason"] == "стадия не указана"
    assert rows[5]["construction_stage_label"] == "стадия не указана"
    assert rows[4]["excluded_reason"] == "стадия «сдан» не выбрана"
    assert rows[2]["construction_stage_origin"] == "calendar"
    assert rows[1]["construction_stage_origin"] == "pulse"
    assert "в ответах, которые читает наш маршрут" not in got["source_note"]


def test_only_pulse_stage_when_estimates_are_switched_off(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    got = _hint(service, stages=["pit", "done"], include_estimated_stage=False)
    flt = got["stage_filter"]
    assert (flt["matched"], flt["estimated_only"]) == (3, 1)
    assert got["price_per_sqm"] == 540_000


def test_a_thin_stage_is_not_covered_by_the_city_median(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    got = _hint(service, stages=["done"])
    assert got["available"] is False
    assert "«сдан»" in got["reason"] and "1" in got["reason"]
    assert "стадию не учитывает" in got["reason"]


def test_without_any_pulse_stage_the_route_says_so(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(service.pulse, "project_stage", lambda cid: {"raw": None})
    got = _hint(service)
    assert got["stage_filter"]["from_pulse"] == 0
    assert "поля стадии нет" in got["stage_filter"]["source_note"]


# --- отрисованные страницы --------------------------------------------------

def _details(stages: list[str]) -> dict:
    """Ответ расшифровки: при выборе «котлован» — другое число и другой счёт."""
    active = bool(stages)
    projects = [
        {"complex_id": 1, "name": "Котлованный", "price_per_sqm": 500000, "eligible": True,
         "construction_stage": "pit", "construction_stage_label": "котлован",
         "construction_stage_origin": "pulse", "construction_stage_origin_title": "Пульс"},
        {"complex_id": 2, "name": "По срокам", "price_per_sqm": 520000, "eligible": True,
         "construction_stage": "pit", "construction_stage_label": "котлован",
         "construction_stage_origin": "calendar",
         "construction_stage_origin_title": "оценка по срокам"},
        {"complex_id": 5, "name": "Безстадийный", "price_per_sqm": 720000,
         "eligible": not active, "excluded_reason": "стадия не указана" if active else None,
         "construction_stage": None, "construction_stage_label": "стадия не указана",
         "construction_stage_origin": None},
    ]
    return {
        "available": True, "basis": "peers", "basis_title": "по сопоставимым проектам рядом",
        "price_per_sqm": 510000 if active else 520000, "sample": 2 if active else 3,
        "segment": "Комфорт", "projects": projects,
        "stage_filter": {
            "active": active, "stages": stages, "labels": ["котлован"] if active else [],
            "title": "«котлован»" if active else "любая", "include_estimated": True,
            "considered": 3, "matched": 2 if active else 3,
            "without_stage_total": 1, "without_stage": 1 if active else 0,
            "other_stage": 0, "estimated_only": 0,
            "options": [{"code": c, "label": t, "count": 2 if c == "pit" else 0}
                        for c, t in stage.CONSTRUCTION_STAGES],
            "suggestion": {"code": "pit", "label": "котлован",
                           "reason": "новый проект выходит в продажу на старте стройки — котловане"},
            "from_pulse": 1, "source_note": "Стадия аналогов пришла полем Пульса.",
        },
    }


STAGE_STATE = """()=>({
  status:document.getElementById('stageStatus').textContent,
  summary:document.getElementById('summary').textContent,
  chips:[...document.querySelectorAll('#stageFilter label')].map(l=>l.textContent.trim()),
  checked:[...document.querySelectorAll('.stagePick:checked')].map(x=>x.value),
  badges:[...document.querySelectorAll('#rows tr')].map(tr=>tr.children[8].textContent.trim()),
  suggest:document.getElementById('stageSuggest').textContent,
  url:location.search,
})"""


def test_the_breakdown_page_filters_by_stage_on_the_rendered_page() -> None:
    import browser

    path = browser.chromium_or_skip()
    from playwright.sync_api import sync_playwright

    sent: list[dict] = []

    def route(route):
        request = route.request
        if request.url.endswith("/market/price-hint/details"):
            body = json.loads(request.post_data or "{}")
            sent.append(body)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(_details(body.get("stages") or [])))
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body=price_hint_ui.page())

    with sync_playwright() as pw, pw.chromium.launch(executable_path=str(path)) as engine:
        page = engine.new_page()
        page.route("http://stand.local/**", route)
        page.goto("http://stand.local/cabinet/price-hint?latitude=55.75&longitude=37.6")
        page.wait_for_function("()=>document.querySelectorAll('.stagePick').length===4")
        before = page.evaluate(STAGE_STATE)
        page.check(".stagePick[value=pit]")
        page.wait_for_function(
            "()=>document.getElementById('stageStatus').textContent.startsWith('Посчитано')")
        after = page.evaluate(STAGE_STATE)
        page.uncheck(".stagePick[value=pit]")
        page.wait_for_function(
            "()=>document.getElementById('stageStatus').textContent.startsWith('Стадия не')")
        page.click("#stageApply")
        page.wait_for_function(
            "()=>document.getElementById('stageStatus').textContent.startsWith('Посчитано')")
        suggested = page.evaluate(STAGE_STATE)

    assert "stages" not in sent[0]
    assert before["status"].startswith("Стадия не выбрана"), before
    assert "аналогов 3" in before["status"], before
    assert before["chips"][0].startswith("котлован") and before["chips"][0].endswith("2"), before
    assert before["chips"][-1].startswith("стадия не указана"), before
    assert before["badges"] == ["котлован Пульс", "котлован оценка по срокам",
                                "стадия не указана"], before
    assert "Подсказка для нашего проекта: котлован" in before["suggest"], before

    assert sent[1]["stages"] == ["pit"] and sent[1]["include_estimated_stage"] is True
    assert after["status"].startswith("Посчитано по стадии «котлован»: аналогов 2 из 3"), after
    assert "без стадии исключено 1" in after["status"], after
    assert "510 000" in after["summary"].replace(" ", " "), after
    assert "по стадии «котлован», аналогов 2" in after["summary"], after
    assert after["checked"] == ["pit"] and "stages=pit" in after["url"], after

    assert "stages" not in sent[2]
    assert sent[3]["stages"] == ["pit"], sent
    assert suggested["checked"] == ["pit"], suggested


def test_the_price_button_sends_the_chosen_stage_and_names_it() -> None:
    import browser

    path = browser.chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_registry  # noqa: PLC0415

    sent: list[dict] = []
    answer = {"available": True, "price_th_per_sqm": 510.0, "sample": 2,
              "observed_at": "2026-09-28", "basis": "peers",
              "stage_filter": {"active": True, "title": "«котлован»",
                               "matched": 2, "considered": 3}}

    def reply(route):
        sent.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=200, content_type="application/json", body=json.dumps(answer))

    with browser.serve(main_registry.app, 19431) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page()
            page.on("dialog", lambda d: d.dismiss())
            page.route("**/market/price-hint", reply)
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("()=>!!document.getElementById('daHintStage')", timeout=20000)
            options = page.evaluate(
                "()=>[...document.getElementById('daHintStage').options].map(o=>o.textContent)")
            # Вводные на старте свёрнуты — выбор делается тем же событием,
            # что даёт список при касании.
            page.evaluate("()=>{const s=document.getElementById('daHintStage');"
                          "s.value='pit';s.dispatchEvent(new Event('change'))}")
            page.evaluate("()=>{document.getElementById('cadastralNumbers').value="
                          "'77:01:0004023:1000';document.getElementById('daHintBtn').click()}")
            page.wait_for_function(
                "()=>{const n=document.getElementById('daHintNote');"
                "return n&&n.textContent&&n.textContent!=='Считаю…'}", timeout=15000)
            note = page.evaluate("()=>document.getElementById('daHintNote').textContent")
            # Выбор переживает перерисовку вводных.
            page.evaluate("()=>renderInputs()")
            page.wait_for_function("()=>!!document.getElementById('daHintStage')", timeout=5000)
            state = page.evaluate("""()=>{
              const f=document.getElementById('f_apartment_price_th');
              return {unit:f.closest('.field').querySelector('.unit').textContent,
                      stage:document.getElementById('daHintStage').value}}""")

    assert options == ["аналоги: любая стадия", "аналоги: котлован", "аналоги: каркас",
                       "аналоги: отделка", "аналоги: сдан"], options
    assert sent and sent[0]["stages"] == ["pit"], sent
    assert "по стадии «котлован», аналогов 2 из 3" in note, note
    assert "стадия аналогов «котлован»" in state["unit"], state
    assert state["stage"] == "pit", state
