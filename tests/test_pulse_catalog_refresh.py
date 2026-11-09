"""Два процесса читают один каталог и выбирают актуальную базу цены."""

from __future__ import annotations

import os
import time

from market_search.http import save_json
from market_search.pulse import PulseClient, make_pulse_client

RUSSIA = "https://russia.pulsprodaj.ru"
MOSCOW = "https://pulsprodaj.ru"


def _row(cid, name="Атлантис"):
    return {"complex_id": cid, "name": name, "latitude": 55.9066,
            "longitude": 37.7255, "address": "Московская область, Мытищи"}


def _network(directory):
    return make_pulse_client(directory, base=f"{RUSSIA},{MOSCOW}", login="l", password="p")


def test_a_warm_client_notices_atomic_replacement_even_with_the_same_size_and_mtime(tmp_path, monkeypatch):
    client = PulseClient(tmp_path, base=MOSCOW)
    save_json(client.catalog_path, [_row("7")])
    assert client.projects(fetch=False)[0].complex_id == "7"
    before = client.catalog_path.stat()
    save_json(client.catalog_path, [_row("8")])
    os.utime(client.catalog_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert client.catalog_path.stat().st_size == before.st_size
    monkeypatch.setattr(client, "_fetch_projects", lambda: (_ for _ in ()).throw(AssertionError("network")))
    assert client.projects(fetch=False)[0].complex_id == "8"


def test_a_warm_catalog_honours_ttl_without_network_in_suggestions(tmp_path, monkeypatch):
    client = PulseClient(tmp_path, base=MOSCOW, ttl_seconds=60)
    save_json(client.catalog_path, [_row("7")])
    assert client.projects()[0].complex_id == "7"
    old = time.time() - 120
    os.utime(client.catalog_path, (old, old))
    calls = []
    monkeypatch.setattr(client, "_fetch_projects", lambda: (calls.append(True), [_row("8")])[1])
    assert client.projects(fetch=False)[0].complex_id == "7"
    assert calls == []
    assert client.projects()[0].complex_id == "8"
    assert client.projects()[0].complex_id == "8"
    assert calls == [True]


def test_another_worker_switches_neighbours_and_prices_when_russia_catalog_appears(tmp_path, monkeypatch):
    first, second = _network(tmp_path), _network(tmp_path)
    save_json(first.sites[1].catalog_path, [_row("4033")])
    # russia ещё не загрузилась; оба процесса запомнили московских соседей.
    for network in (first, second):
        assert network.projects(fetch=False)[0].complex_id == "4033"
    save_json(first.sites[0].catalog_path, [_row("50-c350624")])
    assert first.projects(refresh=True, fetch=False)[0].complex_id == "50-c350624"
    for site in second.sites:
        monkeypatch.setattr(site, "_fetch_projects", lambda: (_ for _ in ()).throw(AssertionError("network")))
    monkeypatch.setattr(second.sites[0], "segments", lambda **kw: {})
    monkeypatch.setattr(second.sites[1], "segments", lambda **kw: {})
    assert second.suggest("Атлантис")[0]["complex_id"] == "50-c350624"
    nearby = second.near(55.9066, 37.7255, 2.5)
    assert [project.complex_id for _, project in nearby] == ["50-c350624"]
    assert second.superseded == {"50": 1}
    monkeypatch.setattr(second.sites[0], "price", lambda cid: {"price_per_sqm": 250000})
    monkeypatch.setattr(second.sites[1], "price", lambda cid: (_ for _ in ()).throw(AssertionError("wrong base")))
    assert second.price(nearby[0][1].complex_id)["price_per_sqm"] == 250000


def test_direct_price_lookup_rechecks_the_owner_of_an_already_known_id(tmp_path, monkeypatch):
    network = _network(tmp_path)
    save_json(network.sites[1].catalog_path, [_row("50-001200")])
    assert network.projects(fetch=False)[0].base == MOSCOW
    save_json(network.sites[0].catalog_path, [_row("50-001200")])
    monkeypatch.setattr(network.sites[0], "price", lambda cid: {"price_per_sqm": 250000})
    monkeypatch.setattr(network.sites[1], "price", lambda cid: (_ for _ in ()).throw(AssertionError("old owner")))
    assert network.price("50-001200")["price_per_sqm"] == 250000


def test_the_merged_catalog_also_honours_each_bases_ttl(tmp_path, monkeypatch):
    network = _network(tmp_path)
    for site in network.sites:
        save_json(site.catalog_path, [_row("50-c350624" if site is network.sites[0] else "4033")])
    assert network.projects()[0].complex_id == "50-c350624"
    old = time.time() - 172800
    os.utime(network.sites[0].catalog_path, (old, old))
    calls = []
    monkeypatch.setattr(network.sites[0], "_fetch_projects", lambda: (calls.append(True), [_row("50-c350625")])[1])
    assert network.projects(fetch=False)[0].complex_id == "50-c350624"
    assert calls == []
    assert network.projects()[0].complex_id == "50-c350625"
    assert network.projects()[0].complex_id == "50-c350625"
    assert calls == [True]


def test_a_removed_catalog_is_not_kept_in_memory_for_disk_only_readers(tmp_path):
    client = PulseClient(tmp_path, base=MOSCOW)
    save_json(client.catalog_path, [_row("7")])
    assert client.projects(fetch=False)
    client.catalog_path.unlink()
    assert client.projects(fetch=False) == []
