"""Isolated staging entrypoint for commercial engine QA.

This does not affect main. It mounts the existing DevelopAid v2 web UI on the
commercial-engine feature branch so beta economics can be tested in a browser.
"""
from main import app
from developaid_v2 import install as install_v2

install_v2(app)
