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


import re

ENTRY_POINTS = [ROOT / "CLAUDE.md", ROOT / "AGENTS.md", WS / "README.md",
                WS / "CONTROL_HANDOFF.md", *sorted((WS / "roles").glob("*.md"))]

# Имя действующего контроля живёт только в CONTROL_ACTIVE. Фраза, которая
# называет поставщика контролем текстом, устареет при первом переключении —
# и резерв, прочитавший её, возьмёт очередь вторым хозяином.
_FIXED_CONTROLLER = [
    re.compile(r"(под контролем|контрол\w*\s*—)[^\n.;]{0,40}\b(Codex|Claude)\b", re.I),
    re.compile(r"\bКонтроль\s+(Codex|Claude)\b"),
    re.compile(r"текущ\w+ контрол\w*[^\n.;]{0,40}\b(Codex|Claude)\b", re.I),
    re.compile(r"CONTROL_ACTIVE`?\s*\)?\s*=\s*`?(codex|claude)", re.I),
]


def names_a_fixed_controller(text: str) -> list[str]:
    return [m.group(0) for rx in _FIXED_CONTROLLER for m in rx.finditer(text)]


def test_every_entry_point_leads_to_the_active_file():
    for path in ENTRY_POINTS:
        assert "CONTROL_ACTIVE" in path.read_text(encoding="utf-8"), path


def test_no_entry_point_names_the_controller_in_text():
    found = {str(p.relative_to(ROOT)): names_a_fixed_controller(p.read_text(encoding="utf-8"))
             for p in ENTRY_POINTS}
    assert not {k: v for k, v in found.items() if v}, found


def test_a_text_that_hardcodes_the_controller_is_caught():
    """Подделки из рецензии: каждая должна быть поймана."""
    for fake in ("Очередью управляет контроль — Codex, CONTROL_ACTIVE не читать.",
                 "Ты работаешь под контролем текущего разговора Codex с владельцем.",
                 "U --> C[Контроль Claude]",
                 "Ты — текущий контроль PLATO в Codex.",
                 "(`docs/work_sessions/CONTROL_ACTIVE` = `claude`)"):
        assert names_a_fixed_controller(fake), fake
    assert not names_a_fixed_controller(
        "Действующий контроль — тот, что назван в `CONTROL_ACTIVE`.")


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
