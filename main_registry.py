"""DevelopAid application entrypoint with persistent Telegram user registry."""

import main as _base
from developaid_v2 import install as install_v2
from mpt_extension import install as install_mpt
from telegram_user_registry import install

app = _base.app
core = _base.core
install_mpt(_base)
registry = install(_base)
install_v2(app)