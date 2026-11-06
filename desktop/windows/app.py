"""Windows online client; calculation and access control remain on the server."""
from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
import sys
import webbrowser
from urllib.parse import urlsplit

APP_URL = "https://developaid.ru/"
_BROWSER_OPEN = webbrowser.open


def open_external(url: str, *args, **kwargs) -> bool:
    """Open web links without forwarding local files or OS command protocols."""
    if not isinstance(url, str) or any(ord(c) < 32 or ord(c) == 127 for c in url):
        return False
    try:
        target = urlsplit(url)
        if (target.scheme.lower() != "https" or not target.hostname
                or target.username is not None or target.password is not None):
            return False
        target.port  # Reject malformed ports before invoking the operating system.
    except ValueError:
        return False
    return bool(_BROWSER_OPEN(url, *args, **kwargs))


def configure_webview(webview) -> None:
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    # pywebview's Edge backend forwards popup URLs to this standard-library hook.
    # Keep files, javascript and arbitrary custom protocols out of the OS launcher.
    webbrowser.open = open_external


def main() -> int:
    if sys.platform != "win32":
        raise RuntimeError("Эта сборка предназначена для Windows.")
    profile = Path(os.environ["LOCALAPPDATA"]) / "DevelopAid"
    profile.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=profile / "desktop.log", level=logging.WARNING)
    try:
        import webview
        from webview.menu import Menu, MenuAction

        configure_webview(webview)
        window = webview.create_window(
            "DevelopAid", APP_URL, width=1440, height=960,
            min_size=(1000, 700), background_color="#ffffff", zoomable=True,
            js_api=None,
        )
        menu = [Menu("DevelopAid", [
            MenuAction("Открыть главную", lambda: window.load_url(APP_URL)),
            MenuAction("Открыть в браузере", lambda: webbrowser.open(APP_URL)),
            MenuAction("Закрыть", window.destroy),
        ])]
        # No Python API is exposed to the remote page. Never fall back to IE.
        webview.start(gui="edgechromium", private_mode=False,
                      storage_path=str(profile / "WebView2"), menu=menu, debug=False)
        return 0
    except Exception:
        logging.exception("Desktop startup failed")
        ctypes.windll.user32.MessageBoxW(
            None,
            "Не удалось запустить DevelopAid. Проверьте наличие Microsoft Edge "
            "WebView2 Runtime. Подробности записаны в " + str(profile / "desktop.log"),
            "DevelopAid", 0x10,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
