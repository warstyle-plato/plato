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
# market_analysis кладёт собственный style-блок рядом с существующими стилями
# монолитной PAGE. Внутри исходного <style> вложенный тег недопустим, поэтому
# оставляем сами правила в исходном блоке и одну закрывающую метку.
core.PAGE = core.PAGE.replace(
    '<style id="developaid-market-style">\n', '', 1
).replace('</style>\n</style>', '</style>', 1)
install_v2(app)
