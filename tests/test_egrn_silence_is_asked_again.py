"""Молчание ЕГРН переспрашивается; отсутствие объекта — нет, до срока свежести.

Кэш выкупа хранил ответ `found: False` навсегда, а движок превращает 503/429
НСПД именно в такой ответ. Разовый сбой портала навсегда оставлял площадку с
«Выкуп не собран: …503», и повторного запроса не было ни разу.
"""

from __future__ import annotations

from auction_search import krt_investment_score as kis

PROJECT = {"slug": "egrn-test"}
NUMBERS = ["77:01:0000001:1", "77:01:0000001:2"]


def _found(number, value=1_000_000.0, ownership="Частная собственность"):
    return {"found": True, "cadastral_number": number, "kind": "land",
            "ownership": ownership, "cadastral_value_rub": value}


def _silent(number):
    return {"found": False, "lookup_failed": True, "cadastral_number": number,
            "note": "НСПД временно недоступен (503)"}


def test_a_portal_failure_is_asked_again(tmp_path, monkeypatch):
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(kis.time, "time", lambda: clock["now"])
    asked = []
    portal_up = {"value": False}

    def lookup(numbers):
        asked.append(list(numbers))
        return [_found(n) if portal_up["value"] else _silent(n) for n in numbers]

    first = kis._cached_cadastral_buyout(PROJECT, NUMBERS, lookup, cache_root=tmp_path, chunk=6)
    assert first["pending"] is True
    assert "не ответил" in first["reason"] and "503" in first["reason"]
    assert first["retry_after_seconds"] == kis.BURDEN_NETWORK_RETRY_SECONDS

    # Сразу же — не долбим портал.
    kis._cached_cadastral_buyout(PROJECT, NUMBERS, lookup, cache_root=tmp_path, chunk=6)
    assert len(asked) == 1

    clock["now"] += kis.BURDEN_NETWORK_RETRY_SECONDS + 1
    portal_up["value"] = True
    third = kis._cached_cadastral_buyout(PROJECT, NUMBERS, lookup, cache_root=tmp_path, chunk=6)
    assert len(asked) == 2, "молчание ЕГРН закэшировано навсегда"
    assert third["available"] is True
    assert third["amount_mln"] == 2.0


def test_an_absent_object_is_an_answer_until_it_goes_stale(tmp_path, monkeypatch):
    clock = {"now": 2_000_000.0}
    monkeypatch.setattr(kis.time, "time", lambda: clock["now"])
    asked = []

    def lookup(numbers):
        asked.append(list(numbers))
        return [{"found": False, "cadastral_number": n,
                 "note": "В ЕГРН по этому номеру сведений не найдено."} for n in numbers]

    got = kis._cached_cadastral_buyout(PROJECT, NUMBERS[:1], lookup, cache_root=tmp_path)
    assert got["pending"] is False and got["available"] is False
    clock["now"] += kis.BURDEN_NETWORK_RETRY_SECONDS + 1
    kis._cached_cadastral_buyout(PROJECT, NUMBERS[:1], lookup, cache_root=tmp_path)
    assert len(asked) == 1, "окончательный ответ переспрашивается как сбой"
    clock["now"] += kis.BURDEN_ANSWER_TTL_SECONDS
    kis._cached_cadastral_buyout(PROJECT, NUMBERS[:1], lookup, cache_root=tmp_path)
    assert len(asked) == 2, "ответ ЕГРН без срока свежести"


def test_owner_words_of_the_register():
    bucket = kis._ownership_bucket
    assert bucket("Собственность субъекта Российской Федерации", "77:05:1:1") == "moscow"
    assert bucket("Собственность субъекта Российской Федерации", "50:21:1:1") == "non_moscow"
    assert bucket("Собственность г. Москвы", "77:05:1:1") == "moscow"
    assert bucket("Собственность города Москвы", "77:05:1:1") == "moscow"
    assert bucket("Общая долевая собственность (город Москва, ООО «Ромашка»)") == "unknown"
    assert bucket("Общая долевая собственность") == "non_moscow"
    assert bucket("Собственность Российской Федерации") == "non_moscow"
    assert bucket("Собственность публично-правовых образований") == "unknown"
    assert bucket("") == "unknown"
