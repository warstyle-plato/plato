"""Нажатая кнопка обязана сходить в источник, а не перерисовать файл.

Снимок каталога КРТ живёт сутки, и обход источника начинался ТОЛЬКО у
просроченного снимка. «Обновить каталог» на свежем снимке не читал ничего:
страница перерисовывала тот же файл. Опубликованный вчера проект решения ждал
ночного обхода, а на экране это выглядело как «в источнике его нет» —
владелец открыл документ по ул. Архитектора Власова, вл. 59, не нашёл его у
нас и спросил: «Так я жал обновить, значит вручную не обновляется каталог?»
(04.09.2026).

Кнопка, которая ничего не делает, хуже отсутствующей: по ней судят об
источнике. И рядом второе — возраст снимка обязан быть на экране: без даты
«263 площадки» читается как ответ города сию секунду.

Запуск: python3 -m pytest tests/test_the_refresh_button_reads_the_source.py -q
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_registry import KrtRegistry  # noqa: E402


def _registry(tmp_path: Path) -> tuple[KrtRegistry, list[str]]:
    """Реестр со свежим полным снимком и счётчиком заказанных обходов."""
    registry = KrtRegistry(tmp_path, fetch=lambda url: b"")
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    from market_search import krt_registry as module

    registry.path.write_text(json.dumps({
        "schema_version": module.CACHE_SCHEMA_VERSION,
        "complete": True,
        "projects": [],
    }), encoding="utf-8")
    asked: list[str] = []
    registry.refresh_in_background = lambda: asked.append("catalogue") or True  # type: ignore[assignment]
    return registry, asked


def test_a_fresh_snapshot_is_not_re_read_on_its_own(tmp_path) -> None:
    """Обычное открытие страницы источник не трогает — иначе город бьют зря."""
    registry, asked = _registry(tmp_path)
    registry.catalogue()
    assert asked == [], "свежий полный снимок сам по себе обход не заказывает"


def test_the_hand_asks_the_source_even_on_a_fresh_snapshot(tmp_path) -> None:
    """Ровно та поломка: нажатая кнопка на суточном снимке читала файл."""
    registry, asked = _registry(tmp_path)
    registry.catalogue(refresh=True)
    assert asked == ["catalogue"], (
        "«Обновить каталог» обязано означать обход источника, а не перерисовку")


def test_the_snapshot_says_when_it_was_taken(tmp_path) -> None:
    """Возраст снимка — часть ответа, а не подробность."""
    registry, _ = _registry(tmp_path)
    status = registry.status()
    assert status["retrieved_at"] > time.time() - 120, "дата снимка не доехала"
    assert status["ttl_seconds"] == registry.ttl_seconds
    assert "decisions_refreshing" in status, "ход обхода решений не назван"


def test_the_decisions_are_refreshed_off_thread(tmp_path) -> None:
    """Шестьдесят страниц поиска в срок ответа не укладываются.

    Работу принимают, а не держат соединением: обход идёт фоном, а его ход
    виден полем состояния — иначе нажавший кнопку человек видит прежний список
    и решает, что обновление не работает.
    """
    registry = KrtRegistry(tmp_path, fetch=lambda url: b"")
    seen: list[bool] = []
    started = {"busy": False}

    def slow(*, refresh: bool = False, **_):
        # Состояние снимается ДО отметки о вызове: ждущий поток просыпается по
        # отметке, и обратный порядок дал бы гонку, а не проверку.
        started["busy"] = registry.status()["decisions_refreshing"]
        seen.append(refresh)
        return {}

    registry.decisions = slow  # type: ignore[assignment]
    assert registry.refresh_decisions_in_background() is True
    for _ in range(200):
        if seen:
            break
        time.sleep(0.01)
    assert seen == [True], "фоновый обход решений не позвал источник заново"
    assert started["busy"], "ход обхода решений не виден снаружи"


def test_the_route_passes_the_hand_through(tmp_path, monkeypatch) -> None:
    """Проверять надо ту поверхность, на которую жалуются, — маршрут."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auction_search.api import install

    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    asked: list[bool] = []
    decisions_asked: list[str] = []
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **kw: asked.append(bool(kw.get("refresh"))) or [],
            status=lambda: {"complete": True, "refreshing": False,
                            "decisions_refreshing": False,
                            "retrieved_at": 1_756_900_000, "ttl_seconds": 86400},
            refresh_decisions_in_background=lambda: decisions_asked.append("go") or True,
        ),
    )
    install(app)
    client = TestClient(app)

    plain = client.get("/auctions/krt", headers={"X-Market-Key": "test-key"})
    assert plain.status_code == 200, plain.text
    assert asked == [False]
    assert decisions_asked == [], "открытие страницы решения заново не читает"
    assert plain.json()["retrieved_at"] == 1_756_900_000, "дата снимка не доехала до экрана"

    forced = client.get("/auctions/krt?refresh=true", headers={"X-Market-Key": "test-key"})
    assert forced.status_code == 200, forced.text
    assert asked == [False, True], "рука до каталога не дошла"
    assert decisions_asked == ["go"], (
        "решения mos.ru — второй источник этого же экрана, и кнопка одна")


def test_the_button_on_the_page_asks_for_the_source() -> None:
    """Кнопка звала перерисовку — на экране это неотличимо от обновления."""
    from auction_search import ui

    page = ui.auctions_page()
    assert "$('krtRefresh').onclick=()=>loadKrt(true);" in page, \
        "кнопка «Обновить каталог» обязана звать обход источника"
    assert "'/auctions/krt'+(force?'?refresh=true':'')" in page
    assert "renderKrtSnapshotNote" in page, "дату снимка на экране никто не рисует"
    assert "krtSnapshot" in page
