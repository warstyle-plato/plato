"""Площадка-решение считается моделью — той же, что площадка каталога.

«И как их построить?» (владелец, 05.09.2026) — про 298 площадок, у которых на
mos.ru опубликован проект решения, а карточки в каталоге krt.mos.ru нет. Цифры
у них есть: площадь территории, предельная СПП и площадь квартир прочитаны из
самого PDF. Не было двух вещей.

**Точки.** Разбор субъекта ищет площадку в каталоге, а её там нет по
построению: `build_report("krt:decision:…")` отказывал раньше, чем что-то
считал, и наш служебный ключ уходил геокодеру как адрес человека. Теперь
`find` знает вторую половину списка и отвечает адресом из заголовка решения.

**Обязательств.** Снос и расселение — это CAPEX, а метры Программы реновации
строятся и не продаются. Лежат они в том же PDF, что и ТЭП, и читаются тем же
путём; без них модель продавала бы всё жильё по рынку — ровно ошибка, уже
пойманная на Задонском проезде.

И граница, названная вслух: **нежилые пока не считаем** (решение владельца
05.09.2026 — «давай нежилые пока не считать»). У офисного центра своя
экономика, и считать его пресетом жилья значило бы показать посчитанным то,
что посчитано не тем. Это ответ методики, а не наш пробел.

Запуск: python3 -m pytest tests/test_a_decision_site_is_modelled_too.py -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_search import krt_registry as registry_module  # noqa: E402
from market_search.krt_registry import KrtRegistry  # noqa: E402
from market_search.subject import resolve_subject  # noqa: E402

API = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")

# Снимок решений в том виде, в каком его держит диск.
_SNAPSHOT = {
    "schema_version": registry_module.DECISIONS_CACHE_SCHEMA_VERSION,
    "complete": True,
    "all": [
        {"id": "347614220", "title": "Проект решения о комплексном развитии территории",
         "address": "ул. Архитектора Власова, влд. 59", "okrug": "ЮЗАО",
         "url": "https://www.mos.ru/dgp/documents/view/347614220/",
         "published_at": 1_788_400_000},
        # Заголовок без адреса: город написал «расположенной адресу» без
        # двоеточия, и разбор честно вернул пустую строку.
        {"id": "336775220", "title": "Проект решения … расположенной адресу",
         "address": "", "okrug": "", "published_at": 1_788_300_000,
         "url": "https://www.mos.ru/dgp/documents/view/336775220/"},
    ],
}


def _registry(tmp_path: Path, fetch=None) -> KrtRegistry:
    store = KrtRegistry(tmp_path, fetch=fetch or (lambda url: b""))
    store.decisions_path.parent.mkdir(parents=True, exist_ok=True)
    store.decisions_path.write_text(json.dumps(_SNAPSHOT), encoding="utf-8")
    return store


# --- площадка находится по номеру своего решения -----------------------------

def test_the_decision_site_is_found_by_its_document(tmp_path: Path) -> None:
    """`krt:decision:<id>` разрешается адресом решения, и с диска."""
    store = _registry(tmp_path)
    found = store.find("krt:decision:347614220")
    assert found, "площадка-решение не находится вовсе"
    assert found["name"] == "ул. Архитектора Власова, влд. 59"
    assert found["geocode_query"] == "Москва, ул. Архитектора Власова, влд. 59"
    assert found["no_card"] is True
    # Округ районом не подменяется: он вшестеро крупнее, и точка по нему стояла
    # бы в чужом квартале с уверенным видом.
    assert not found.get("district")

    # Заголовок без адреса опознаёт документ, а не место: такой площадки для
    # геокодера не существует, и это отказ, а не точка наугад.
    assert store.find("krt:decision:336775220") is None
    assert store.find("krt:decision:999999999") is None
    # Каталог при этом ищется по-прежнему — своим слагом.
    assert store.find("krt:decision:abc") is None


def test_the_note_names_the_source_of_the_site(tmp_path: Path) -> None:
    """«Взята из krt.mos.ru» у площадки-решения было бы неверно."""
    store = _registry(tmp_path)
    point = SimpleNamespace(latitude=55.66, longitude=37.53,
                            display_name="ул. Архитектора Власова, 59")
    subject = resolve_subject(
        "krt:decision:347614220", geocode=lambda query: point, find_krt=store.find)
    assert subject.subject_type == "krt"
    said = " ".join(subject.notes)
    assert "mos.ru: проект решения о КРТ" in said, said
    assert "взята из krt.mos.ru" not in said, said


# --- обязательства из того же документа --------------------------------------

_TEXT = (
    "Предельная суммарная поэтажная площадь объектов жилого назначения – 50 400 кв.м, "
    "в том числе для реализации Программы реновации жилищного фонда в городе Москве – "
    "15 100 кв.м. Площадь территории – 3,1 га."
)


def _reader(calls: list[str], *, text: str = _TEXT):
    def fetch(url: str) -> bytes:
        calls.append(url)
        if "attachments" in url:
            return json.dumps({"items": [{"attachments": [
                {"url": "https://www.mos.ru/upload/resh.pdf"}]}]}).encode()
        if url.endswith(".pdf"):
            return b"%PDF-1.4 fake"
        return json.dumps({"title": "Проект решения о КРТ", "institution_id": 7}).encode()

    return fetch


def test_the_duties_come_from_the_same_pdf(tmp_path: Path, monkeypatch) -> None:
    """Обязательства площадки-решения читаются, а не остаются «не знаем»."""
    calls: list[str] = []
    monkeypatch.setattr(registry_module, "pdf_text", lambda data: _TEXT)
    store = _registry(tmp_path, fetch=_reader(calls))

    duties = store.decision_requirements("347614220")
    assert duties["available"] is True
    assert duties["decision_available"] is True
    # Городские нужды — не «да/нет», а объём: доля меряется, а не оценивается.
    assert (duties.get("renovation") or {}).get("area_sqm") == 15_100
    # Второй раз с диска, без единого запроса.
    before = len(calls)
    again = store.decision_requirements("347614220")
    assert again["available"] is True and len(calls) == before

    # Дорога до документа одна на двоих: тот же помощник читает и ТЭП.
    assert API.count("def _requirements_for(") == 1
    source = (ROOT / "market_search" / "krt_registry.py").read_text(encoding="utf-8")
    assert source.count("def _decision_pdf(") == 1
    tep_body = source[source.index("    def decision_tep("):
                      source.index("    def decision_tep_known(")]
    assert "self._decision_pdf(" in tep_body, "у ТЭП своя вторая дорога до PDF"


def test_an_unread_decision_is_not_an_empty_one(tmp_path: Path) -> None:
    """«Не прочитали» — наш пробел, а не «город ничего не потребовал»."""
    def fetch(url: str) -> bytes:
        raise RuntimeError("mos.ru не ответил")

    store = _registry(tmp_path, fetch=fetch)
    duties = store.decision_requirements("347614220")
    assert duties["available"] is False
    assert "неизвестны, а не отсутствуют" in duties["warning"], duties
    assert duties["reason"], "отказ без причины неотличим от молчания"
    # Отказ записан: незаписанный отказ нельзя посчитать.
    assert (store.decision_requirements_dir / "347614220.json").exists()


# --- и сам прогон ------------------------------------------------------------

@pytest.fixture(scope="module")
def core():
    spec = importlib.util.spec_from_file_location("developaid_core", ROOT / "main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["developaid_core"] = module
    spec.loader.exec_module(module)
    return module


_REPORT = {
    "analysis": {"site": {"segment": "Бизнес", "price_per_sqm": 450_000,
                          "sold_lot_avg": 58, "units_per_month": 25}},
    "price_hint": {},
    "subject": {"query": "krt:decision:347614220"},
}

_ROWS = {
    "decisions": [
        {"id": "347614220", "title": "Проект решения о КРТ",
         "address": "ул. Архитектора Власова, влд. 59", "okrug": "ЮЗАО",
         "url": "https://www.mos.ru/dgp/documents/view/347614220/",
         "published_at": 1_788_400_000},
        {"id": "700000001", "title": "Проект решения о КРТ нежилой застройки",
         "address": "Нежилая ул., влд. 1", "okrug": "САО",
         "url": "https://www.mos.ru/dgp/documents/view/700000001/",
         "published_at": 1_788_300_000},
        {"id": "336775220", "title": "Проект решения … расположенной адресу",
         "address": "", "okrug": "", "published_at": 1_788_200_000,
         "url": "https://www.mos.ru/dgp/documents/view/336775220/"},
    ],
    "matched_rows": [],
    "tep": {
        "347614220": {"available": True, "read": True, "area_ha": 3.1,
                      "total_gfa_sqm": 60_000, "housing_gfa_sqm": 50_400},
        # Нежилая площадка: объём назван, жилья нет.
        "700000001": {"available": True, "read": True, "area_ha": 2.0,
                      "total_gfa_sqm": 40_000, "nonresidential_gfa_sqm": 40_000},
    },
}


def _app(monkeypatch, core):
    fastapi = pytest.importorskip("fastapi")
    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "developaid_core", core)
    asked: list[str] = []

    def build_report(query, **kw):
        asked.append(query)
        return dict(_REPORT)

    # Обязательства площадки — те, что читаются из её же решения: метры
    # Программы реновации строятся и не продаются.
    duties = {"available": True, "decision_available": True,
              "renovation": {"mentioned": True, "area_sqm": 15_100,
                             "housing_sqm": 50_400, "zones": 1,
                             "basis": "decision", "quote": "…"}}
    app = fastapi.FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        build_report=build_report,
        search=SimpleNamespace(configured=False),
        krt=SimpleNamespace(
            catalogue=lambda **_: [],
            status=lambda: {"complete": True, "refreshing": False},
            decisions=lambda **_: dict(_ROWS),
            decision_requirements=lambda document_id, **_: dict(duties, asked=document_id),
            requirements=lambda slug, **_: None,
            card_facts=lambda slug, **_: {"available": False},
        ),
    )
    from auction_search import api as auction_api

    auction_api.install(app)
    return app, asked


def _finished(client) -> None:
    for _ in range(400):
        if not client.get("/auctions/krt/ranking").json()["progress"]["running"]:
            return
        time.sleep(0.05)
    raise AssertionError("прогон не кончился — итог читался бы наугад")


def test_the_run_models_the_residential_decision(monkeypatch, core) -> None:
    """Жильё в решении — площадка считается; нежилая названа, а не пропущена."""
    from fastapi.testclient import TestClient

    app, asked = _app(monkeypatch, core)
    client = TestClient(app)
    answer = client.post("/auctions/krt/ranking/refresh", headers={"X-Market-Key": "test-key"},
                         json={"slugs": ["decision:347614220", "decision:700000001",
                                         "decision:336775220"]})
    assert answer.status_code == 200, answer.text
    assert answer.json()["started"] is True, answer.json()
    _finished(client)
    rows = {row["slug"]: row for row in client.get("/auctions/krt/ranking").json()["rows"]}

    # Жилая посчитана моделью — отчёт рынка для неё спрошен.
    assert "krt:decision:347614220" in asked, asked
    housing = rows.get("decision:347614220") or {}
    assert housing.get("available") is True, housing
    # Метры Программы реновации из решения доехали до модели: они строятся и
    # не продаются, иначе площадка продаёт по рынку то, что отдаёт городу.
    renovation = housing.get("renovation") or {}
    assert renovation.get("spp_sqm") == 15_100, renovation
    assert renovation.get("share") == pytest.approx(15_100 / 50_400, abs=0.001), renovation
    assert housing.get("project_llcr_x") is not None, housing
    # И посчитана она нынешней методикой — иначе строка неотличима от прежней.
    assert housing.get("rules_version"), housing

    # Нежилая: отказ методики, названный словами, и рынок за неё не оплачен.
    other = rows.get("decision:700000001") or {}
    assert other.get("available") is False, other
    assert "нежилую площадку модель пока не считает" in str(other.get("reason")), other
    assert "krt:decision:700000001" not in asked, "нежилая всё-таки сходила к рынку"

    # Без адреса — прежний ответ: искать не по чему.
    assert "krt:decision:336775220" not in asked


def test_the_run_covers_both_halves_of_the_list() -> None:
    """Кнопка прогона идёт по тому же списку, что виден на экране."""
    start = API.index("    async def auction_krt_ranking_refresh(")
    body = API[start:API.index("\n    def _press_only(", start)]
    assert "_krt_all_sites" in body, "прогон планирует одну половину списка"
    assert "krt_registry.catalogue" not in body
    # Чем считать строку, решает один и тот же выбор, что и в недельном прогоне.
    assert "_screen_for" in body and "_screen_one" not in body
