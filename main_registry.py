"""DevelopAid application entrypoint with persistent Telegram user registry."""

import main as _base
from telegram_user_registry import install

app = _base.app
core = _base.core
registry = install(_base)
