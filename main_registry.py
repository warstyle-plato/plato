"""DevelopAid application entrypoint with persistent Telegram user registry."""

import main as _base
from developaid_v2 import install as install_v2
from developaid_v2_pwa import install as install_v2_pwa
from telegram_user_registry import install

app = _base.app
core = _base.core
registry = install(_base)
install_v2(app)
install_v2_pwa(app)
