"""DevelopAid application entrypoint with persistent Telegram user registry."""

import main as _base
import developaid_v2 as _v2
from developaid_v2_baselines import apply_accepted_baselines
from developaid_v2_pwa import install as install_v2_pwa
from telegram_user_registry import install

app = _base.app
core = _base.core
registry = install(_base)
apply_accepted_baselines(_v2._PROJECTS)
_v2.install(app)
install_v2_pwa(app)
