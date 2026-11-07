"""Implemented KRTs refresh observations without calculating or restamping models."""

from __future__ import annotations

import copy
import json
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auction_search import api, krt_investment_score, krt_ranking, krt_status
from auction_search.krt_screening import build_krt_model_screening, market_only_screening


RUNNING = {"slug": "running", "name": "Synthetic running site", "status": "В реализации"}
PLANNED = {"slug": "planned", "name": "Synthetic planned site", "status": "Планируемый"}
MARKET = {"analysis": {"site": {"segment": "Комфорт", "units_per_month": 8}},
          "price_hint": {"segment": "Комфорт", "price_per_sqm": 800_000, "basis": "peers"}}
KEY = "synthetic-market-key"


def forbidden(*args, **kwargs):
    pytest.fail("An implemented project reached model/burden/scoring work")


@pytest.mark.parametrize("project,kind", [
    (RUNNING, "running"),
    ({**RUNNING, "status": "  В РЕАЛИЗАЦИИ  ", "status_kind": "planned"}, "running"),
    ({"status_kind": "running"}, "running"),
    (PLANNED, "planned"),
    ({"status": "Не распознано", "status_kind": "planned"}, "unparsed"),
    ({"status_kind": "broken"}, "unparsed"),
    ({"slug": "decision:123", "no_card": True}, "draft"),
])
def test_the_shared_status_preserves_the_source_and_unknown(project, kind):
    assert krt_status.project_kind(project) == kind
    assert bool(krt_status.model_exclusion(project)) == (kind == "running")


def test_direct_screening_stops_before_reading_market_or_core():
    class Bomb:
        __getattr__ = forbidden
        get = forbidden

    answer = build_krt_model_screening({**RUNNING, "housing_gfa_sqm": 50_000}, Bomb(), Bomb())
    assert answer["available"] is False and answer["model_excluded"] is True
    assert "в реализации" in answer["reason"]
    assert "model_inputs" not in answer


def test_a_running_row_does_not_even_compute_the_model_fingerprint(monkeypatch):
    monkeypatch.setattr(krt_ranking, "model_fingerprint", forbidden)
    answer = krt_ranking.score_row(RUNNING, {"available": True,
                                           "entry_capacity": {"available": True, "amount_mln": 999}})
    assert answer["available"] is False and answer["model_excluded"]
    assert answer["computed_at"] == 0 and "entry_capacity_mln" not in answer


def test_direct_burden_stops_before_cached_model_or_cadastral_reads():
    class Bomb:
        __getattr__ = forbidden
        get = forbidden

    answer = krt_investment_score.generic_project_burden(Bomb(), RUNNING, Bomb())
    assert answer["model_excluded"] is True and answer["pending"] is False
    assert "checked_at" not in answer, "Exclusion is not a new financial calculation"


def _closure(fn):
    return dict(zip(fn.__code__.co_freevars, (cell.cell_contents for cell in fn.__closure__ or [])))


def _app(tmp_path, monkeypatch, projects=None):
    projects = projects or [RUNNING]
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CABINET_KEY", KEY)
    monkeypatch.delenv("AUCTIONS_VIEW_KEY", raising=False)
    monkeypatch.setenv("AUCTION_KRT_WEEKLY", "1")
    monkeypatch.setenv("AUCTION_KRT_WATCH", "0")
    monkeypatch.setenv("AUCTION_LOT_NOTES", "0")
    monkeypatch.setenv("AUCTION_KRT_RATING_BACKGROUND", "1")
    core = ModuleType("developaid_core")
    core.VERSION = "synthetic"
    core._run_authoritative_model = forbidden
    monkeypatch.setitem(sys.modules, "developaid_core", core)
    # Capture the real production loop functions, without starting daemons.
    # This changes only api's sys/threading bindings, not Python's modules.
    monkeypatch.setattr(api, "sys", SimpleNamespace(modules={"developaid_core": core}))
    loops = {}

    class Thread:
        def __init__(self, *, target, name, daemon):
            loops[name] = target

        def start(self):
            pass

    monkeypatch.setattr(api, "threading", SimpleNamespace(Thread=Thread))
    model_calls, market_calls, requirements = [], [], []

    def build(project, report, *args, **kwargs):
        model_calls.append(project["slug"])
        assert krt_status.project_kind(project) != "running", "Running project reached model entry"
        return {"available": True, "metrics": {"project_llcr_x": 1.3},
                "phasing": {"saleable_sqm": 1_000},
                "entry_capacity": {"available": True, "amount_mln": 1},
                "market": {"market_price_rub_sqm": 800_000}}

    def market_report(subject, **kwargs):
        market_calls.append(subject)
        return copy.deepcopy(MARKET)

    def duties(slug, **kwargs):
        requirements.append(slug)
        current = next(p for p in projects if p["slug"] == slug)
        current = krt_status.with_last_known_status(current, ranking.stored_row(slug))
        assert krt_status.model_exclusion(current) is None, "Running project reads model obligations"
        return {}

    registry = SimpleNamespace(
        catalogue=lambda **kwargs: copy.deepcopy(projects),
        projects=lambda **kwargs: copy.deepcopy(projects),
        decisions=lambda **kwargs: {"decisions": [], "matched_rows": [], "tep": {}, "complete": True},
        status=lambda: {"complete": True, "refreshing": False},
        find=lambda query: next((dict(p) for p in projects if str(query).endswith(p["slug"])), None),
        map_lookup=lambda *args: {"site": {"centre_merc": [4_000_000, 7_000_000]}},
        requirements=duties,
        card_facts=lambda *args: {"available": True, "developer": "Synthetic current developer"},
    )
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=registry, build_report=market_report, pulse=SimpleNamespace(available=True),
        search=SimpleNamespace(configured=False))
    monkeypatch.setattr(api, "build_krt_model_screening", build)
    monkeypatch.setattr(api.krt_early_projects, "projects", lambda official=None: [])
    monkeypatch.setattr(krt_investment_score, "generic_project_burden", forbidden)
    monkeypatch.setattr(krt_investment_score, "_ordinary_capex", forbidden)
    monkeypatch.setattr(krt_ranking, "model_fingerprint", lambda: "synthetic-fingerprint")
    api.install(app)
    ranking = _closure(loops["krt-weekly"])["krt_ranking"]
    return app, ranking, loops, model_calls, market_calls, requirements


def _keep_old_model(ranking):
    old = {"slug": "running", "status": "Планируемый", "available": True, "computed_at": 100,
           "entry_capacity_mln": 123, "project_llcr_x": 1.25,
           "investment_rating": {"score": 77}, "investment_rating_computed_at": 101}
    ranking._persist({"running": old})
    ranking.save_report("running", {"project": dict(RUNNING), "market": {"old": True},
                                    "screening": {"available": True, "model_inputs": {"old": True}}},
                        computed_at=100)
    return ranking.report_path("running").read_bytes()


def test_the_real_market_route_refreshes_only_market_and_keeps_the_old_model(tmp_path, monkeypatch):
    app, ranking, _, model_calls, market_calls, requirements = _app(tmp_path, monkeypatch)
    old_bytes = _keep_old_model(ranking)
    answer = TestClient(app).get("/auctions/krt/running/market", headers={"X-Market-Key": KEY})
    assert answer.status_code == 200, answer.text
    assert answer.json()["model_screening"]["model_excluded"]
    assert market_calls and not model_calls and not requirements
    assert ranking.report_path("running").read_bytes() == old_bytes
    row = ranking.stored_row("running")
    assert row["entry_capacity_mln"] == 123 and row["computed_at"] == 100
    assert row["investment_rating"] == {"score": 77}
    assert row["surrounding_price_rub_sqm"] == 800_000
    assert row["market_computed_at"] > 100
    report = ranking.report("running")
    assert report["computed_at"] == 100 and report["screening"]["model_inputs"] == {"old": True}
    assert report["market"]["price_hint"]["price_per_sqm"] == 800_000


@pytest.mark.parametrize("old_model", [False, True])
def test_ensure_model_never_recalculates_or_persists_a_running_rating(tmp_path, monkeypatch, old_model):
    app, ranking, _, model_calls, market_calls, requirements = _app(tmp_path, monkeypatch)
    if old_model:
        _keep_old_model(ranking)
    before = ranking.path.read_bytes() if ranking.path.exists() else None
    answer = TestClient(app).get("/auctions/krt/running/investment-score?ensure_model=true",
                                headers={"X-Market-Key": KEY})
    assert answer.status_code == 200, answer.text
    assert answer.json()["rating"]["rankable"] is False
    assert answer.json()["rating"]["score"] is None
    assert not model_calls and not market_calls and not requirements
    assert (ranking.path.read_bytes() if ranking.path.exists() else None) == before


class StopPass(BaseException):
    pass


def _one_pass(monkeypatch, loop, *, background=False, passes=1):
    sleeps = 0

    def sleep(seconds):
        nonlocal sleeps
        if background and seconds == 12:
            return
        sleeps += 1
        if sleeps >= passes:
            raise StopPass

    clock = SimpleNamespace(**{name: getattr(time, name) for name in dir(time)
                               if not name.startswith("__")})
    clock.sleep = sleep
    monkeypatch.setattr(api, "time", clock)
    with pytest.raises(StopPass):
        loop()


def _synchronous_worker(monkeypatch, ranking):
    start = ranking.start

    def run(projects, screen, **kwargs):
        started = start(projects, screen, **kwargs)
        if started:
            ranking._thread.join(timeout=20)
            assert not ranking._thread.is_alive()
        return started

    monkeypatch.setattr(ranking, "start", run)


def test_the_real_weekly_pass_models_only_allowed_projects(tmp_path, monkeypatch):
    app, ranking, loops, model_calls, market_calls, _ = _app(tmp_path, monkeypatch, [RUNNING, PLANNED])
    old_bytes = _keep_old_model(ranking)
    monkeypatch.setattr(ranking, "due", lambda: True)
    _synchronous_worker(monkeypatch, ranking)
    _one_pass(monkeypatch, loops["krt-weekly"])
    assert model_calls == ["planned"]
    assert len(market_calls) == 2
    assert ranking.report_path("running").read_bytes() == old_bytes
    assert ranking.stored_row("running")["computed_at"] == 100
    assert ranking.stored_row("running")["card_facts"]["developer"] == "Synthetic current developer"
    progress = ranking.progress()
    assert progress["model_skipped"] == 1 and progress["done"] == 2 and progress["failed"] == 0


def test_the_real_background_loop_uses_market_freshness_without_a_model(tmp_path, monkeypatch):
    _, ranking, loops, model_calls, market_calls, _ = _app(tmp_path, monkeypatch)
    old_bytes = _keep_old_model(ranking)
    _synchronous_worker(monkeypatch, ranking)
    _one_pass(monkeypatch, loops["krt-rating-background"], background=True, passes=2)
    assert len(market_calls) == 1, "Fresh observations are not a stale model retry every minute"
    assert not model_calls
    assert ranking.report_path("running").read_bytes() == old_bytes
    assert ranking.stored_row("running")["investment_rating"] == {"score": 77}


def test_a_market_only_record_does_not_claim_a_model_was_computed(tmp_path):
    ranking = krt_ranking.KrtRanking(tmp_path)
    observed = market_only_screening(RUNNING, MARKET)
    ranking.save_market_only(RUNNING, observed, MARKET)
    assert not ranking.report_path("running").exists()
    assert ranking.report("running")["computed_at"] == 0
    assert not ranking.report("running")["screening"]["available"]
    assert "computed_at" not in ranking.stored_row("running")


def test_a_corrupt_observations_cache_does_not_hide_a_preserved_model(tmp_path):
    ranking = krt_ranking.KrtRanking(tmp_path)
    _keep_old_model(ranking)
    path = ranking._market_report_path("running")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]")
    assert ranking.report("running")["computed_at"] == 100
    assert ranking.report("running")["screening"]["available"]


@pytest.mark.parametrize("pace,known", [(0, True), (None, False), ("bad", False), (False, False)])
def test_market_observations_distinguish_zero_from_unknown(pace, known):
    report = copy.deepcopy(MARKET)
    report["analysis"]["site"]["units_per_month"] = pace
    observed = market_only_screening(RUNNING, report)["absorption"]
    assert observed["available"] is known
    assert observed["market_units_per_month"] == (0 if known else None)


def test_an_empty_market_reply_is_a_failed_observation_not_a_new_model(tmp_path):
    ranking = krt_ranking.KrtRanking(tmp_path)
    old_bytes = _keep_old_model(ranking)
    assert ranking.start([RUNNING], lambda p: market_only_screening(p, {}))
    ranking._thread.join(timeout=10)
    assert not ranking._thread.is_alive()
    assert ranking.progress()["failed"] == 1
    assert "не вернул отчёт" in ranking.stored_row("running")["market_failure_reason"]
    assert ranking.stored_row("running")["status"] == "В реализации"
    assert ranking.stored_row("running")["model_excluded"] is True
    assert ranking.report_path("running").read_bytes() == old_bytes
    assert ranking.stored_row("running")["computed_at"] == 100


BAD_MARKET_REPORTS = [
    pytest.param({}, id="empty"),
    pytest.param(None, id="missing"),
    pytest.param([], id="list"),
    pytest.param({"error": "synthetic source failure"}, id="source-error"),
    pytest.param({**MARKET, "available": False}, id="explicitly-unavailable"),
    pytest.param({"analysis": "broken"}, id="wrong-analysis"),
    pytest.param({"analysis": {"site": []}}, id="wrong-site"),
    pytest.param({"subject": {"query": "synthetic"}}, id="no-observations"),
    pytest.param({"price_hint": {"price_per_sqm": float("inf"), "basis": "peers"}}, id="infinite-price"),
]


def _keep_good_market(ranking):
    observed = market_only_screening(RUNNING, MARKET)
    ranking.save_market_only(RUNNING, observed, MARKET)
    return ranking._market_report_path("running").read_bytes(), ranking.stored_row("running")


@pytest.mark.parametrize("report", BAD_MARKET_REPORTS)
def test_bad_market_api_does_not_restamp_or_erase_previous_observations(tmp_path, monkeypatch, report):
    app, ranking, _, model_calls, _, requirements = _app(tmp_path, monkeypatch)
    old_model = _keep_old_model(ranking)
    old_market, previous_row = _keep_good_market(ranking)
    app.state.market_discovery_service.build_report = lambda *args, **kwargs: copy.deepcopy(report)
    response = TestClient(app).get("/auctions/krt/running/market", headers={"X-Market-Key": KEY})
    assert response.status_code == 502, response.text
    row = ranking.stored_row("running")
    assert row["market_computed_at"] == previous_row["market_computed_at"]
    assert row["market_failed_at"] and row["market_failure_reason"]
    assert row["surrounding_price_rub_sqm"] == 800_000
    assert row["investment_rating"] == {"score": 77} and row["computed_at"] == 100
    assert ranking._market_report_path("running").read_bytes() == old_market
    assert ranking.report_path("running").read_bytes() == old_model
    assert not model_calls and not requirements


@pytest.mark.parametrize("report", BAD_MARKET_REPORTS)
def test_storage_rechecks_bad_raw_market_even_with_previously_good_screening(tmp_path, report):
    ranking = krt_ranking.KrtRanking(tmp_path)
    old_model = _keep_old_model(ranking)
    old_market, previous_row = _keep_good_market(ranking)
    good_screening = market_only_screening(RUNNING, MARKET)
    with pytest.raises(ValueError):
        ranking.save_market_only(RUNNING, good_screening, report)
    assert ranking.stored_row("running")["market_computed_at"] == previous_row["market_computed_at"]
    assert ranking.stored_row("running")["market_failure_reason"]
    assert ranking._market_report_path("running").read_bytes() == old_market
    assert ranking.report_path("running").read_bytes() == old_model


def test_storage_rejects_an_explicit_problem_even_if_the_raw_market_looks_valid(tmp_path):
    ranking = krt_ranking.KrtRanking(tmp_path)
    old_market, previous_row = _keep_good_market(ranking)
    problem = {**market_only_screening(RUNNING, MARKET), "market_problem": "Synthetic review failed"}
    with pytest.raises(ValueError, match="Synthetic review failed"):
        ranking.save_market_only(RUNNING, problem, MARKET)
    row = ranking.stored_row("running")
    assert row["market_failure_reason"] == "Synthetic review failed"
    assert row["market_computed_at"] == previous_row["market_computed_at"]
    assert ranking._market_report_path("running").read_bytes() == old_market


def test_zero_sales_without_a_known_price_are_valid_observations(tmp_path):
    ranking = krt_ranking.KrtRanking(tmp_path)
    report = {"analysis": {"site": {"units_per_month": 0}}}
    observed = market_only_screening(RUNNING, report)
    ranking.save_market_only(RUNNING, observed, report)
    row = ranking.stored_row("running")
    assert row["market_computed_at"] and not row["market_failed_at"]
    assert row["surrounding_sales_units_per_month"] == 0
    assert row["surrounding_price_rub_sqm"] is None


UNKNOWN_RUNNING = {**RUNNING, "status": "Новое значение, не распознано", "status_kind": "running"}


def test_an_unparsed_transition_retains_last_running_without_relabelling_the_raw_status():
    excluded = krt_status.model_exclusion(UNKNOWN_RUNNING)
    assert krt_status.project_kind(UNKNOWN_RUNNING) == "unparsed"
    assert excluded["status_kind"] == "unparsed"
    assert excluded["last_known_status_kind"] == "running"
    assert "не распознан" in excluded["reason"] and "не подтверждено" in excluded["reason"]
    assert UNKNOWN_RUNNING["status"] == "Новое значение, не распознано"


def test_unknown_following_running_stops_direct_screening_and_burden_before_reads():
    class Bomb:
        __getattr__ = forbidden
        get = forbidden

    project = {**UNKNOWN_RUNNING, "housing_gfa_sqm": 50_000}
    for answer in (build_krt_model_screening(project, Bomb(), Bomb()),
                   krt_investment_score.generic_project_burden(Bomb(), project, Bomb())):
        assert answer["model_excluded"] and answer["status_kind"] == "unparsed"


def test_a_recognized_planned_transition_replaces_the_old_running_history():
    previous = krt_status.with_last_known_status(RUNNING)
    unknown = krt_status.with_last_known_status(UNKNOWN_RUNNING, previous)
    assert krt_status.model_exclusion(unknown)
    planned = krt_status.with_last_known_status({**unknown, "status": "Планируемый"}, unknown)
    assert planned["last_known_status_kind"] == "planned"
    assert planned["status_kind"] == "planned"
    assert krt_status.model_exclusion(planned) is None
    unknown_again = krt_status.with_last_known_status(UNKNOWN_RUNNING, planned)
    assert unknown_again["last_known_status_kind"] == "planned"
    assert unknown_again["status_kind"] == "unparsed"
    assert krt_status.project_kind(unknown_again) == "unparsed"
    assert krt_status.model_exclusion(unknown_again) is None
    assert krt_status.model_exclusion({"status": "Нераспознанный новый статус"}) is None


def test_the_real_weekly_loop_preserves_a_model_during_an_unknown_running_transition(tmp_path, monkeypatch):
    _, ranking, loops, model_calls, _, requirements = _app(tmp_path, monkeypatch, [UNKNOWN_RUNNING])
    old_model = _keep_old_model(ranking)
    monkeypatch.setattr(ranking, "due", lambda: True)
    _synchronous_worker(monkeypatch, ranking)
    _one_pass(monkeypatch, loops["krt-weekly"])
    assert not model_calls and not requirements
    assert ranking.report_path("running").read_bytes() == old_model
    row = ranking.stored_row("running")
    assert row["computed_at"] == 100 and row["entry_capacity_mln"] == 123
    assert row["status"] == UNKNOWN_RUNNING["status"]
    assert row["status_kind"] == "unparsed" and row["last_known_status_kind"] == "running"
    assert ranking.progress()["model_skipped"] == 1


def test_running_history_and_its_planned_replacement_survive_separate_apps(tmp_path, monkeypatch):
    app, ranking, _, calls, _, _ = _app(tmp_path, monkeypatch, [UNKNOWN_RUNNING])
    _keep_old_model(ranking)
    response = TestClient(app).get("/auctions/krt/running/market", headers={"X-Market-Key": KEY})
    assert response.status_code == 200 and not calls
    assert ranking.stored_row("running")["last_known_status_kind"] == "running"

    # A new process with no derived status hint still has the saved witness.
    no_hint = {key: value for key, value in UNKNOWN_RUNNING.items() if key != "status_kind"}
    app, ranking, _, calls, _, _ = _app(tmp_path, monkeypatch, [no_hint])
    old_model = ranking.report_path("running").read_bytes()
    response = TestClient(app).get("/auctions/krt/running/market", headers={"X-Market-Key": KEY})
    assert response.status_code == 200 and not calls
    assert ranking.report_path("running").read_bytes() == old_model

    # A recognized source transition, unlike unknown, permits the normal model.
    app, ranking, _, calls, _, _ = _app(tmp_path, monkeypatch, [{**UNKNOWN_RUNNING, "status": "Планируемый"}])
    response = TestClient(app).get("/auctions/krt/running/market", headers={"X-Market-Key": KEY})
    assert response.status_code == 200 and calls == ["running"]
    assert ranking.stored_row("running")["last_known_status_kind"] == "planned"

    app, ranking, _, calls, _, _ = _app(tmp_path, monkeypatch, [UNKNOWN_RUNNING])
    response = TestClient(app).get("/auctions/krt/running/market", headers={"X-Market-Key": KEY})
    assert response.status_code == 200 and calls == ["running"]
    assert ranking.stored_row("running")["status_kind"] == "unparsed"
    assert ranking.stored_row("running")["last_known_status_kind"] == "planned"


def test_unknown_running_rating_refuses_truthfully_without_market_or_model(tmp_path, monkeypatch):
    app, ranking, _, calls, market_calls, requirements = _app(tmp_path, monkeypatch, [UNKNOWN_RUNNING])
    old_model = _keep_old_model(ranking)
    response = TestClient(app).get("/auctions/krt/running/investment-score?ensure_model=true",
                                   headers={"X-Market-Key": KEY})
    assert response.status_code == 200
    rating = response.json()["rating"]
    assert rating["rankable"] is False and rating["status_kind"] == "unparsed"
    assert "не распознан" in rating["reason"] and "Последний известный" in rating["reason"]
    assert not calls and not market_calls and not requirements
    assert ranking.report_path("running").read_bytes() == old_model


def test_source_snapshot_retains_and_updates_status_history_without_running_models(tmp_path):
    from market_search.krt_registry import KrtRegistry

    status = ["В реализации"]

    def fetch(url):
        return (f'<a href="/projects/synthetic">Synthetic site</a>'
                f'<p>Статус: {status[0]}</p>').encode()

    registry = KrtRegistry(tmp_path, fetch=fetch)
    for value, last_known, excluded in [
        ("В реализации", "running", True),
        ("Новое значение, не распознано", "running", True),
        ("Планируемый", "planned", False),
        ("Другое нераспознанное значение", "planned", False),
    ]:
        status[0] = value
        row = registry.projects(refresh=True, max_pages=1)[0].to_dict()
        assert row["status"] == value and row["last_known_status_kind"] == last_known
        assert bool(krt_status.model_exclusion(row)) is excluded
        reloaded = KrtRegistry(tmp_path, fetch=forbidden).catalogue()[0]
        assert reloaded["last_known_status_kind"] == last_known
        assert reloaded["status"] == value


@pytest.mark.parametrize("old_snapshot", [[], {"projects": [None, 123]}, {"projects": 123}])
def test_bad_old_history_does_not_block_a_successful_source_refresh(tmp_path, old_snapshot):
    from market_search.krt_registry import KrtRegistry

    page = '<a href="/projects/synthetic">Synthetic site</a><p>Статус: Планируемый</p>'.encode()
    registry = KrtRegistry(tmp_path, fetch=lambda url: page)
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(json.dumps(old_snapshot))
    rows = registry.projects(refresh=True, max_pages=1)
    assert rows and rows[0].slug == "synthetic"
    assert rows[0].last_known_status_kind == "planned"
