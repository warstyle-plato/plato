"""Windows online client; calculation and access control remain on the server."""
from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
import sys
from threading import Event
import webbrowser
from urllib.parse import urlsplit

APP_URL = "https://developaid.ru/"
_BROWSER_OPEN = webbrowser.open


def web_url_allowed(url: str, *, local_origin: str | None = None) -> bool:
    """Only HTTPS in production; a specific loopback origin is for the CI page."""
    if not isinstance(url, str) or any(ord(c) < 32 or ord(c) == 127 for c in url):
        return False
    try:
        target = urlsplit(url)
        if (not target.hostname or target.username is not None
                or target.password is not None):
            return False
        target.port  # Reject malformed ports, too.
        if target.scheme.lower() == "https":
            return True
        if local_origin is not None:
            local = urlsplit(local_origin)
            return (target.scheme == local.scheme == "http"
                    and target.hostname == local.hostname == "127.0.0.1"
                    and target.netloc == local.netloc)
    except ValueError:
        return False
    return False


def open_external(url: str, *args, **kwargs) -> bool:
    """Do not forward files or OS command protocols to the browser launcher."""
    return bool(_BROWSER_OPEN(url, *args, **kwargs)) if web_url_allowed(url) else False


class NavigationGuard:
    """Enforce the policy on real WebView2 events, before any remote page loads."""
    def __init__(self, window, *, local_origin: str | None = None):
        self.window = window
        self.local_origin = local_origin
        self.native_attached = False
        self.core_attached = False
        self.failed = False
        self.blocked = Event()
        self.popup_blocked = Event()

    def navigation(self, sender, args):
        if not web_url_allowed(str(args.Uri), local_origin=self.local_origin):
            args.Cancel = True
            self.blocked.set()

    def external_scheme(self, sender, args):
        args.Cancel = True
        self.blocked.set()

    def popup(self, sender, args):
        if not web_url_allowed(str(args.Uri)):
            args.Handled = True
            self.popup_blocked.set()

    def _attach_core(self, core):
        if self.core_attached:
            return
        core.LaunchingExternalUriScheme += self.external_scheme
        core.NewWindowRequested += self.popup
        self.core_attached = True

    def closing(self):
        # pywebview's persistent-profile path exits the WinForms loop without
        # disposing WebView2. Dispose on its UI thread before Python finalizes,
        # so pending .NET callbacks cannot enter a torn-down interpreter.
        native = self.window.native.webview
        try:
            if native.CoreWebView2 is not None:
                native.CoreWebView2.Stop()
        finally:
            native.Dispose()

    def _fail_closed(self):
        self.failed = True
        # This callback runs on the WinForms UI thread before shown; public
        # window.destroy waits for shown and cannot safely close this stage.
        try:
            self.window.native.Close()
        finally:
            self.window.native.Dispose()

    def initialized(self, sender, args):
        try:
            if not args.IsSuccess:
                raise RuntimeError("WebView2 initialization failed")
            self._attach_core(sender.CoreWebView2)
        except Exception:
            self._fail_closed()
            raise RuntimeError("Cannot enforce the WebView2 navigation policy") from None

    def attach(self):
        try:
            native = self.window.native.webview
            # The control-level event is available before CoreWebView2 is ready.
            native.NavigationStarting += self.navigation
            native.CoreWebView2InitializationCompleted += self.initialized
            if native.CoreWebView2 is not None:
                self._attach_core(native.CoreWebView2)
            self.native_attached = True
        except Exception:
            self._fail_closed()
            raise RuntimeError("Cannot enforce the WebView2 navigation policy") from None


def guard_navigation(window, *, local_origin: str | None = None) -> NavigationGuard:
    guard = NavigationGuard(window, local_origin=local_origin)
    window.events.before_show += guard.attach
    window.events.closing += guard.closing
    return guard


def configure_webview(webview) -> None:
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["IGNORE_SSL_ERRORS"] = False
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
        guard = guard_navigation(window)
        menu = [Menu("DevelopAid", [
            MenuAction("Открыть главную", lambda: window.load_url(APP_URL)),
            MenuAction("Открыть в браузере", lambda: webbrowser.open(APP_URL)),
            MenuAction("Закрыть", window.destroy),
        ])]
        # No Python API is exposed to the remote page. Never fall back to IE.
        webview.start(gui="edgechromium", private_mode=False,
                      storage_path=str(profile / "WebView2"), menu=menu, debug=False)
        return 1 if guard.failed else 0
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
