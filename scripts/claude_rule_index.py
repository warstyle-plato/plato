#!/usr/bin/env python3
"""Индекс правил собирается из архива, а не пишется руками.

Индекс — производная архива: на каждое правило строка с его номером и именем.
Написанный руками, он расходится с архивом молча на первом же слиянии, которое
дописало правило (так и вышло: main дописал семь, а ссылки индекса остались на
прежних строках). Поэтому генератор один, и сторож зовёт его же: два ответа на
вопрос «где лежит это правило» однажды разойдутся, и оба будут выглядеть
верными.

    python3 scripts/claude_rule_index.py            # напечатать индекс
    python3 scripts/claude_rule_index.py --write    # записать его в файл
    python3 scripts/claude_rule_index.py --check    # сверить файл с архивом
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "docs" / "CLAUDE_HISTORY_2026-09-20.md"
INDEX = ROOT / "docs" / "CLAUDE_RULE_INDEX.md"

# Раздел архива → метка в индексе. Раздел, которого здесь нет, метки не
# получает: выдуманная метка сказала бы о правиле то, чего архив не говорит.
SECTIONS = {
    "Правила, выведенные из поломок": "rules",
    "Проверки": "checks",
    "Устройство": "setup",
    "Стенд": "stand",
    "Задачи и вопросы": "backlog",
}

HEAD = """# Индекс исторических правил CLAUDE

Собирается из архива: `python3 scripts/claude_rule_index.py --write`.
Руками не править — правка потеряется при следующей сборке.
Полный снимок прежнего файла: `docs/CLAUDE_HISTORY_2026-09-20.md`.
Ищите здесь по имени файла, функции, маршруту, предмету или ключевому слову; затем открывайте только нужный фрагмент архива.
"""


def rules(text: str) -> list[tuple[int, str, str]]:
    """Правило — пункт верхнего уровня; имя бывает перенесено на вторую строку."""
    out: list[tuple[int, str, str]] = []
    lines = text.split("\n")
    section = ""
    for i, line in enumerate(lines):
        if line.startswith("## "):
            section = SECTIONS.get(line[3:].strip(), "")
            continue
        if not line.startswith("- "):
            continue
        if line.startswith("- **"):
            # имя — всё до закрывающих звёздочек, сколько бы строк оно ни заняло
            name = line[4:]
            k = i
            while "**" not in name and k + 1 < len(lines):
                k += 1
                name += " " + lines[k].strip()
            name = name.split("**")[0].strip()
        else:
            # пункт без выделенного имени (команда, факт стенда) — берём его
            # первую строку: искать его будут по ней же
            name = line[2:].strip()
        out.append((i + 1, section, " ".join(name.split())))
    return out


def build() -> str:
    text = ARCHIVE.read_text(encoding="utf-8")
    body = "".join(
        f"- L{n} [{tag}] {name}\n" if tag else f"- L{n} {name}\n"
        for n, tag, name in rules(text)
    )
    return HEAD + "\n" + body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="записать индекс в файл")
    ap.add_argument("--check", action="store_true", help="сверить файл с архивом")
    args = ap.parse_args()
    want = build()
    if args.write:
        INDEX.write_text(want, encoding="utf-8")
        print(f"{INDEX.relative_to(ROOT)}: {want.count(chr(10))} строк, "
              f"{len(rules(ARCHIVE.read_text(encoding='utf-8')))} правил")
        return 0
    if args.check:
        have = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
        if have == want:
            print("индекс совпадает с архивом")
            return 0
        print("индекс разошёлся с архивом — пересобрать: "
              "python3 scripts/claude_rule_index.py --write", file=sys.stderr)
        return 1
    sys.stdout.write(want)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
