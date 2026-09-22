from __future__ import annotations

from types import SimpleNamespace

from developaid_v2 import _project_cadastral_numbers


class _LookupRequest:
    def __init__(self, query: str, limit: int = 30):
        self.query = query
        self.limit = limit


def test_v2_keeps_cadastral_numbers_already_present_in_glavapu_source():
    calls = []

    core = SimpleNamespace(
        LandLookupRequest=_LookupRequest,
        land_lookup=lambda request: calls.append(request) or {},
    )
    parsed = {"source": {"cadastral_numbers": ["77:07:0008006:3", "77:07:0008006:3"]}}

    assert _project_cadastral_numbers(core, parsed, "Гродненская 18а") == [
        "77:07:0008006:3"
    ]
    assert calls == [], "готовый кадастр не должен запускать второй поиск"


def test_v2_address_search_recovers_cadastral_number_for_land_map():
    seen = {}

    def land_lookup(request):
        seen["query"] = request.query
        seen["limit"] = request.limit
        return {
            "results": [
                {
                    "found": True,
                    "kind": "land",
                    "cadastral_number": "77:07:0008006:3",
                },
                {
                    "found": True,
                    "kind": "building",
                    "cadastral_number": "77:07:0008006:999",
                },
            ]
        }

    core = SimpleNamespace(LandLookupRequest=_LookupRequest, land_lookup=land_lookup)
    parsed = {"source": {"cadastral_numbers": []}}

    assert _project_cadastral_numbers(core, parsed, "Гродненская 18а") == [
        "77:07:0008006:3"
    ]
    assert seen == {"query": "Гродненская 18а", "limit": 30}


def test_v2_address_lookup_failure_does_not_break_tep_project():
    def fail(_request):
        raise TimeoutError("НСПД временно недоступна")

    core = SimpleNamespace(LandLookupRequest=_LookupRequest, land_lookup=fail)

    assert _project_cadastral_numbers(
        core, {"source": {}}, "Гродненская 18а"
    ) == []
