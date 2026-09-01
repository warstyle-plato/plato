"""Площадки банкротства пробуются до того, как их разбирают.

ЕФРСБ как агрегатор закрыт: простому запросу капча Qrator, живому браузеру
403 без единого запроса за данными (ответы с ядра 25–26.08.2026). Обходить
защиту не будем — от этого она и поставлена.

Значит читаем сами площадки. По таблице владельца из 81 лота на чужих
площадках пять адресов дают больше половины: Сбербанк-АСТ, ЭТП ГПБ, Фабрикант,
Альфалот, ЭТП РФ. Но код пишется по ответу, а не по догадке — ровно так ГИС
Торги приехали на прод с тридцатью гаражами.

Запуск: python3 -m pytest tests/test_the_platforms_are_probed_first.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.adapters import etp_probe  # noqa: E402


def source() -> str:
    return (ROOT / "auction_search" / "adapters" / "etp_probe.py").read_text()


def test_the_five_platforms_from_the_table_are_covered() -> None:
    names = {name for name, _ in etp_probe.PLATFORMS}
    assert names == {"Сбербанк-АСТ", "ЭТП ГПБ", "Фабрикант", "Альфалот", "ЭТП РФ"}


def test_every_attempt_names_what_was_asked() -> None:
    for platform in etp_probe.probe()["platforms"]:
        assert platform["attempts"], f"{platform['name']}: проба обязана назвать адреса"
        for attempt in platform["attempts"]:
            assert attempt["url"].startswith("https://")
            assert attempt.get("http_status") is not None or attempt.get("reason")


def test_there_is_no_parser_yet() -> None:
    body = source()
    assert "def discover_moscow" not in body
    assert "def fetch_lot" not in body
    assert "разбора нет" in etp_probe.probe()["parsing"]


def test_a_challenge_page_is_not_data() -> None:
    """200 со страницей проверки браузера — отказ, а не пустой источник."""
    body = source()
    assert "challenge" in body
    for mark in ("__qrator", "ddos-guard", "captcha"):
        assert mark in body


def test_the_certificate_check_is_not_disabled() -> None:
    body = source()
    for forbidden in ("CERT_NONE", "check_hostname = False", "_create_unverified"):
        assert forbidden not in body
    assert "trust_context" in body


def test_the_endpoint_is_wired() -> None:
    api = (ROOT / "auction_search" / "api.py").read_text()
    assert "/auctions/etp/probe" in api and "etp_probe" in api


def test_the_roseltorg_section_is_probed_with_a_control_request() -> None:
    """Раздел Росэлторга спрашивается рядом с нынешним путём разведки.

    «Раздел отвечает» и «раздел отвечает лучше нынешнего» — разные
    утверждения, и второе без контрольного запроса не проверяется: у ГИС
    Торгов параметр региона не фильтровал, а выдачу менял, и понять это можно
    было только сравнением.
    """
    from auction_search.adapters import roseltorg_probe

    labels = [label for label, _url in roseltorg_probe.SECTIONS]
    urls = [url for _label, url in roseltorg_probe.SECTIONS]
    assert any("razvitie-territorii" in url for url in urls)
    assert any(label.startswith("КОНТРОЛЬ") for label in labels)
    assert any("procedures/search" in url for url in urls), (
        "контрольный запрос — это нынешняя разведка по тегам")

    body = (ROOT / "auction_search" / "adapters" / "roseltorg_probe.py").read_text()
    assert "def discover_moscow" not in body and "def fetch_lot" not in body
    assert "разбора нет" in roseltorg_probe.probe.__doc__ + body
    for forbidden in ("CERT_NONE", "check_hostname = False", "_create_unverified"):
        assert forbidden not in body
    api = (ROOT / "auction_search" / "api.py").read_text()
    assert "/auctions/roseltorg/probe" in api and "/auctions/roseltorg/browser" in api
