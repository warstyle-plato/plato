"""Minimal public preview entrypoint for the non-residential DevelopAid beta.

Render preview does not need the Telegram registry, market cabinet or IA layers.
It mounts the normal /v2 interface on top of the same core app and therefore
keeps the preview small while exercising the real commercial beta routes.
"""

from main import app
from developaid_v2 import install as install_v2

install_v2(app)
