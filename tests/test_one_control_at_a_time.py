"""Очередью и выпуском владеет один контроль; второй поставщик — резерв.

Проверяется не текст ради текста, а то, на что опираются обе схемы:
файл действующего контроля читается однозначно, и каждый вход (Claude, Codex,
передача контроля, реестр) ведёт к нему. Иначе резерв, прочитавший свой вход,
не узнал бы, что он резерв, — и очередь получила бы двух хозяев.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "docs" / "work_sessions"
KNOWN = {"codex", "claude"}


def active_control(text: str) -> str:
    """Имя действующего контроля: ровно одна непустая строка из известных."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1 or lines[0] not in KNOWN:
        raise ValueError(f"CONTROL_ACTIVE должен содержать одно из {sorted(KNOWN)}: {lines!r}")
    return lines[0]


def test_the_active_control_is_named_once():
    assert active_control((WS / "CONTROL_ACTIVE").read_text(encoding="utf-8")) in KNOWN


def test_an_ambiguous_file_is_refused():
    """Подделки: два хозяина, пусто, неизвестный — не принимаются."""
    for bad in ("codex\nclaude\n", "", "\n\n", "gemini\n", "Codex и Claude\n"):
        try:
            active_control(bad)
        except ValueError:
            continue
        raise AssertionError(f"принято неоднозначное значение {bad!r}")


def test_every_entry_point_leads_to_the_active_file():
    for path in (ROOT / "CLAUDE.md", ROOT / "AGENTS.md", WS / "README.md",
                 WS / "CONTROL_HANDOFF.md", WS / "roles" / "reserve.md"):
        assert "CONTROL_ACTIVE" in path.read_text(encoding="utf-8"), path


def test_the_registry_knows_the_reserve():
    registry = json.loads((WS / "registry.json").read_text(encoding="utf-8"))
    assert registry["control"]["active_file"] == "CONTROL_ACTIVE"
    reserve = [r for r in registry["roles"] if r["id"] == "reserve"]
    assert reserve and (WS / reserve[0]["start"]).is_file()
    assert (WS / registry["control"]["reserve"]).is_file()


def test_the_reserve_may_not_merge_or_release():
    rules = (WS / "RESERVE_CONTROL.md").read_text(encoding="utf-8")
    for forbidden in ("release-merge.yml", "release-approval.yml", "не сливает"):
        assert forbidden in rules
