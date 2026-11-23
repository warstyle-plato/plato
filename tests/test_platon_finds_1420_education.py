"""Публичная принятая норма доходит до реального инструмента, со ссылкой."""
from pathlib import Path

import pytest

import main as wrapper
import project_knowledge as knowledge


SOURCE = "http://publication.pravo.gov.ru/document/5000202610260001"


@pytest.mark.parametrize("query", [
    "1420-ПП 26.10.2026 детский сад школа 50 109 1000 жителей",
    "Московская область норматив мест детских садов и школ на 1000 жителей действующая редакция",
    "65 135 мест на 1000 жителей старая редакция 1420",
])
def test_public_tool_returns_the_current_rule_and_marks_old_numbers(query):
    answer = wrapper.core._execute_agent_tool(
        "search_project_knowledge", {"query": query, "source": "normative"}, None, {})
    entries = [entry["text"] for entry in answer.get("entries", [])]
    rule = next((text for text in entries if "50 мест" in text and "109 мест" in text), "")
    assert rule, answer
    assert SOURCE in rule
    assert "26.10.2026" in rule
    assert "65 и 135 — прежняя редакция" in rule
    assert "разрешение на строительство" in rule
    assert "не уменьшаются автоматически" in rule


def test_registry_provisions_carry_their_own_source_and_confirmation_limits(tmp_path, monkeypatch):
    import json
    root = tmp_path
    target = root / knowledge.REGISTRY_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps([{
        "id": "synthetic-public-act", "short_name": "Публичный акт",
        "status": "not_confirmed", "current_as_of": "2026-11-23",
        "source_url": "https://example.org/public-act", "source_label": "Синтетика",
        "provisions_use": "Последующие поправки не проверены.",
        "key_provisions": [{"point": "1", "subject": "Требование", "text": "Публичное положение"}],
    }], ensure_ascii=False))
    monkeypatch.setattr(knowledge, "_ROOT", root)
    text = knowledge._provision_entries()[0]["text"]
    assert "https://example.org/public-act" in text
    assert "not_confirmed" in text
    assert "Последующие поправки не проверены" in text
    assert "дата действия: не подтверждена" in text


def test_only_the_public_registry_and_excerpt_ship_not_runtime_state():
    from test_plato_knows_what_we_wrote_down import _docker_keeps
    root = Path(__file__).resolve().parents[1]
    rules = [s.strip() for s in (root / ".dockerignore").read_text().splitlines()
             if s.strip() and not s.startswith("#")]
    assert _docker_keeps("data/normatives/registry.json", rules)
    assert _docker_keeps("docs/normative/mo_1420_education.md", rules)
    for name in ("data/normatives/check_state.json", "data/runtime.db", ".env",
                 "docs/normative/mo_rngp_chain/raw.ocr.txt"):
        assert not _docker_keeps(name, rules), name
