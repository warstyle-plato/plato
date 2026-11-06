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
        'ALLOW_DOWNLOADS': True, 'ALLOW_FILE_URLS': False,
        'OPEN_EXTERNAL_LINKS_IN_BROWSER': True,
    }
    assert app.webbrowser.open is app.open_external


def test_client_rejects_non_windows_without_starting_a_renderer(monkeypatch):
    app = client()
    monkeypatch.setattr(app.sys, 'platform', 'linux')
    with pytest.raises(RuntimeError, match='Windows'):
        app.main()
