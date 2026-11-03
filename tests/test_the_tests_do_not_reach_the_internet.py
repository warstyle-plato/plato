"""Внешняя сеть в прогоне оборвана сразу, а localhost открыт.

Доля CI упиралась в потолок 80 минут без единого упавшего теста: браузерные
проверки поднимают приложение в процессе прогона, сервер ходил в НСПД и ЦБ,
проверка ссылок нормативов — на госсайты, и с раннера они молчали до
таймаута. Запрет объявлен в `tests/conftest.py`; здесь проверяется, что он
действует, — на адресе, который без запрета висел бы до таймаута.

Запуск: python3 -m pytest tests/test_the_tests_do_not_reach_the_internet.py -q
"""

from __future__ import annotations

import os
import socket
import time

import pytest


@pytest.mark.skipif(os.environ.get("TESTS_ALLOW_NETWORK") in {"1", "true", "yes"},
                    reason="сеть включена руками: TESTS_ALLOW_NETWORK")
def test_an_external_address_is_refused_at_once() -> None:
    # Немаршрутизируемый адрес: без запрета соединение ждёт таймаута.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    started = time.monotonic()
    try:
        with pytest.raises(ConnectionRefusedError, match="внешнюю сеть"):
            sock.connect(("10.255.255.1", 443))
    finally:
        sock.close()
    assert time.monotonic() - started < 1.0, "отказ обязан быть мгновенным"


@pytest.mark.skipif(os.environ.get("TESTS_ALLOW_NETWORK") in {"1", "true", "yes"},
                    reason="сеть включена руками: TESTS_ALLOW_NETWORK")
def test_the_proxy_does_not_carry_the_request_past_the_refusal() -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        assert not os.environ.get(name) and not os.environ.get(name.lower()), name


def test_localhost_stays_open() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.settimeout(2)
        client.connect(server.getsockname())
    finally:
        client.close()
        server.close()
