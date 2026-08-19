"""Пустое окно Платона объясняет себя картинкой, а не молчит.

До первого вопроса в окне было только поле ввода и служебная строка: человек не
понимает, о чём тут спрашивать. Иллюстрация с репликой отвечает на это быстрее
абзаца текста (решение владельца, 19.08.2026) — и на этом её работа кончается:
с первым сообщением она уходит.

Три правила, из которых сделано:
* картинка отдаётся адресом и кэшируется, а не вшивается в `PAGE` — страница
  уходит на каждый запрос целиком, и её вес платился бы каждым открытием;
* реплика — текст, а не часть картинки: её правят, ищут поиском и читают вслух;
* в отчёте и PDF картинки нет вовсе — они уходят в банк.

Запуск: python3 -m pytest tests/test_platon_window_has_a_face.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
client = TestClient(wrapper.app)


def test_the_picture_is_served_by_url_and_cached():
    answer = client.get("/assets/platon-hero.webp")
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "image/webp"
    assert "max-age" in answer.headers.get("cache-control", "")
    # Вес — то, ради чего файл лежит отдельно: страница его не несёт.
    assert len(answer.content) < 80 * 1024
    assert "platon-hero" not in core.PAGE.replace('src="/assets/platon-hero.webp"', "")


def test_the_asset_route_does_not_hand_out_the_engine():
    assert client.get("/assets/main_legacy.py").status_code == 404
    assert client.get("/assets/..%2Fmain_legacy.py").status_code in (400, 404)


def test_the_greeting_is_text_not_pixels():
    hero = core.PAGE[core.PAGE.index('<div id="aiHero"'):]
    hero = hero[:hero.index("</div></div>")]
    assert "Привет! Я Платон." in hero
    assert "Помогу настроить отчёт" in hero
    assert 'alt=""' in hero, "декоративная картинка не должна дублировать текст озвучкой"


def test_the_hero_leaves_with_the_first_message():
    for name in ("appendAiMessage", "appendAiProposals"):
        body = core.PAGE[core.PAGE.index(f"function {name}("):]
        body = body[:body.index("\n}")]
        assert "hideAiHero()" in body, name


def test_the_report_stays_without_pictures():
    """Отчёт уходит в банк: персонажу там места нет."""
    import inspect

    source = inspect.getsource(core._build_developaid_pdf)
    assert "platon-hero" not in source
    assert "aiHero" not in source
