"""Проба SPA показывает контракт, достаточный для написания читателя."""

from auction_search.adapters.browser_probe import _network_call


class _Request:
    resource_type = "fetch"
    method = "POST"
    url = "https://www.sberbank-ast.ru/api/Processing/main"
    post_data = '{"service":"public-search","page":1,"csrfToken":"private"}'


class _Response:
    request = _Request()
    status = 200

    @staticmethod
    def header_value(_name):
        return "application/json"

    @staticmethod
    def text():
        return ('{"items":[{"id":"lot-1"}],"total":1,'
                '"session":{"token":"private"}}')


def test_the_probe_shows_request_and_response_without_headers() -> None:
    got = _network_call(_Response())
    assert got["request_body_head"].startswith('{"service"')
    assert '"csrfToken":"[redacted]"' in got["request_body_head"]
    assert '"token":"[redacted]"' in got["response_body_head"]
    assert "private" not in str(got)
    assert got["response_keys"] == ["items", "session", "total"]
    assert "headers" not in got and "cookies" not in got


def test_non_data_resources_are_ignored() -> None:
    response = _Response()
    response.request = _Request()
    response.request.resource_type = "image"
    assert _network_call(response) is None
