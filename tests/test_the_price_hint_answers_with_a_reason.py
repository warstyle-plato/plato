"""Кнопка «Рекомендация DevelopAid» отвечает причиной, а не поломкой разбора.

Владелец, 04.09.2026: «рекомендация не работает, пишет unexpected token».
С поля «Участок» на маршрут приходит кадастровый номер; если ЕГРН не дал по
нему границ, `resolve_subject` бросает `SubjectNotFound`, маршрут его не ловил
и отдавал 500 с ТЕКСТОМ «Internal Server Error». Браузер разбирал это как JSON
и показывал «Unexpected token 'I'» — поломку разбора вместо причины.

Запуск: python3 -m pytest tests/test_the_price_hint_answers_with_a_reason.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from market_search import api as market_api  # noqa: E402
from market_search.subject import SubjectNotFound  # noqa: E402
from market_search import ui_v6  # noqa: E402


def _client(monkeypatch, raiser) -> TestClient:
    app = FastAPI()
    market_api.install(app)
    monkeypatch.setattr(app.state.market_discovery_service, "price_hint", raiser)
    return TestClient(app, raise_server_exceptions=False)


def test_an_unrecognised_parcel_is_an_answer_not_a_crash(monkeypatch) -> None:
    """Неопознанный участок — 422 с причиной, и тело остаётся JSON."""
    def raiser(**_kwargs):
        raise SubjectNotFound("Кадастровый номер не опознан: ЕГРН не дал границ участка")

    answer = _client(monkeypatch, raiser).post(
        "/market/price-hint", json={"address": "77:01:0004023:1000"})
    assert answer.status_code == 422, answer.text
    assert answer.headers["content-type"].startswith("application/json")
    assert "ЕГРН" in answer.json()["detail"]


def test_any_other_failure_still_speaks_json(monkeypatch) -> None:
    """Неожиданная ошибка тоже уходит JSON'ом и называет себя."""
    def raiser(**_kwargs):
        raise TypeError("float() argument must be a string or a real number, not 'NoneType'")

    answer = _client(monkeypatch, raiser).post(
        "/market/price-hint", json={"address": "Москва, Тишинская площадь, 8"})
    assert answer.status_code == 502, answer.text
    assert answer.headers["content-type"].startswith("application/json")
    detail = answer.json()["detail"]
    assert "TypeError" in detail and "Ориентир не посчитан" in detail


def test_the_route_is_not_on_the_event_loop() -> None:
    """Обработчик синхронный: внутри поход в сеть, и на цикле он держит воркер."""
    source = (ROOT / "market_search" / "api.py").read_text(encoding="utf-8")
    assert "    def market_price_hint(" in source
    assert "async def market_price_hint(" not in source


def _function(script: str, name: str) -> str:
    """Границу функции считаем скобками: соседний комментарий не контракт."""
    start = script.index(f"function {name}(")
    # У асинхронной функции контракт начинается со слова async: без него node
    # разбирает тело как обычную функцию и падает на первом await.
    if script[max(0, start - 6):start] == "async ":
        start -= 6
    depth, index, seen = 0, script.index("{", start), False
    while index < len(script):
        if script[index] == "{":
            depth, seen = depth + 1, True
        elif script[index] == "}":
            depth -= 1
            if seen and depth == 0:
                return script[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец функции {name}")


def test_the_button_reads_the_answer_knowing_it_may_not_be_one() -> None:
    """Не-JSON в ответе называется кодом и первыми словами, а не «Unexpected token»."""
    script = ui_v6.PRICE_HINT_SCRIPT
    assert "daReadJson(response)" in script, "кнопка разбирает ответ мимо общего чтения"
    assert "await response.json()" not in script, "остался слепой разбор"
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    body = _function(script, "daReadJson")
    program = (
        body + "\n"
        "const html='<html><head><title>504 Gateway Time-out</title></head>"
        "<body><h1>504 Gateway Time-out</h1></body></html>';\n"
        "(async()=>{\n"
        "  const ok=await daReadJson({status:200,text:async()=>JSON.stringify({available:true,price_th_per_sqm:1500})});\n"
        "  let said='';\n"
        "  try{await daReadJson({status:504,text:async()=>html})}catch(e){said=e.message}\n"
        "  let plain='';\n"
        "  try{await daReadJson({status:500,text:async()=>'Internal Server Error'})}catch(e){plain=e.message}\n"
        "  process.stdout.write(JSON.stringify({ok,said,plain}));\n"
        "})();"
    )
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    got = json.loads(done.stdout)
    assert got["ok"]["price_th_per_sqm"] == 1500
    for said in (got["said"], got["plain"]):
        assert "Unexpected token" not in said, said
        assert "HTTP" in said, said
    assert "504" in got["said"] and "Gateway" in got["said"]
    assert "Internal Server Error" in got["plain"]
