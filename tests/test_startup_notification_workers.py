"""ASGI tests do not start notification loops that outlive their fixtures."""
from types import SimpleNamespace

from fastapi.testclient import TestClient


NAMES = {"usage-digest", "management-report", "access-notices"}


def capture_notification_starts(monkeypatch, wrapper):
    started = []
    native_thread = wrapper.threading.Thread

    class Captured:
        def __init__(self, target, name, daemon):
            self.target, self.name, self.daemon = target, name, daemon

        def start(self):
            started.append(self)

    def thread(*args, **kwargs):
        if kwargs.get("name") in NAMES:
            return Captured(kwargs["target"], kwargs["name"], kwargs["daemon"])
        return native_thread(*args, **kwargs)

    # Replace only the wrapper's dependency. Changing threading.Thread itself
    # would also change the base class imported by AnyIO's ASGI portal.
    monkeypatch.setattr(wrapper, "threading", SimpleNamespace(Thread=thread))
    return started


def test_testclient_startup_leaves_notification_workers_to_explicit_tests(monkeypatch):
    import main

    started = capture_notification_starts(monkeypatch, main)
    with TestClient(main.app):
        pass
    assert started == [], "A notification loop survives ASGI fixture shutdown and uses another test's roots"


def test_production_startup_keeps_all_three_notification_workers(monkeypatch):
    import main

    started = capture_notification_starts(monkeypatch, main)
    # The native function reads this dependency; no actual process/module
    # registry or thread is changed, and none of the recorded loops is run.
    monkeypatch.setattr(main, "sys", SimpleNamespace(modules={}))
    main._start_usage_digest()
    assert {row.name: row.target for row in started} == {
        "usage-digest": main._usage_digest_loop,
        "management-report": main._management_report_loop,
        "access-notices": main._access_notices_loop,
    }
    assert all(row.daemon for row in started)
