"""Передача знания о проекте — СБОРКОЙ из живых источников, а не копией.

Зачем. Знание о PLATO лежит в `CLAUDE.md` (415 правил, 735 КБ), в бэклоге
вопросов и в нормативной библиотеке. Отдать это другому помощнику целиком
нельзя — не влезет; а переписать выжимку руками значит завести вторую копию,
и она разойдётся с оригиналом на первой же правке. Правило проекта здесь то
же, что у `VERSION`: копию негде обновлять, потому что копии нет.

Поэтому здесь СБОРЩИК. Он ничего не помнит сам: каждое утверждение вынимается
из файла или измеряется на месте, и если источник переписали — выжимка
переедет за ним. Своего знания о проекте в этом файле нет ни строки, и это
проверяется тестом.

Что собирается:

* устройство и стенд — разделами из `CLAUDE.md` как есть;
* указатель правил — заголовок каждого правила с номером строки, чтобы
  читатель шёл в оригинал за подробностями, а не верил пересказу;
* открытые вопросы — из `docs/questions_backlog.md`;
* нормативная база — из реестра, который читает Платон;
* живые числа — версия, число правил, число тестов: измеряются, а не пишутся.

Запуск:
    python3 scripts/handover.py                 — на экран
    python3 scripts/handover.py --out FILE.md   — в файл
    python3 scripts/handover.py --full          — вместе с полным CLAUDE.md
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = ROOT / "CLAUDE.md"
BACKLOG = ROOT / "docs" / "questions_backlog.md"
NORMATIVE = ROOT / "docs" / "normative" / "README.md"
REGISTRY = ROOT / "data" / "normatives" / "registry.json"

# Разделы `CLAUDE.md`, которые уходят В ЦЕЛОМ: они короткие и пересказу не
# подлежат — это устройство системы и описание стенда. Список имён, а не
# содержимого: содержимое живёт в файле.
WHOLE_SECTIONS = ("Устройство", "Проверки", "Стенд")


def _sections(text: str) -> dict[str, str]:
    """Разбить документ по заголовкам второго уровня."""
    out: dict[str, str] = {}
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].strip()] = parts[i + 1].strip()
    return out


def _rule_index(text: str) -> list[tuple[int, str]]:
    """Заголовок каждого правила и строка, где оно лежит.

    Берётся только ПЕРВОЕ предложение в звёздочках — само утверждение. Тело
    правила не копируется намеренно: пересказ разошёлся бы с оригиналом, а
    номер строки ведёт к нему целиком.
    """
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    for number, line in enumerate(lines, start=1):
        if not line.lstrip().startswith("- **"):
            continue
        # Заголовок правила бывает перенесён на вторую строку. Первая версия
        # разбора требовала закрывающих звёздочек в той же строке и молча
        # теряла 76 правил из 415 — потерянное правило читается как его
        # отсутствие, а счёт при этом выглядел посчитанным.
        chunk = line
        step = number
        while "**" not in chunk[chunk.index("- **") + 4:] and step < len(lines):
            chunk += " " + lines[step].strip()
            step += 1
        match = re.search(r"- \*\*(.+?)\*\*", chunk, flags=re.DOTALL)
        if match:
            headline = re.sub(r"\s+", " ", match.group(1)).strip().rstrip(".")
            found.append((number, headline))
    return found


def _backlog_open(text: str) -> list[str]:
    """Открытые вопросы — из раздела «Вопросы», как он назван в самом бэклоге."""
    section = _sections(text).get("Вопросы", "")
    return [m.group(1).strip().rstrip(".")
            for m in re.finditer(r"^\*\*(.+?)\*\*", section, flags=re.MULTILINE)]


def _version() -> str:
    match = re.search(r'^VERSION = "([^"]+)"',
                      (ROOT / "main_legacy.py").read_text(encoding="utf-8"),
                      flags=re.MULTILINE)
    return match.group(1) if match else "не прочитана"


def _test_count() -> str:
    """Сколько проверок в наборе — счётом, а не по памяти.

    Число в тексте протухает: прежняя запись «~965 тестов» пережила пятикратный
    рост набора. Считается сбором pytest, а не заглядыванием в документ.
    """
    try:
        run = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q",
                              "--collect-only"],
                             capture_output=True, text=True, timeout=900, cwd=ROOT)
        match = re.search(r"(\d+) tests? collected", run.stdout)
        if match:
            return match.group(1)
    except Exception:                                    # noqa: BLE001
        pass
    return "не измерено"


def _normative_rows() -> list[dict]:
    try:
        rows = json.loads(REGISTRY.read_text(encoding="utf-8"))
        return [r for r in rows if isinstance(r, dict)]
    except Exception:                                    # noqa: BLE001
        return []


def build(full: bool = False, count_tests: bool = True) -> str:
    knowledge = KNOWLEDGE.read_text(encoding="utf-8")
    sections = _sections(knowledge)
    rules = _rule_index(knowledge)
    questions = _backlog_open(BACKLOG.read_text(encoding="utf-8")) if BACKLOG.exists() else []
    normative = _normative_rows()
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    out: list[str] = []
    add = out.append

    add("# PLATO / DevelopAid — передача знания")
    add("")
    add(f"Собрано {stamp}, выпуск {_version()}.")
    add("")
    add("**Это сборка, а не документ.** Каждое утверждение ниже вынуто из живого "
        "источника; правил своих у этого файла нет. Собирает "
        "`python3 scripts/handover.py`. Если что-то здесь расходится с "
        "`CLAUDE.md` — верен `CLAUDE.md`, а сборщик сломан.")
    add("")
    add("## Что читать и в каком порядке")
    add("")
    add(f"1. `CLAUDE.md` — знание о проекте: {len(rules)} правил, выведенных из "
        "поломок. Это главный файл; он читается в начале каждой сессии.")
    add(f"2. `docs/questions_backlog.md` — что в работе и что не решено "
        f"({len(questions)} открытых вопросов).")
    add(f"3. `docs/normative/` — нормативная база файлами: акты не протухают, "
        f"ссылки на правовые системы протухают ({len(normative)} карточек в реестре).")
    if count_tests:
        add(f"4. `tests/` — {_test_count()} проверок. Многие из них — записанные "
            "правила: тест держит утверждение, а не текст.")
    add("")

    for name in WHOLE_SECTIONS:
        if name in sections:
            add(f"## {name}")
            add("")
            add(sections[name])
            add("")

    add("## Указатель правил")
    add("")
    add("Заголовок каждого правила и строка в `CLAUDE.md`. Тело не переписано "
        "намеренно: пересказ правила — это второе правило, и оно разойдётся с "
        "первым. За подробностями — в оригинал по номеру строки.")
    add("")
    for number, headline in rules:
        add(f"- `CLAUDE.md:{number}` — {headline}")
    add("")

    if questions:
        add("## Открытые вопросы")
        add("")
        add("Из раздела «Вопросы» бэклога — то, что ждёт решения владельца или "
            "измерения.")
        add("")
        for item in questions:
            add(f"- {item}")
        add("")

    if normative:
        add("## Нормативная база")
        add("")
        add("Реестр, который читает Платон (`data/normatives/registry.json`). "
            "Статус `review_required` значит, что редакция по официальному "
            "публикатору не сверена, — это ответ, а не пробел.")
        add("")
        for row in normative:
            add(f"- **{row.get('short_name') or row.get('id')}** "
                f"({row.get('scope')}, {row.get('status')}) — "
                f"{row.get('source_url') or 'ссылки нет'}")
        add("")

    if full:
        add("## CLAUDE.md целиком")
        add("")
        add(knowledge)
        add("")

    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="куда записать; без него — на экран")
    parser.add_argument("--full", action="store_true",
                        help="приложить CLAUDE.md целиком")
    parser.add_argument("--no-tests", action="store_true",
                        help="не считать тесты (сбор pytest занимает минуту)")
    args = parser.parse_args()

    text = build(full=args.full, count_tests=not args.no_tests)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"собрано: {args.out}, {len(text)} знаков")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
