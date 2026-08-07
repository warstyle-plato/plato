"""DevelopAid application entrypoint with persistent Telegram user registry."""

import main as _base
from developaid_v2 import install as install_v2
from market_search import install as install_market_search
from market_search.ui import install as install_market_ui
from telegram_user_registry import install

app = _base.app
core = _base.core
registry = install(_base)
market_search = install_market_search(app)
install_market_ui(core)
install_v2(app)
