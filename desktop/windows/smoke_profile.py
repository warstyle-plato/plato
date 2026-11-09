"""Own the native smoke browser until its temporary profile is no longer in use."""
from __future__ import annotations

from pathlib import Path
import shutil
from tempfile import mkdtemp


def _open_process(pid):
    from System.Diagnostics import Process
    process = Process.GetProcessById(pid)
    try:
        # Open the kernel handle while this CoreWebView2 still owns the PID.
        # Waiting after closure must not look up a reused numeric PID.
        _ = process.Handle
    except Exception:
        process.Close()
        raise
    return process


class WebViewProfile:
    def __init__(self, *, open_process=None, exit_timeout_ms=15000):
        self._open_process = open_process or _open_process
        self.exit_timeout_ms = exit_timeout_ms
        self.path = None
        self.process = None
        self.pid = None
        self.tracking_error = None
        self.closing = False

    def __enter__(self):
        self.path = Path(mkdtemp(prefix='developaid-smoke-'))
        return self

    def _capture(self, core):
        if self.process is not None or self.tracking_error is not None or self.closing:
            return
        try:
            folder = Path(str(core.Environment.UserDataFolder)).resolve()
            if not folder.is_relative_to(self.path.resolve()):
                raise RuntimeError('WebView2 does not use this smoke check\'s temporary profile')
            pid = int(core.BrowserProcessId)
            if pid <= 0:
                raise RuntimeError('WebView2 did not provide a browser process ID')
            self.process = self._open_process(pid)
            self.pid = pid
        except Exception as error:
            # A managed event cannot safely tear down the Python caller. Keep
            # the failure and propagate it from __exit__; it is not a success.
            self.tracking_error = error

    def initialized(self, sender, args):
        if self.closing or self.process is not None:
            return
        if args.IsSuccess:
            self._capture(sender.CoreWebView2)
        elif self.tracking_error is None:
            self.tracking_error = RuntimeError('Native WebView2 initialization failed')

    def watch(self, window):
        def attach():
            try:
                native = window.native.webview
                native.CoreWebView2InitializationCompleted += self.initialized
                if native.CoreWebView2 is not None:
                    self._capture(native.CoreWebView2)
            except Exception as error:
                self.tracking_error = error
        window.events.before_show += attach

    def __exit__(self, exc_type, error, traceback):
        self.closing = True
        if self.tracking_error is not None:
            raise RuntimeError(f'Cannot verify WebView2 shutdown; profile retained at {self.path}') from self.tracking_error
        if self.process is None:
            raise RuntimeError(f'WebView2 browser process was not captured; profile retained at {self.path}')
        try:
            if not self.process.WaitForExit(self.exit_timeout_ms):
                raise TimeoutError(f'WebView2 browser process {self.pid} did not exit; profile retained at {self.path}')
        finally:
            self.process.Close()
        # Stop/Dispose closes the controller, but the browser releases its
        # profile asynchronously. Only its confirmed exit authorizes deletion.
        shutil.rmtree(self.path)
        return False
