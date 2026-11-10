"""Process ownership and cleanup order, independent of native WebView2 availability."""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).parents[1]/'desktop'/'windows'


def module(name='smoke_profile'):
    spec = spec_from_file_location('windows_'+name+'_under_test', ROOT/(name+'.py'))
    result = module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class Process:
    def __init__(self, calls, *, exits=True, error=None):
        self.calls, self.exits, self.error = calls, exits, error

    def WaitForExit(self, milliseconds):
        self.calls.append(('wait', milliseconds))
        if self.error:
            raise self.error
        return self.exits

    def Close(self):
        self.calls.append(('close',))


def core(profile, pid=71):
    return SimpleNamespace(BrowserProcessId=pid,
        Environment=SimpleNamespace(UserDataFolder=str(profile.path/'WebView2')))


def test_exit_is_confirmed_before_profile_cleanup_and_only_the_captured_process_is_used(monkeypatch):
    owner = module()
    calls = []
    process = Process(calls)
    original_cleanup = owner.shutil.rmtree
    def cleanup(path):
        assert calls == [('open', 71), ('wait', 15000), ('close',)]
        calls.append(('cleanup',))
        original_cleanup(path)
    monkeypatch.setattr(owner.shutil, 'rmtree', cleanup)
    def opened(pid):
        calls.append(('open', pid))
        return process
    with owner.WebViewProfile(open_process=opened) as profile:
        path = profile.path
        native = core(profile)
        profile._capture(native)
        # A later PID value never causes a new lookup after the UI has closed.
        native.BrowserProcessId = 9001
    assert calls[-1] == ('cleanup',) and not path.exists()


def test_timeout_is_a_failure_and_does_not_delete_a_profile_still_in_use():
    owner = module()
    calls = []
    profile = owner.WebViewProfile(open_process=lambda pid: Process(calls, exits=False), exit_timeout_ms=5)
    try:
        with pytest.raises(TimeoutError, match='71 did not exit; profile retained'):
            with profile:
                profile._capture(core(profile))
        assert calls == [('wait', 5), ('close',)] and profile.path.exists()
    finally:
        shutil.rmtree(profile.path)


def test_wait_error_is_not_hidden_and_does_not_clean_up_early():
    owner = module()
    calls = []
    profile = owner.WebViewProfile(open_process=lambda pid: Process(calls, error=OSError('synthetic wait failure')))
    try:
        with pytest.raises(OSError, match='synthetic wait failure'):
            with profile:
                profile._capture(core(profile))
        assert calls == [('wait', 15000), ('close',)] and profile.path.exists()
    finally:
        shutil.rmtree(profile.path)


def test_another_profile_is_never_opened_waited_or_deleted(tmp_path):
    owner = module()
    calls = []
    foreign = tmp_path/'foreign-webview'; foreign.mkdir()
    marker = foreign/'user-file'; marker.write_text('keep')
    profile = owner.WebViewProfile(open_process=lambda pid: calls.append(pid))
    try:
        with pytest.raises(RuntimeError, match='Cannot verify WebView2 shutdown') as failure:
            with profile:
                profile._capture(SimpleNamespace(BrowserProcessId=9001,
                    Environment=SimpleNamespace(UserDataFolder=str(foreign))))
        assert isinstance(failure.value.__cause__, RuntimeError)
        assert 'temporary profile' in str(failure.value.__cause__)
        assert not calls and marker.read_text() == 'keep' and profile.path.exists()
    finally:
        shutil.rmtree(profile.path)


def test_missing_capture_fails_instead_of_attempting_cleanup():
    owner = module()
    profile = owner.WebViewProfile()
    try:
        with pytest.raises(RuntimeError, match='process was not captured'):
            with profile:
                pass
        assert profile.path.exists()
    finally:
        shutil.rmtree(profile.path)


def test_body_failure_is_preserved_after_owned_process_exit():
    owner = module()
    calls = []
    with pytest.raises(ValueError, match='synthetic smoke failure'):
        with owner.WebViewProfile(open_process=lambda pid: Process(calls)) as profile:
            path = profile.path
            profile._capture(core(profile))
            raise ValueError('synthetic smoke failure')
    assert calls == [('wait', 15000), ('close',)] and not path.exists()


def test_cleanup_error_is_not_ignored(monkeypatch):
    owner = module()
    calls = []
    profile = owner.WebViewProfile(open_process=lambda pid: Process(calls))
    def fail(path):
        raise OSError('synthetic cleanup failure')
    monkeypatch.setattr(owner.shutil, 'rmtree', fail)
    try:
        with pytest.raises(OSError, match='synthetic cleanup failure'):
            with profile:
                profile._capture(core(profile))
        assert calls == [('wait', 15000), ('close',)]
    finally:
        # The patch is global to shutil; restore it before the test's cleanup.
        monkeypatch.undo()
        shutil.rmtree(profile.path)


def test_native_factory_opens_the_original_kernel_handle_before_the_pid_can_be_reused(monkeypatch):
    owner = module()
    calls = []
    class Native:
        @property
        def Handle(self):
            calls.append('handle')
            return 71
        def Close(self):
            calls.append('close')
    native = Native()
    def get_process(pid):
        calls.append(('lookup', pid))
        return native
    monkeypatch.setitem(sys.modules, 'System.Diagnostics', SimpleNamespace(Process=SimpleNamespace(GetProcessById=get_process)))
    assert owner._open_process(71) is native
    assert calls == [('lookup', 71), 'handle']


def test_factory_handle_failure_releases_the_handle_and_is_propagated(monkeypatch):
    owner = module()
    calls = []
    class Native:
        @property
        def Handle(self):
            raise OSError('synthetic handle failure')
        def Close(self):
            calls.append('close')
    monkeypatch.setitem(sys.modules, 'System.Diagnostics',
        SimpleNamespace(Process=SimpleNamespace(GetProcessById=lambda pid: Native())))
    with pytest.raises(OSError, match='synthetic handle failure'):
        owner._open_process(71)
    assert calls == ['close']


def test_initialization_capture_is_idempotent_and_late_failure_does_not_reenter_shutdown():
    owner = module()
    calls = []
    with owner.WebViewProfile(open_process=lambda pid: Process(calls)) as profile:
        native = SimpleNamespace(CoreWebView2=core(profile))
        profile.initialized(native, SimpleNamespace(IsSuccess=True))
        profile.initialized(native, SimpleNamespace(IsSuccess=True))
        profile.initialized(native, SimpleNamespace(IsSuccess=False))
        assert profile.tracking_error is None
    assert calls == [('wait', 15000), ('close',)]


class EventHook:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


def test_native_smoke_wires_profile_tracking_before_webview_start_and_waits_after_return(monkeypatch):
    owner = module()
    calls = []
    profile = owner.WebViewProfile(open_process=lambda pid: Process(calls))
    monkeypatch.setitem(sys.modules, 'smoke_profile', owner)
    monkeypatch.setitem(sys.modules, 'app', SimpleNamespace(
        configure_webview=lambda view: None,
        guard_navigation=lambda window, **kwargs: None))
    smoke = module('smoke_test')
    native = SimpleNamespace(CoreWebView2=None,
        CoreWebView2InitializationCompleted=EventHook())
    window = SimpleNamespace(native=SimpleNamespace(webview=native),
        events=SimpleNamespace(before_show=EventHook()))
    server = SimpleNamespace(server_port=1234, serve_forever=lambda: None,
        shutdown=lambda: calls.append(('server_shutdown',)),
        server_close=lambda: calls.append(('server_close',)))

    def start(check, **options):
        assert options['storage_path'] == str(profile.path/'WebView2')
        assert options['gui'] == 'edgechromium' and options['private_mode'] is False
        assert len(window.events.before_show.handlers) == 1
        window.events.before_show.handlers[0]()
        native.CoreWebView2 = core(profile)
        assert native.CoreWebView2InitializationCompleted.handlers == [profile.initialized]
        native.CoreWebView2InitializationCompleted.handlers[0](native, SimpleNamespace(IsSuccess=True))
        assert profile.process is not None
        calls.append(('gui_return',))

    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(
        create_window=lambda *args, **kwargs: window, start=start))
    monkeypatch.setattr(smoke, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(smoke, 'WebViewProfile', lambda: profile)
    monkeypatch.setattr(smoke, 'ThreadingHTTPServer', lambda *args: server)
    monkeypatch.setattr(smoke, 'Thread', lambda **kwargs: SimpleNamespace(start=lambda: None))
    # No browser assertions are simulated as successful: this checks the real
    # main's lifecycle wiring, while the native Windows smoke remains required.
    assert smoke.main() == 1
    assert calls == [('gui_return',), ('server_shutdown',), ('server_close',),
                     ('wait', 15000), ('close',)]
    assert not profile.path.exists()


def test_watch_reports_a_native_hook_failure_instead_of_deleting_the_profile():
    owner = module()
    profile = owner.WebViewProfile()
    window = SimpleNamespace(events=SimpleNamespace(before_show=EventHook()))
    try:
        with pytest.raises(RuntimeError, match='Cannot verify WebView2 shutdown') as failure:
            with profile:
                profile.watch(window)
                window.events.before_show.handlers[0]()
        assert isinstance(failure.value.__cause__, AttributeError)
        assert profile.path.exists()
    finally:
        shutil.rmtree(profile.path)


def test_real_owned_child_has_exited_before_cleanup_and_an_unrelated_child_survives(monkeypatch):
    owner = module()
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    child = None
    original_cleanup = owner.shutil.rmtree
    class ChildProcess:
        def WaitForExit(self, milliseconds):
            try:
                child.wait(timeout=milliseconds/1000)
            except subprocess.TimeoutExpired:
                return False
            return True
        def Close(self):
            pass
    def cleanup(path):
        assert child.poll() == 0
        assert unrelated.poll() is None
        original_cleanup(path)
    monkeypatch.setattr(owner.shutil, 'rmtree', cleanup)
    try:
        with owner.WebViewProfile(open_process=lambda pid: ChildProcess()) as profile:
            folder = profile.path/'WebView2'; folder.mkdir()
            child = subprocess.Popen([sys.executable, '-c',
                'import sys; f=open(sys.argv[1],"w"); print("holding",flush=True); sys.stdin.readline(); f.close()',
                str(folder/'held')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            assert child.stdout.readline().strip() == 'holding'
            profile._capture(core(profile, child.pid))
            child.stdin.write('close\n'); child.stdin.flush()
        assert not profile.path.exists() and unrelated.poll() is None
    finally:
        for process in (child, unrelated):
            if process is not None and process.poll() is None:
                process.terminate()
            if process is not None:
                process.wait(timeout=5)
