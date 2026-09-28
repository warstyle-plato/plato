"""Уровень каталога меняет владелец сервиса; поле на экране — личный сценарий.

Ориентир рейтинга решает, какая строка каталога устарела: смена отправляет на
пересчёт все шестьсот строк и переписывает записанные баллы. Маршрут смены стоял
за ОБЩИМ ключом кабинета — тем же, что у всей команды, — а кнопка «Пересчитать
рейтинги» сначала записывала введённое число этой настройкой и только потом
считала. То есть любой, кто вписал своё «450 000», менял уровень всем.

Решение владельца (27.09.2026): «мне не надо, чтобы пользователь поставил
450 000 как ориентир и для всех каталог перечитался… себе считай что хочешь, но
нас интересует уровень 600», затем — «маршрут смены под ключом владельца».

Проверяется поведением: настоящий маршрут приложения и настоящая функция
страницы. На прежнем коде обе проверки падают — ключ кабинета пускал, а кнопка
звала маршрут смены.

Запуск: python3 -m pytest tests/test_the_catalogue_level_is_the_owners_setting.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import page_blocks  # noqa: E402

from auction_search import api, ui  # noqa: E402
from auction_search.krt_ranking import KrtRanking  # noqa: E402

OWNER_KEY = "owner-key-for-the-check"
CABINET_KEY = "cabinet-key-for-the-check"
LEVEL = 600_000.0


class _Registry:
    def find(self, query):
        return None

    def catalogue(self, refresh=False):
        return []

    def decisions(self, refresh=False):
        return []


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CABINET_KEY", CABINET_KEY)
    monkeypatch.delenv("AUCTIONS_VIEW_KEY", raising=False)
    # Движок подкладывается ТОТ ЖЕ, что кладёт main.py: правило «кто владелец»
    # объявлено в нём, и заглушка отвечала бы за него.
    import main_legacy

    monkeypatch.setitem(sys.modules, "developaid_core", main_legacy)
    application = FastAPI()
    application.state.market_discovery_service = types.SimpleNamespace(
        krt=_Registry(), city=None)
    api.install(application)
    return application, KrtRanking(tmp_path / "market")


def _post(client, *, params=None, headers=None):
    return client.post("/auctions/krt/investment-rating/target",
                       params=params or {}, headers=headers or {},
                       json={"price_target_rub_sqm": 450_000})


def test_the_cabinet_key_does_not_change_the_level(app, monkeypatch):
    """Общий ключ кабинета уровень каталога не меняет."""
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", OWNER_KEY)
    application, ranking = app
    client = TestClient(application)
    answer = _post(client, headers={"X-Market-Key": CABINET_KEY})
    assert answer.status_code == 403, answer.text
    assert "владельц" in answer.json()["detail"].lower()
    # Настройка осталась объявленным уровнем, а не чьим-то числом.
    assert ranking.rating_target(LEVEL) == LEVEL


def test_the_owner_key_changes_the_level(app, monkeypatch):
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", OWNER_KEY)
    application, ranking = app
    client = TestClient(application)
    answer = _post(client, params={"key": OWNER_KEY})
    assert answer.status_code == 200, answer.text
    assert answer.json()["price_target_rub_sqm"] == 450_000
    assert ranking.rating_target(LEVEL) == 450_000


def test_without_an_owner_to_recognise_the_route_refuses_and_says_why(app, monkeypatch):
    """«Опознать нечем» — это отказ с причиной, а не «разрешено всем».

    Витрина примеров в таком случае честно открыта: её нечем закрыть. Здесь же
    настройка переписывает каталог ВСЕМ, и открывать её нельзя.
    """
    monkeypatch.delenv("DEVELOPAID_ADMIN_KEY", raising=False)
    monkeypatch.delenv("DEVELOPAID_ADMIN_IDS", raising=False)
    application, ranking = app
    answer = _post(TestClient(application), params={"key": OWNER_KEY})
    assert answer.status_code == 403, answer.text
    detail = answer.json()["detail"]
    assert "ни списка владельцев, ни ключа владельца" in detail, detail


# --- страница: кнопка считает, но уровень не пишет ------------------------

STAND_PRELUDE = """
const calls = [];
const box = {style:{}, className:'', textContent:'', innerHTML:''};
const btn = {disabled:false, innerHTML:'', textContent:''};
const input = {value: String(%(typed)s)};
const nodes = {krtRatingBtn: btn, krtRankStatus: box, krtRatingTarget: input};
const $ = id => (nodes[id] || null);
const esc = s => String(s == null ? '' : s);
const state = {krtRatingTarget: %(level)s, krtRank: {}, krtModels: {},
  krt: [{slug:'alpha', status:'Планируемый'}],
  krtFiltered: [{slug:'alpha', status:'Планируемый'}]};
const KRT_EARLY_ONLY = false;
const needLogin = e => { throw e };
const renderKrt = () => {};
const loadKrtRanking = async () => {};
const askJson = async (url, opts) => {
  calls.push({url: String(url), method: String((opts||{}).method || 'GET')});
  if (String(url).indexOf('/investment-score') >= 0)
    return {rating: {display_score: 61, imputed: []}};
  return {};
};
"""

STAND_TAIL = """
startKrtInvestmentRating().then(() => console.log(JSON.stringify(
  {calls: calls, status: box.textContent})));
"""


def _press(typed: float, level: float) -> dict:
    """Нажать настоящую кнопку страницы торгов в node."""
    page = ui.auctions_page()
    out, _taken = page_blocks.run(
        STAND_PRELUDE % {"typed": typed, "level": level}, STAND_TAIL, page=page)
    return json.loads(out)


def test_the_button_never_writes_the_shared_level() -> None:
    """Кнопка не зовёт маршрут смены уровня — ни при своём числе, ни при уровне."""
    for typed in (450_000, int(LEVEL)):
        got = _press(typed, LEVEL)
        wrote = [call for call in got["calls"]
                 if "investment-rating/target" in call["url"]]
        assert not wrote, f"кнопка записывает общий уровень: {wrote}"


def test_a_personal_number_is_named_a_personal_scenario() -> None:
    got = _press(450_000, LEVEL)
    assert "личный сценарий" in got["status"], got["status"]
    assert "600 000" in got["status"].replace(" ", " "), got["status"]
    # Считает она по введённому числу — сценарий на то и личный.
    asked = [call for call in got["calls"] if "/investment-score" in call["url"]]
    assert asked and "price_target_rub_sqm=450000" in asked[0]["url"], asked


def test_the_level_itself_is_not_called_a_scenario() -> None:
    got = _press(int(LEVEL), LEVEL)
    assert "личный сценарий" not in got["status"], got["status"]
