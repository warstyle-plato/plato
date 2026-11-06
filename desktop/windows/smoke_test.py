"""Native Windows CI check, with synthetic local content and no production access."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread

from app import configure_webview


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<!doctype html><title>DevelopAid smoke</title><p id="ready">ready</p>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main() -> int:
    if sys.platform != 'win32':
        raise RuntimeError('This check requires native Windows WebView2')
    import webview

    configure_webview(webview)
    result = {'native_webview2': False, 'session_storage': False, 'no_python_api': False}
    with TemporaryDirectory(prefix='developaid-smoke-') as profile:
        server = ThreadingHTTPServer(('127.0.0.1', 0), Page)
        Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}/'
        # load_url requires the native shown event; exercise a visible window like the app.
        window = webview.create_window('DevelopAid smoke', url, hidden=False, js_api=None)

        def check():
            try:
                if not window.events.loaded.wait(40):
                    return
                result['native_webview2'] = window.evaluate_js(
                    'document.querySelector("#ready").textContent') == 'ready'
                result['no_python_api'] = window.evaluate_js(
                    'Object.keys(window.pywebview.api).length') == 0
                window.evaluate_js('localStorage.setItem("synthetic-smoke", "saved")')
                # Edge's Source setter may ignore an identical URI after pywebview
                # has cleared loaded. A new query forces same-origin navigation.
                window.load_url(url + '?reload=1')
                if not window.events.loaded.wait(40):
                    return
                result['session_storage'] = window.evaluate_js(
                    'localStorage.getItem("synthetic-smoke")') == 'saved'
            finally:
                window.destroy()

        try:
            webview.start(check, gui='edgechromium', private_mode=False,
                          storage_path=str(Path(profile) / 'WebView2'), debug=False)
        finally:
            server.shutdown()
            server.server_close()
    print(json.dumps(result))
    return 0 if all(result.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
