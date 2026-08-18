#!/usr/bin/env python3
"""Версия на main обязана строго расти.

Две параллельные сессии взяли номер от одного и того же main и обе объявили
0.18.45 — разные правки под одним номером. Общей памяти у сессий нет, общий у
них репозиторий, поэтому проверяет он: если движок изменился, а `VERSION` не
выросла, сборка красная.

Запуск: python3 scripts/check_version_grows.py [предыдущий_коммит]
"""

from __future__ import annotations

import re
import subprocess
import sys

ENGINE = "main_legacy.py"
_VERSION = re.compile(r'^VERSION = "([^"]+)"', re.M)


def _version(text: str) -> tuple[int, ...]:
    found = _VERSION.search(text)
    if not found:
        raise SystemExit(f"В {ENGINE} не нашлась строка VERSION = \"…\"")
    parts = found.group(1).split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        raise SystemExit(f"Версия не разбирается на числа: {found.group(1)}")


def _show(ref: str) -> str:
    return subprocess.run(["git", "show", f"{ref}:{ENGINE}"],
                          capture_output=True, text=True, check=True).stdout


def main() -> int:
    previous_ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD~1"
    try:
        before_text = _show(previous_ref)
    except subprocess.CalledProcessError:
        # Первый коммит или мелкая история: сравнивать не с чем — это не повод
        # ронять сборку.
        print(f"Предыдущей версии нет ({previous_ref}) — сравнение пропущено.")
        return 0
    after_text = _show("HEAD")
    if before_text == after_text:
        print("Движок не менялся — версия может остаться прежней.")
        return 0
    before, after = _version(before_text), _version(after_text)
    if after > before:
        print(f"Версия выросла: {'.'.join(map(str, before))} → {'.'.join(map(str, after))}")
        return 0
    print(f"Версия не выросла: было {'.'.join(map(str, before))}, "
          f"стало {'.'.join(map(str, after))}.", file=sys.stderr)
    print("Движок изменился, значит выпуск другой. Поднимите VERSION в "
          f"{ENGINE} — она объявляется там один раз.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
