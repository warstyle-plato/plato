"""Offline fixed-host egress selection; no live proxy/origin is contacted."""
import asyncio
from dataclasses import FrozenInstanceError
import inspect
import json
import os
import socket
from urllib.request import getproxies_environment, proxy_bypass_environment

import httpx2
import pytest

import developaid_krt_origin_audit as audit

RUNTIME = {"commit": "b" * 40, "version": "0.29.44"}
HTML = b'<a href="/projects/site-one">Synthetic project</a><p>Status</p>'


@pytest.fixture(autouse=True)
def isolated_offline_environment(monkeypatch):
    for name in list(os.environ):
        if name.lower().endswith("_proxy"):
            monkeypatch.delenv(name)
    def forbidden(*args, **kwargs):
        pytest.fail("proxy policy tests forbid network sockets")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.mark.parametrize("environment,mode", [
    ({}, "direct"),
    ({"HTTP_PROXY": "http://irrelevant.invalid:8000", "ALL_PROXY": "socks5://irrelevant.invalid:8001"}, "direct"),
    ({"HTTPS_PROXY": "http://upper.invalid:8080"}, "configured_https_proxy"),
    ({"HTTPS_PROXY": "http://upper.invalid:8080", "https_proxy": "https://lower.invalid:8443"}, "configured_https_proxy"),
    ({"HTTPS_PROXY": "http://upper.invalid:8080", "https_proxy": ""}, "direct"),
    ({"HTTPS_PROXY": "http://upper.invalid:8080", "NO_PROXY": "api.krt.mos.ru"}, "proxy_bypassed"),
    ({"HTTPS_PROXY": "http://upper.invalid:8080", "NO_PROXY": ".krt.mos.ru"}, "proxy_bypassed"),
    ({"HTTPS_PROXY": "http://upper.invalid:8080", "NO_PROXY": "*"}, "proxy_bypassed"),
    ({"HTTPS_PROXY": "http://upper.invalid:8080", "NO_PROXY": "api.krt.mos.ru.evil"}, "configured_https_proxy"),
    ({"HTTPS_PROXY": "http://upper.invalid:8080", "NO_PROXY": "*", "no_proxy": "unrelated.invalid"}, "configured_https_proxy"),
])
def test_fixed_https_selection_matches_linux_urllib(environment, mode, monkeypatch):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    snapshot = getproxies_environment()
    expected_configured = bool(snapshot.get("https"))
    expected_bypassed = expected_configured and proxy_bypass_environment("api.krt.mos.ru", snapshot)
    policy = audit._proxy_policy()
    observed = policy.observation()
    assert observed["mode"] == mode
    assert observed["configured"] == expected_configured
    assert observed["bypassed"] == expected_bypassed
    assert observed["selected"] == (expected_configured and not expected_bypassed)
    assert not observed["refused"] and observed["refusal"] == "none"
    if policy.proxy:
        assert httpx2.URL(policy.proxy) == httpx2.URL(snapshot["https"])
    serialized = json.dumps(observed)
    assert len(serialized) < 256 and "invalid" not in serialized and "http:" not in serialized


@pytest.mark.parametrize("value,reason", [
    ("http://SYNTHETIC-USER:SYNTHETIC-PASSWORD@proxy.invalid:8080", "credentials"),
    ("http://SYNTHETIC-USER@proxy.invalid:8080", "credentials"),
    ("https://%75ser:%70ass@proxy.invalid", "credentials"),
    ("http://:SYNTHETIC-PASSWORD@proxy.invalid", "credentials"),
    ("proxy.invalid:8080", "invalid"),
    ("socks5://proxy.invalid:8080", "invalid"),
    ("ftp://proxy.invalid:8080", "invalid"),
    ("http://proxy.invalid/path", "invalid"),
    ("http://proxy.invalid?token=SYNTHETIC", "invalid"),
    ("http://proxy.invalid#SYNTHETIC", "invalid"),
    ("http://proxy.invalid:0", "invalid"),
    ("http://proxy.invalid:65536", "invalid"),
    ("http://proxy.invalid:bad", "invalid"),
    ("http://[broken", "invalid"),
    ("http://proxy%40invalid", "invalid"),
    ("http://proxy\\invalid", "invalid"),
    (" http://proxy.invalid:8080", "invalid"),
    ("http://proxy.invalid\n", "invalid"),
    ("http://" + "x" * 2048, "invalid"),
])
def test_credentialed_or_invalid_config_refuses_before_client_and_never_exports_value(value, reason, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", value)
    monkeypatch.setattr(audit, "_new_client", lambda *a, **k: pytest.fail("refused config must not create a client"))
    result = asyncio.run(audit.capture(runtime=RUNTIME))
    assert result["gaps"] == ["proxy_configuration_refused"]
    assert result["pages"] == [] and result["bytes"] == 0 and result["roster"] == []
    assert result["transport"] is None and result["transport_failure"] is None
    assert not result["complete"] and not result["walk_complete"]
    assert not result["production_acceptance"] and not result["historical_period_proven"]
    assert not result["source_files_written"] and result["source_updated_at"] is None
    observed = result["transport_policy"]
    assert observed == {"mode": "proxy_refused", "configured": True, "selected": False,
                        "bypassed": False, "refused": True, "refusal": reason}
    assert value not in json.dumps(result) and "SYNTHETIC" not in json.dumps(result)
    assert "proxy.invalid" not in repr(audit._proxy_policy())


def test_credentials_are_refused_even_when_no_proxy_would_bypass(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://SYNTHETIC-USER:SYNTHETIC-PASSWORD@proxy.invalid")
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setattr(audit, "_new_client", lambda *a, **k: pytest.fail("credentials refuse before any attempt"))
    result = asyncio.run(audit.capture(runtime=RUNTIME))
    assert result["transport_policy"]["refused"] and result["transport_policy"]["bypassed"]
    assert not result["transport_policy"]["selected"] and result["pages"] == []


def test_selected_proxy_and_origin_share_verified_context_without_environment_auth(monkeypatch):
    observed = {}
    def client(**kwargs):
        observed.update(kwargs)
        return object()
    monkeypatch.setattr(audit.httpx2, "AsyncClient", client)
    audit._new_client("https://proxy.invalid:8443")
    context = observed["verify"]
    assert context.check_hostname and context.verify_mode.name == "CERT_REQUIRED"
    assert observed["proxy"].ssl_context is context
    assert observed["proxy"].auth is None and not observed["proxy"].headers
    assert observed["trust_env"] is False and observed["follow_redirects"] is False
    assert observed["timeout"].connect == audit.MAX_SECONDS == 45
    assert observed["limits"].max_connections == 1
    assert "auth" not in observed and "cookies" not in observed


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_real_proxy_constructor_assigns_TLS_only_to_encrypted_proxy_transport(scheme, monkeypatch):
    context = audit.trust_context()
    monkeypatch.setattr(audit, "trust_context", lambda: context)
    # Construct the real httpx2/httpcore2 transports; do not make requests.
    native = audit._new_client(scheme + "://constructor-proxy.invalid:8080")
    try:
        assert native._transport._pool._ssl_context is context
        pools = [transport._pool for transport in native._mounts.values() if transport is not None]
        assert len(pools) == 1
        proxy = pools[0]
        assert proxy._ssl_context is context
        assert proxy._proxy_ssl_context is (context if scheme == "https" else None)
        assert proxy._proxy_url.scheme == scheme.encode()
        assert proxy._proxy_headers == []
        assert context.check_hostname and context.verify_mode.name == "CERT_REQUIRED"
    finally:
        asyncio.run(native.aclose())


def memory_factory(monkeypatch, respond):
    actual = httpx2.AsyncClient
    calls, proxies = [], []
    async def route(request):
        calls.append(request)
        response = respond(request)
        if inspect.isawaitable(response):
            response = await response
        return response
    def factory(**kwargs):
        proxies.append(kwargs.pop("proxy", None))
        return actual(**kwargs, transport=httpx2.MockTransport(route))
    monkeypatch.setattr(audit.httpx2, "AsyncClient", factory)
    return calls, proxies


def test_configured_transport_is_passed_to_client_without_exporting_its_value(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://selected-private.invalid:8080")
    calls, proxies = memory_factory(monkeypatch, lambda request: httpx2.Response(
        200, stream=httpx2.ByteStream(HTML)))
    result = asyncio.run(audit.capture(runtime=RUNTIME))
    assert len(calls) == len(proxies) == 1 and proxies[0] is not None
    assert str(proxies[0].url) == "http://selected-private.invalid:8080"
    assert result["complete"] and result["transport_policy"]["selected"]
    assert "selected-private.invalid" not in json.dumps(result)


def test_one_snapshot_and_one_client_survive_environment_change_between_pages(monkeypatch):
    snapshot_calls = []
    def snapshot():
        snapshot_calls.append(1)
        assert len(snapshot_calls) == 1
        return {"https": "http://chosen.invalid:8080"}
    monkeypatch.setattr(audit, "getproxies_environment", snapshot)
    first = HTML + b'<button class="show_more" data-url="/projects/?PAGEN_1=2">More</button>'
    def respond(request):
        monkeypatch.setenv("HTTPS_PROXY", "http://SYNTHETIC:SECRET@late.invalid")
        return httpx2.Response(200, stream=httpx2.ByteStream(first if not request.url.query else HTML.replace(b"site-one", b"site-two")))
    calls, proxies = memory_factory(monkeypatch, respond)
    result = asyncio.run(audit.capture(runtime=RUNTIME))
    assert result["complete"] and len(calls) == 2 and len(proxies) == len(snapshot_calls) == 1
    assert str(proxies[0].url) == "http://chosen.invalid:8080"
    assert result["transport_policy"]["selected"] and "late.invalid" not in json.dumps(result)
    assert all("cookie" not in r.headers and "authorization" not in r.headers and "proxy-authorization" not in r.headers for r in calls)


def test_concurrent_walks_keep_each_policy_private_and_immutable(monkeypatch):
    snapshots = iter([{"https": "http://first.invalid:8080"}, {"https": "https://second.invalid:8443", "no": "api.krt.mos.ru"}])
    monkeypatch.setattr(audit, "getproxies_environment", lambda: next(snapshots))
    arrivals = []
    async def exercise():
        both = asyncio.Event()
        async def respond(request):
            arrivals.append(1)
            if len(arrivals) == 2:
                both.set()
            await both.wait()
            return httpx2.Response(200, stream=httpx2.ByteStream(HTML))
        calls, proxies = memory_factory(monkeypatch, respond)
        first, second = await asyncio.gather(audit.capture(runtime=RUNTIME), audit.capture(runtime=RUNTIME))
        assert first["complete"] and second["complete"] and len(calls) == 2
        assert first["transport_policy"]["selected"] and second["transport_policy"]["bypassed"]
        assert str(proxies[0].url) == "http://first.invalid:8080" and proxies[1] is None
        assert "first.invalid" not in json.dumps([first, second]) and "second.invalid" not in json.dumps([first, second])
    asyncio.run(exercise())
    policy = audit._ProxyPolicy(proxy="http://private.invalid:8080", configured=True)
    with pytest.raises(FrozenInstanceError):
        policy.proxy = "http://other.invalid:8080"


def test_public_policy_field_is_bounded_and_cannot_become_a_url_selector():
    with pytest.raises(audit.InputError):
        audit.validate_request(json.dumps({"purpose": audit.PURPOSE, "proxy": "http://caller.invalid"}).encode())
    assert audit.ORIGIN == "https://api.krt.mos.ru/projects/"
    assert (audit.MAX_SECONDS, audit.MAX_BYTES, audit.MAX_PAGES, audit.MAX_ROWS, audit.MAX_TRANSPORT_EVENTS) == (45, 4194304, 100, 4000, 6)
