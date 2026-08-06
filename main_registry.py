"""DevelopAid application entrypoint with persistent Telegram user registry."""

import main as _base
import market_analysis
from developaid_v2 import install as install_v2
from telegram_user_registry import install

app = _base.app
core = _base.core
registry = install(_base)
# Один модуль обслуживает основной веб-интерфейс и действующий Telegram-бот.
# Установка идёт до /v2: тестовый интерфейс не является владельцем расчёта.
market_analysis.install(_base)
install_v2(app)
