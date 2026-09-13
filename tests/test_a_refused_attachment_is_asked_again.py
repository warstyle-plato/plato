"""Повтор загрузки вложения: площадка отвечает через раз.

Измерено на живых лотах Росэлторга (13.09.2026): у лота 33444 из 26 вложений
четыре ответили HTTP 503 — «Сведения о земельных участках», «График КРТ»,
«Схема границ», «Материалы градостроительного потенциала», — а лот 33452 за
один заход отдал 0 документов, за следующий 26. Один запрос на вложение выдаёт
перебой площадки за отсутствие документа.

Что закреплено здесь:

- **повторяется то, что имеет смысл повторять.** 503 и обрыв — да; 401, 403 и
  404 не повторяются вовсе: второй такой же запрос получит тот же ответ;
- **число попыток называется в отказе.** «HTTP 503» и «HTTP 503 после трёх
  попыток» — разные утверждения о площадке;
- **срок сбора сильнее повтора.** Пауза, не укладывающаяся в остаток, съедает
  время остальных вложений — тогда недобранным окажется весь лот;
- **таймаут — наш отказ с именем, а не сырой OSError.** Прежде он уходил
  наружу как есть, вызывающий его не ловил, и одно повисшее вложение роняло
  разбор ЛОТА целиком.

Запуск: python3 -m pytest tests/test_a_refused_attachment_is_asked_again.py -q
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import deadline as budget, documents  # noqa: E402

URL = "https://www.roseltorg.ru/file/get/1/name/Схема.pdf"


class Answer:
    """Площадка, отвечающая по сценарию. Считает, сколько раз её спросили."""

    def __init__(self, *script):
        self.script = list(script)
        self.asked = 0

    def __call__(self, req, timeout=None, context=None):
        self.asked += 1
        step = self.script[min(self.asked - 1, len(self.script) - 1)]
        if isinstance(step, Exception):
            raise step
        return step


class Response:
    def __init__(self, data: bytes, content_type: str = "application/pdf"):
        self.data = data
        self.headers = {"Content-Type": content_type}
        self.url = URL

    def read(self, _limit=None):
        return self.data

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def refusal(code: int) -> HTTPError:
    return HTTPError(URL, code, f"HTTP {code}", {}, None)


@pytest.fixture(autouse=True)
def no_real_pauses(monkeypatch):
    """Отступ проверяется по вызовам, а не ожиданием: проверка не спит."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda pause: slept.append(pause))
    monkeypatch.setattr(documents.time, "sleep", lambda pause: slept.append(pause))
    return slept


def test_a_platform_that_answers_every_other_time_is_asked_again(monkeypatch):
    answer = Answer(refusal(503), refusal(503), Response(b"%PDF-1.4 file"))
    monkeypatch.setattr(documents, "urlopen", answer)
    data, content_type, authenticated = documents.download_document(URL)
    assert data == b"%PDF-1.4 file"
    assert (content_type, authenticated) == ("application/pdf", False)
    assert answer.asked == 3


def test_the_pause_grows_between_attempts(monkeypatch, no_real_pauses):
    answer = Answer(refusal(503), refusal(503), Response(b"%PDF"))
    monkeypatch.setattr(documents, "urlopen", answer)
    documents.download_document(URL)
    # Три запроса подряд без паузы — это один запрос, посланный трижды.
    assert no_real_pauses == [2.0, 5.0]
    assert no_real_pauses == list(documents.RETRY_BACKOFF_SECONDS)


def test_the_refusal_names_how_many_times_we_asked(monkeypatch):
    answer = Answer(refusal(503))
    monkeypatch.setattr(documents, "urlopen", answer)
    with pytest.raises(documents.DocumentTemporaryRefusal) as refused:
        documents.download_document(URL)
    assert answer.asked == documents.DOWNLOAD_ATTEMPTS
    said = str(refused.value)
    assert "503" in said
    assert f"попыток: {documents.DOWNLOAD_ATTEMPTS}" in said


def test_a_closed_door_is_not_knocked_three_times(monkeypatch):
    """401 и 403 — это «нас не пустили», и второй запрос ответит тем же."""
    for code in (401, 403):
        answer = Answer(refusal(code))
        monkeypatch.setattr(documents, "urlopen", answer)
        with pytest.raises(documents.DocumentAuthorizationRequired):
            documents.download_document(URL)
        assert answer.asked == 1, code
    assert not (documents.RETRIABLE_STATUS & {401, 403, 404, 410})


def test_a_missing_document_is_not_asked_again(monkeypatch):
    answer = Answer(refusal(404))
    monkeypatch.setattr(documents, "urlopen", answer)
    with pytest.raises(documents.DocumentExtractionError) as refused:
        documents.download_document(URL)
    assert answer.asked == 1
    assert not isinstance(refused.value, documents.DocumentTemporaryRefusal)


def test_a_timeout_is_our_named_refusal_and_not_a_raw_error(monkeypatch):
    """Сырой таймаут роняет разбор ЛОТА: вызывающий ловит только наши ошибки."""
    answer = Answer(socket.timeout("timed out"))
    monkeypatch.setattr(documents, "urlopen", answer)
    with pytest.raises(documents.DocumentTemporaryRefusal) as refused:
        documents.download_document(URL)
    assert answer.asked == documents.DOWNLOAD_ATTEMPTS
    assert "timed out" in str(refused.value)
    assert isinstance(refused.value, documents.DocumentExtractionError)


def test_the_collection_deadline_stops_the_retries(monkeypatch, no_real_pauses):
    """Остаток срока меньше паузы — повтора нет: время нужно другим вложениям."""
    answer = Answer(refusal(503))
    monkeypatch.setattr(documents, "urlopen", answer)
    with pytest.raises(documents.DocumentTemporaryRefusal) as refused:
        documents.download_document(URL, deadline=budget.start(1.0))
    assert answer.asked == 1
    assert no_real_pauses == []
    assert "попыток: 1" in str(refused.value)


def test_a_lot_with_room_still_gets_its_retries(monkeypatch):
    """Предохранитель: при живом сроке повтор обязан работать, иначе
    предыдущая проверка не значит ничего — она была бы зелена и без срока."""
    answer = Answer(refusal(503), Response(b"%PDF"))
    monkeypatch.setattr(documents, "urlopen", answer)
    documents.download_document(URL, deadline=budget.start(600.0))
    assert answer.asked == 2
