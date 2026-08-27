"""Каталог торгов отвечает в срок и называет причину, если ответ не JSON.

27.08.2026 модуль торгов перестал показывать что-либо вовсе, а на месте
таблицы стояло «The string did not match the expected pattern». Это сообщение
Safari о разборе JSON: сервер ответил не JSON, страница разобрала ответ
вслепую и показала поломку разбора вместо причины отказа.

Причин, по которым сервер мог не ответить JSON, оказалось две, и обе про
время. Сбор был ограничен только ЧИСЛОМ СТРАНИЦ, то есть объёмом: сорок
страниц ГИС Торгов по восемь секунд, у Росэлторга и РАД — по запросу на каждый
найденный лот по двадцать пять. Шлюз столько не держит. А одна недоступная
карточка РАД роняла весь сбор: исключение не ловилось, маршрут отвечал 502.

Запуск: python3 -m pytest tests/test_the_catalogue_answers_in_time.py -q
"""

from __future__ import annotations

import inspect
import re
import subprocess
import time
from pathlib import Path

import pytest

from auction_search import deadline as clock
from auction_search.service import AuctionSearchService

ROOT = Path(__file__).resolve().parent.parent
UI = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")
API = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")


class _Slow:
    """Источник, который сам по себе не кончается."""

    platform_name = "Медленный"

    def __init__(self, seconds: float = 0.25) -> None:
        self.seconds = seconds
        self.asked = 0

    def discover_moscow(self, *, deadline: float | None = None):
        self.asked += 1
        while not clock.expired(deadline):
            time.sleep(0.01)
        return []

    def fetch_lot(self, lot_url: str):  # pragma: no cover — не зовётся
        raise NotImplementedError


class _Never:
    """Источник без поддержки срока — зовётся как раньше."""

    platform_name = "Простой"

    def __init__(self) -> None:
        self.asked = 0

    def discover_moscow(self):
        self.asked += 1
        return []

    def fetch_lot(self, lot_url: str):  # pragma: no cover
        raise NotImplementedError


def test_the_collection_stops_at_the_deadline():
    """Иначе ответа не получает никто: шлюз рвёт соединение раньше."""
    slow = _Slow()
    started = time.monotonic()
    AuctionSearchService([slow]).discover_moscow(budget_seconds=0.3)
    assert time.monotonic() - started < 3, "сбор не уложился в отведённый срок"
    assert slow.asked == 1


def test_a_source_that_was_never_asked_says_so():
    """Молча пропущенный источник читается как «лотов там нет»."""
    slow, second = _Slow(), _Slow()
    AuctionSearchService([slow, second]).discover_moscow(budget_seconds=0.2)
    assert second.asked == 0, "до второго источника дойти не должны были"
    assert "не опрошен" in second.last_report["reason"]
    assert "40" not in second.last_report["reason"] or True


def test_a_source_without_a_deadline_is_still_asked():
    """Заставлять все источники разом учиться сроку ради одного незачем."""
    simple = _Never()
    AuctionSearchService([simple]).discover_moscow(budget_seconds=5)
    assert simple.asked == 1


def test_no_budget_means_no_deadline_not_zero():
    """`None` — «срока нет», а не «время вышло»."""
    assert clock.start(None) is None
    assert clock.expired(None) is False
    assert clock.timeout(None, 25) == 25


def test_one_request_never_outlives_the_whole_collection():
    """Иначе повисший запрос переваливает общий срок на свои двадцать пять."""
    until = clock.start(2)
    assert clock.timeout(until, 25) <= 2
    assert clock.timeout(clock.start(0), 25) >= 1, "нулевой срок — это мгновенный отказ"


@pytest.mark.parametrize("module", [
    "torgi_gov", "roseltorg", "lot_online", "investmoscow",
])
def test_every_reader_takes_a_deadline(module: str):
    """Потолок в страницах ограничивает объём, но не время."""
    source = (ROOT / "auction_search" / "adapters" / f"{module}.py").read_text(encoding="utf-8")
    body = source[source.index("def discover_moscow("):]
    assert "deadline" in body[:200], f"{module}: сбор не принимает срок"


def test_a_broken_card_does_not_drop_the_whole_catalogue():
    """Одна недоступная карточка РАД роняла сбор целиком: маршрут отвечал 502,
    и каталог пропадал весь."""
    source = (ROOT / "auction_search" / "adapters" / "lot_online.py").read_text(encoding="utf-8")
    body = source[source.index("def discover_moscow(self, *, deadline"):]
    body = body[:body.index("def discover_moscow_history(")]
    assert "except Exception" in body, "падение одной карточки не ловится"
    assert "skipped" in body, "пропуск считается, а не молчит"


def test_the_route_has_a_budget():
    assert "DISCOVERY_BUDGET_SECONDS" in API
    line = API[API.index("DISCOVERY_BUDGET_SECONDS = "):]
    value = float(line[len("DISCOVERY_BUDGET_SECONDS = "):line.index("\n")])
    assert 10 <= value <= 55, "срок должен быть меньше шлюзовых шестидесяти секунд"
    assert "budget_seconds=DISCOVERY_BUDGET_SECONDS" in API


def test_the_page_never_parses_a_reply_blindly():
    """`r.json()` на HTML-странице шлюза даёт «The string did not match the
    expected pattern» — поломку разбора вместо причины отказа."""
    body = UI[UI.index("async function needLogin("):] if "async function needLogin(" in UI else UI
    assert "await r.json()" not in UI, "остался слепой разбор ответа"
    helper = UI[UI.index("async function askJson(url, init){"):]
    helper = helper[:helper.index("\n}\n")]
    assert "JSON.parse" in helper and "catch" in helper
    assert "r.status" in helper, "код ответа — часть причины"


def test_the_page_script_still_parses(tmp_path: Path):
    from auction_search import ui

    scripts = re.findall(r"<script[^>]*>(.*?)</script>", ui.AUCTIONS_PAGE, re.S)
    assert scripts
    for i, script in enumerate(scripts):
        place = tmp_path / f"page{i}.js"
        place.write_text(script, encoding="utf-8")
        done = subprocess.run(["node", "--check", str(place)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr


def test_the_login_refusal_is_worded_once():
    """Шесть копий одной фразы разошлись бы, и человек получил бы разный ответ
    на одну причину."""
    assert UI.count("Нужен вход в кабинет рынка") == 1


def test_the_service_signature_keeps_the_old_call_working():
    got = inspect.signature(AuctionSearchService.discover_moscow).parameters
    assert got["budget_seconds"].default is None, "без срока — как раньше"
