"""Упоминание 1310-ПП в карточке прежней редакции ведёт к самой поправке."""
from copy import deepcopy

import normatives_registry as registry


def test_1745_names_a_registered_amendment_and_links_its_source_at_the_edition():
    rows = {row["id"]: row for row in registry._load_registry()}
    old, amendment = rows["mo-1745-vri-kd"], rows["mo-1310-vri-ksu"]
    assert old["latest_amendment_ids"] == [amendment["id"]]
    card = registry._card(old)
    edition = card[card.index('<div class="amend">'):card.index('<div class="twocol">')]
    assert "Текущий консолидированный Порядок целиком не подтверждён" in edition
    assert ('href="' + amendment["source_url"] + '"') in edition
    assert "Официальный текст поправки: 1310-ПП" in edition
    assert old["source_url"] != amendment["source_url"], "ссылка на 1745 не подменяет поправку"
    assert old["status"] == amendment["status"] == "not_confirmed"


def test_amendment_url_is_read_from_its_card_rather_than_copied_into_the_reader(monkeypatch):
    rows = deepcopy(registry._load_registry())
    amendment = next(row for row in rows if row["id"] == "mo-1310-vri-ksu")
    amendment["source_url"] = "https://official.invalid/reviewed-amendment"
    old = next(row for row in rows if row["id"] == "mo-1745-vri-kd")
    monkeypatch.setattr(registry, "_load_registry", lambda: rows)
    links = registry._latest_amendment_links(old)
    assert 'href="https://official.invalid/reviewed-amendment"' in links
    assert "1373919" not in links


def test_an_unresolved_or_non_https_reference_does_not_become_a_fake_source(monkeypatch):
    monkeypatch.setattr(registry, "_load_registry", lambda: [
        {"id": "unsafe", "source_url": "javascript:alert(1)", "short_name": "Поправка"},
    ])
    assert registry._latest_amendment_links({"latest_amendment_ids": ["missing", "unsafe"]}) == ""
