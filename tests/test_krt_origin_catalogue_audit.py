"""A fixed read-only origin walk cannot turn into refresh, SSRF or a session."""
import asyncio
import builtins
import hashlib
import inspect
import json
from types import SimpleNamespace

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import developaid_krt_origin_audit as audit

RUNTIME = {"commit": "a" * 40, "version": "0.29.26"}
PATH = "/auctions/krt/audit/origin-catalogue"
KEY = "OWNER-MARKER-NOT-AN-ORIGIN-CREDENTIAL"


def page(slug="site-one", status="В реализации", next_url=None, name="NAME-MUST-NOT-LEAVE"):
    body = (f'<a href="/projects/{slug}">{name}</a><p>Статус: {status}</p>'
            '<p>Общий объем застройки: 987654321</p>')
    if next_url is not None:
        body += f'<button class="show_more" data-url="{next_url}">Ещё</button>'
    return body.encode()


@pytest.fixture
def mock_origin(monkeypatch):
    actual_client = httpx2.AsyncClient
    calls, settings = [], []

    def setup(respond):
        async def seen(request):
            calls.append(request)
            response = respond(request)
            if inspect.isawaitable(response):
                response = await response
            if response.is_stream_consumed:
                # Mock Response(content=...) is already read. The real network
                # supplies an unconsumed stream, including for an empty body.
                response = httpx2.Response(response.status_code, headers=response.headers,
                    stream=httpx2.ByteStream(response.content), request=request)
            return response

        def client(**kwargs):
            settings.append(kwargs)
            return actual_client(**kwargs, transport=httpx2.MockTransport(seen))

        monkeypatch.setattr(audit.httpx2, "AsyncClient", client)
        return calls, settings
    return setup


def capture():
    return asyncio.run(audit.capture(runtime=RUNTIME))


def test_complete_native_walk_binds_each_body_and_exports_only_slug_status(mock_origin):
    bodies = [page(next_url="/projects/?PAGEN_1=2"), page("site-two", "Планируемый")]
    calls, settings = mock_origin(lambda request: httpx2.Response(
        200, content=bodies[0 if request.url.query == b"" else 1],
        headers={"Date": "Fri, 13 Nov 2026 20:00:00 GMT", "Age": "600",
                 "ETag": "opaque-tag", "Set-Cookie": "MARKER-COOKIE=secret; Path=/"}))
    result = capture()
    assert result["complete"] and result["walk_complete"] and result["gaps"] == []
    assert [str(call.url) for call in calls] == [audit.ORIGIN, audit.ORIGIN + "?PAGEN_1=2"]
    assert result["roster"] == [{"slug": "site-one", "status": "В реализации"},
                                {"slug": "site-two", "status": "Планируемый"}]
    assert result["bytes"] == sum(map(len, bodies))
    assert [p["sha256"] for p in result["pages"]] == [hashlib.sha256(b).hexdigest() for b in bodies]
    assert all(p["body_complete"] for p in result["pages"])
    assert not result["production_acceptance"] and not result["historical_period_proven"]
    assert result["source_updated_at"] is None and result["http_headers_are_not_source_dates"]
    assert result["origin_cache_revalidation"] == "requested_not_attested"
    assert not result["source_files_written"]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "NAME-MUST-NOT-LEAVE" not in serialized and "987654321" not in serialized
    assert "MARKER-COOKIE" not in serialized
    for call in calls:
        assert call.method == "GET"
        assert "cookie" not in call.headers and "authorization" not in call.headers
        assert call.headers["cache-control"] == "no-cache"
        assert call.headers["accept-encoding"] == "identity"
    assert settings[0]["follow_redirects"] is False and settings[0]["trust_env"] is False
    assert settings[0]["verify"].verify_mode.name == "CERT_REQUIRED"


@pytest.mark.parametrize("next_url", [
    "https://evil.example/projects/?PAGEN_1=2", "http://api.krt.mos.ru/projects/?PAGEN_1=2",
    "/other/?PAGEN_1=2", "/projects/?PAGEN_1=2&url=http://169.254.169.254/",
    "/projects/?PAGEN_1=two", "/projects/?PAGEN_1=-1", "/projects/?PAGEN_1=0",
    "/projects/?PAGEN_1=2#fragment", "https://api.krt.mos.ru@evil.example/projects/?PAGEN_1=2",
    "https://api.krt.mos.ru:444/projects/?PAGEN_1=2", "",
])
def test_foreign_or_non_native_next_link_stops_without_second_request(mock_origin, next_url):
    calls, _ = mock_origin(lambda request: httpx2.Response(200, content=page(next_url=next_url)))
    result = capture()
    assert not result["complete"] and "invalid_next_link" in result["gaps"]
    assert len(calls) == 1 and str(calls[0].url) == audit.ORIGIN


def test_repeated_next_page_is_not_a_complete_catalogue(mock_origin):
    calls, _ = mock_origin(lambda request: httpx2.Response(200, content=page(
        slug="site-one" if not request.url.query else "site-two", next_url="/projects/?PAGEN_1=2")))
    result = capture()
    assert len(calls) == 2 and not result["complete"]
    assert result["gaps"] == ["repeated_next_link"]


def test_repeated_response_under_another_url_is_explicitly_incomplete(mock_origin):
    calls, _ = mock_origin(lambda request: httpx2.Response(200, content=page(next_url="/projects/?PAGEN_1=2")))
    result = capture()
    assert len(calls) == 2 and not result["complete"] and result["gaps"] == ["repeated_page"]


def test_skipped_native_page_is_not_silently_called_complete(mock_origin):
    calls, _ = mock_origin(lambda request: httpx2.Response(200, content=page(next_url="/projects/?PAGEN_1=7")))
    result = capture()
    assert len(calls) == 1 and not result["complete"] and result["gaps"] == ["nonsequential_next_link"]


@pytest.mark.parametrize("anchor", [
    '<a href="/projects/site-two"></a><p>Статус: В реализации</p>',
    '<a href="https://api.krt.mos.ru/projects/site-two">Another project</a>',
])
def test_native_parser_cannot_silently_drop_a_recognized_project_identity(mock_origin, anchor):
    mock_origin(lambda request: httpx2.Response(200, content=page() + anchor.encode()))
    result = capture()
    assert not result["complete"] and result["gaps"] == ["project_identity_coverage_incomplete"]


@pytest.mark.parametrize("status,code", [(302, "redirect_refused"), (503, "http_status")])
def test_redirects_and_errors_are_not_followed_or_retried(mock_origin, status, code):
    calls, _ = mock_origin(lambda request: httpx2.Response(status, headers={"Location": "http://169.254.169.254/"}))
    result = capture()
    assert len(calls) == 1 and result["gaps"] == [code] and not result["complete"]


def test_combined_byte_budget_is_not_reset_per_page(mock_origin, monkeypatch):
    first = page(next_url="/projects/?PAGEN_1=2")
    second = page("site-two")
    monkeypatch.setattr(audit, "MAX_BYTES", len(first) + 10)
    calls, _ = mock_origin(lambda request: httpx2.Response(200, content=first if not request.url.query else second))
    result = capture()
    assert len(calls) == 2 and result["bytes"] == len(first) + 10
    assert result["gaps"] == ["body_limit"] and not result["complete"]
    assert result["roster"] == [{"slug": "site-one", "status": "В реализации"}]
    assert result["pages"][-1]["body_complete"] is False
    assert result["pages"][-1]["sha256"] == hashlib.sha256(second[:10]).hexdigest()


def test_page_budget_and_parse_failure_preserve_partial_observation(mock_origin, monkeypatch):
    monkeypatch.setattr(audit, "MAX_PAGES", 2)
    calls, _ = mock_origin(lambda request: httpx2.Response(200, content=page(
        "site-one" if not request.url.query else "site-two", next_url="/projects/?PAGEN_1=" + ("2" if not request.url.query else "3"))))
    result = capture()
    assert len(calls) == 2 and result["gaps"] == ["page_limit"]
    assert len(result["roster"]) == 2 and not result["complete"]


@pytest.mark.parametrize("body", [b"", b"<html>challenge, not a catalogue</html>", b"\xff\xfe"])
def test_unparsed_response_is_not_an_empty_success(mock_origin, body):
    mock_origin(lambda request: httpx2.Response(200, content=body))
    result = capture()
    assert not result["complete"] and result["gaps"] == ["unrecognized_catalogue"]


def test_origin_transport_failure_is_typed_without_exception_text_or_retry(mock_origin):
    def refused(request):
        raise httpx2.ConnectError("SECRET-IN-EXCEPTION", request=request)
    calls, _ = mock_origin(refused)
    result = capture()
    assert len(calls) == 1 and result["gaps"] == ["transport_error"]
    assert "SECRET" not in json.dumps(result)


def test_total_deadline_cancels_slow_stream_and_closes_response(mock_origin, monkeypatch):
    closed = []
    class Slow(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b"prefix"
            await asyncio.sleep(5)
            yield page()
        async def aclose(self):
            closed.append(True)
    monkeypatch.setattr(audit, "MAX_SECONDS", 0.03)
    mock_origin(lambda request: httpx2.Response(200, stream=Slow()))
    result = capture()
    assert result["gaps"] == ["total_time_limit"] and not result["complete"]
    assert result["elapsed_ms"] < 1000 and closed
    assert result["pages"][0]["sha256"] == hashlib.sha256(b"prefix").hexdigest()


def test_total_deadline_covers_later_connection_and_keeps_prior_page(mock_origin, monkeypatch):
    monkeypatch.setattr(audit, "MAX_SECONDS", 0.03)
    async def respond(request):
        if request.url.query:
            await asyncio.sleep(5)
        return httpx2.Response(200, content=page(next_url="/projects/?PAGEN_1=2"))
    calls, _ = mock_origin(respond)
    result = capture()
    assert len(calls) == 2 and result["gaps"] == ["total_time_limit"]
    assert result["elapsed_ms"] < 1000 and len(result["roster"]) == 1


def test_duplicate_slug_is_observed_but_not_accepted_and_ambiguous_pagination_stops(mock_origin):
    calls, _ = mock_origin(lambda request: httpx2.Response(200, content=page(next_url="/projects/?PAGEN_1=2")
        if not request.url.query else page(status="Планируемый")))
    result = capture()
    assert len(calls) == 2 and result["gaps"] == ["duplicate_slug", "conflicting_status"]
    assert result["walk_complete"] and not result["complete"]
    assert result["observed_occurrence_count"] == 2 and result["observed_unique_slug_count"] == 1
    assert len(result["roster"]) == 2 and result["observed_duplicate_occurrence_count"] == 1
    assert result["conflicting_status_observations"] == [{"slug": "site-one", "statuses": ["В реализации", "Планируемый"]}]
    mock_origin(lambda request: httpx2.Response(200, content=page(next_url="/projects/?PAGEN_1=2") +
        b'<button class="show_more" data-url="/projects/?PAGEN_1=3">More</button>'))
    assert capture()["gaps"] == ["invalid_next_link"]


def test_compressed_body_is_refused_without_inflation_or_retry(mock_origin):
    calls, _ = mock_origin(lambda request: httpx2.Response(200, stream=httpx2.ByteStream(b"not-gzip"),
        headers={"Content-Encoding": "gzip"}))
    result = capture()
    assert len(calls) == 1 and result["bytes"] == 0
    assert result["gaps"] == ["unsupported_content_encoding"]


def test_roster_output_and_metadata_are_bounded(mock_origin, monkeypatch):
    mock_origin(lambda request: httpx2.Response(200, content=page(), headers={"ETag": "X" * 1000}))
    assert len(capture()["pages"][0]["cache_headers"]["etag"]) == 256
    monkeypatch.setattr(audit, "MAX_ROWS", 0)
    result = capture()
    assert result["gaps"] == ["roster_limit"] and not result["complete"] and result["roster"] == []
    monkeypatch.setattr(audit, "MAX_ROWS", 4000)
    monkeypatch.setattr(audit, "MAX_OUTPUT_BYTES", 1)
    result = capture()
    assert result["gaps"] == ["output_limit"] and not result["complete"]
    assert result["roster"] == [] and result["roster_sha256"] is None
    assert not result["walk_complete"] and result["output_truncated"]


def duplicate_shape(next_url=None):
    """Anonymized retained282/280 duplicate/status shape; this HTML is synthetic."""
    return (page('exact-repeat', 'Планируемый') + page('exact-repeat', 'Планируемый') +
            page('status-conflict', 'Планируемый') +
            page('status-conflict', 'В реализации', next_url=next_url))


def test_adjacent_observed_duplicate_shape_preserves_both_rows_and_following_pages(mock_origin):
    bodies = [duplicate_shape('/projects/?PAGEN_1=2'),
              page('after-duplicate', next_url='/projects/?PAGEN_1=3'), page('last-site')]
    calls, _ = mock_origin(lambda request: httpx2.Response(200,
        content=bodies[0 if not request.url.query else int(request.url.params['PAGEN_1']) - 1]))
    result = capture()
    assert len(calls) == 3 and result['walk_complete'] and not result['complete']
    assert result['gaps'] == result['quality_gaps'] == ['duplicate_slug', 'conflicting_status']
    assert result['observed_occurrence_count'] == 6 and result['observed_unique_slug_count'] == 4
    assert result['observed_duplicate_occurrence_count'] == 2 and result['occurrence_identity_ambiguous']
    assert result['roster'] == [
        {'slug': 'exact-repeat', 'status': 'Планируемый'},
        {'slug': 'exact-repeat', 'status': 'Планируемый'},
        {'slug': 'status-conflict', 'status': 'Планируемый'},
        {'slug': 'status-conflict', 'status': 'В реализации'},
        {'slug': 'after-duplicate', 'status': 'В реализации'},
        {'slug': 'last-site', 'status': 'В реализации'},
    ]
    assert result['conflicting_status_observations'] == [
        {'slug': 'status-conflict', 'statuses': ['В реализации', 'Планируемый']}]
    assert [item['observed_occurrence_count'] for item in result['pages']] == [4, 1, 1]
    assert not result['production_acceptance'] and not result['historical_period_proven']
    assert result['source_updated_at'] is None


def test_image_name_and_more_links_are_one_native_occurrence(mock_origin):
    body = (b'<a href="/projects/site-one"><img src="picture"></a>' + page() +
            '<a href="/projects/site-one">Подробнее</a>'.encode())
    mock_origin(lambda request: httpx2.Response(200, content=body))
    result = capture()
    assert result['complete'] and result['walk_complete'] and result['quality_gaps'] == []
    assert result['observed_occurrence_count'] == result['observed_unique_slug_count'] == 1 and len(result['roster']) == 1


def test_nested_named_anchors_preserve_adjacent_status_observations(mock_origin):
    body = ('<div><a href="/projects/same-site"><span><strong>First name</strong></span>'
            '<span>Подробнее</span></a><p>Статус: Планируемый</p></div>\n'
            '<div><a href="/projects/same-site"><span><strong>Second name</strong></span>'
            '<span>Подробнее</span></a><p>Статус: В реализации</p></div>').encode()
    mock_origin(lambda request: httpx2.Response(200, content=body))
    result = capture()
    assert result['walk_complete'] and not result['complete']
    assert result['observed_occurrence_count'] == 2 and result['observed_unique_slug_count'] == 1
    assert [row['status'] for row in result['roster']] == ['Планируемый', 'В реализации']
    assert result['quality_gaps'] == ['duplicate_slug', 'conflicting_status']


def test_conflicting_status_labels_within_one_occurrence_are_observed_not_silently_overwritten(mock_origin):
    first = page('same-site', 'Планируемый', next_url='/projects/?PAGEN_1=2')
    first += '<p>Статус: В реализации</p>'.encode()
    calls, _ = mock_origin(lambda request: httpx2.Response(200,
        content=first if not request.url.query else page('following-site')))
    result = capture()
    assert len(calls) == 2 and result['walk_complete'] and not result['complete']
    assert result['observed_occurrence_count'] == 2 and result['observed_unique_slug_count'] == 2
    assert result['observed_duplicate_occurrence_count'] == 0
    assert result['roster'][0] == {'slug': 'same-site', 'status': 'В реализации',
        'status_observations': ['Планируемый', 'В реализации']}
    assert result['quality_gaps'] == ['ambiguous_status_within_occurrence', 'conflicting_status']
    assert result['conflicting_status_observations'] == [
        {'slug': 'same-site', 'statuses': ['В реализации', 'Планируемый']}]


def test_status_evidence_limit_is_an_explicit_incomplete_observation(mock_origin):
    body = page() + ''.join(f'<p>Статус: observed-{i}</p>' for i in range(9)).encode()
    mock_origin(lambda request: httpx2.Response(200, content=body))
    result = capture()
    assert not result['walk_complete'] and not result['complete']
    assert result['gaps'] == ['status_observation_limit'] and result['roster'] == []


def test_retained_282_280_shape_wrapper_keeps_both_duplicates_and_a_following_page(mock_origin):
    # Derived from the already inspected saved metadata shape only:282entries,
    #280exactslugs; adjacent duplicates136/137 and156/157. IDs/names/HTML here
    #are synthetic, not the primary origin HTML or a new freshness observation.
    observations = [{'slug': f'shape-site-{i:03d}', 'status': 'Планируемый'} for i in range(282)]
    observations[137] = dict(observations[136])
    observations[157] = dict(observations[156], status='В реализации')
    first = b'\n'.join(page(row['slug'], row['status']) for row in observations)
    first += b'<button class="show_more" data-url="/projects/?PAGEN_1=2">More</button>'
    following = {'slug': 'following-wrapper-sentinel', 'status': 'В реализации'}
    calls, _ = mock_origin(lambda request: httpx2.Response(200, content=first if not request.url.query
        else page(following['slug'], following['status'])))
    result = capture()
    assert len(calls) == 2 and result['walk_complete'] and not result['complete']
    assert result['roster'] == observations + [following]
    assert result['observed_occurrence_count'] == 283 and result['observed_unique_slug_count'] == 281
    assert result['observed_duplicate_occurrence_count'] == 2
    assert result['quality_gaps'] == ['duplicate_slug', 'conflicting_status']
    assert result['conflicting_status_observations'] == [
        {'slug': observations[156]['slug'], 'statuses': ['В реализации', 'Планируемый']}]
    assert [p['observed_occurrence_count'] for p in result['pages']] == [282, 1]


def test_later_timeout_after_quality_gap_still_fails_walk_closed(mock_origin, monkeypatch):
    monkeypatch.setattr(audit, 'MAX_SECONDS', 0.03)
    async def respond(request):
        if request.url.query:
            await asyncio.sleep(5)
        return httpx2.Response(200, content=duplicate_shape('/projects/?PAGEN_1=2'))
    calls, _ = mock_origin(respond)
    result = capture()
    assert len(calls) == 2 and not result['walk_complete'] and not result['complete']
    assert result['gaps'] == ['duplicate_slug', 'conflicting_status', 'total_time_limit']
    assert result['observed_occurrence_count'] == 4 and result['elapsed_ms'] < 1000


def test_quality_gap_does_not_mask_a_later_transport_failure(mock_origin):
    calls, _ = mock_origin(lambda request: httpx2.Response(200,
        content=duplicate_shape('/projects/?PAGEN_1=2')) if not request.url.query
        else httpx2.Response(503))
    result = capture()
    assert len(calls) == 2 and not result['walk_complete'] and not result['complete']
    assert result['gaps'] == ['duplicate_slug', 'conflicting_status', 'http_status']
    assert result['observed_occurrence_count'] == 4 and result['observed_unique_slug_count'] == 2


@pytest.mark.parametrize('failure,code', [('skip', 'nonsequential_next_link'),
    ('empty', 'unrecognized_catalogue'), ('redirect', 'redirect_refused'),
    ('repeated', 'repeated_page'), ('nameless', 'project_identity_coverage_incomplete')])
def test_quality_gap_never_turns_a_failed_walk_into_complete(mock_origin, failure, code):
    first = duplicate_shape('/projects/?PAGEN_1=2')
    second = {'skip': page('later-site', next_url='/projects/?PAGEN_1=7'), 'empty': b'',
              'repeated': first,
              'nameless': page('later-site') + b'<a href="/projects/missing-name"></a>'}
    def respond(request):
        if not request.url.query:
            return httpx2.Response(200, content=first)
        if failure == 'redirect':
            return httpx2.Response(302, headers={'Location': 'https://evil.example/'})
        return httpx2.Response(200, content=second[failure])
    calls, _ = mock_origin(respond)
    result = capture()
    assert len(calls) == 2 and not result['walk_complete'] and not result['complete']
    assert code in result['gaps']
    assert result['quality_gaps'] == ['duplicate_slug', 'conflicting_status']


@pytest.mark.parametrize('limit,code', [('pages', 'page_limit'), ('rows', 'roster_limit'),
    ('bytes', 'body_limit'), ('output', 'output_limit')])
def test_quality_observation_retains_all_existing_budgets(mock_origin, monkeypatch, limit, code):
    first = duplicate_shape('/projects/?PAGEN_1=2')
    if limit == 'pages':
        monkeypatch.setattr(audit, 'MAX_PAGES', 1)
    elif limit == 'rows':
        monkeypatch.setattr(audit, 'MAX_ROWS', 4)
    elif limit == 'bytes':
        monkeypatch.setattr(audit, 'MAX_BYTES', len(first) + 5)
    else:
        monkeypatch.setattr(audit, 'MAX_OUTPUT_BYTES', 1)
    mock_origin(lambda request: httpx2.Response(200, content=first if not request.url.query else page('later-site')))
    result = capture()
    assert not result['complete'] and not result['walk_complete'] and code in result['gaps']
    if limit == 'output':
        assert result['output_truncated'] and result['conflicting_status_observations'] == []
    else:
        assert result['observed_occurrence_count'] == 4 and result['observed_unique_slug_count'] == 2


@pytest.fixture
def client(monkeypatch):
    import main as wrapper
    import auction_search.api as api
    class NoStore:
        def __getattr__(self, name):
            pytest.fail("origin audit touched application store: " + name)
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(krt=NoStore())
    monkeypatch.setattr(api, "KrtRanking", lambda *a, **k: NoStore())
    api.install(app)
    core = wrapper.core
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setenv("MARKET_CABINET_KEY", "market-is-not-owner")
    monkeypatch.setenv("AUCTIONS_VIEW_KEY", "view-is-not-owner")
    monkeypatch.setattr(core, "usage_admin_ids", lambda: [777])
    monkeypatch.setattr(core, "COMMIT", RUNTIME["commit"])
    monkeypatch.setattr(core, "VERSION", RUNTIME["version"])
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("body", [{}, {"key": "wrong", "purpose": audit.PURPOSE},
    {"key": "market-is-not-owner", "purpose": audit.PURPOSE},
    {"key": "view-is-not-owner", "session": "invalid", "purpose": audit.PURPOSE}])
def test_real_owner_admission_precedes_collector_import_and_network(client, monkeypatch, body):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == "developaid_krt_origin_audit":
            pytest.fail("collector imported before owner admission")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    response = client.post(PATH, json=body, headers={"X-Market-Key": "market-is-not-owner"})
    assert response.status_code == 403 and response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("selector", ["url", "path", "page", "refresh", "project", "root"])
def test_caller_selectors_are_rejected_before_network(client, monkeypatch, selector):
    monkeypatch.setattr(audit, "_new_client", lambda: pytest.fail("network before strict validation"))
    response = client.post(PATH, json={"key": KEY, "purpose": audit.PURPOSE, selector: "x"})
    assert response.status_code == 400


def test_query_selector_and_duplicate_keys_are_rejected(client, monkeypatch):
    monkeypatch.setattr(audit, "_new_client", lambda: pytest.fail("unexpected network"))
    response = client.post(PATH + "?url=http://169.254.169.254/", json={"key": KEY, "purpose": audit.PURPOSE})
    assert response.status_code == 400
    response = client.post(PATH, content='{"key":"' + KEY + '","purpose":"' + audit.PURPOSE + '","purpose":"other"}')
    assert response.status_code == 400


def test_authorized_route_has_zero_store_model_calls_and_never_forwards_key(client, mock_origin):
    calls, _ = mock_origin(lambda request: httpx2.Response(200, content=page()))
    response = client.post(PATH, json={"key": KEY, "session": "", "purpose": audit.PURPOSE})
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    result = response.json()
    assert result["complete"] and result["runtime"] == RUNTIME and len(calls) == 1
    assert KEY not in response.text and KEY not in str(calls[0].headers) and not calls[0].content


def test_header_admission_works_but_unconfigured_owner_never_fails_open(client, monkeypatch, mock_origin):
    calls, _ = mock_origin(lambda request: httpx2.Response(200, content=page()))
    response = client.post(PATH, json={"purpose": audit.PURPOSE}, headers={"X-Developaid-Admin-Key": KEY})
    assert response.status_code == 200 and len(calls) == 1
    monkeypatch.delenv("DEVELOPAID_ADMIN_KEY")
    import main as wrapper
    monkeypatch.setattr(wrapper.core, "usage_admin_ids", lambda: [])
    response = client.post(PATH, json={"key": KEY, "purpose": audit.PURPOSE})
    assert response.status_code == 403 and len(calls) == 1
