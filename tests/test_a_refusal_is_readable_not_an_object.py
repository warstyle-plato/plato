"""Отказ читается словами, а кнопка пересчёта не упирается в потолок списка.

«[object Object]» вместо причины (владелец, 05.09.2026, нажав «Пересчитать
только их»). Поломок было две, и вторая пряталась за первой.

**Кнопка не работала вовсе.** Страница шлёт в прогон слаги отобранных
площадок, а `KrtRankingRequest.slugs` принимал не больше 400 — потолок
поставлен, когда каталог держал 124 площадки. Сейчас их 580, и на полном
каталоге приходил 422 всегда.

**Сказать об этом было нечем.** У проверки тела FastAPI `detail` — не строка,
а СПИСОК замечаний, и `new Error(list)` даёт message «[object Object]». То же
правило, из-за которого разбор ответа вообще читает текст, а не зовёт
`r.json()` вслепую: ответ разбирают, зная, что он может быть не тем, чего
ждали.

Запуск: python3 -m pytest tests/test_a_refusal_is_readable_not_an_object.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search.api import KrtRankingRequest  # noqa: E402
from auction_search.ui import auctions_page  # noqa: E402


def test_the_ceiling_fits_the_catalogue():
    """Потолок списка считается от каталога, а не от позапрошлого числа.

    Каталог — 580 строк на снимке прода (282 карточки плюс 298 площадок с
    проектом решения). Потолок ниже него означает, что кнопка «пересчитать
    отобранное» отказывает ровно тогда, когда отобрано всё.
    """
    ceiling = next(
        one for one in KrtRankingRequest.model_fields["slugs"].metadata
        if getattr(one, "max_length", None)
    ).max_length
    assert ceiling >= 1000, f"потолок {ceiling} ниже живого каталога в 580 строк"

    # И он работает: список в 580 слагов принимается, как принимается пустой.
    KrtRankingRequest(slugs=[f"s{i}" for i in range(580)], only_stale=True)


def _fn(page: str, name: str) -> str:
    """Кусок страницы по границам функции, а не по соседней строке."""
    start = page.index(f"function {name}(")
    depth, seen, i = 0, False, page.index("{", start)
    while i < len(page):
        if page[i] == "{":
            depth, seen = depth + 1, True
        elif page[i] == "}":
            depth -= 1
            if seen and depth == 0:
                return page[start:i + 1]
        i += 1
    raise AssertionError(f"на странице нет функции {name}")


def test_a_validation_refusal_says_what_was_wrong():
    """Список замечаний становится фразой, а не «[object Object]».

    Гоняется настоящий код страницы, а не его пересказ: строковая проверка
    увидела бы имя функции и в сломанном виде.
    """
    node = subprocess.run(["which", "node"], capture_output=True, text=True)
    if node.returncode:
        pytest.skip("node недоступен")

    page = auctions_page()
    program = "\n".join([
        _fn(page, "askWhy"),
        # Ровно то, что отдаёт FastAPI на слишком длинный список.
        "const long422=" + json.dumps({"detail": [{
            "type": "too_long", "loc": ["body", "slugs"],
            "msg": "List should have at most 400 items after validation, not 580"}]}) + ";",
        "const plain=" + json.dumps({"detail": "Нужен ключ доступа к кабинету"}) + ";",
        "const nothing={};",
        """
console.log(JSON.stringify({
  many: askWhy(long422, 422),
  plain: askWhy(plain, 401),
  nothing: askWhy(nothing, 500),
}));
""",
    ])
    done = subprocess.run([node.stdout.strip(), "-e", program],
                          capture_output=True, text=True, timeout=120)
    assert not done.returncode, done.stderr
    said = json.loads(done.stdout)

    # Главное: объекта на экране нет ни в одном ответе.
    for key, text in said.items():
        assert "[object Object]" not in text, (key, text)

    # Замечание проверки названо: и поле, и что с ним не так.
    assert "slugs" in said["many"], said["many"]
    assert "at most 400" in said["many"], said["many"]
    # Строковый отказ остаётся собой — пересказывать его незачем.
    assert said["plain"] == "Нужен ключ доступа к кабинету"
    # Пустое тело — код и есть весь ответ, но фраза всё равно человеческая.
    assert "500" in said["nothing"] and said["nothing"].strip()


# --- служебный ключ вместо адреса --------------------------------------------

def test_the_point_asks_the_address_not_our_key():
    """У площадки-решения спрашивается её адрес, а не `krt:decision:…`.

    «Адрес „krt:decision:347614220“ не найден» стояло жёлтой плашкой в карточке
    (владелец, 05.09.2026). Реестр знает только каталог, площадки-решения в нём
    нет, и наш служебный ключ уходил геокодеру как запрос человека. Площадка
    ищется в обеих половинах списка — то же правило, что у кнопки публикаций.
    """
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auction_search.api import install

    asked: list[str] = []

    decisions = {
        "total": 1, "matched": 0, "complete": True, "stale": False,
        "retrieved_at": 1_788_000_000, "matched_rows": [], "tep": {},
        "tep_coverage": {"read": 0, "failed": 0, "unknown": 1, "silent": 0, "reasons": {}},
        "tep_pending": [],
        "decisions": [{"id": "347614220", "title": "Проект решения …",
                       "url": "https://www.mos.ru/x/1/", "okrug": "ЦАО",
                       "address": "Большой Тишинский пер., влд. 8",
                       "published_at": 1_787_605_200}],
    }

    def resolve_subject(text: str):
        asked.append(text)
        return SimpleNamespace(to_dict=lambda: {
            "query": text, "latitude": 55.7, "longitude": 37.6,
            "precision": "street", "address": text, "notes": []})

    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        resolve_subject=resolve_subject,
        krt=SimpleNamespace(
            catalogue=lambda **_: [],
            status=lambda: {"complete": True, "refreshing": False,
                            "decisions_refreshing": False,
                            "retrieved_at": 1_788_000_000, "ttl_seconds": 86_400},
            decisions=lambda **_: dict(decisions),
        ),
    )
    install(app)

    answer = TestClient(app).get("/auctions/krt/decision:347614220/point")
    assert answer.status_code == 200, answer.text
    assert asked, "геокодер не спрошен вовсе"
    # Спросили адрес документа, а не наш ключ.
    assert "krt:" not in asked[0], asked
    assert "Большой Тишинский" in asked[0], asked
