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

# Имя действующего контроля живёт только в CONTROL_ACTIVE. Предложение, где
# слова о контроле, очереди, слиянии или выпуске стоят рядом с именем
# поставщика, называет контроль текстом при любом порядке слов — и устареет
# при первом переключении. Исключения перечислены поимённо: это фразы, которые
# говорят «смотри файл», а не «контроль — такой-то».
_CONTROL_WORDS = re.compile(r"контрол|очеред|слива|слия|выкат|выпуск|управля", re.I)
_PROVIDER = re.compile(r"\b(Codex|Claude)\b")
_ALLOWED = {
    "Если там не `codex`, разговор Codex — резерв: исполнитель, страж или отчёт "
    "владельцу, без слияния и выпуска.",
    "Там твой поставщик (`claude` для Claude, `codex` для Codex) — ты действующий "
    "контроль: переходи к [CONTROL_HANDOFF.md](../CONTROL_HANDOFF.md).",
}


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;!?])\s+|\n\s*\n|\n\s*[-*] |\n\s*\d+\. ", text)
    return [" ".join(p.split()).lstrip("-* ") for p in parts if p.strip()]


# Пересказ содержимого файла рядом с его именем — та же копия ответа.
_RETOLD_VALUE = re.compile(r"CONTROL_ACTIVE`?\s*\)?\s*=\s*`?(codex|claude)", re.I)


def names_a_fixed_controller(text: str) -> list[str]:
    found = [s for s in _sentences(text)
             if _CONTROL_WORDS.search(s) and _PROVIDER.search(s) and s not in _ALLOWED]
    return found + [m.group(0) for m in _RETOLD_VALUE.finditer(text)]


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
                 "Файл CONTROL_ACTIVE устарел, не читать: контроль очереди и выпуска — "
                 "разговор Codex с владельцем.",
                 "Очередью PR и выпуском управляет разговор Codex с владельцем.",
                 "Сливает и выкатывает только Claude-контроль.",
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
