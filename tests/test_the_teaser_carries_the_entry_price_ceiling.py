"""Тизер и полный PDF печатают потолок цены входа — тот же, что страница.

Владелец (22.10.2026, снимок блока «Инвестиционное решение»): «в тизеры надо
вставить вот это из результатов тоже» — максимум цены входа и запас к цене.
Прежде тизер этих чисел не знал, а полный PDF писал «подбирается на странице».

Здесь закреплено:

- в тексте настоящего тизера стоят потолок и запас, совпадающие с ответом
  `/ia/goal-seek` страницы на том же расчёте, и четыре подписи плиток;
- ответ страницы для тех же вводных берётся без пересчёта; подделанный или
  посчитанный для других вводных — не берётся, сборка подбирает сама и
  говорит об этом;
- полный PDF печатает то же число вместо прежней фразы;
- проект без показателя покрытия: «не подбирается» с причиной от движка.

Запуск: python3 -m pytest tests/test_the_teaser_carries_the_entry_price_ceiling.py -q
"""

from __future__ import annotations

import copy
import io
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as wrapper  # noqa: E402
from ia_preview import install  # noqa: E402

core = wrapper.core
pypdf = pytest.importorskip("pypdf")

PRICE = 2000.0
LABELS = ("Цена входа", "Максимум цены входа", "Запас к цене")


@pytest.fixture(scope="module", autouse=True)
def signing_key():
    # Подпись ответа подбора считается ключом бота; на проде он есть. Сам
    # токен не ставится: с ним включился бы вход, а он здесь ни при чём.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(core, "_entry_price_key", lambda: "test-key:entry-price")
        yield


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    install(app, core)
    return TestClient(app)


def _payload(**over) -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    # Проект, который порог проходит: иначе потолка нет и сверять нечего.
    inputs.update(apartment_price_th=650, commercial_price_th=650, parking_price_th=5000,
                  purchase_price_mln=PRICE)
    inputs.update(over)
    return {"inputs": inputs, "tep": copy.deepcopy(core.TEP_DEFAULT),
            "rates": copy.deepcopy(core.RATE_CURVE), "phasing": {}}


def _text(pdf: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return re.sub(r"\s+", " ", text.replace(" ", " "))


def _mln(value: float) -> str:
    return core._tile_mln(value).replace(" ", " ")


def _teaser(monkeypatch, tmp_path, payload: dict) -> str:
    """Тизер настоящей фоновой сборкой `_teaser_build`, без НСПД."""
    monkeypatch.setattr(core, "_TEASER_JOB_DIR", tmp_path / "teaser", raising=False)
    monkeypatch.setattr(core, "land_screening", lambda **kw: {"parcels": [], "verdict": {}})
    monkeypatch.setattr(core, "_teaser_map_png", lambda site: None)
    ticket = "a" * 32
    core._teaser_build(ticket, payload, dict(payload["inputs"]))
    meta = json.loads(core._teaser_job_path(ticket, "json").read_bytes())
    assert "error" not in meta, meta
    return _text(core._teaser_job_path(ticket, "pdf").read_bytes())


def _report(monkeypatch, tmp_path, payload: dict) -> str:
    monkeypatch.setattr(core, "_REPORT_JOB_DIR", tmp_path / "report", raising=False)
    monkeypatch.setattr(core, "land_screening", lambda **kw: {"parcels": [], "verdict": {}})
    ticket = "b" * 32
    full = {**payload, "result": {}, "sensitivity": {"items": []}}
    core._report_build(ticket, full)
    meta = json.loads(core._teaser_job_path(ticket, "json", "report").read_bytes())
    assert "error" not in meta, meta
    return _text(core._teaser_job_path(ticket, "pdf", "report").read_bytes())


@pytest.fixture(scope="module")
def page_goal(client) -> dict:
    data = client.post("/ia/goal-seek", json=_payload()).json()
    assert data["available"] is True, data
    return data


def test_the_page_answer_carries_its_tiles_and_fingerprint(page_goal) -> None:
    labels = [tile["label"] for tile in page_goal["tiles"]]
    assert labels[1:] == list(LABELS)
    assert page_goal["fingerprint"] and page_goal["signature"]
    assert page_goal["tiles"][2]["value"] == core._tile_mln(page_goal["solution"]["variable"])


def test_the_teaser_prints_the_page_ceiling_without_a_second_search(
        page_goal, monkeypatch, tmp_path) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("ответ страницы для тех же вводных подобран заново")
    monkeypatch.setattr(core, "_tool_goal_seek", forbidden)
    # Ответ проходит через JSON браузера: «2000.0» возвращается «2000».
    returned = json.loads(json.dumps(page_goal))
    text = _teaser(monkeypatch, tmp_path, {**_payload(), "goal_seek": returned})
    ceiling = page_goal["solution"]["variable"]
    for label in LABELS:
        assert label in text
    assert _mln(ceiling) in text
    assert _mln(ceiling - PRICE) in text
    assert "Подбор выполнен полным пересчётом модели DevelopAid " + core.VERSION in text


def test_without_a_page_answer_the_build_finds_the_same_ceiling(
        page_goal, monkeypatch, tmp_path) -> None:
    text = _teaser(monkeypatch, tmp_path, _payload())
    assert _mln(page_goal["solution"]["variable"]) in text
    assert _mln(page_goal["solution"]["variable"] - PRICE) in text


def test_a_forged_ceiling_is_not_printed(page_goal, monkeypatch, tmp_path) -> None:
    forged = copy.deepcopy(page_goal)
    forged["solution"]["variable"] = 99999.0
    forged["solution"]["change_abs"] = 99999.0 - PRICE
    text = _teaser(monkeypatch, tmp_path, {**_payload(), "goal_seek": forged})
    assert _mln(99999.0) not in text
    assert _mln(page_goal["solution"]["variable"]) in text


def test_a_ceiling_for_other_inputs_is_searched_again_and_said_so(
        client, monkeypatch, tmp_path) -> None:
    other = client.post("/ia/goal-seek", json=_payload(apartment_price_th=700)).json()
    text = _teaser(monkeypatch, tmp_path, {**_payload(), "goal_seek": other})
    assert _mln(other["solution"]["variable"]) not in text
    assert "относился к другим вводным" in text


def test_the_full_pdf_prints_the_number_instead_of_the_promise(
        page_goal, monkeypatch, tmp_path) -> None:
    text = _report(monkeypatch, tmp_path, {**_payload(), "goal_seek": page_goal})
    assert "подбирается на странице" not in text
    assert "Максимум цены входа" in text
    assert _mln(page_goal["solution"]["variable"]) in text


def test_a_project_without_debt_cover_is_not_searched_and_says_why(monkeypatch) -> None:
    from test_nonres_debt_metric import _nonres_inputs

    def forbidden(*args, **kwargs):
        raise AssertionError("подбор по показателю, которого нет")
    monkeypatch.setattr(core, "_tool_goal_seek", forbidden)
    x, t = _nonres_inputs(offices_strategy="direct")
    bundle = core._run_authoritative_model(x, t, [], {})
    goal = core.entry_price_for_report(bundle, x, t, [], {}, None)
    block = core.entry_price_block(bundle, x, goal)
    ceiling = block["tiles"][2]
    assert ceiling["label"] == "Максимум цены входа" and ceiling["value"] == "не подбирается"
    assert "выручкой прямых продаж" in ceiling["note"]
    text = _text(core.build_teaser_pdf(bundle, x, t, {}, entry_price=block))
    assert "не подбирается" in text and "прямых продаж" in text
