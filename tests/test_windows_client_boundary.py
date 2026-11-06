"""The online prototype must not expose an OS protocol launcher or bypass access."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest


def client():
    spec = spec_from_file_location('windows_client_under_test', Path(__file__).parents[1] / 'desktop/windows/app.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('url', [
    'file:///C:/Windows/System32/cmd.exe', 'javascript:alert(1)',
    'ms-msdt:/id', 'shell:AppsFolder', 'data:text/html,test',
    'https://user:secret@example.test/', 'https://example.test:bad/',
    'https://example.test/\nfile:///C:/private', 'http://example.test/',
    '//example.test/', 'https:///missing-host',
])
def test_external_links_never_forward_unsafe_protocols_or_credentials(monkeypatch, url):
    app = client()
    calls = []
    monkeypatch.setattr(app, '_BROWSER_OPEN', lambda *a, **k: calls.append(a) or True)
    assert app.open_external(url) is False
    assert calls == []


def test_external_https_link_and_main_menu_keep_the_system_browser(monkeypatch):
    app = client()
    calls = []
    monkeypatch.setattr(app, '_BROWSER_OPEN', lambda *a, **k: calls.append(a) or True)
    assert app.open_external('https://developaid.ru/') is True
    assert app.open_external('https://t.me/developaid') is True
    assert len(calls) == 2


def test_webview_keeps_downloads_and_has_no_file_access(monkeypatch):
    app = client()
    fake = SimpleNamespace(settings={})
    monkeypatch.setattr(app.webbrowser, 'open', app.webbrowser.open)
    app.configure_webview(fake)
    assert fake.settings == {
        'ALLOW_DOWNLOADS': True, 'ALLOW_FILE_URLS': False, 'IGNORE_SSL_ERRORS': False,
        'OPEN_EXTERNAL_LINKS_IN_BROWSER': True,
    }
    assert app.webbrowser.open is app.open_external


def test_client_rejects_non_windows_without_starting_a_renderer(monkeypatch):
    app = client()
    monkeypatch.setattr(app.sys, 'platform', 'linux')
    with pytest.raises(RuntimeError, match='Windows'):
        app.main()


class EventHook:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


def test_native_guard_binds_before_show_and_cancels_navigation_and_os_schemes():
    app = client()
    core = SimpleNamespace(LaunchingExternalUriScheme=EventHook(), NewWindowRequested=EventHook())
    control = SimpleNamespace(NavigationStarting=EventHook(),
                              CoreWebView2InitializationCompleted=EventHook(), CoreWebView2=core)
    window = SimpleNamespace(native=SimpleNamespace(webview=control),
                             events=SimpleNamespace(before_show=EventHook()))
    guard = app.guard_navigation(window)
    assert window.events.before_show.handlers == [guard.attach]
    guard.attach()
    assert guard.native_attached and guard.core_attached
    assert control.NavigationStarting.handlers == [guard.navigation]
    assert core.LaunchingExternalUriScheme.handlers == [guard.external_scheme]
    for url in ('file:///C:/synthetic', 'http://example.test/', 'custom://synthetic',
                'https://user:password@example.test/'):
        args = SimpleNamespace(Uri=url, Cancel=False)
        control.NavigationStarting.handlers[0](control, args)
        assert args.Cancel is True
    allowed = SimpleNamespace(Uri='https://developaid.ru/report', Cancel=False)
    guard.navigation(control, allowed)
    assert allowed.Cancel is False
    external = SimpleNamespace(Cancel=False)
    guard.external_scheme(core, external)
    assert external.Cancel is True
    popup = SimpleNamespace(Uri='file:///C:/synthetic', Handled=False)
    guard.popup(core, popup)
    assert popup.Handled is True


def test_only_explicit_synthetic_loopback_origin_can_use_http():
    app = client()
    assert not app.web_url_allowed('http://127.0.0.1:1234/')
    assert app.web_url_allowed('http://127.0.0.1:1234/?reload=1', local_origin='http://127.0.0.1:1234/')
    assert not app.web_url_allowed('http://127.0.0.1:1235/', local_origin='http://127.0.0.1:1234/')
    assert not app.web_url_allowed('http://example.test/', local_origin='http://127.0.0.1:1234/')


def test_missing_native_guard_support_closes_the_window():
    app = client()
    closed = []
    window = SimpleNamespace(native=SimpleNamespace(
        Close=lambda: closed.append('close'), Dispose=lambda: closed.append('dispose')))
    with pytest.raises(RuntimeError, match='navigation policy'):
        app.NavigationGuard(window).attach()
    assert closed == ['close', 'dispose']
