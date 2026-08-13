"""Мини-приложение обязано считать ТЭП на сервере, а не в скрытом iframe.

«Считает две минуты» и «не может открыть штатный расчёт, считает формулами» —
это одна поломка. В Telegram WebView запускался скрытый iframe с калькулятором
ГлавАПУ: он там не работает, каждый шаг ожидания ждал по минуте, потом падал, и
расчёт уходил на серверные формулы. На экране это выглядело как «2 из 4 ·
Открываю штатный расчёт ГлавАПУ…» и долгая тишина.

Ветка, уводящая Telegram на серверный расчёт, в коде была — но проверяла
`window.Telegram.WebApp.initData`. SDK Telegram на странице не подключён, и
`window.Telegram` здесь не существует вовсе: мини-приложение открывается обычной
ссылкой с параметрами сессии в хеше. Условие было всегда ложным, и ветка не
срабатывала ни разу.

Признак телеграма — параметры, которыми бот открыл окно.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _detect(session: str = "", cad: str = "", telegram_sdk: bool = False) -> bool:
    """Прогоняет настоящую isTelegramWebApp из PAGE."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    match = re.search(r"^function isTelegramWebApp\(\)\{.*?^\}", core.PAGE, re.S | re.M)
    assert match, "isTelegramWebApp не найдена на странице"
    script = (
        f"const telegramSession={json.dumps(session)};\n"
        f"const telegramCad={json.dumps(cad)};\n"
        + ("const window={Telegram:{WebApp:{initData:'user=1'}}};\n"
           if telegram_sdk else "const window={};\n")
        + match.group(0) + "\n"
        "console.log(JSON.stringify(isTelegramWebApp()));\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_session_from_the_bot_means_telegram():
    """Так бот и открывает окно: параметрами в хеше."""
    assert _detect(session="abc123") is True


def test_the_cadastral_launch_means_telegram_too():
    """Кнопка «Посчитать по кадастру» открывает окно с номером и без сессии."""
    assert _detect(cad="77:03:0006001:1") is True


def test_a_plain_browser_is_not_telegram():
    """Сайт обязан остаться сайтом: там iframe работает и нужен."""
    assert _detect() is False


def test_the_sdk_still_counts_when_it_is_there():
    """Если SDK когда-нибудь подключат — признак обязан сработать и по нему."""
    assert _detect(telegram_sdk=True) is True


def test_the_missing_sdk_does_not_throw():
    """window.Telegram отсутствует — это не повод падать посреди расчёта."""
    assert _detect(session="", cad="") is False


def test_the_telegram_branch_no_longer_asks_for_initdata():
    """Проверка по initData была всегда ложной — её не должно остаться в
    решении о маршруте."""
    flow = re.search(r"async function obtainCadastralTep\(.*?\n\}", core.PAGE, re.S)
    assert flow, "obtainCadastralTep не найдена"
    body = flow.group(0)
    assert "isTelegramWebApp()" in body
    assert "initData" not in body, "маршрут снова зависит от отсутствующего SDK"


def test_telegram_turns_off_before_the_iframe_starts():
    """Серверный расчёт обязан стоять до запуска iframe, иначе WebView опять
    будет ждать калькулятор, которого не откроет."""
    flow = re.search(r"async function obtainCadastralTep\(.*?\n\}", core.PAGE, re.S)
    body = flow.group(0)
    assert 0 < body.find("isTelegramWebApp()") < body.find("Открываю штатный расчёт ГлавАПУ")


def test_the_log_marks_the_client_correctly():
    """В журнале запуск из телеграма помечался как «site» по той же причине —
    разбирать по нему было нечего."""
    assert "const client=isTelegramWebApp()?'telegram':'site';" in core.PAGE
