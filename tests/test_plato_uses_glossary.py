"""Платон использует словарь PR #588 как источник терминологии.

Словарь не должен быть только документацией для разработчика: тот же файл
`docs/glossary.md` доступен агенту через его штатную дверь знаний, а ответ
получает явное правило — терминология словаря приоритетна и источник надо
называть.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402
import project_knowledge as knowledge  # noqa: E402

core = wrapper.core


def test_the_glossary_is_its_own_source() -> None:
    rows = knowledge.entries("glossary")
    assert rows, "docs/glossary.md не прочитан"
    assert {row["source"] for row in rows} == {"glossary"}
    text = " ".join(row["text"] for row in rows)
    assert "СПП" in text and "Наземная площадь" in text


def test_a_term_question_returns_the_glossary_and_names_it() -> None:
    answer = knowledge.search("что такое СПП в ГНС", source="glossary")
    assert answer["available"] is True
    assert answer["entries"]
    assert all("Словарь DevelopAid" in row["source"] for row in answer["entries"])
    assert "docs/glossary.md" in answer["note"]
    assert "используй именно его терминологию" in answer["note"]
    assert "укажи в ответе источник" in answer["note"]


def test_plato_reaches_the_glossary_through_the_real_agent_tool() -> None:
    answer = core._execute_agent_tool(
        "search_project_knowledge",
        {"query": "что такое СПП в ГНС", "source": "all"}, None, {})
    assert answer["available"] is True
    glossary = [row for row in answer["entries"] if "Словарь DevelopAid" in row["source"]]
    assert glossary, answer
    assert any("СПП" in row["text"] for row in glossary)
    assert "Словарь DevelopAid" in answer["note"]


def test_the_glossary_is_part_of_the_runtime_patterns() -> None:
    assert "docs/glossary.md" in knowledge._patterns()
