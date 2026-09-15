"""Карточка лота спрашивается второй раз: Росэлторг отвечает через раз.

Проход за извещениями (0.23.64) 14.09.2026 увидел на проде шесть лотов, спросил
пять и по ВСЕМ пяти получил «URLError: <urlopen error timed out>» — записал пять
отказов площадки и ушёл ждать полчаса. Карточка при этом отвечает за секунду:
двенадцать замеров с прода дали 0,9–1,4 с, один раз 11,1 с при потолке 20 с.
А контрольная проба той же карточки с паузами по сорок секунд дала
502 / 502 / 200 / 200 / 502 / 502 — то есть площадка отвечает через раз, и
второго вопроса у страницы не было вовсе.

Повтор у вложений живёт с 0.23.44, и его правило записано там же: «повторяется
только то, что имеет смысл повторять». Здесь та же болезнь на соседней двери, и
потому политика (`RETRIABLE_STATUS`, `ATTEMPTS`, `BACKOFF_SECONDS`) объявлена
ОДИН раз — в `reading`, ниже уровнем: два механизма на одно явление в этом
проекте всегда расходились.

Запуск: python3 -m pytest tests/test_a_refused_card_is_asked_again.py -q
"""

from __future__ import annotations

import io
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import deadline as budget, documents, reading  # noqa: E402
from auction_search.adapters import roseltorg  # noqa: E402

CARD = b"<html><head><title>Lot</title></head><body>karta</body></html>"
URL = "https://www.roseltorg.ru/procedure/21000005000000032802/1"


class _Answer(io.BytesIO):
    def __init__(self, body: bytes = CARD):
        super().__init__(body)
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def geturl(self):
        return URL

    @property
    def headers(self):
        class _H:
            @staticmethod
            def get_content_charset():
                return "utf-8"

            @staticmethod
            def get(name, default=""):
                return "text/html; charset=utf-8" if name == "Content-Type" else default
        return _H()


def _answers(monkeypatch, answers, paused=None):
    """Площадка отвечает по списку; паузы записываются, а не выжидаются."""
    asked = {"count": 0}

    def urlopen(*args, **kwargs):
        index = min(asked["count"], len(answers) - 1)
        asked["count"] += 1
        outcome = answers[index]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome() if callable(outcome) else outcome

    monkeypatch.setattr(reading, "urlopen", urlopen)
    monkeypatch.setattr(reading.time, "sleep",
                        lambda pause: (paused if paused is not None else []).append(pause))
    return asked


def _timeout() -> URLError:
    return URLError(socket.timeout("timed out"))


def test_a_timed_out_card_is_asked_again(monkeypatch) -> None:
    """Один таймаут стоил целого лота — а площадка отвечает со второго раза."""
    paused: list[float] = []
    asked = _answers(monkeypatch, [_timeout(), _Answer()], paused)
    html = roseltorg.RoseltorgAdapter._read(URL, 20, attempts=reading.ATTEMPTS)
    assert "karta" in html
    assert asked["count"] == 2, "второго вопроса не было"
    assert paused == [reading.BACKOFF_SECONDS[0]], "три запроса без паузы — это один запрос"


def test_the_exhausted_attempts_are_named(monkeypatch) -> None:
    """«HTTP 503» и «HTTP 503 после трёх попыток» — разные утверждения."""
    asked = _answers(monkeypatch, [_timeout()])
    with pytest.raises(reading.Refused) as refused:
        roseltorg.RoseltorgAdapter._read(URL, 20, attempts=reading.ATTEMPTS)
    assert asked["count"] == reading.ATTEMPTS
    said = str(refused.value)
    assert f"попыток: {reading.ATTEMPTS} из {reading.ATTEMPTS}" in said
    assert "timed out" in said, "чем отказала площадка — часть отказа"


def test_a_final_refusal_is_not_asked_twice(monkeypatch) -> None:
    """403 и 404 не повторяются: второй такой же запрос получит тот же ответ."""
    asked = _answers(monkeypatch, [HTTPError(URL, 403, "Forbidden", None, None)])
    with pytest.raises(HTTPError):
        roseltorg.RoseltorgAdapter._read(URL, 20, attempts=reading.ATTEMPTS)
    assert asked["count"] == 1
    assert not (reading.RETRIABLE_STATUS & {401, 403, 404, 410})


def test_the_budget_is_stronger_than_the_repeat(monkeypatch) -> None:
    """Пауза, не укладывающаяся в остаток, съедает время остальных лотов."""
    paused: list[float] = []
    asked = _answers(monkeypatch, [_timeout()], paused)
    with pytest.raises(reading.Refused) as refused:
        roseltorg.RoseltorgAdapter._read(
            URL, 20, attempts=reading.ATTEMPTS,
            deadline=time.monotonic() + reading.BACKOFF_SECONDS[0] / 2)
    assert asked["count"] == 1, "срок сильнее повтора"
    assert paused == []
    assert "попыток: 1" in str(refused.value)


def test_the_card_of_a_lot_asks_again(monkeypatch) -> None:
    """Проверяем ту дверь, в которую ходит проход: `fetch_lot`, а не `_read`."""
    asked = _answers(monkeypatch, [_timeout(), _Answer()])
    lot = roseltorg.RoseltorgAdapter().fetch_lot(URL)
    assert lot.source.external_lot_id == "21000005000000032802/1"
    assert asked["count"] == 2


def test_the_repeat_policy_is_declared_once() -> None:
    """Два механизма на одно явление разошлись бы молча."""
    assert documents.RETRIABLE_STATUS is reading.RETRIABLE_STATUS
    assert documents.DOWNLOAD_ATTEMPTS == reading.ATTEMPTS
    assert documents.RETRY_BACKOFF_SECONDS is reading.BACKOFF_SECONDS
    source = (ROOT / "auction_search" / "documents.py").read_text(encoding="utf-8")
    assert "frozenset({408" not in source, "вторая политика повтора"


def test_reading_asks_once_unless_told_otherwise(monkeypatch) -> None:
    """Предохранитель: прежнее поведение — один запрос, и оно не изменилось."""
    asked = _answers(monkeypatch, [_timeout()])
    with pytest.raises(URLError):
        reading.fetch(URL, timeout=5)
    assert asked["count"] == 1
    assert budget.left(None) is None
